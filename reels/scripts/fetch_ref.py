#!/usr/bin/env python3
"""레퍼런스 1개를 '뜯을' 재료를 내려받는다: 메타 · 대본(타임스탬프) · 화면 캡처.
분석(대본 구조·번역·화면 분석·새 대본 5개)은 Claude가 /ref-analyze 스킬로 이 재료를 읽고 쓴다.

  python3 reels/scripts/fetch_ref.py <url 또는 refs id> [--frames] [--cookies-from-browser chrome] [--whisper]

출력: reels/data/analysis/<id>/
  meta.json        제목·작성자·수치·길이
  transcript.json  [{"start": 0.0, "end": 2.1, "text": "…"}]  (자막 없으면 빈 배열 + meta.transcript_source = "없음")
  transcript.txt   [mm:ss] 줄 단위
  frames/          --frames 일 때: 첫 3초는 1초마다(f_000.jpg…), 이후 2초마다 최대 40장

필요: yt-dlp, (frames) ffmpeg, (--whisper) pip install faster-whisper
틱톡은 /video/<숫자> 링크(쿠키 불필요). 인스타는 공개 릴스만. 로그인 벽에 막히면 --cookies-from-browser chrome 을 붙인다(본인 브라우저 로그인 사용).
"""
import argparse, glob, json, os, re, subprocess, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ap = argparse.ArgumentParser()
ap.add_argument('ref'); ap.add_argument('--frames', action='store_true'); ap.add_argument('--whisper', action='store_true')
ap.add_argument('--cookies-from-browser')
a = ap.parse_args()

url = a.ref
if not url.startswith('http'):
    db = os.path.join(ROOT, 'data', 'refs.jsonl')
    refs = {json.loads(l)['id']: json.loads(l) for l in open(db, encoding='utf-8') if l.strip()}
    url = refs[a.ref]['url']
m = re.search(r'(?:v=|shorts/|youtu\.be/)([\w-]{11})', url)
t = re.search(r'tiktok\.com/.*?/video/(\d+)', url)
rid = f'yt_{m.group(1)}' if m else (f'tt_{t.group(1)}' if t else 'ig_' + re.search(r'/(?:reels?|p)/([\w-]+)', url).group(1))
OUT = os.path.join(ROOT, 'data', 'analysis', rid); os.makedirs(OUT, exist_ok=True)

import yt_dlp
base = {'quiet': True, 'no_warnings': True}
if a.cookies_from_browser: base['cookiesfrombrowser'] = (a.cookies_from_browser,)
need_media = a.frames or a.whisper
opts = {**base, 'skip_download': not need_media, 'outtmpl': os.path.join(OUT, 'media.%(ext)s'),
        'format': 'bv*[height<=720]+ba/b[height<=720]/b', 'merge_output_format': 'mp4', 'ignoreerrors': False}
with yt_dlp.YoutubeDL(opts) as y:
    info = y.extract_info(url, download=True)

# 자막은 따로 받는다 — 실패(429 등)해도 영상·화면은 살린다. 원어 자막을 먼저, 자동 번역 자막은 요청하지 않는다.
lang = (info.get('language') or '').split('-')[0]
have = set(info.get('subtitles') or {}) | set(info.get('automatic_captions') or {})
want = [l for l in ([f'{lang}-orig', lang] if lang else []) + ['ko-orig', 'en-orig', 'ko', 'en'] if l in have]
for l in list(dict.fromkeys(want))[:2]:
    try:
        with yt_dlp.YoutubeDL({**base, 'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True,
                               'subtitleslangs': [l], 'subtitlesformat': 'json3', 'sleep_interval_subtitles': 1,
                               'outtmpl': os.path.join(OUT, 'media.%(ext)s')}) as y:
            y.extract_info(url, download=True)
        if glob.glob(os.path.join(OUT, 'media.*.json3')): break
    except Exception as e:
        print(f'! 자막({l}) 받기 실패: {str(e)[:120]}', file=sys.stderr)

up = info.get('upload_date')
meta = {'id': rid, 'url': url, 'title': info.get('title'), 'description': (info.get('description') or '')[:1500],
        'author': info.get('channel') or info.get('uploader'), 'author_followers': info.get('channel_follower_count'),
        'views': info.get('view_count'), 'likes': info.get('like_count'), 'comments': info.get('comment_count'),
        'duration': info.get('duration'), 'uploaded': f'{up[:4]}-{up[4:6]}-{up[6:]}' if up else None,
        'language': info.get('language')}

segs, src = [], '없음'
subs = sorted(glob.glob(os.path.join(OUT, 'media.*.json3')), key=lambda p: (0 if (meta['language'] or 'x')[:2] in os.path.basename(p) else 1, p))
if subs:
    j = json.load(open(subs[0], encoding='utf-8'))
    for ev in j.get('events', []):
        t = ''.join(s.get('utf8', '') for s in ev.get('segs', [])).replace('\n', ' ').strip()
        if t:
            st = ev.get('tStartMs', 0) / 1000
            segs.append({'start': round(st, 2), 'end': round(st + ev.get('dDurationMs', 0) / 1000, 2), 'text': t})
    src = '자막 ' + os.path.basename(subs[0]).split('.')[-2]

media = next((p for p in glob.glob(os.path.join(OUT, 'media.*')) if p.rsplit('.', 1)[-1] in ('mp4', 'webm', 'mkv', 'mov')), None)
if not segs and a.whisper and media:
    try:
        from faster_whisper import WhisperModel
        for s in WhisperModel('small', compute_type='int8').transcribe(media)[0]:
            segs.append({'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip()})
        src = 'whisper small (음성 인식 — 오인식 가능, 원문 확인 필요)'
    except ImportError:
        print('! faster-whisper 미설치: pip install faster-whisper', file=sys.stderr)

if a.frames and media:
    fd = os.path.join(OUT, 'frames'); os.makedirs(fd, exist_ok=True)
    run = lambda *c: subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *c], check=False)
    run('-i', media, '-t', '3', '-vf', 'fps=1,scale=-2:640', os.path.join(fd, 'f_0%02d.jpg'))          # 첫 3초 = 후킹 화면
    run('-ss', '3', '-i', media, '-vf', 'fps=1/2,scale=-2:640', '-frames:v', '40', os.path.join(fd, 'g_%03d.jpg'))  # g_001 = 3초, 이후 2초 간격
    meta['frames'] = len(glob.glob(os.path.join(fd, '*.jpg')))
    meta['frames_note'] = 'f_0NN = N-1초, g_NNN = 3 + (NNN-1)*2 초'

meta['transcript_source'] = src; meta['segments'] = len(segs)
json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(segs, open(os.path.join(OUT, 'transcript.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
with open(os.path.join(OUT, 'transcript.txt'), 'w', encoding='utf-8') as f:
    for s in segs: f.write(f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}\n")
print(f"{rid}: 대본 {len(segs)}줄 ({src}) · 화면 {meta.get('frames', 0)}장 → {os.path.relpath(OUT)}")
if not segs: print('대본이 없습니다 — --whisper 로 다시 받거나, 화면(--frames)의 자막 텍스트를 읽어 대본을 복원하세요.')
