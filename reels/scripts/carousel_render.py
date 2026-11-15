#!/usr/bin/env python3
"""캐러셀(카드뉴스) 자동 제작: 스펙 JSON → 1080×1350 PNG 여러 장 + caption.txt

  python3 reels/scripts/carousel_render.py reels/specs/<이름>.json [--out reels/out/carousel]
  python3 reels/scripts/carousel_render.py --lint-only reels/specs/<이름>.json

스펙:
{
  "channel": "손해사정사",            // config.json channels 의 키 → 브랜드명·포인트 색·법규
  "theme": "paper" | "night" | "clean",
  "slug": "claim-3years",
  "source_ref": "yt_xxx",            // 구조를 빌린 레퍼런스 id (기록용, 화면에 안 나옴)
  "caption": "게시글 캡션…",
  "hashtags": ["보험금청구"],
  "slides": [
    {"type": "cover", "kicker": "…", "title": "…", "subtitle": "…"},
    {"type": "point", "no": "01", "heading": "…", "body": "…", "bullets": ["…"]},
    {"type": "checklist", "heading": "…", "items": ["…"]},
    {"type": "compare", "heading": "…", "left": {"label": "…", "items": ["…"]}, "right": {"label": "…", "items": ["…"]}},
    {"type": "quote", "text": "…", "by": "…"},
    {"type": "cta", "heading": "…", "body": "…", "action": "저장해 두고 필요할 때 꺼내 보세요"}
  ]
}
규칙(자동 점검): 5~10장, 첫 장 cover·마지막 장 cta, 제목 28자 이내 권장, 법규 금지 표현 경고, 글자가 넘치면 자동 축소.
필요: pip install playwright && playwright install chromium   (한글 글꼴: Pretendard 또는 OS 기본 고딕)
"""
import argparse, html, json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CFG = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
ap = argparse.ArgumentParser()
ap.add_argument('spec'); ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'carousel')); ap.add_argument('--lint-only', action='store_true')
a = ap.parse_args()
S = json.load(open(a.spec, encoding='utf-8'))
ch = CFG['channels'].get(S.get('channel'), {})
brand, accent, law = ch.get('brand', S.get('channel', '')), S.get('accent') or ch.get('accent', '#374785'), ch.get('law', '')

# ---------- 점검 ----------
BAN = {
    '공통': ['100%', '완치', '무조건', '반드시 낫', '부작용 없', '부작용이 없'],
    '의료광고법': ['최고', '유일', '최초', '보장', '전후 사진', '비포 애프터', '확실한 효과', '통증 없'],
    '화장품법': ['치료', '재생', '항염', '주름 제거', '여드름 치료', '피부과 수준'],
    '의료기기법': ['최고', '완벽', '청력 회복', '보장'],
    '보험(개별 약관)': ['무조건 받', '100% 지급', '전액 보장'],
}
texts = []
def walk(o):
    if isinstance(o, str): texts.append(o)
    elif isinstance(o, dict): [walk(v) for k, v in o.items() if k != 'type']
    elif isinstance(o, list): [walk(v) for v in o]
walk(S['slides']); walk(S.get('caption', ''))
warn, err = [], []
sl = S['slides']
if not 5 <= len(sl) <= 10: err.append(f'슬라이드 {len(sl)}장 (5~10장)')
if sl[0]['type'] != 'cover': err.append('첫 장은 cover')
if sl[-1]['type'] != 'cta': err.append('마지막 장은 cta')
for i, s in enumerate(sl, 1):
    h = s.get('title') or s.get('heading') or ''
    if len(h) > 28: warn.append(f'{i}장 제목 {len(h)}자 (28자 이내 권장): {h}')
    if s['type'] == 'point' and len(s.get('body', '')) > 120: warn.append(f'{i}장 본문 {len(s["body"])}자 — 한 장 한 메시지로 줄이기')
keys = ['공통'] + [k for k in BAN if k != '공통' and k.split('(')[0] in law]
for k in keys:
    for w in BAN[k]:
        for t in texts:
            if w in t: warn.append(f'[{k}] 금지·주의 표현 "{w}": {t[:40]}')
for w in ch.get('ban', []):
    if any(w in t for t in texts): err.append(f'채널 금지 테마 "{w}"')
