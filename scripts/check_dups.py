#!/usr/bin/env python3
"""후보 JSON(cand_*.json)을 직전 2회차 제목(prev_titles.txt)과 4-gram 자카드 유사도로 비교해 표로 출력.
사용: python3 scripts/check_dups.py [--work work] [--th 0.30]"""
import argparse, json, os, re, glob
ap = argparse.ArgumentParser()
ap.add_argument('--work', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work'))
ap.add_argument('--th', type=float, default=0.30)
a = ap.parse_args(); OUT = os.path.join(os.path.abspath(a.work), 'out')
prev = [l.split('\t') for l in open(f'{OUT}/prev_titles.txt', encoding='utf-8').read().splitlines() if l.strip()]
def ng(s):
    s = re.sub(r'[^\w가-힣]', '', s); return {s[i:i+4] for i in range(len(s)-3)}
P = [(c, t, ng(t)) for c, d, t in prev]
exact = {t for _, _, t in prev}
for f in sorted(glob.glob(f'{OUT}/cand_*.json')):
    for ch, items in json.load(open(f, encoding='utf-8')).items():
        print(f'\n## {ch} ({len(items)})')
        for it in items:
            n = ng(it['주제'])
            best = max(((len(n & p) / len(n | p)) if n | p else 0, c, t) for c, t, p in P)
            flag = '  !!EXACT' if it['주제'] in exact else (f'  !!SIM {best[0]:.2f} {best[1]}:{best[2][:30]}' if best[0] > a.th else '')
            print(f"{it['No']:>2} [{it['형식']}/{it['카테고리']}/{it['권장 길이']}] {it['주제']} ({len(it['주제'])}){flag}")
