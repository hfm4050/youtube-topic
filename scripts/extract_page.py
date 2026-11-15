#!/usr/bin/env python3
"""notion-fetch 결과(저장된 tool-result 파일 또는 세션 jsonl)에서 페이지 본문을 추출해
work/out/health_raw.md, structure.txt, prev_titles.txt(직전 2회차 126개 제목)를 만든다.

사용:
  python3 scripts/extract_page.py <fetch 결과 파일> [--work work]
  <fetch 결과 파일> 후보:
    - Claude Code: ~/.claude/projects/<프로젝트 슬러그>/<세션id>.jsonl  (가장 긴 tool_result 중 3ca9025a 포함)
    - Cowork:      /root/.claude/projects/-home-claude/<id>/tool-results/mcp-Notion-notion-fetch-*.txt
    - 또는 본문 마크다운을 그대로 저장한 .md 파일
"""
import argparse, json, os, re, sys

ap = argparse.ArgumentParser()
ap.add_argument('src')
ap.add_argument('--work', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work'))
a = ap.parse_args()
OUT = os.path.join(os.path.abspath(a.work), 'out'); os.makedirs(OUT, exist_ok=True)

def strings(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)

raw = open(a.src, encoding='utf-8', errors='replace').read()
cands = []
if a.src.endswith('.jsonl'):
    for line in raw.splitlines():
        try: cands += [s for s in strings(json.loads(line)) if '<content>' in s]
        except Exception: pass
else:
    try: cands = [s for s in strings(json.loads(raw)) if '<content>' in s]
    except Exception: cands = [raw]
# fetch 결과 text 가 JSON 문자열 안에 또 들어 있는 경우 한 번 더 파싱
more = []
for s in cands:
    try: more += [t for t in strings(json.loads(s)) if '<content>' in t]
    except Exception: pass
cands += more
cands = [c for c in cands if '3ca9025a' in c or '담당 채널' in c] or cands
assert cands, '<content> 를 찾지 못함'
text = max(cands, key=len)
m = re.search(r'<content>\n?(.*?)\n?</content>', text, re.S)
body = m.group(1) if m else text
open(f'{OUT}/health_raw.md', 'w', encoding='utf-8').write(body)

lines = body.split('\n')
struct = []
for i, l in enumerate(lines):
    if l.strip() == '<toggle>' and i + 1 < len(lines): struct.append(lines[i + 1])
    elif l.startswith('### 📄'): struct.append(l)
open(f'{OUT}/structure.txt', 'w', encoding='utf-8').write('\n'.join(struct))

# 직전 2회차 제목: '### 📄 M/D' 블록 중 날짜가 가장 최근인 2개 (이번 달 주차 토글은 오름차순, 지난 달은 내림차순이라 위치로 고르지 않음)
import datetime as _dt
_today = _dt.date.today()
def _key(mm):
    mo, dy = int(mm.group(1)), int(mm.group(2))
    yr = _today.year - (1 if mo > _today.month + 1 else 0)
    return _dt.date(yr, mo, dy)
NAME = {'유이성형외과': '유이선생', '스타라인성형외과': '스타라인', '강남여성병원': '성장인', '코스모어플러스': '코스모어',
        '홍성옥교수': '홍성옥교수', '킴스히어링': '킴스히어링', '손해사정사 박신성': '손해사정사'}
heads = [(i, re.search(r'### 📄 (\d+)/(\d+)', l)) for i, l in enumerate(lines) if l.startswith('### 📄')]
recent = sorted(heads, key=lambda h: _key(h[1]), reverse=True)[:2]
rows = []
for i, mm in recent:
    k = [h[0] for h in heads].index(i)
    end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
    date = f'{mm.group(1)}/{mm.group(2)}'
    for l in lines[i:end]:
        b = re.match(r'<b>(.+?)</b> — (.+)', l)
        if b and b.group(1) in NAME:
            for t in b.group(2).split(' / '):
                rows.append(f"{NAME[b.group(1)]}\t{date}\t{t.strip().replace(chr(92), '')}")
open(f'{OUT}/prev_titles.txt', 'w', encoding='utf-8').write('\n'.join(rows))
print(f'health_raw.md {len(body):,} chars | <toggle> {body.count("<toggle>")}/{body.count("</toggle>")} | <file {body.count("<file ")} | <page url= {body.count("<page url=")}')
print(f'structure.txt {len(struct)} lines | prev_titles.txt {len(rows)} lines (회차 {[l[1].group(0) for l in recent]})')
print('남은 일: prev_hooks.md(채널별 직전 2회차 훅·연속 훅 경고)는 health_raw.md 를 읽고 손으로/에이전트가 작성')
