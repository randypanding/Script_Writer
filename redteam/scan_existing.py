# -*- coding: utf-8 -*-
"""红队——在【已登记站点】内发现新增的时间排序发布页/列表中枢。
对每个已登记站点 host，抓取其 sitemap，只保留符合"发布列表/中枢/RSS"特征且
未在该站已登记 URL 集合中的子页。绝不新增站点（host 必须匹配已登记站或其子域）。
输出：scan_existing.jsonl（每条含 host + new_points）
"""
import json, re, os, concurrent.futures, sys
from urllib.parse import urlparse, urljoin, unquote

KNOWN = '/tmp/Site_Watch/content/points_export.json'
OUT = '/workspace/redteam/scan_existing.jsonl'

try:
    import requests
except Exception:
    os.system(sys.executable + ' -m pip install requests html5lib -q')
    import requests

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}

# 发布列表/中枢关键词（最后一段）
HUB_LAST_SEG = {
    'news', 'newsroom', 'media', 'media-releases', 'media-releases-and-documents',
    'media-releases-documents', 'media-centre', 'media-centre', 'media-statements',
    'media-statement', 'media-updates', 'press-releases', 'press-release',
    'announcements', 'announcement', 'releases', 'release', 'statements', 'statement',
    'publications', 'publications-and-resources', 'articles', 'insights', 'bulletins',
    'reports', 'report', 'speeches', 'speech', 'transcripts', 'podcasts', 'blog',
    'latest', 'news-and-updates', 'news-and-events', 'news-and-media', 'news-and-articles',
    'news-and-analysis', 'updates', 'update', 'whats-new', 'hot-topics', 'highlights',
    'communications', 'media-releases-and-speeches', 'newsroom', 'news-releases',
    'newsletter', 'newsletters', 'release-calendar', 'events', 'webinars',
}
HUB_ANY_SEG = {'news', 'media', 'releases', 'announcements', 'publications', 'speeches'}
# 真实 feed 路径：仅当末段是 feed/rss/atom 文件名或 .xml 扩展名
RSS_END = ('.xml', '.rss', '.atom', 'feed.xml', 'rss.xml', 'atom.xml', 'index.xml')
RSS_LAST_SEG = {'feed', 'rss', 'atom', 'feeds', 'rss.xml', 'feed.xml', 'atom.xml', 'index.xml', 'news.xml'}

def norm_host(u):
    if not u: return ''
    if '://' not in u: u = 'https://' + u
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith('www.') else h

def sitemap_urls(home, timeout=30):
    """抓取嵌套 sitemap，返回 (所有叶子 url 列表, rss 候选列表)。"""
    cands = []
    base = home.rstrip('/')
    for u in [base + '/sitemap.xml', base + '/sitemap_index.xml', base + '/sitemap-index.xml']:
        try:
            r = requests.get(u, headers=HEADERS, timeout=timeout)
            if r.ok and ('<urlset' in r.text or '<sitemapindex' in r.text or '<sitemapindex' in r.text.lower()):
                cands.append((u, r))
        except Exception:
            pass
    urls = set()
    seen = set()
    stack = [c[0] for c in cands] + [u for u, _ in cands]
    # re-fetch approach simpler: iterate found sitemaps
    def extract(text):
        out = set()
        for m in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', text):
            out.add(m.strip())
        return out
    # BFS over sitemap links pointing to .xml
    queue = [(u, r) for u, r in cands]
    while queue and len(queue) < 200:
        u, r = queue.pop(0)
        if u in seen: continue
        seen.add(u)
        locs = extract(r.text)
        for loc in locs:
            if 'sitemap' in loc.lower() and loc.lower().endswith('.xml') and enemy(loc):
                try:
                    rr = requests.get(loc, headers=HEADERS, timeout=timeout)
                    if rr.ok:
                        queue.append((loc, rr))
                except Exception:
                    pass
            else:
                urls.add(loc.split('#')[0])
    return urls

def enemy(u):  # skip sitemaps of other hosts
    return True

def classify(url):
    path = urlparse(url).path
    pl = path.rstrip('/')
    last = pl.split('/')[-1] if pl else ''
    l = last.lower()
    # 排除 sitemap / robots / 静态资源
    if 'sitemap' in pl.lower() or 'robots' in l or l in ('favicon.ico',):
        return None
    # 仅接受 feed / 末段中枢词命中。绝不用"中段含 news"来判定——
    # 否则单篇文章 /news/<slug> 会被误判为列表页。
    if url.lower().endswith(RSS_END) or l in RSS_LAST_SEG:
        return 'rss'
    if l in HUB_LAST_SEG:
        return 'list_page_hub'
    return None

def process(host, baseurl, reg_urls):
    try:
        urls = sitemap_urls(baseurl)
    except Exception as e:
        return None
    newpts = []
    for u in urls:
        if norm_host(u) and host != norm_host(u):
            continue  # 只保留本站
        k = classify(u)
        if not k:
            continue
        nu = u.split('#')[0].rstrip('/')
        if nu in reg_urls or nu == baseurl.rstrip('/'):
            continue
        newpts.append({'url': nu, 'kind': k})
    # 去重（同 url）
    seen=set(); dedup=[]
    for p in newpts:
        if p['url'] in seen: continue
        seen.add(p['url']); dedup.append(p)
    if not dedup:
        return None
    return {'host': host, 'base': baseurl, 'new_points': dedup}

def main():
    doc = json.load(open(KNOWN, encoding='utf-8'))
    hosts = []
    for s in doc['sites']:
        h = norm_host(s.get('url'))
        if not h: continue
        # base url of site url
        base = s['url'].rstrip('/')
        reg = {p.get('url','').split('#')[0].rstrip('/') for p in s.get('points',[])}
        hosts.append((h, base, reg))
    out = open(OUT, 'w', encoding='utf-8')
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(process, h, b, r): h for (h, b, r) in hosts}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            done += 1
            if r:
                out.write(json.dumps(r, ensure_ascii=False) + '\n')
                out.flush()
    out.close()
    print('processed', done, 'of', len(hosts), 'hosts')

if __name__ == '__main__':
    main()