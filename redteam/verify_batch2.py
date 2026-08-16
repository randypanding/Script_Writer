import requests, re
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
urls = [
    ('afp_newscentre', 'https://afp.gov.au/news-centre'),
    ('afp_podcasts', 'https://afp.gov.au/news-centre/podcasts'),
    ('afp_statement', 'https://afp.gov.au/news-centre?content_type_id=media-statement'),
    ('afp_community', 'https://afp.gov.au/news-centre/community-information'),
    ('austrac_pubs', 'https://www.austrac.gov.au/industry-and-business/education-and-resources/publications-and-resources'),
    ('austrac_news2', 'https://www.austrac.gov.au/news-and-media/news'),
]
for name, u in urls:
    try:
        r = s.get(u, timeout=25)
        heads = [re.sub('<[^>]+>', '', h).strip() for h in re.findall(r'<h[12][^>]*>(.*?)</h[12]>', r.text, re.S)][:2]
        ct = r.headers.get('content-type', '')[:30]
        print(f'{name} | {r.status_code} | ct={ct} | len={len(r.text)} | heads={heads}')
    except Exception as e:
        print(f'{name} | ERR {str(e)[:60]}')