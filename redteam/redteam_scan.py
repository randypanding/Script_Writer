# -*- coding: utf-8 -*-
"""红队扫描：枚举每个目标站点的 sitemap，分类出"内容发布点/列表页"，
与 content/points_export.json 已登记监控点位对比，找出未登记的新内容发布点。
"""
import json, os, re, sys, time
from urllib.parse import urlparse
import requests
from defusedxml import ElementTree as ET

BASE = '/tmp/Site_Watch'
POINTS = os.path.join(BASE, 'content', 'points_export.json')

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}

LIST_KEYWORDS = [
    "news", "newsroom", "media", "media-release", "press-release",
    "publication", "report", "document", "resource", "research", "article", "stories",
    "statement", "speech", "notice", "consultation", "policy", "insight", "blog",
    "update", "latest", "archive", "pubs", "library", "gallery", "events", "whats-new",
    "media-centre", "information", "announcement", "releases", "reviews", "submissions",
    "communique", "communiques", "transcript", "transcripts",
    "order", "orders", "gazette", "bulletin", "newsletters", "newsletter", "post",
    "posts", "briefing", "briefings", "fact-sheet", "factsheet", "fact-sheets",
    "speeches", "answers", "questions", "written", "journals", "papers",
    "reports", "publications", "index", "listing", "feed", "rss", "what's new",
]

ARTICLE_DATE_RE = re.compile(r'/(?:20\d{2}|19\d{2})[/-](?:\d{1,2})[/-](?:\d{1,2})')

# 内容"发布枢纽"关键词：这些词作为路径最后一个段时，表示这是一个内容聚合/发布点
HUB_LAST_SEG = [
    "news", "newsroom", "media", "media-release", "media-releases", "media-centre",
    "press-release", "press-releases", "publications", "publication", "reports",
    "report", "documents", "document", "resources", "resource", "research",
    "articles", "article", "stories", "statements", "statement", "speeches",
    "speech", "notices", "notice", "consultations", "consultation", "policies",
    "policy", "insights", "insight", "blog", "updates", "update", "latest",
    "archive", "pubs", "library", "gallery", "events", "whats-new", "what-s-new",
    "information", "announcements", "announcement", "releases", "reviews",
    "submissions", "communique", "communiques", "transcripts", "transcript",
    "orders", "order", "gazette", "bulletins", "bulletin", "newsletters",
    "newsletter", "posts", "post", "briefings", "briefing", "fact-sheets",
    "fact-sheet", "factsheets", "answers", "questions", "journals", "papers",
    "listed-documents", "publications-list", "media-releases", "media-release",
    "information-releases", "replies", "responses",
]

JUNK = [
    "/login", "/logon", "/logout", "/signup", "/register", "/search", "?q=",
    "/jobs", "/careers", "/vacancy", "/phonebook", "/checks", "/print",
    "/dmsdocument", "/interface", "/meteye", "/email-to-friend", "/web/checks/",
    "/static/", "/assets/", "/images/", "/css/", "/js/", "/fonts/", "/img/",
    "/media/uploads", "/_uploads", "/download", "/api/", "/wp-content/uploads",
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".zip", ".mp3", ".mp4", ".ico", ".json",
    "/tag/", "/author/", "/category/", "/taxonomy/", "/password/", "/404",
]
ASSET_SUFFIX = ('.jpg', '.png', '.gif', '.svg', '.pdf', '.zip', '.mp3', '.mp4',
                '.css', '.js', '.woff', '.ico', '.doc', '.docx', '.xlsx', '.csv')

def norm(u):
    if not u:
        return ""
    u = u.split('#')[0].split('?')[0]
    return u.rstrip('/')

def host_of(u):
    try:
        h = urlparse(u).netloc.lower()
    except Exception:
        return ""
    return h[4:] if h.startswith('www.') else h

NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'