if '보험' in law and not any('약관' in t for t in texts): warn.append('보험 채널: "개별 약관에 따라 다름" 문구가 없음')
for m in warn: print('⚠', m)
for m in err: print('✖', m)
if err: sys.exit(1)
if a.lint_only: print('lint 통과' + (f' (경고 {len(warn)})' if warn else '')); sys.exit(0)

# ---------- 렌더 ----------
THEMES = {
    'paper': dict(bg='#F4EFE6', ink='#1F1B16', sub='#6B6257', card='#FBF8F2', line='#D9D0C1'),
    'night': dict(bg='#14161A', ink='#F2F0EB', sub='#A7A39A', card='#1D2026', line='#30343C'),
    'clean': dict(bg='#FFFFFF', ink='#15181D', sub='#5C6470', card='#F3F5F8', line='#DDE2E8'),
}
T = THEMES[S.get('theme', 'paper')]
e = lambda s: html.escape(str(s or '')).replace('\n', '<br>')
def em(s):  # **강조** → 포인트 색
    return re.sub(r'\*\*(.+?)\*\*', r'<em>\1</em>', e(s))
def ul(items, cls='ul'): return f'<ul class="{cls}">' + ''.join(f'<li>{em(x)}</li>' for x in items or []) + '</ul>'

def body(s):
    t = s['type']
    if t == 'cover':
        return f'<div class="cover"><div class="kicker">{e(s.get("kicker"))}</div><h1>{em(s["title"])}</h1><p class="lead">{em(s.get("subtitle"))}</p><div class="swipe">넘겨서 보기 →</div></div>'
    if t == 'point':
        return f'<div class="no">{e(s.get("no"))}</div><h2>{em(s["heading"])}</h2><p class="body">{em(s.get("body"))}</p>{ul(s.get("bullets")) if s.get("bullets") else ""}'
    if t == 'checklist':
        return f'<h2>{em(s["heading"])}</h2>{ul(s["items"], "check")}'
    if t == 'compare':
        col = lambda c, k: f'<div class="col {k}"><div class="label">{e(c["label"])}</div>{ul(c["items"])}</div>'
        return f'<h2>{em(s["heading"])}</h2><div class="cmp">{col(s["left"], "l")}{col(s["right"], "r")}</div>'
    if t == 'quote':
        return f'<div class="quote"><div class="mark">“</div><p>{em(s["text"])}</p><div class="by">{e(s.get("by"))}</div></div>'
    if t == 'cta':
        return f'<div class="cta"><h2>{em(s["heading"])}</h2><p class="body">{em(s.get("body"))}</p><div class="btn">{e(s.get("action") or "저장해 두고 필요할 때 꺼내 보세요")}</div></div>'
    raise ValueError(t)

