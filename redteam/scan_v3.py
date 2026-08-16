# -*- coding: utf-8 -*-
"""v3 红队探查：针对"未登记 sitemap / 仅 list_page 或 rss 登记"的站点，
用 常见路径枚举 + 首页导航提取 + RSS 探测 三种渠道，
找出"已在网站目录中但未登记为监控点位"的内容发布点/列表页。
输出 JSONL（增量写盘，断点续扫）。
"""
import json, os, re, time
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

BASE = '/tmp/Site_Watch'
POINTS = os.path.join(BASE, 'content', 'points_export.json')
OUT_JSONL = '/workspace/redteam/scan_v3.jsonl'
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}

# 常见列表页路径（沿用 discovery.py 的思路并扩充）
COMMON_PATHS = [
    "/news/", "/newsroom/", "/media/", "/media-releases/", "/media-centre/",
    "/media-centre/media-releases/", "/publications/", "/publication/", "/reports/",
    "/documents/", "/resources/", "/research/", "/articles/", "/stories/",
    "/press-releases/", "/statements/", "/media-statements/", "/speeches/",
    "/notices/", "/consultations/", "/policies/", "/submissions/", "/latest/",
    "/archive/", "/whats-new/", "/what's-new/", "/insights/", "/blog/",
    "/updates/", "/announcements/", "/media/communications/", "/communications/",
    "/news-and-media/", "/news-and-publications/", "/news-and-updates/",
    "/media-and-pubs/", "/what-we-do/news/", "/about/news/", "/about-us/news/",
    "/corporate/news/", "/publications-and-research/", "/research-and-publications/",
    "/news-release/", "/media-centre/statements/", "/media-centre/speeches/",
    "/information-releases/", "/published-information/", "/about-media-centre/",
    "/news-and-media-centre/", "/latest-news/", "/news-and-events/", "/media-room/",
    "/news-media/", "/news-media-releases/",
]

RSS_PATHS = [
    "/rss/", "/rss.xml", "/feed/", "/feed.xml", "/feeds/", "/news.xml",
    "/news.rss", "/news/feed/", "/atom.xml", "/index.xml", "/rss/news/",
    "/news/rss", "/news.xml", "/latest/rss", "/media/rss", "/media/feed/",
]

# 首页/导航链接里，命中这些路径段即为列表页候选
NAV_HUB_WORDS = ["news", "media", "publication", "report", "document", "resource",
                 "research", "article", "stories", "statement", "speech", "notice",
                 "consultation", "policy", "insight", "blog", "update", "latest",
                 "archive", "event", "release", "gazette", "bulletin", "whats-new"]

ASSET = ('.pdf', '.jpg', '.png', '.gif', '.svg', '.css', '.js', '.zip', '.mp3',
         '.mp4', '.doc', '.docx', '.xlsx', '.csv', '.ico', '.woff')
JUNK = ["/login", "/logout", "/signup", "/register", "/search", "?q=", "/jobs",
        "/careers", "/vacancy", "/print", "/api/", "/tag/", "/author/",
        "/category/", "/wp-content/", "/wp-includes/", "/feed"]


def norm(u):
    if not u:
        return ""
    return u.split('#')[0].split('?')[0].rstrip('/')


def host_of(u):
    try:
        h = urlparse(u).netloc.lower()
        return h[4:] if h.startswith('www.') else h
    except Exception:
        return ""


def is_list_candidate(path):
    """路径中含列表页特征词（不一定在末段），用于导航链接粗筛。"""
    low = (path or '').lower()
    if not low:
        return False
    if any(a in low for a in ASSET):
        return False
    if any(j in low for j in JUNK):
        return False
    return any(w in low for w in NAV_HUB_WORDS)


def classify(url):
    """末段命中发布枢纽词 -> 列表页；否则文章/其他。"""
    low = urlparse(url).path.lower()
    if not low or low == '/':
        return False, "home"
    if url.lower().endswith(ASSET):
        return False, "asset"
    if any(j in low for j in JUNK):
        return False, "junk"
    lp = low.rstrip('/').split('/')[-1]
    if low.endswith('.xml') or low.endswith('.rss') or low.endswith('/feed') \
       or low.endswith('/rss') or low.endswith('/atom') \
       or lp in ('feed', 'rss', 'rss.xml', 'feed.xml', 'atom.xml', 'index.xml', 'news.xml'):
        return True, "rss"
    segs = [s for s in low.rstrip('/').split('/') if s]
    from scan_v2 import HUB_LAST_SEG
    if segs and segs[-1].lower() in HUB_LAST_SEG:
        return True, "hub"
    return False, "other"


