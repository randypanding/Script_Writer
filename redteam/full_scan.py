# -*- coding: utf-8 -*-
"""全量扫描：顺序扫描所有 199 站点，查找未登记的内容发布点。
输出 JSON 报告 + 控制台摘要。
"""
import json, os, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, '/workspace/redteam')
from redteam_scan import RedTeamScanner, load_sites, norm

OUTPUT = '/workspace/redteam/scan_report.json'
MAX_WORKERS = 6  # 不要太多，避免被封


def scan_one(site):
    sc = RedTeamScanner()
    t0 = time.time()
    try:
        res = sc.scan_site(site)
        delta = time.time() - t0
        return {**res, 'time_sec': round(delta, 1)}
    except Exception as e:
        delta = time.time() - t0
        return {
            'site_name': site['site_name'],
            'url': site['url'],
            'error': str(e),
            'time_sec': round(delta, 1),
            'new_points': [],
        }


def main():
    sites = load_sites()
    print(f"全量扫描 {len(sites)} 站点 (max_workers={MAX_WORKERS})...")
    t0 = time.time()
    all_results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {ex.submit(scan_one, s): s for s in sites}
        for fut in as_completed(fut_map):
            res = fut.result()
            name = res['site_name']
            all_results[name] = res
            done += 1
            err = res.get('error') or ''
            np = len(res.get('new_points', []))
            print(f"  [{done}/{len(sites)}] {name}: sitemap_urls={res.get('sitemap_urls',0)} new_points={np} {err}")
    
    total = time.time() - t0
    print(f"\n完成！耗时 {total:.0f}s")
    
    # 汇总
    has_new = []
    no_new = []
    for name, r in all_results.items():
        if r.get('new_points') and len(r['new_points']) > 0:
            has_new.append(r)
        else:
            no_new.append(r)
    
    has_new.sort(key=lambda r: -len(r['new_points']))
    
    report = {
        'total_sites': len(sites),
        'total_time_sec': round(total, 1),
        'sites_with_new': len(has_new),
        'sites_without_new': len(no_new),
        'total_new_points': sum(len(r['new_points']) for r in has_new),
        'results': all_results,
        'summary': [
            {
                'site_name': r['site_name'],
                'url': r['url'],
                'host': r.get('host', ''),
                'sitemap_urls': r.get('sitemap_urls', 0),
                'registered': r.get('registered', 0),
                'new_points': r['new_points'],
                'n_new': len(r['new_points']),
            }
            for r in has_new
        ],
    }
    
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {OUTPUT}")
    
    print("\n" + "="*70)
    print(f"未登记内容发布点 (共计 {report['total_new_points']} 个，分布在 {len(has_new)} 站点)")
    print("="*70)
    for s in report['summary'][:80]:
        print(f"\n{s['site_name']} | {s['url']} | 已登记: {s['registered']} 新发现: {s['n_new']}")
        for p in s['new_points'][:10]:
            print(f"  [{p['kind']}] {p['url']}")
        if len(s['new_points']) > 10:
            print(f"  ... 还有 {len(s['new_points'])-10} 个")
    
    # 输出也到文件
    summary_path = '/workspace/redteam/scan_summary.txt'
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"未登记内容发布点 (共计 {report['total_new_points']} 个，分布在 {len(has_new)} 站点)\n")
        f.write("="*70 + "\n")
        for s in report['summary']:
            f.write(f"\n{s['site_name']} | {s['url']} | 已登记: {s['registered']} 新发现: {s['n_new']}\n")
            for p in s['new_points']:
                f.write(f"  [{p['kind']}] {p['url']}\n")
    print(f"\n摘要已保存: {summary_path}")


if __name__ == '__main__':
    main()