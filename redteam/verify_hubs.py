# -*- coding: utf-8 -*-
"""深度验证：对候选未登记内容发布点做真实 HTTP 探测，
确认是真实列表页(返回200且含链接/条目标题)而非软404/机器人拦截页。
输出 verified_hubs.jsonl + 汇总报告。
"""
import json, re, time, random
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
           "Accept": "text/html"}

# 高价值待验证候选（从 v2/v3 中挑选的、跨机构的典型发布点）
CANDIDATES = {
    "Stats NZ": {
        "https://www.stats.govt.nz/information-releases/": "信息发布列表页(核心)",
        "https://www.stats.govt.nz/publications/": "出版物列表页",
        "https://www.stats.govt.nz/news/": "新闻",
        "https://www.stats.govt.nz/insights/": "洞察",
        "https://www.stats.govt.nz/research/": "研究",
    },
    "ASIC": {
        "https://www.asic.gov.au/about-asic/news-centre/speeches": "演讲",
        "https://www.asic.gov.au/about-asic/news-centre/articles": "文章",
        "https://www.asic.gov.au/about-asic/corporate-publications/newsletters": "简报",
        "https://www.asic.gov.au/newsroom/media-releases": "媒体发布",
        "https://www.asic.gov.au/regulatory-resources/find-a-document/reports": "报告",
    },
    "Austrade": {
        "https://www.austrade.gov.au/en/news-and-analysis/media-centre/media-releases": "媒体发布",
        "https://www.austrade.gov.au/en/news-and-analysis/newsletters": "简报",
        "https://www.austrade.gov.au/en/news-and-analysis/news": "新闻",
    },
    "Clean Energy Regulator": {
        "https://cer.gov.au/news-and-media/media-centre/media-releases": "媒体发布",
        "https://cer.gov.au/news-and-media/news": "新闻",
    },
    "IRD NZ": {
        "https://www.ird.govt.nz/media-releases": "媒体发布",
        "https://www.ird.govt.nz/index/news": "新闻",
        "https://www.ird.govt.nz/about-us/publications": "出版物",
    },
    "LINZ": {
        "https://www.linz.govt.nz/about-us/information-releases": "信息发布",
        "https://www.linz.govt.nz/consultations": "咨询",
        "https://www.linz.govt.nz/news": "新闻",
    },
    "ANSTO": {
        "https://www.ansto.gov.au/news": "新闻",
        "https://www.ansto.gov.au/research/publications": "出版物",
        "https://www.ansto.gov.au/archive": "档案",
    },
    "NDIS": {
        "https://www.ndis.gov.au/news/media": "媒体",
        "https://www.ndis.gov.au/publications": "出版物",
        "https://www.ndis.gov.au/news/stories": "故事",
    },
    "DFAT": {
        "https://www.dfat.gov.au/trade/agreements/Pages/news": "协议新闻",
        "https://www.dfat.gov.au/news/news/Pages/statement": "声明",
    },
    "Treasury AU": {
        "https://treasury.gov.au/media-release": "媒体发布",
        "https://treasury.gov.au/news": "新闻",
    },
}

LINK_RE = re.compile(r'<a[^>]+href=[\'"]?([^\'" >]+)', re.I)
TITLE_RE = re.compile(r'<(h[1-4])[^>]*>(.*?)</\1>', re.I | re.S)

def check(url, sess):
    try:
        r = sess.get(url, timeout=15)
        ct = (r.headers.get('content-type') or '')
        text = r.text
        links = set(m for m in LINK_RE.findall(text) if m.startswith('/') or m.startswith('http'))
        links = {url[:url.rfind('/')+1] + m.lstrip('/') if m.startswith('/')
                 else m for m in links if not m.startswith('#')}
        headers = [h for h in TITLE_RE.findall(text)]
        # 软404判断：仅对短内容(<5000字符)用关键词判重；长内容(>5000)视为真实页面
        htmlish = '<html' in text.lower() or '<div' in text.lower()
        low = text.lower()
        soft = False
        if len(text) < 5000:
            soft = (len(text) < 600) or any(k in low for k in
                    ['access denied', 'protected by', 'cf-error', 'not found', '404',
                     'blocked', 'robot', 'captcha', 'too many requests', 'robot check'])
        elif any(k in low for k in ['access denied', 'cf-error', 'captcha', 'robot check']):
            soft = True
        return {
            'status': r.status_code, 'len': len(text), 'links': len(links),
            'headings': len(headers), 'content_type': ct[:40],
            'html': htmlish, 'soft404': (soft and r.status_code == 200),
            'sample_heading': (headers[0][1][:60].strip() if headers else ''),
        }
    except Exception as e:
        return {'status': None, 'error': str(e)[:40]}

def main():
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.trust_env = True
    out = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {}
        for site, urls in CANDIDATES.items():
            for u, note in urls.items():
                futs[ex.submit(check, u, sess)] = (site, u, note)
        for f in as_completed(futs):
            site, u, note = futs[f]
            res = f.result()
            ok = (res.get('status') == 200 and res.get('html') and res.get('len', 0) >= 1500
                  and (res.get('links', 0) >= 3 or res.get('headings', 0) >= 1)
                  and not res.get('soft404'))
            row = {'site': site, 'url': u, 'note': note, 'ok': ok, **res}
            out.append(row)
            print(('OK  ' if ok else '--- ') + f"{site} | {note} | {res.get('status')} len={res.get('len')} links={res.get('links')} h={res.get('headings')} soft={res.get('soft404')} err={res.get('error','')}")
    with open('verified_hubs.jsonl', 'w') as fh:
        for row in out:
            fh.write(json.dumps(row) + '\n')
    good = [r for r in out if r['ok']]
    print(f"\n==== 验证完成: 候选 {len(out)}, 确认真实列表页 {len(good)} ====")
    for r in good:
        print('  +', r['site'], '|', r['note'], '|', r['url'])

if __name__ == '__main__':
    main()