def get(url, sess, timeout=12, method='GET'):
    try:
        r = sess.request(method, url, timeout=timeout, allow_redirects=True)
        return r
    except Exception:
        return None


def html_links(text, base_url, host):
    links = set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', text):
        href = m.group(1)
        if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
            continue
        full = urljoin(base_url, href)
        if host_of(full) != host:
            continue
        if any(a in full.lower() for a in ASSET):
            continue
        links.add(norm(full))
    return links


def probe_site(site):
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.trust_env = True
    start = time.time()
    host = host_of(site['url'])
    proto = site['url'].split(':', 1)[0] if ':' in site['url'] else 'https'
    base = f"{proto}://{host}"
    registered = {norm(p['url']) for p in site.get('points') or []}
    new_points = []
    seen = set()

    # 渠道1：常见路径枚举（GET 首页判活 + 常见列表路径直接 GET）
    home = get(base + '/', sess, 15)
    home_text = home.text if home and home.status_code == 200 else ""
    path_status = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(get, base + p, sess, 10): p for p in COMMON_PATHS}
        for f in as_completed(futs):
            p = futs[f]
            r = f.result()
            path_status[p] = 1 if r and r.status_code == 200 else 0
            if path_status[p]:
                u = base + p
                n = norm(u)
                if n and n not in seen and n not in registered:
                    seen.add(n)
                    new_points.append({'url': u, 'kind': 'list_page'})

    # 渠道2：首页导航链接提取
    if home_text:
        for link in html_links(home_text, base + '/', host):
            n = norm(link)
            if not n or n in seen or n in registered:
                continue
            u_path = urlparse(link).path
            if is_list_candidate(u_path) and classify(link)[0]:
                seen.add(n)
                new_points.append({'url': link, 'kind': classify(link)[1]})

    # 渠道3：RSS 探测
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(get, base + p, sess, 10): p for p in RSS_PATHS}
        for f in as_completed(futs):
            p = futs[f]
            r = f.result()
            if r and r.status_code == 200:
                txt = r.text[:2000].lstrip()
                if txt.lower().startswith('<?xml') and 'rss' in txt.lower()[:3000] \
                   or ('<rss' in txt[3:400] ) or ('<feed' in txt[3:400]):
                    u = base + p
                    n = norm(u)
                    if n and n not in seen and n not in registered:
                        seen.add(n)
                        new_points.append({'url': u, 'kind': 'rss'})

    # 去重（同 host 内）
    return {
        'site_name': site['site_name'],
        'url': site['url'],
        'host': host,
        'registered': len(registered),
        'home_status': 1 if home and home.status_code == 200 else 0,
        'common_paths_200': sum(path_status.values()),
        'new_points': new_points,
        'time_sec': round(time.time() - start, 1),
    }


def main():
    pts = json.load(open(POINTS))
    sites = pts['sites']
    # 只跑未登记 sitemap 的（sitemap 渠道已在 v2 覆盖）；且 v3 未跑过
    todo = []
    for s in sites:
        modes = {p.get('source_type') for p in (s.get('points') or [])}
        if 'sitemap' in modes:
            continue
        todo.append(s['site_name'])
    done = set()
    if os.path.exists(OUT_JSONL):
        for line in open(OUT_JSONL, encoding='utf-8'):
            try:
                done.add(json.loads(line)['site_name'])
            except Exception:
                pass
    todo = [s for s in sites if s['site_name'] in todo and s['site_name'] not in done]
    print(f"v3 待扫 {len(todo)} 站 (无 sitemap 登记的)")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(probe_site, s): s['site_name'] for s in todo}
        n = 0
        for f in as_completed(futs):
            res = f.result()
            with open(OUT_JSONL, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(res, ensure_ascii=False) + '\n')
            n += 1
            print(f"[{n}/{len(todo)}] {res['site_name']} home={res['home_status']} "
                  f"paths200={res['common_paths_200']} new={len(res['new_points'])}")
    print("V3 DONE")


if __name__ == '__main__':
    main()