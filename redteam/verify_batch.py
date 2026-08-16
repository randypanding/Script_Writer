import requests, re, sys
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

urls = [
    ('cyber_news', 'https://www.cyber.gov.au/about-us/view-all-content/news'),
    ('cyber_alerts', 'https://www.cyber.gov.au/about-us/about-acsc/alerts-and-advisories'),
    ('cyber_all', 'https://www.cyber.gov.au/about-us/view-all-content'),
    ('afp_newscentre', 'https://www.afp.gov.au/news-centre'),
    ('afp_media_release', 'https://www.afp.gov.au/news-centre?content_type_id=media-release'),
    ('austrac_news', 'https://www.austrac.gov.au/news-and-media/news-and-media-releases'),
    ('austrac_media', 'https://www.austrac.gov.au/news-and-media/news'),
    ('austrac_rss', 'https://www.austrac.gov.au/media-release/rss.xml'),
]
for name, u in urls:
    try:
        r = s.get(u, timeout=20)
        heads = [re.sub('<[^>]+>', '', h).strip() for h in re.findall(r'<h[12][^>]*>(.*?)</h[12]>', r.text, re.S)][:2]
        ct = r.headers.get('content-type', '')[:30]
        print(f'{name} | {r.status_code} | ct={ct} | len={len(r.text)} | heads={heads}')
    except Exception as e:
        print(f'{name} | ERR {str(e)[:60]}')