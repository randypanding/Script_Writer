# -*- coding: utf-8 -*-
"""红队合并（只增不新建站点）：仅把新发现的监控点补充到【已登记】站点下。
规则：
- 以 baseline_points.json（git 9916f71，199 站）为准做底。
- 对每个发现的 URL，取 host；若 host 命中已登记站点的 host 或其子域(base-domain 匹配)，
  则作为该站新增 point；否则【丢弃】，绝不新建站点。
- 每个新增 point 必须是按时间排序的列表/发布页（kind: list_page*/rss）。
输出：content/points_export.json（站点数保持 199，只可能增加点位）。
"""
import json, os, glob
from datetime import datetime
from urllib.parse import urlparse

BASE = '/tmp/Site_Watch'
POINTS = os.path.join(BASE, 'content', 'points_export.json')
BASELINE = '/workspace/redteam/baseline_points.json'
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

# ---- 底：baseline ----
doc = json.load(open(BASELINE, encoding='utf-8'))
sites = doc['sites']

# 已登记 host（含子域名）的根列表；记录 site 对象以及是否本身就是"子域条目"
reg_by_host = {}            # host -> site dict entry
for s in sites:
    h = norm_host(s.get('url'))
    if h:
        reg_by_host[h] = s

def match_site(h_url):
    """返回该 URL host 命中的站点 dict；无命中返回 None。优先精确，其次根域匹配。"""
    h = h_url
    if h in reg_by_host:
        return reg_by_host[h]
    # 子域匹配：h 是某个已登记 host 的子域
    # 只允许注册 host 是其自身、或其末尾 '.' 分隔的子域
    for r, s in reg_by_host.items():
        if h != r and (h.endswith('.' + r)):
            return s
    return None

dropped = []      # (host, url) 未命中已登记站点，丢弃
added = 0
skipped = 0

def add_point(target, host, url, kind):
    global added
    global skipped
    if '{' in url or '}' in url:
        # 模板占位 URL 不可监控，跳过（如 /{slug}/media-releases）
        return
    nurl = url.split('#')[0].rstrip('/')
    if not nurl or '://' not in nurl:
        return
    for p in target['points']:
        if p.get('url', '').rstrip('/') == nurl:
            skipped += 1
            return
    target['points'].append({
        'source_type': src_of(kind),
        'url': nurl,
        'baseline': None,
        'enabled': True,
        'notes': 'redteam-existing',
    })
    added += 1

def process_entry(host, url, kind):
    global dropped
    h = norm_host(host) if host else norm_host(url)
    if not h:
        return
    target = match_site(h)
    if target is None:
        dropped.append((h, url))
        return
    add_point(target, h, url, kind)

# ---- 处理各发现文件 ----
def handle_pts(pts, host=None):
    for pt in pts or []:
        u = pt.get('url')
        if u:
            process_entry(pt.get('host') or host, u, pt.get('kind'))

# findings_web.jsonl + findings_batch*.jsonl
for p in [os.path.join(RT, 'findings_web.jsonl')] + sorted(glob.glob(os.path.join(RT, 'findings_batch*.jsonl'))):
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
        handle_pts(r.get('unregistered'), h)

# 仅并入**人工核验过的**列表中枢 (verified_hubs.jsonl)。
# 注意：不再并入 scan_v2/scan_v3 的原始 sitemap 批量点位——那些含大量单篇文档，非真正的时间排序发布页。
if os.path.exists(os.path.join(RT, 'verified_hubs.jsonl')):
    for line in open(os.path.join(RT, 'verified_hubs.jsonl'), encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        process_entry(r.get('host'), r.get('url'), 'list_page')

doc['sites'] = sites
doc['total_sites'] = len(sites)
doc['total_points'] = sum(len(s['points']) for s in sites)
doc['generated_at'] = datetime.now().isoformat()

bak = os.path.join(RT, 'points_export_backup.json')
import shutil
shutil.copy(POINTS, bak)
with open(POINTS, 'w', encoding='utf-8') as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)

print(f"站点总数(保持): {doc['total_sites']}")
print(f"新增点位(仅已登记站点内): {added}")
print(f"跳过重复: {skipped}")
print(f"丢弃(非已登记站点): {len(dropped)}")
uniq_drop_hosts = sorted({h for h, _ in dropped})
print(f"被丢弃 host 数: {len(uniq_drop_hosts)}")
for h in uniq_drop_hosts:
    print('  DROP', h)