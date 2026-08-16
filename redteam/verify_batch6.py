import requests, re
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
urls = [
    ('customs_media', 'https://www.customs.govt.nz/about-us/news/media-releases/'),
    ('customs_stories', 'https://www.customs.govt.nz/about-us/news/our-stories/'),
    ('customs_news', 'https://www.customs.govt.nz/about-us/news/'),
    ('sfo_releases', 'https://www.sfo.govt.nz/media-cases/media-releases'),
    ('sfo_cases', 'https://www.sfo.govt.nz/media-cases/cases'),
    ('defnz_news', 'https://www.defence.govt.nz/news/'),
    ('corrections_media', 'https://www.corrections.govt.nz/news-and-information/media-releases'),
    ('justice_media', 'https://www.justice.govt.nz/about/news-and-media/media-releases/'),
]
for name, u in urls:
    try:
        r = s.get(u, timeout=22)
        heads = [re.sub('<[^>]+>', '', h).strip() for h in re.findall(r'<h[12][^>]*>(.*?)</h[12]>', r.text, re.S)][:2]
        ct = r.headers.get('content-type', '')[:28]
        print(f'{name} | {r.status_code} | ct={ct} | len={len(r.text)} | heads={heads}')
    except Exception as e:
        print(f'{name} | ERR {str(e)[:50]}')