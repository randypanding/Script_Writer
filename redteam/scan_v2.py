# -*- coding: utf-8 -*-
"""v2：快速并行 sitemap 扫描 + 增量写盘（每完成一站即追加一行 JSONL）。
对每站：优先取已登记 sitemap，其次探测 /sitemap.xml 等；解析 index→子sitemap 并行拉取；
分类内容发布枢纽，与已登记点位 diff，输出未登记发布点。
"""
import json, os, sys, re, time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from defusedxml import ElementTree as ET
import requests

sys.path.insert(0, '/workspace/redteam')
from redteam_scan import load_sites, norm, host_of, HUB_LAST_SEG

BASE = '/tmp/Site_Watch'
POINTS = os.path.join(BASE, 'content', 'points_export.json')
OUT_JSONL = '/workspace/redteam/scan_v2.jsonl'
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
ASSET_SUFFIX = ('.jpg', '.png', '.gif', '.svg', '.pdf', '.zip', '.mp3', '.mp4',
                '.css', '.js', '.woff', '.ico', '.doc', '.docx', '.xlsx', '.csv')
ARTICLE_DATE_RE = re.compile(r'/(?:20\d{2}|19\d{2})[/-](?:\d{1,2})[/-](?:\d{1,2})')
JUNK = ["/login", "/logout", "/signup", "/register", "/search", "?q=", "/jobs",
        "/careers", "/vacancy", "/phonebook", "/print", "/dmsdocument", "/api/"]


def classify(url):
    low = urlparse(url).path.lower()
    u_low = url.lower()
    if not low or low == '/':
        return False, "home"
    if u_low.endswith(ASSET_SUFFIX):
        return False, "asset"
    if any(j in low for j in JUNK):
        return False, "junk"
    lp = low.rstrip('/').split('/')[-1]
    if low.endswith('.xml') or low.endswith('/feed') or low.endswith('/rss') \
       or low.endswith('/atom') or lp in ('feed', 'rss', 'rss.xml', 'feed.xml',
                                          'atom.xml', 'index.xml', 'news.xml'):
        return True, "rss"
    segs = [s for s in low.rstrip('/').split('/') if s]
    if segs and segs[-1].lower() in HUB_LAST_SEG:
        return True, "hub"
    if ARTICLE_DATE_RE.search(low):
        return False, "article"
    return False, "other"


def get(url, sess, timeout=10):
    try:
        return sess.get(url, timeout=timeout, allow_redirects=True)
    except Exception:
        return None


def get_sitemap_urls(site, sess):
    """优先已登记 sitemap 点位，其次常见路径。返回候选列表。"""
    cands = []
    for p in site['points']:
        if p['source_type'] == 'sitemap':
            cands.append(p['url'])
    host = host_of(site['url'])
    cands.append(f"https://{host}/sitemap.xml")
    cands.append(f"https://{host}/sitemap_index.xml")
    return cands


def scan_site(site):
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.trust_env = True
    registered = {norm(p['url']) for p in site['points']}
    start = time.time()
    # 1) 试候选 sitemap，拿到顶层 xml
    top_content, containers = [], set()
    found_top = None
    for c in get_sitemap_urls(site, sess):
        r = get(c, sess, 12)
        if not r or r.status_code != 200:
            continue
        try:
            root = ET.fromstring(r.text.encode('utf-8'))
        except Exception:
            continue
        tag = root.tag.split('}')[-1]
        if tag in ('urlset', 'sitemapindex'):
            found_top = r.text
            status = 'urlset' if tag == 'urlset' else 'index'
            break
    if found_top is not None:
        root = ET.fromstring(found_top.encode('utf-8'))
        tag = root.tag.split('}')[-1]
        if tag == 'urlset':
            for url in root.findall(f'{NS}url'):
                loc = url.findtext(f'{NS}loc', '').strip()
                if loc:
                    top_content.append(loc)
        elif tag == 'sitemapindex':
            subs = []
            for sm in root.findall(f'{NS}sitemap'):
                loc = sm.findtext(f'{NS}loc', '').strip()
                if loc:
                    containers.add(norm(loc))
                    subs.append(loc)
            # 并行拉子 sitemap
            with ThreadPoolExecutor(max_workers=8) as ex:
                futs = [ex.submit(get, s, sess, 12) for s in subs[:30]]
                for f in as_completed(futs):
                    r = f.result()
                    if not r or r.status_code != 200:
                        continue
                    try:
                        sr = ET.fromstring(r.text.encode('utf-8'))
                        if sr.tag.split('}')[-1] == 'urlset':
                            for url in sr.findall(f'{NS}url'):
                                loc = url.findtext(f'{NS}loc', '').strip()
                                if loc:
                                    top_content.append(loc)
                    except Exception:
                        continue
    # 2) 分类 + diff
    new_points = []
    seen = set()
    for u in top_content:
        n = norm(u)
        if not n or n in seen:
            continue
        seen.add(n)
        if n in registered or n in containers:
            continue
        is_list, kind = classify(u)
        if is_list:
            new_points.append({'url': u, 'kind': kind})
    return {
        'site_name': site['site_name'],
        'url': site['url'],
        'host': host_of(site['url']),
        'sitemap_urls': len(top_content),
        'registered': len(registered),
        'n_containers': len(containers),
        'new_points': new_points,
        'time_sec': round(time.time() - start, 1),
    }


def main():
    sites = load_sites()
    # 去掉已扫过的（断点续扫）
    done = set()
    if os.path.exists(OUT_JSONL):
        for line in open(OUT_JSONL, encoding='utf-8'):
            try:
                done.add(json.loads(line)['site_name'])
            except Exception:
                pass
    todo = [s for s in sites if s['site_name'] not in done]
    print(f"共 {len(sites)} 站，待扫 {len(todo)}")
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(scan_site, s): s for s in todo}
        n = 0
        for f in as_completed(futs):
            res = f.result()
            with open(OUT_JSONL, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(res, ensure_ascii=False) + '\n')
            n += 1
            print(f"[{n}/{len(todo)}] {res['site_name']} smap={res['sitemap_urls']} new={len(res['new_points'])}")
    print("DONE")


if __name__ == '__main__':
    main()