import hashlib, json, os, re, urllib.request
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

UA = 'GTOCRB-Radar/3.0 (+https://github.com/podacionar-rgb/grupo)'
BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, 'radar-sources.json'), encoding='utf-8') as f:
    sources = json.load(f)

state_path = os.path.join(BASE, 'radar-status.json')
try:
    with open(state_path, encoding='utf-8') as f:
        old = json.load(f)
except FileNotFoundError:
    old = {}

def fetch(url, limit=900_000):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml,text/xml;q=0.9,*/*;q=0.7'
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limit), getattr(r, 'status', 200), r.geturl()

def absolute(url, base):
    from urllib.parse import urljoin
    return urljoin(base, url)

def clean(text):
    return re.sub(r'\s+', ' ', BeautifulSoup(text or '', 'html.parser').get_text(' ', strip=True)).strip()

def page_meta(url):
    try:
        data, status, final_url = fetch(url, 650_000)
        soup = BeautifulSoup(data, 'html.parser')
        title = clean(soup.title.get_text()) if soup.title else ''
        for key in [('property','og:title'), ('name','twitter:title')]:
            tag = soup.find('meta', attrs={key[0]: key[1]})
            if tag and tag.get('content'):
                title = clean(tag['content']); break
        image = ''
        for key in [('property','og:image'), ('name','twitter:image')]:
            tag = soup.find('meta', attrs={key[0]: key[1]})
            if tag and tag.get('content'):
                image = absolute(tag['content'], final_url); break
        return title, image, status
    except Exception:
        return '', '', None

def discover_feed(url):
    try:
        data, _, final_url = fetch(url, 500_000)
        soup = BeautifulSoup(data, 'html.parser')
        for link in soup.find_all('link'):
            typ = (link.get('type') or '').lower()
            rel = ' '.join(link.get('rel') or []).lower()
            href = link.get('href')
            if href and ('rss' in typ or 'atom' in typ or 'feed' in rel):
                return absolute(href, final_url)
    except Exception:
        pass
    for suffix in ['rss', 'rss.xml', 'feed', 'feed/', 'feeds/posts/default?alt=rss']:
        candidate = url.rstrip('/') + '/' + suffix
        try:
            data, _, _ = fetch(candidate, 350_000)
            if feedparser.parse(data).entries:
                return candidate
        except Exception:
            continue
    return None

def entry_image(entry, article_url):
    for key in ('media_content','media_thumbnail'):
        for media in entry.get(key, []) or []:
            if media.get('url'):
                return absolute(media['url'], article_url)
    for enc in entry.get('enclosures', []) or []:
        href = enc.get('href','')
        if href and (enc.get('type','').startswith('image') or re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', href, re.I)):
            return absolute(href, article_url)
    _, image, _ = page_meta(article_url)
    return image

def parse_source(src):
    feed_url = discover_feed(src['url'])
    items = []
    if feed_url:
        try:
            data, _, _ = fetch(feed_url, 1_200_000)
            feed = feedparser.parse(data)
            for entry in feed.entries[:20]:
                link = entry.get('link','').strip()
                title = clean(entry.get('title',''))
                if not link or not title:
                    continue
                items.append({
                    'source': src['name'], 'type': src['type'], 'title': title,
                    'url': link, 'image': entry_image(entry, link),
                    'published': entry.get('published') or entry.get('updated') or ''
                })
        except Exception:
            pass
    if not items:
        try:
            data, _, final_url = fetch(src['url'], 1_200_000)
            soup = BeautifulSoup(data, 'html.parser')
            seen = set()
            for a in soup.find_all('a', href=True):
                href = absolute(a['href'], final_url)
                text = clean(a.get_text(' ', strip=True))
                if not text or len(text) < 25 or href in seen or not href.startswith('http'):
                    continue
                if href.rstrip('/') == final_url.rstrip('/'):
                    continue
                if any(x in href.lower() for x in ['/login','/privacy','/termos','/contato','/anuncie','/sobre']):
                    continue
                seen.add(href)
                title, image, _ = page_meta(href)
                items.append({'source':src['name'],'type':src['type'],'title':title or text,'url':href,'image':image,'published':''})
                if len(items) >= 12:
                    break
        except Exception:
            pass
    return items

now = datetime.now(timezone.utc).isoformat()
all_news = []
new = {'updated_at': now, 'sources': []}
for src in sources:
    item = {**src, 'checked_at': now, 'status': 'erro', 'changed': False, 'http_status': None, 'content_hash': None}
    try:
        data, status, _ = fetch(src['url'], 700_000)
        digest = hashlib.sha256(re.sub(rb'\s+', b' ', data)).hexdigest()
        previous = old.get('sources_by_name', {}).get(src['name'], {})
        item.update({'http_status':status,'content_hash':digest,'changed':bool(previous.get('content_hash')) and previous.get('content_hash') != digest,'status':'ok'})
        all_news.extend(parse_source(src))
    except Exception as e:
        item['error'] = type(e).__name__
    new['sources'].append(item)

seen = set(); unique = []
for item in all_news:
    key = item['url'].split('#')[0].rstrip('/')
    if key in seen:
        continue
    seen.add(key)
    unique.append(item)
# Keep a large rolling pool: 120 items instead of the previous 36.
unique = unique[:120]
with open(os.path.join(BASE, 'news.json'), 'w', encoding='utf-8') as f:
    json.dump({'updated_at':now,'items':unique}, f, ensure_ascii=False, indent=2)

new['sources_by_name'] = {x['name']: x for x in new['sources']}
new['summary'] = {
    'total':len(sources),
    'ok':sum(x['status']=='ok' for x in new['sources']),
    'errors':sum(x['status']=='erro' for x in new['sources']),
    'changed':sum(x['changed'] for x in new['sources']),
    'news_found':len(unique),
    'automatic_publication':False
}
with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(new, f, ensure_ascii=False, indent=2)
print(json.dumps(new['summary'], ensure_ascii=False))
