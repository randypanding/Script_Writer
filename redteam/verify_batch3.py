import requests, re
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
urls = [
    ('cyber_alert_rss', 'https://www.cyber.gov.au/rss.xml'),
    ('cyber_alerts_path', 'https://www.cyber.gov.au/about-us/about-acsc/alerts-and-advisories'),
    ('asd_media', 'https://www.asd.gov.au/media'),
    ('asd_pubs', 'https://www.asd.gov.au/about/accountability-governance/publications'),
    ('nacc_media', 'https://www.nacc.gov.au/media-centre'),
    ('nacc_media_rel', 'https://www.nacc.gov.au/media-releases'),
    ('niche_ona', 'https://www.ona.gov.au/media-releases'),
    ('onis_media', 'https://www.oni.gov.au/media-centre'),
]
for name, u in urls:
    try:
        r = s.get(u, timeout=22)
        heads = [re.sub('<[^>]+>', '', h).strip() for h in re.findall(r'<h[123][^>]*>(.*?)</h[123]>', r.text, re.S)][:2]
        ct = r.headers.get('content-type', '')[:30]
        print(f'{name} | {r.status_code} | ct={ct} | len={len(r.text)} | heads={heads}')
    except Exception as e:
        print(f'{name} | ERR {str(e)[:55]}')