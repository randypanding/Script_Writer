import requests, re
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
urls = [
    ('nacc_news', 'https://www.nacc.gov.au/news-and-media'),
    ('gcsb_news', 'https://www.gcsb.govt.nz/news'),
    ('gcsb_rss', 'https://www.gcsb.govt.nz/news/rss'),
    ('nzsis_news', 'https://www.nzsis.govt.nz/news'),
    ('nzsis_rss', 'https://www.nzsis.govt.nz/news/rss'),
    ('ncsc_news', 'https://www.ncsc.govt.nz/news/'),
    ('oni_news', 'https://www.oni.gov.au/news'),
    ('igis_pubs', 'https://igis.govt.nz/publications'),
    ('igis_releases', 'https://igis.govt.nz/publications/media-releases/announcements'),
]
for name, u in urls:
    try:
        r = s.get(u, timeout=22)
        ct = r.headers.get('content-type', '')[:28]
        print(f'{name} | {r.status_code} | ct={ct} | len={len(r.text)}')
    except Exception as e:
        print(f'{name} | ERR {str(e)[:50]}')