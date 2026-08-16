# -*- coding: utf-8 -*-
"""把红队发现的所有新监控点合并进 content/points_export.json，
按 host 匹配到已有站点；无匹配 host 则新建站点。输出保留原有点位并去重。
"""
import json, os, re
from datetime import datetime
from urllib.parse import urlparse

BASE = '/tmp/Site_Watch'
POINTS = os.path.join(BASE, 'content', 'points_export.json')
RT = '/workspace/redteam'

def norm_host(u):
    if not u:
        return ''
    if '://' not in u:
        u = 'https://' + u
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith('www.') else h

def src_of(kind):
    k = (kind or '').lower()
    if 'rss' in k or k in ('feed', 'atom'):
        return 'rss'
    if 'sitemap' in k:
        return 'sitemap'
    return 'list_page'

def base_of(u):
    m = re.match(r'(https?://[^/]+)', u)
    return m.group(1) + '/' if m else u

def main():
    doc = json.load(open(POINTS, 'r', encoding='utf-8'))
    sites = doc['sites']

    # host -> site entry 索引
    host2site = {}
    for s in sites:
        h = norm_host(s.get('url'))
        if h:
            host2site[h] = s

    # 收集所有新点: host -> {url: source_type}
    new_by_host = {}
    def bump(host, url, kind):
        st = src_of(kind)
        nurl = url.split('#')[0].rstrip('/')
        if not nurl or '://' not in nurl:
            return
        h = norm_host(host) or norm_host(url)
        new_by_host.setdefault(h, {})[nurl] = st

    added_site_name = {}

    # 1) verified_hubs.jsonl —— 已实况确认的列表页
    p = os.path.join(RT, 'verified_hubs.jsonl')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            bump(norm_host(r.get('url')), r.get('url'), 'list_page')

    # 2) scan_v2.jsonl —— sitemap 分类发现的发布点
    p = os.path.join(RT, 'scan_v2.jsonl')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            h = r.get('host') or norm_host(r.get('url'))
            if h:
                added_site_name[h] = r.get('site_name', h)
            for pt in r.get('new_points', []):
                hh = norm_host(pt.get('url')) or h
                bump(hh, pt.get('url'), pt.get('kind'))

    # 3) scan_v3.jsonl —— 无 sitemap 站点探测发现的发布点
    p = os.path.join(RT, 'scan_v3.jsonl')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            h = r.get('host') or norm_host(r.get('url'))
            if h:
                added_site_name.setdefault(h, r.get('site_name', h))
            for pt in r.get('new_points', []):
                hh = norm_host(pt.get('url')) or h
                bump(hh, pt.get('url'), pt.get('kind'))

    # 4) findings_web.jsonl + findings_batch*.jsonl —— Web 搜索枚举的发布中心
    import glob as _glob
    fw_files = [os.path.join(RT, 'findings_web.jsonl')] + sorted(
        _glob.glob(os.path.join(RT, 'findings_batch*.jsonl')))
    for p in fw_files:
        if not os.path.exists(p):
            continue
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            h = r.get('host')
            if h:
                added_site_name.setdefault(h, r.get('site', h))
            for pt in r.get('unregistered', []):
                bump(h, pt.get('url'), pt.get('kind'))

    # 应用合并：命中已存在站点则插入其 points，否则记为新站点
    sites_by_host = dict(host2site)
    new_sites = []
    added_pt = 0
    already = 0
    for host, urlmap in new_by_host.items():
        target = sites_by_host.get(host)
        if target is None:
            url_for_site = base_of(next(iter(urlmap)))
            name = added_site_name.get(host, host)
            target = {'site_name': name, 'url': url_for_site, 'enabled': True, 'points': [], }
            sites_by_host[host] = target
            new_sites.append(target)
        existing_urls = {p['url'].split('#')[0].rstrip('/') for p in target['points']}
        for u, st in urlmap.items():
            if u in existing_urls:
                already += 1
                continue
            if any(p.get('url', '').rstrip('/') == u for p in target['points']):
                already += 1
                continue
            target['points'].append({
                'source_type': st,
                'url': u,
                'baseline': None,
                'enabled': True,
                'notes': 'redteam',
            })
            existing_urls.add(u)
            added_pt += 1

    sites.extend(new_sites)

    doc['sites'] = sites
    doc['total_sites'] = len(sites)
    doc['total_points'] = sum(len(s['points']) for s in sites)
    doc['generated_at'] = datetime.now().isoformat()
    doc['description'] = doc.get('description', '') + ' (红队补点)'

    # 备份再覆盖
    bak = os.path.join(RT, 'points_export_backup.json')
    with open(bak, 'w', encoding='utf-8') as f:
        json.dump(json.load(open(POINTS, encoding='utf-8')), f, ensure_ascii=False, indent=2)
    with open(POINTS, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    print(f"完成: 新增站点 {len(new_sites)}, 新增点位 {added_pt}, 已存在跳过 {already}")
    print(f"总量: {doc['total_sites']} 站 / {doc['total_points']} 点")
    print(f"备份: {bak}")

if __name__ == '__main__':
    main()