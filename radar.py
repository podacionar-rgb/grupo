import hashlib, json, os, re, urllib.request
from datetime import datetime, timezone

UA = 'GTOCRB-Radar/1.0 (+https://github.com/podacionar-rgb/grupo)'
BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, 'radar-sources.json'), encoding='utf-8') as f:
    sources = json.load(f)

state_path = os.path.join(BASE, 'radar-status.json')
try:
    with open(state_path, encoding='utf-8') as f:
        old = json.load(f)
except FileNotFoundError:
    old = {}

now = datetime.now(timezone.utc).isoformat()
new = {'updated_at': now, 'sources': []}
for src in sources:
    item = {**src, 'checked_at': now, 'status': 'erro', 'changed': False, 'http_status': None, 'content_hash': None}
    try:
        req = urllib.request.Request(src['url'], headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(700_000)
            item['http_status'] = getattr(r, 'status', 200)
        text = re.sub(rb'\s+', b' ', data)
        digest = hashlib.sha256(text).hexdigest()
        item['content_hash'] = digest
        previous = old.get('sources_by_name', {}).get(src['name'], {})
        item['changed'] = bool(previous.get('content_hash')) and previous.get('content_hash') != digest
        item['status'] = 'ok'
    except Exception as e:
        item['error'] = type(e).__name__
    new['sources'].append(item)

new['sources_by_name'] = {x['name']: x for x in new['sources']}
new['summary'] = {
    'total': len(sources),
    'ok': sum(x['status'] == 'ok' for x in new['sources']),
    'errors': sum(x['status'] == 'erro' for x in new['sources']),
    'changed': sum(x['changed'] for x in new['sources']),
    'automatic_publication': False,
}
with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(new, f, ensure_ascii=False, indent=2)
print(json.dumps(new['summary'], ensure_ascii=False))
