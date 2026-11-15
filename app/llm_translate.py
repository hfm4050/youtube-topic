#!/usr/bin/env python3
"""해외 레퍼런스의 원문 제목을 한국어 한 줄로 옮겨 refs.jsonl 의 title_ko 에 저장한다 (대시보드가 호출).

  python app/llm_translate.py --model claude-haiku-5-5 --ids yt_abc,ig_def

사람이 적은 topic_ko(한 줄 주제 판단)는 건드리지 않는다. 마지막 줄에 `COST_JSON {...}` 을 찍어 서버가 건당 비용을 기록한다.
"""
import argparse, json, os, re, shutil, subprocess, sys, urllib.error, urllib.request

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
DB = os.path.join(ROOT, 'reels', 'data', 'refs.jsonl')
ap = argparse.ArgumentParser()
ap.add_argument('--model', required=True)
ap.add_argument('--ids', required=True)
a = ap.parse_args()
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

models = json.load(open(os.path.join(APP, 'models.json'), encoding='utf-8'))
price = next((m for m in models['models'] if m['id'] == a.model), None)
if not price:
    sys.exit('알 수 없는 모델입니다: ' + a.model)

want = [x for x in a.ids.split(',') if x.strip()]
lines = [l for l in open(DB, encoding='utf-8') if l.strip()]
refs = [json.loads(l) for l in lines]
by = {r['id']: r for r in refs}
todo = [by[i] for i in want if i in by and (by[i].get('title') or '').strip()]
if not todo:
    sys.exit('번역할 항목이 없습니다.')
print(f'{len(todo)}개 제목을 {price["label"]} 로 옮깁니다…', flush=True)

items = '\n'.join(f"{r['id']}\t{(r.get('title') or '').strip()[:200]}" for r in todo)
PROMPT = (
    '아래는 해외 영상(유튜브·릴스·틱톡) 레퍼런스의 원문 제목이나 캡션이다. 각 항목이 무엇에 관한 영상인지 '
    '한국어 한 줄(공백 포함 40자 이내)로 알기 쉽게 옮겨라.\n'
    '- 직역이 아니라 주제가 드러나게 쓴다. 해시태그·이모지·계정명은 빼고 핵심만 남긴다.\n'
    '- 원문에 없는 수치·주장·효과를 지어내지 않는다. 뜻을 알 수 없으면 그 항목의 값은 빈 문자열로 둔다.\n'
    '- 도구를 쓰지 말고, 설명 없이 JSON 객체 하나만 답한다: {"<id>": "<한국어 한 줄>", ...}\n\n'
    + items)

usage = {'in': 0, 'out': 0}


def strip_fence(t):
    t = t.strip()
    m = re.search(r'\{.*\}', t, re.S)
    return m.group(0) if m else t


if price['engine'] == 'openai':
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        sys.exit('OPENAI_API_KEY 가 없습니다. 「API 키 설정」에서 등록하세요.')
    body = {'model': a.model, 'max_completion_tokens': 8000, 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'user', 'content': PROMPT}]}
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(body).encode('utf-8'),
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        sys.exit(f'OpenAI API 오류 {e.code}: {e.read().decode("utf-8", "replace")[:300]}')
    u = r.get('usage') or {}
    usage['in'], usage['out'] = u.get('prompt_tokens') or 0, u.get('completion_tokens') or 0
    out = r['choices'][0]['message'].get('content') or ''
    usd = round((usage['in'] * price['in'] + usage['out'] * price['out']) / 1e6, 4)
else:
    exe = shutil.which('claude')
    if not exe:
        sys.exit('claude CLI 를 찾지 못했습니다.')
    p = subprocess.run([exe, '-p', PROMPT, '--model', a.model, '--output-format', 'json'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        sys.exit((p.stdout or '') + (p.stderr or ''))
    if isinstance(d, list):
        d = next((x for x in reversed(d) if isinstance(x, dict) and x.get('type') == 'result'), {})
    out, u = d.get('result') or '', d.get('usage') or {}
    usage['in'] = (u.get('input_tokens') or 0) + (u.get('cache_read_input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0)
    usage['out'] = u.get('output_tokens') or 0
    usd = d.get('total_cost_usd')

try:
    got = json.loads(strip_fence(out))
except ValueError:
    print(out[:500], file=sys.stderr)
    sys.exit('모델이 JSON 으로 답하지 않았습니다.')

n = 0
for r in refs:
    v = got.get(r['id'])
    if isinstance(v, str) and v.strip():
        r['title_ko'] = re.sub(r'\s+', ' ', v).strip()[:80]
        n += 1
with open(DB, 'w', encoding='utf-8') as f:                  # 줄 순서는 그대로 두고 값만 갱신
    for r in refs:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f'{n}개 한글 요약 저장', flush=True)
print('COST_JSON ' + json.dumps({'usd': usd, 'in': usage['in'], 'out': usage['out'], 'model': a.model}, ensure_ascii=False))
