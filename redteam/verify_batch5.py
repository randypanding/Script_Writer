import requests, re
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
for name, u in [('gcsb_news','https://www.gcsb.govt.nz/news'),('nzsis_news','https://www.nzsis.govt.nz/news')]:
    r = s.get(u, timeout=22, allow_redirects=True)
    print('====', name, 'final_url=', r.url, 'status=', r.status_code)
    print(r.text[:300].replace('\n',' ') )
    print('---links---')
    print(re.findall(r'href="([^"]+)"', r.text)[:10])