import requests, re
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
urls = [
    ('rbnz_news','https://www.rbnz.govt.nz/news-and-events/news'),
    ('rbnz_speeches','https://www.rbnz.govt.nz/news-and-events/speeches'),
    ('rbnz_ocr','https://www.rbnz.govt.nz/monetary-policy/monetary-policy-decisions'),
    ('rbnz_domestic','https://www.rbnz.govt.nz/financial-markets/domestic-markets/domestic-markets-releases-listing-page'),
    ('rbnz_consultations','https://consultations.rbnz.govt.nz/'),
    ('mbie_news','https://www.mbie.govt.nz/about/news'),
    ('mfat_media','https://www.mfat.govt.nz/en/media-and-resources'),
    ('treasury_ms','https://www.treasury.govt.nz/publications/media-statement'),
    ('treasury_speech','https://www.treasury.govt.nz/publications/speech'),
    ('treasury_publications','https://www.treasury.govt.nz/publications'),
    ('nzdm','https://debtmanagement.treasury.govt.nz/investor-resources/media-statements'),
    ('inz_newscentre','https://www.immigration.govt.nz/about-us/news-centre/'),
]
for name, u in urls:
    try:
        r = s.get(u, timeout=20)
        heads = [re.sub('<[^>]+>','',h).strip() for h in re.findall(r'<h[12][^>]*>(.*?)</h[12]>', r.text, re.S)][:2]
        ct = r.headers.get('content-type','')[:25]
        low = r.text.lower()
        soft = len(r.text) < 800 or any(k in low for k in ['access denied','cf-error','captcha','robot check','404'])
        print(f'{name} | {r.status_code} | {ct} | len={len(r.text)} | soft={soft} | heads={heads}')
    except Exception as e:
        print(f'{name} | ERR {str(e)[:50]}')