CSS = f'''
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1080px;height:1350px}}
body{{background:{T['bg']};color:{T['ink']};font-family:Pretendard,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR","Noto Sans CJK KR",sans-serif;
 word-break:keep-all;overflow-wrap:break-word;-webkit-font-smoothing:antialiased}}
.page{{position:relative;width:1080px;height:1350px;padding:96px 88px 150px;display:flex;flex-direction:column}}
.top{{display:flex;justify-content:space-between;align-items:center;font-size:28px;font-weight:600;color:{T['sub']};letter-spacing:.02em}}
.top .dot{{display:inline-block;width:14px;height:14px;border-radius:50%;background:{accent};margin-right:14px;vertical-align:1px}}
.fit{{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0;transform-origin:center left}}
em{{font-style:normal;color:{accent}}}
h1{{font-size:104px;line-height:1.16;font-weight:800;letter-spacing:-.035em;text-wrap:balance}}
h2{{font-size:72px;line-height:1.22;font-weight:800;letter-spacing:-.03em;margin-bottom:44px;text-wrap:balance}}
.kicker{{font-size:34px;font-weight:700;color:{accent};margin-bottom:36px;letter-spacing:.01em}}
.lead{{font-size:42px;line-height:1.5;color:{T['sub']};margin-top:44px;font-weight:500}}
.swipe{{margin-top:72px;font-size:30px;font-weight:700;color:{T['ink']};opacity:.55}}
.no{{font-size:40px;font-weight:800;color:{accent};margin-bottom:28px;font-variant-numeric:tabular-nums}}
.body{{font-size:44px;line-height:1.55;font-weight:500}}
ul{{list-style:none;margin-top:40px;display:flex;flex-direction:column;gap:22px}}
li{{font-size:40px;line-height:1.45;font-weight:500;background:{T['card']};border:2px solid {T['line']};border-radius:22px;padding:28px 34px}}
.check li{{padding-left:92px;position:relative}}
.check li::before{{content:"";position:absolute;left:34px;top:34px;width:34px;height:34px;border-radius:9px;border:4px solid {accent}}}
.check li::after{{content:"";position:absolute;left:46px;top:38px;width:11px;height:20px;border:solid {accent};border-width:0 5px 5px 0;transform:rotate(42deg)}}
.cmp{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
.col{{background:{T['card']};border:2px solid {T['line']};border-radius:26px;padding:34px 30px}}
.col.r{{border-color:{accent}}}
.col .label{{font-size:34px;font-weight:800;margin-bottom:8px}} .col.r .label{{color:{accent}}}
.col ul{{margin-top:22px;gap:14px}} .col li{{font-size:34px;border:0;background:none;padding:0;border-top:2px solid {T['line']};border-radius:0;padding-top:16px}}
.quote .mark{{font-size:200px;line-height:.6;color:{accent};font-weight:800}}
.quote p{{font-size:64px;line-height:1.35;font-weight:700;letter-spacing:-.02em;text-wrap:balance}}
.quote .by{{margin-top:44px;font-size:32px;color:{T['sub']};font-weight:600}}
.cta .btn{{display:inline-block;margin-top:56px;background:{accent};color:#fff;font-size:38px;font-weight:800;padding:30px 44px;border-radius:999px}}
.foot{{position:absolute;left:88px;right:88px;bottom:64px;display:flex;justify-content:space-between;align-items:flex-end;font-size:24px;color:{T['sub']};border-top:2px solid {T['line']};padding-top:22px;gap:24px}}
.foot .n{{font-weight:800;font-variant-numeric:tabular-nums;color:{T['ink']};white-space:nowrap}}
'''
note = S.get('disclaimer') or {'의료광고법': '개인에 따라 결과가 다를 수 있으며, 진료는 의료진과 상담하세요.', '화장품법': '개인차가 있을 수 있습니다.',
       '의료기기법': '개인에 따라 효과가 다를 수 있습니다.'}.get(law.split('·')[0], '개별 약관에 따라 다를 수 있습니다.' if '보험' in law else '')
def page(s, i, n):
    return f'<!doctype html><html lang="ko"><meta charset="utf-8"><style>{CSS}</style><body><div class="page"><div class="top"><span><span class="dot"></span>{e(brand)}</span><span>{e(S.get("series", ""))}</span></div><div class="fit"><div class="inner">{body(s)}</div></div><div class="foot"><span>{e(note)}</span><span class="n">{i} / {n}</span></div></div></body></html>'

from playwright.sync_api import sync_playwright
import datetime as dt
out = os.path.join(a.out, f"{dt.date.today().isoformat()}_{S.get('channel','')}_{S.get('slug','carousel')}"); os.makedirs(out, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1080, 'height': 1350}, device_scale_factor=1)
    for i, s in enumerate(sl, 1):
        pg.set_content(page(s, i, len(sl))); pg.evaluate('document.fonts.ready')
        scale = pg.evaluate('''() => { const f = document.querySelector('.fit'), n = document.querySelector('.inner'); let z = 1;
            while (n.scrollHeight > f.clientHeight && z > 0.6) { z -= 0.04; n.style.zoom = z; } return z; }''')
        if scale < 0.8: print(f'⚠ {i}장 글이 많아 {scale:.0%}로 축소됨 — 내용을 줄이는 편이 좋음')
        pg.screenshot(path=os.path.join(out, f'{i:02d}.png'))
    b.close()
cap = S.get('caption', '') + ('\n\n' + ' '.join('#' + h for h in S['hashtags']) if S.get('hashtags') else '')
open(os.path.join(out, 'caption.txt'), 'w', encoding='utf-8').write(cap)
json.dump(S, open(os.path.join(out, 'spec.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{len(sl)}장 → {os.path.relpath(out)}')
