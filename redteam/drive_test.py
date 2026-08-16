# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, '/workspace/redteam')
from redteam_scan import RedTeamScanner, load_sites, BASE

NAMES = sys.argv[1:] if len(sys.argv) > 1 else [
    "Ministry of Foreign Affairs and Trade",
    "Ministry of Defence",
    "Ministry of Justice",
    "Ministry of Social Development",
    "Ministry of Health",
]
sites = load_sites()
targets = [s for s in sites if any(n in s['site_name'] for n in NAMES)]
print(f"targets: {[t['site_name'] for t in targets]}")
sc = RedTeamScanner()
for site in targets:
    t0 = time.time()
    try:
        res = sc.scan_site(site)
        np_ = res['new_points']
        print("="*70)
        print(f"{res['site_name']} | {res['url']} | sitemap_urls={res['sitemap_urls']} registered={res['registered']} new_points={len(np_)} | {time.time()-t0:.1f}s")
        for p in np_[:40]:
            print(f"   [{p['kind']}] {p['url']}")
    except Exception as e:
        print(f"ERR {site['site_name']}: {e}")