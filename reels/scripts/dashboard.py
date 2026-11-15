#!/usr/bin/env python3
"""refs.jsonl → reels/out/dashboard.html (포착 · 검수 대기 · 촬영 대기 보드). 브라우저로 열어 본다.
  python3 reels/scripts/dashboard.py
"""
import html, json, os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
db = os.path.join(ROOT, 'data', 'refs.jsonl')
refs = [json.loads(l) for l in open(db, encoding='utf-8') if l.strip()] if os.path.exists(db) else []
refs.sort(key=lambda r: r.get('outlier') or 0, reverse=True)
e = lambda s: html.escape(str(s if s is not None else ''))
num = lambda n: '—' if n is None else (f'{n/10000:.0f}만' if n >= 10000 else f'{n:,}')
PLAT = {'youtube': '유튜브', 'youtube_shorts': '쇼츠', 'instagram': '릴스', 'tiktok': '틱톡'}
def card(r):
    done = os.path.exists(os.path.join(ROOT, 'data', 'analysis', r['id'], 'analysis.md'))
    th = f'<img loading="lazy" src="{e(r["thumb"])}" alt="">' if r.get('thumb') and r['platform'] != 'instagram' else '<div class="ph">릴스</div>'
    return (f'<a class="card" href="{e(r["url"])}" target="_blank" rel="noopener" data-status="{e(r.get("status"))}" data-region="{e(r.get("region"))}" data-fit="{e(r.get("fit") or "")}">'
            f'<div class="th">{th}<span class="x">{e(r.get("outlier") or "—")}배</span>{"<span class=c>캐러셀 후보</span>" if r.get("carousel_candidate") else ""}</div>'
            f'<div class="t">{e(r.get("topic_ko") or r.get("title") or r["id"])}</div>'
            f'<div class="m">{PLAT.get(r["platform"], "")} · {"해외" if r.get("region") == "GLOBAL" else "국내"} · {e(r.get("fit") or "미배정")}</div>'
            f'<div class="m">조회 {num(r.get("views"))} · 좋아요 {num(r.get("likes"))} · 댓글 {num(r.get("comments"))}</div>'
            f'<div class="m a">@{e(r.get("author") or "")}{" · 분석 완료" if done else ""}</div>'
            f'<div class="j">{e(r.get("note") or r.get("judge") or "")}</div></a>')
cnt = lambda s: sum(1 for r in refs if r.get('status') == s)
fits = sorted({r.get('fit') for r in refs if r.get('fit')})
page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>릴스 파이프라인</title>
<style>
:root{{--bg:#F6F7F9;--card:#fff;--ink:#16191F;--sub:#646C79;--line:#E1E5EB;--ac:#2F5BD3}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121418;--card:#1B1E24;--ink:#ECEEF2;--sub:#9AA2AE;--line:#2C313A;--ac:#7FA2FF}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Pretendard,"Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif}}
header{{padding:20px 24px 0;max-width:1400px;margin:auto}}h1{{font-size:20px;margin:0 0 14px}}
.tabs{{display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--line)}}
.tabs button{{border:0;background:none;color:var(--sub);font:inherit;font-weight:600;padding:10px 14px;cursor:pointer;border-bottom:2px solid transparent}}
.tabs button[aria-selected=true]{{color:var(--ac);border-color:var(--ac)}}
.f{{display:flex;gap:8px;padding:12px 0;flex-wrap:wrap}}select{{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}}
main{{max-width:1400px;margin:auto;padding:8px 24px 48px;display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;color:inherit;text-decoration:none;display:flex;flex-direction:column;padding-bottom:10px}}
.card:hover{{border-color:var(--ac)}}.th{{position:relative;aspect-ratio:4/3;background:var(--line)}}.th img{{width:100%;height:100%;object-fit:cover;display:block}}
.ph{{display:grid;place-items:center;height:100%;color:var(--sub);font-weight:700}}
.x{{position:absolute;left:8px;top:8px;background:#111c;color:#fff;font-weight:800;font-size:13px;padding:2px 8px;border-radius:6px;font-variant-numeric:tabular-nums}}
.c{{position:absolute;right:8px;top:8px;background:var(--ac);color:#fff;font-size:12px;font-weight:700;padding:2px 8px;border-radius:6px}}
.t{{font-weight:700;padding:10px 12px 4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.m,.j{{font-size:12.5px;color:var(--sub);padding:0 12px}}.a{{color:var(--ink)}}.j{{margin-top:4px;font-size:12px}}
.empty{{grid-column:1/-1;color:var(--sub);padding:40px 0;text-align:center}}
</style>
<header><h1>릴스 파이프라인 <span style="color:var(--sub);font-weight:500;font-size:14px">· 수집 {len(refs)}건</span></h1>
<div class="tabs" role="tablist">{''.join(f'<button role="tab" data-s="{s}" aria-selected="{str(s == "검수대기").lower()}">{l} {cnt(s)}</button>' for s, l in [('포착', '포착'), ('검수대기', '검수 대기'), ('촬영대기', '촬영 대기'), ('완료', '완료'), ('제외', '제외')])}</div>
<div class="f"><select id="rg"><option value="">국내·해외 전체</option><option value="KR">국내</option><option value="GLOBAL">해외</option></select>
<select id="ft"><option value="">모든 채널</option>{''.join(f'<option>{e(x)}</option>' for x in fits)}</select></div></header>
<main>{''.join(card(r) for r in refs)}<div class="empty" hidden>해당하는 레퍼런스가 없습니다.</div></main>
<script>
let s='검수대기';const q=x=>document.querySelector(x),cards=[...document.querySelectorAll('.card')];
function go(){{let n=0;const rg=q('#rg').value,ft=q('#ft').value;cards.forEach(c=>{{const ok=c.dataset.status===s&&(!rg||c.dataset.region===rg)&&(!ft||c.dataset.fit===ft);c.hidden=!ok;c.style.display=ok?'':'none';n+=ok}});q('.empty').hidden=n>0}}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{{s=b.dataset.s;document.querySelectorAll('.tabs button').forEach(x=>x.setAttribute('aria-selected',x===b));go()}});
q('#rg').onchange=q('#ft').onchange=go;go();
</script></html>'''
out = os.path.join(ROOT, 'out', 'dashboard.html'); os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, 'w', encoding='utf-8').write(page)
print(f'{len(refs)}건 → {os.path.relpath(out)}')
