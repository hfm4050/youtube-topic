#!/usr/bin/env python3
"""OpenAI(ChatGPT) API 로 레퍼런스 분석·대본 5개·제작 기획을 만든다 (대시보드 서버가 호출).

  python app/llm_openai.py analysis|scripts5|plan <ref id> --model gpt-6.1-sol [--fit 채널]

표준 라이브러리만 쓴다(Chat Completions REST). 키는 환경변수 OPENAI_API_KEY.
입력: reels/data/analysis/<id>/ 의 meta.json · transcript.txt · frames/ (분석 단계는 화면 이미지를 함께 보낸다)
출력: analysis.md + analysis.json / scripts5.md / plan.md.  마지막 줄에 `COST_JSON {...}` (서버가 건당 비용 기록).
"""
import argparse, base64, glob, json, os, sys, urllib.error, urllib.request

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
ap = argparse.ArgumentParser()
ap.add_argument('step', choices=['analysis', 'scripts5', 'plan'])
ap.add_argument('ref')
ap.add_argument('--model', required=True)
ap.add_argument('--fit', default='')
a = ap.parse_args()
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

KEY = os.environ.get('OPENAI_API_KEY')
if not KEY:
    sys.exit('OPENAI_API_KEY 가 없습니다. 대시보드 「API 키 설정」에서 ChatGPT(OpenAI) 키를 등록하세요.')
D = os.path.join(ROOT, 'reels', 'data', 'analysis', a.ref)
read = lambda p, d='': open(p, encoding='utf-8').read() if os.path.exists(p) else d
price = next((m for m in json.load(open(os.path.join(APP, 'models.json'), encoding='utf-8'))['models'] if m['id'] == a.model), None)

skill = read(os.path.join(ROOT, '.claude', 'skills', 'ref-analyze', 'SKILL.md'))
cfg = json.load(open(os.path.join(ROOT, 'reels', 'config.json'), encoding='utf-8'))
ch = cfg['channels'].get(a.fit) or {}
ch_txt = (f"대상 채널: {a.fit} ({ch.get('brand', '')}) · 적용 법규: {ch.get('law', '')} · 금지 테마: {', '.join(ch.get('ban', [])) or '없음'}"
          if ch else '대상 채널: 정해지지 않음 — 가장 맞는 채널 하나를 골라 이유를 적는다. 채널 목록: ' + ', '.join(cfg['channels']))
SYSTEM = ('당신은 숏폼·유튜브 레퍼런스를 분석해 한국 병의원·전문직 채널용 콘텐츠를 기획하는 편집자다. 한국어로 쓴다. '
          '수치·경험담·대본을 지어내지 않는다(주어진 meta·대본·화면에 있는 것만). 의료광고법(효과 보장·최상급·전후 비교 금지), '
          '화장품법(의약품 오인 표현 금지), 보험(개별 약관 상이 명시)을 지킨다. 원문의 주장은 검증 전에는 우리 대본에 옮기지 않는다.\n\n'
          '아래는 따라야 할 작업 지침(스킬 문서)이다.\n\n' + skill)
meta, transcript = read(os.path.join(D, 'meta.json'), '{}'), read(os.path.join(D, 'transcript.txt'))
if not os.path.exists(os.path.join(D, 'meta.json')):
    sys.exit(f'재료가 없습니다: {D} — 먼저 「재료 다시 받기」를 실행하세요.')


def frames():
    """첫 3초(f_*) 전부 + 이후(g_*)는 고르게 최대 10장."""
    fs = sorted(glob.glob(os.path.join(D, 'frames', 'f_*.jpg')))
    gs = sorted(glob.glob(os.path.join(D, 'frames', 'g_*.jpg')))
    if len(gs) > 10:
        gs = [gs[round(i * (len(gs) - 1) / 9)] for i in range(10)]
    return fs + gs


def call(user_parts, json_mode=False):
    body = {'model': a.model, 'max_completion_tokens': 16000,
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user_parts}]}
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(body).encode('utf-8'),
                                 headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    try:
        return json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', 'replace')
        try:
            msg = json.loads(msg)['error']['message']
        except Exception:
            pass
        raise RuntimeError(f'OpenAI API 오류 {e.code}: {msg[:500]}')