class RedTeamScanner:
    def __init__(self):
        self.sess = requests.Session()
        self.sess.headers.update(HEADERS)
        self.sess.trust_env = True
        self.timeout = 25

    def get(self, url):
        try:
            return self.sess.get(url, timeout=self.timeout, allow_redirects=True)
        except Exception:
            return None

    def _parse(self, text):
        try:
            return ET.fromstring(text.encode('utf-8'))
        except Exception:
            return None

    def fetch_sitemaps(self, host):
        """返回 (all_content_urls, sitemap_container_urls)"""
        candidates = []
        r = self.get(f"https://{host}/robots.txt")
        if r and r.status_code == 200 and 'sitemap:' in r.text.lower():
            for line in r.text.splitlines():
                if line.lower().startswith('sitemap:'):
                    candidates.append(line.split(':', 1)[1].strip())
        for p in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                  "/sitemap.txt", "/wp-sitemap.xml", "/sitemap/sitemap.xml"]:
            candidates.append(f"https://{host}{p}")

        all_content = []
        containers = set()
        queue = []
        seen = set()
        for c in candidates:
            n = norm(c)
            if n and n not in seen:
                seen.add(n)
                queue.append(c)
        processed = set()
        while queue and len(processed) < 60:
            sm = queue.pop(0)
            if sm in processed:
                continue
            processed.add(sm)
            r = self.get(sm)
            if not r or r.status_code != 200:
                continue
            root = self._parse(r.text)
            if root is None:
                continue
            tag = root.tag.split('}')[-1]
            if tag == 'sitemapindex':
                for sitemap in root.findall(f'{NS}sitemap'):
                    loc = sitemap.findtext(f'{NS}loc', '').strip()
                    if loc:
                        containers.add(norm(loc))
                        if norm(loc) not in seen:
                            seen.add(norm(loc))
                            queue.append(loc)
            elif tag == 'urlset':
                for url in root.findall(f'{NS}url'):
                    loc = url.findtext(f'{NS}loc', '').strip()
                    if loc:
                        all_content.append(loc)
        return all_content, containers

    def classify(self, url):
        low = urlparse(url).path.lower()
        u_low = url.lower()
        if not low or low == '/':
            return False, "home"
        if u_low.endswith(ASSET_SUFFIX):
            return False, "asset"
        if any(j in low for j in JUNK):
            return False, "junk"
        last_part = low.rstrip('/').split('/')[-1]
        if low.endswith('.xml') or low.endswith('.rss') or low.endswith('.atom') \
           or low.endswith('/feed') or low.endswith('/rss') or low.endswith('/atom') \
           or last_part in ('feed', 'rss', 'rss.xml', 'feed.xml', 'atom.xml', 'index.xml', 'news.xml'):
            return True, "rss"
        # 内容发布枢纽：路径最后一个段是内容型关键词 → 聚合页/发布点
        segs = [s for s in low.rstrip('/').split('/') if s]
        if segs and segs[-1].lower() in HUB_LAST_SEG:
            return True, "hub"
        if ARTICLE_DATE_RE.search(low):
            return False, "article"
        return False, "other"

    def scan_site(self, site):
        url = site['url']
        registered = {norm(p['url']) for p in site['points']}
        reg_kinds = {norm(p['url']): p['source_type'] for p in site['points']}
        base_host = host_of(url)
        content_urls, containers = self.fetch_sitemaps(base_host)
        new_points = []
        seen = set()
        for u in content_urls:
            n = norm(u)
            if not n or n in seen:
                continue
            seen.add(n)
            if n in registered or n in containers:
                continue
            is_list, kind = self.classify(u)
            if is_list:
                new_points.append({'url': u, 'kind': kind})
        return {
            'site_name': site['site_name'],
            'url': url,
            'host': base_host,
            'sitemap_urls': len(content_urls),
            'registered': len(registered),
            'n_containers': len(containers),
            'new_points': new_points,
        }


def load_sites():
    with open(POINTS, encoding='utf-8') as f:
        doc = json.load(f)
    return doc['sites']

if __name__ == '__main__':
    sites = load_sites()
    print(f"共 {len(sites)} 站点")