# -*- coding: utf-8 -*-
"""阶段2：对站点做常见列表页路径探测 + 首页导航链接提取，分类出内容发布点，
与已登记点位对比，发现未登记的新内容发布点（尤其无 sitemap 的站点）。
"""
import json, os, sys, re, time
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
sys.path.insert(0, '/workspace/redteam')
from redteam_scan import RedTeamScanner, load_sites, norm, host_of

COMMON_PATHS = [
    "/news", "/news/", "/newsroom", "/newsroom/", "/media", "/media/", "/media-releases",
    "/media-releases/", "/media-centre", "/media-centre/", "/publications", "/publications/",
    "/reports", "/reports/", "/documents", "/documents/", "/resources", "/resources/",
    "/research", "/research/", "/articles", "/articles/", "/stories", "/stories/",
    "/press-releases", "/press-releases/", "/statements", "/statements/", "/speeches",
    "/speeches/", "/releases", "/releases/", "/notices", "/notices/", "/consultations",
    "/consultations/", "/policies", "/policies/", "/submissions", "/submissions/",
    "/latest", "/latest/", "/whats-new", "/whats-new/", "/insights", "/insights/",
    "/blog", "/blog/", "/updates", "/updates/", "/archive", "/archive/", "/information",
    "/information/", "/about/news", "/about-us/news", "/news-and-media", "/news-and-media/",
    "/media-releases", "/media-centre", "/newsroom", "/news-events", "/news-events/",
    "/publications-and-reports", "/publications-and-reports/", "/rss", "/rss/", "/feed",
    "/feed/", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml", "/news.xml",
]

ASSET_SUFFIX = ('.jpg', '.png', '.gif', '.svg', '.pdf', '.zip', '.mp3', '.mp4',
                '.css', '.js', '.woff', '.ico', '.doc', '.docx', '.xlsx', '.csv')


def main():
    sites = load_sites()
    sc = RedTeamScanner()
    results = []
    for site in sites:
        url = site['url']
        base_host = host_of(url)
        registered = {norm(p['url']) for p in site['points']}
        found = []
        # 常见路径探测（HEAD）
        for p in COMMON_PATHS:
            test = f"https://{base_host}{p}"
            n = norm(test)
            if n in registered:
                continue
            try:
                r = requests.head(test, timeout=8, allow_redirects=True,
                                  headers={"User-Agent": sc.sess.headers['User-Agent']})
                if r.status_code == 200:
                    found.append({'url': test, 'kind': 'probe'})
            except Exception:
                continue
        # 首页 nav 链接提取（GET 首页解析）
        try:
            r = sc.get(url)
            if r and r.status_code == 200:
                for m in re.finditer(r'href=["\']([^"\']+)["\']', r.text):
                    link = urljoin(url, m.group(1))
                    if '#' in link:
                        link = link.split('#')[0]
                    if '?' in link:
                        link = link.split('?')[0]
                    link = link.rstrip('/')
                    if not link or link in registered:
                        continue
                    if link.endswith(ASSET_SUFFIX):
                        continue
                    if host_of(link) != base_host:
                        continue
                    low = urlparse(link).path.lower()
                    if any(k in low for k in ['news', 'media', 'publication', 'report',
                                              'statement', 'speech', 'release', 'blog',
                                              'insight', 'consultation', 'notice',
                                              'resource', 'research', 'update', 'latest',
                                              'feed', 'rss', 'events', 'whats-new']):
                        found.append({'url': link, 'kind': 'nav'})
        except Exception:
            pass
        # 去重
        seen = set()
        dedup = []
        for f in found:
            if f['url'] not in seen:
                seen.add(f['url'])
                dedup.append(f)
        results.append({
            'site_name': site['site_name'],
            'url': url,
            'host': base_host,
            'registered': len(registered),
            'new_points': dedup,
        })
        print(f"{site['site_name']} | new={len(dedup)}")
    with open('/workspace/redteam/phase2_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("phase2 saved")


if __name__ == '__main__':
    main()