usage = {'in': 0, 'cached': 0, 'out': 0}
def run(text, images=(), json_mode=False):
    parts = [{'type': 'text', 'text': text}]
    for p in images:
        parts.append({'type': 'text', 'text': f'[화면 {os.path.basename(p)}]'})
        parts.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(open(p, 'rb').read()).decode(), 'detail': 'low'}})
    try:
        r = call(parts, json_mode)
    except RuntimeError as e:
        if not images:
            raise
        print(f'! 이미지 입력 실패 → 글만으로 다시 시도합니다: {e}', flush=True)
        r = call([{'type': 'text', 'text': text + '\n\n(화면 이미지는 전달하지 못했다. 화면 분석은 "화면 확인 못 함"으로 적는다.)'}], json_mode)
    u = r.get('usage') or {}
    usage['in'] += u.get('prompt_tokens') or 0
    usage['out'] += u.get('completion_tokens') or 0
    usage['cached'] += ((u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)
    ch0 = r['choices'][0]
    if ch0.get('finish_reason') == 'length':
        print('! 출력이 길이 제한에 걸려 잘렸을 수 있습니다.', flush=True)
    return ch0['message'].get('content') or ''


base = f'## 레퍼런스 meta.json\n{meta}\n\n## 대본 transcript.txt (타임스탬프)\n{transcript or "(자막 없음 — 화면 속 자막에서 복원하고 그렇게 표시한다)"}\n'
if a.step == 'analysis':
    imgs = frames()
    print(f'화면 {len(imgs)}장 + 대본을 {a.model} 에 보냅니다…', flush=True)
    names = ', '.join(os.path.basename(p) for p in imgs)
    out = run(base + f'\n## 전달한 화면 파일\n{names}\n(f_0NN.jpg = N-1초, g_NNN.jpg = 3 + (NNN-1)×2 초)\n\n'
              '## 할 일\n스킬 문서의 "② analysis.md (화면·대본 분석)"만 수행한다. ③④는 하지 않는다.\n'
              '결과를 JSON 객체 하나로 돌려준다: {"analysis_md": "<다섯 부분을 담은 마크다운 전문>", "analysis_json": {<아래 스키마>}}\n'
              'analysis_json 의 frames[].file 은 위 "전달한 화면 파일"에 있는 이름만 쓴다.\n\n'
              '## analysis_json 스키마\n' + read(os.path.join(APP, 'analysis_schema.md')), imgs, json_mode=True)
    d = json.loads(out)
    open(os.path.join(D, 'analysis.md'), 'w', encoding='utf-8').write(d['analysis_md'])
    json.dump(d['analysis_json'], open(os.path.join(D, 'analysis.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"analysis.md {len(d['analysis_md']):,}자 · analysis.json 저장", flush=True)
else:
    ana = read(os.path.join(D, 'analysis.md'))
    if not ana:
        sys.exit('analysis.md 가 없습니다. 먼저 분석을 실행하세요.')
    if a.step == 'scripts5':
        print(f'분석 결과로 대본 5개를 {a.model} 에 요청합니다…', flush=True)
        out = run(base + f'\n## analysis.md\n{ana}\n\n## {ch_txt}\n\n## 할 일\n스킬 문서의 "③ scripts5.md (대본 5개)"만 수행해 마크다운 전문만 돌려준다(코드 블록으로 감싸지 않는다). '
                  '구조만 빌리고 내용은 대상 채널 분야로 새로 쓴다. 마지막에 비교 표를 넣는다.')
        open(os.path.join(D, 'scripts5.md'), 'w', encoding='utf-8').write(out)
        print(f'scripts5.md {len(out):,}자 저장', flush=True)
    else:
        s5 = read(os.path.join(D, 'scripts5.md'))
        if not s5:
            sys.exit('scripts5.md 가 없습니다. 먼저 대본 5개를 만드세요.')
        print(f'추천 대본의 제작 기획을 {a.model} 에 요청합니다…', flush=True)
        out = run(base + f'\n## analysis.md\n{ana}\n\n## scripts5.md\n{s5}\n\n## {ch_txt}\n\n## 할 일\n스킬 문서의 "④ plan.md (제작 기획)"만 수행해 마크다운 전문만 돌려준다(코드 블록으로 감싸지 않는다). '
                  '비교 표에서 추천된 1~2개 대본에 대해 컷 리스트 표·준비물·촬영 장소·캡션 초안·댓글 유도·첫 프레임·업로드 형식을 쓴다.')
        open(os.path.join(D, 'plan.md'), 'w', encoding='utf-8').write(out)
        print(f'plan.md {len(out):,}자 저장', flush=True)

usd = None
if price:   # 캐시된 입력은 정가의 일부만 받지만 모델마다 달라 정가로 계산한다(실제 청구는 이보다 같거나 적다)
    usd = round((usage['in'] * price['in'] + usage['out'] * price['out']) / 1e6, 4)
print('COST_JSON ' + json.dumps({'usd': usd, 'in': usage['in'], 'out': usage['out'], 'model': a.model}, ensure_ascii=False))
