#!/usr/bin/env python3
"""63개 주제 → CSV(UTF-8 BOM) + 건강한마케팅 페이지 재조립 파트(p0/p1../footer).

사용:
  python3 scripts/gen.py --date 2026-11-17 [--file file-upload://ID]
    --date  이번 회차 날짜(화요일). 월/주차/요일은 자동 계산(RUNBOOK 4-2절 4항 ISO식).
    --file  업로드된 CSV의 file-upload://ID. 생략하면 FILE_PLACEHOLDER (CSV만 먼저 만들 때).
    --work  작업 폴더(기본: 이 저장소의 work/). work/out/ 에 cand_*.json, health_raw.md 가 있어야 한다.
입력: work/topics.py (SEL/TITLE/EVIDENCE/THEME), work/out/cand_{beauty,medical,life}.json, work/out/health_raw.md
출력: work/out/전체7개채널_63개주제_{date}_한글수정.csv, csv_body.txt(업로드용·BOM 없음),
      block.md(회차 블록), p0_head.md, p{k}_past.md, p{n}_footer.md, full_filled.md
"""
import argparse, csv, datetime as dt, json, os, re, sys

ap = argparse.ArgumentParser()
ap.add_argument('--date', required=True)
ap.add_argument('--file', default='FILE_PLACEHOLDER')
ap.add_argument('--work', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work'))
ap.add_argument('--test', action='store_true', help='회차명 뒤에 (테스트 발행) 붙임')
a = ap.parse_args()
WORK = os.path.abspath(a.work); OUT = os.path.join(WORK, 'out')
sys.path.insert(0, WORK)
from topics import SEL, TITLE, DISPLAY, PD, THEME, EVIDENCE  # noqa

d = dt.date.fromisoformat(a.date)
WD = '월화수목금토일'[d.weekday()]
MD = f'{d.month}/{d.day}'
first = d.replace(day=1)
# ISO식 주차: 1일이 월~목이면 그 주가 1주차, 금~일이면 다음 주가 1주차
monday1 = first - dt.timedelta(days=first.weekday())
if first.weekday() >= 4:
    monday1 += dt.timedelta(days=7)
WEEK = (d - dt.timedelta(days=d.weekday()) - monday1).days // 7 + 1
assert WEEK >= 1, '이 날짜는 전 달 마지막 주에 속함(월 전환 처리 필요)'
SUFFIX = ' (테스트 발행)' if a.test or WD != '화' else ''
print(f'회차: {a.date} ({WD}) = {d.month}월 {WEEK}주차{SUFFIX}')

ORDER = ["유이선생", "스타라인", "성장인", "코스모어", "홍성옥교수", "킴스히어링", "손해사정사"]
cands = {}
for g in ['beauty', 'medical', 'life']:
    cands.update(json.load(open(f'{OUT}/cand_{g}.json', encoding='utf-8')))

rows, topics = [], {}
for ch in ORDER:
    byno = {c['No']: c for c in cands[ch]}
    sel = [byno[n] for n in SEL[ch]]
    assert sum(c['형식'] == '롱폼' for c in sel) == 6 and sum(c['형식'] == '숏폼' for c in sel) == 3, ch
    lst = []
    for i, c in enumerate(sel, 1):
        t = TITLE.get((ch, c['No']), c['주제']).strip()
        t = re.sub(r'\s*30초\(숏폼\)$', '', t)
        assert len(t) <= 50, (ch, t, len(t))
        ev = EVIDENCE.get((ch, c['No']), c['벤치마크 근거'])
        lst.append({**c, '주제': t, 'No': i})
        rows.append([ch, i, t, c['키워드'], c['카테고리'], c['형식'], c['권장 길이'], ev, c['핵심 스토리라인'], '', '', '', ''])
    topics[ch] = lst
assert len(rows) == 63
HDR = ['채널', 'No', '주제(가제)', '키워드', '카테고리', '형식', '권장 길이', '벤치마크 근거', '핵심 스토리라인', '구독자수', '조회수', '좋아요', '댓글수']
csv_name = f'전체7개채널_63개주제_{a.date}_한글수정.csv'
with open(f'{OUT}/{csv_name}', 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f); w.writerow(HDR); w.writerows(rows)
with open(f'{OUT}/csv_body.txt', 'w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow(HDR); w.writerows(rows)

def esc(s):
    return s.replace('~', '\\~').replace('|', '\\|').replace('*', '\\*').replace('_', '\\_')
def titles(ch):
    return ' / '.join(esc(t['주제']) for t in topics[ch])

kw_rows = '\n'.join(f'| {DISPLAY[ch]} | {esc(THEME[ch][0])} | {THEME[ch][1]} | {PD[ch]} |' for ch in ORDER)
block = f'''### 📄 {MD} ({WD}) — 전체 7개 채널 · 63개 주제{SUFFIX}

<file source="{a.file}" />

<toggle>
채널별 1순위 키워드 한눈에 보기

| 채널 | 1순위 키워드 테마 | 비중(추정) | 담당 |
| --- | --- | --- | --- |
{kw_rows}
</toggle>

<toggle>
성형·피부 계열 27개 주제 (유이 · 스타라인 · 코스모어플러스)

<b>유이성형외과</b> — {titles("유이선생")}

<b>스타라인성형외과</b> — {titles("스타라인")}

<b>코스모어플러스</b> — {titles("코스모어")}
</toggle>

<toggle>
의료 전문 계열 18개 주제 (홍성옥교수 · 강남여성병원)

<b>홍성옥교수</b> — {titles("홍성옥교수")}

<b>강남여성병원</b> — {titles("성장인")}
</toggle>

<toggle>
생활·금융 계열 18개 주제 (킴스히어링 · 손해사정사)

<b>킴스히어링</b> — {titles("킴스히어링")}

<b>손해사정사 박신성</b> — {titles("손해사정사")}
</toggle>'''
open(f'{OUT}/block.md', 'w', encoding='utf-8').write(block)

# ---- 페이지 재조립 ----
raw = open(f'{OUT}/health_raw.md', encoding='utf-8').read()
lines = raw.split('\n')
depth, tops, start = 0, [], None
for i, l in enumerate(lines):
    if l.strip() == '<toggle>':
        if depth == 0: start = i
        depth += 1
    elif l.strip() == '</toggle>':
        depth -= 1
        if depth == 0: tops.append((start, i)); start = None
assert depth == 0
cur = tops[0]
head = '\n'.join(lines[:cur[0]]).rstrip('\n')
cur_txt = '\n'.join(lines[cur[0]:cur[1] + 1])
past = ['\n'.join(lines[s:e + 1]) for s, e in tops[1:]]
footer = '\n'.join(lines[tops[-1][1] + 1:]).strip('\n')
assert footer.startswith('---'), footer[:40]
assert f'# 📅 {d.year}년 {d.month}월' in head, '월이 바뀌었습니다 — RUNBOOK 4-2절 3항(월 전환)을 수동 적용하세요'

# 직전 주차 ' · 최신' 제거
n_latest = cur_txt.count(' · 최신')
assert n_latest == 1, f"' · 최신' {n_latest}개"
cur_txt = cur_txt.replace(' · 최신', '', 1)
# 이번 주차 예정 토글 채우기
pat = re.compile(rf'📂 {d.month}월 {WEEK}주차 \({MD} 화\) — 예정\n\n<callout[^\n]*>\n[^\n]*\n</callout>')
m = pat.search(cur_txt)
assert m, f'예정 토글을 찾지 못함: 📂 {d.month}월 {WEEK}주차 ({MD} 화) — 예정'
cur_txt = cur_txt[:m.start()] + f'📂 {d.month}월 {WEEK}주차 ({MD} 화) · 최신\n\n{block}' + cur_txt[m.end():]

p0 = head + '\n\n' + cur_txt + '\n\n---'
open(f'{OUT}/p0_head.md', 'w', encoding='utf-8').write(p0)
for k, p in enumerate(past, 1):
    open(f'{OUT}/p{k}_past.md', 'w', encoding='utf-8').write(p)
open(f'{OUT}/p{len(past)+1}_footer.md', 'w', encoding='utf-8').write(footer)
full = p0 + '\n\n' + '\n\n'.join(past) + '\n\n' + footer
open(f'{OUT}/full_filled.md', 'w', encoding='utf-8').write(full)

assert full.count('<toggle>') == full.count('</toggle>') == raw.count('<toggle>') + 4
assert full.count('<file ') == raw.count('<file ') + 1
assert full.count(' · 최신') == 1
assert full.count('\n# ') == 1
assert full.count('<page url=') == raw.count('<page url=')
print('OK csv rows', len(rows), 'csv bytes', os.path.getsize(f'{OUT}/{csv_name}'),
      '| p0', len(p0), 'past', [len(p) for p in past], 'footer', len(footer), 'full', len(full),
      '| <file>', full.count('<file '), 'toggles', full.count('<toggle>'))
print('parts:', ['p0_head.md'] + [f'p{k}_past.md' for k in range(1, len(past)+1)] + [f'p{len(past)+1}_footer.md'])
