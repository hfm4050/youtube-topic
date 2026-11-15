#!/usr/bin/env python3
"""콘텐츠 스튜디오 — 레퍼런스 → 화면·대본 분석 → 대본 5개 → 제작 기획 대시보드 (로컬 웹앱).

  python app/server.py [--port 5180]      → http://localhost:5180

표준 라이브러리만 쓴다. 실제 작업은 기존 스크립트와 Claude Code CLI 에 맡긴다.
  - 링크 추가·수집:  reels/scripts/collect.py (yt-dlp)
  - 재료 내려받기:   reels/scripts/fetch_ref.py --frames
  - 분석·대본·기획:  claude -p (ref-analyze 스킬의 ②③④) → reels/data/analysis/<id>/*.md
업로드는 하지 않는다. 의료·보험 문구는 사람이 검수한다.
"""
import argparse, csv, glob, json, mimetypes, os, re, shutil, subprocess, sys, threading, time, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
REELS = os.path.join(ROOT, 'reels')
DB = os.path.join(REELS, 'data', 'refs.jsonl')
ANA = os.path.join(REELS, 'data', 'analysis')
WORK_OUT = os.path.join(ROOT, 'work', 'out')
ENV = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
STATUSES = ['포착', '검수대기', '촬영대기', '완료', '제외']
STEP_FILE = {'analysis': 'analysis.md', 'scripts5': 'scripts5.md', 'plan': 'plan.md'}
JOBS = {}


def cfg():
    return json.load(open(os.path.join(REELS, 'config.json'), encoding='utf-8'))


def read(p, default=''):
    try:
        return open(p, encoding='utf-8').read()
    except OSError:
        return default


def ref_id(url):
    m = re.search(r'(?:v=|shorts/|youtu\.be/)([\w-]{11})', url)
    if m:
        return 'yt_' + m.group(1)
    m = re.search(r'tiktok\.com/.*?/video/(\d+)', url)
    if m:
        return 'tt_' + m.group(1)
    m = re.search(r'instagram\.com/(?:reels?|p)/([\w-]+)', url)
    return 'ig_' + m.group(1) if m else None


def resolve_short(url):
    """vm.tiktok.com · vt.tiktok.com · tiktok.com/t/ 단축 링크를 /video/<id> 주소로 푼다."""
    if re.search(r'(?:vm|vt)\.tiktok\.com/|tiktok\.com/t/', url):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return urllib.request.urlopen(req, timeout=15).geturl().split('?')[0]
        except Exception:
            return url
    return url


def safe_id(rid):
    return rid if re.fullmatch(r'(yt|ig|tt)_[\w-]+', rid or '') else None


def flags(rid):
    d = os.path.join(ANA, rid)
    fr = sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, 'frames', '*.jpg')))
    return {'fetched': os.path.exists(os.path.join(d, 'meta.json')), 'frame0': fr[0] if fr else None,
            **{k: os.path.exists(os.path.join(d, f)) for k, f in STEP_FILE.items()}}


def load_refs():
    refs = []
    if os.path.exists(DB):
        for l in open(DB, encoding='utf-8'):
            if l.strip():
                r = json.loads(l)
                r.update(flags(r['id']))
                refs.append(r)
    refs.sort(key=lambda r: (r.get('outlier') or 0), reverse=True)
    return refs


# ---------------- 백그라운드 작업 ----------------
def run_job(kind, steps, ref=None):
    """steps: [(설명, argv)] 를 순서대로 실행. 하나라도 실패하면 멈춘다."""
    jid = uuid.uuid4().hex[:10]
    job = JOBS[jid] = {'id': jid, 'kind': kind, 'ref': ref, 'status': 'running', 'log': '', 'started': time.time()}

    def work():
        for label, argv in steps:
            job['log'] += f'\n▶ {label}\n'
            try:
                p = subprocess.Popen(argv, cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
                for line in p.stdout:
                    job['log'] = (job['log'] + line)[-12000:]
                if p.wait() != 0:
                    job['status'] = 'error'
                    if 'authenticate' in job['log'] or 'OAuth' in job['log']:
                        job['log'] += '\n※ Claude Code 로그인이 만료됐습니다. 터미널(cmd)에서 claude 를 실행하고 /login 한 뒤 다시 눌러 주세요.\n'
                    job['log'] += f'\n✖ 실패 (종료 코드 {p.returncode})\n'
                    return
            except Exception as e:  # 실행 파일 없음 등
                job['status'] = 'error'
                job['log'] += f'\n✖ {e.__class__.__name__}: {e}\n'
                return
        job['status'] = 'done'
        job['log'] += '\n✔ 완료\n'

    threading.Thread(target=work, daemon=True).start()
    return job


def py(*args):
    return [sys.executable, *args]


def claude_cmd(prompt):
    exe = shutil.which('claude')
    if not exe:
        raise RuntimeError('claude CLI 를 찾지 못했습니다 (Claude Code 설치 필요).')
    return [exe, '-p', prompt, '--permission-mode', 'acceptEdits', '--allowedTools', 'Read,Write,Edit,Glob,Grep']


def step_prompt(step, rid, fit):
    d = f'reels/data/analysis/{rid}'
    base = (f'.claude/skills/ref-analyze/SKILL.md 와 CLAUDE.md 의 "레퍼런스·릴스·캐러셀" 절을 읽고 따르세요. '
            f'대상 레퍼런스 폴더: {d}/ (meta.json, transcript.txt, frames/). 질문하지 말고 끝까지 완료하세요. '
            f'수치·경험담·대본을 지어내지 않습니다. 셸 명령은 쓰지 않고 Read/Write 만 사용합니다. ')
    if step == 'analysis':
        return base + (f'스킬의 "② analysis.md (화면·대본 분석)"만 수행해 {d}/analysis.md 를 작성하세요. '
                       f'frames/ 의 f_0NN.jpg(첫 3초)는 전부, g_NNN.jpg 는 장면이 바뀌는 곳 위주로 8~12장을 Read 로 직접 봅니다. '
                       f'대본이 비어 있으면 화면 자막에서 복원하고 그렇게 표시합니다. ③④는 하지 않습니다.')
    if step == 'scripts5':
        return base + (f'{d}/analysis.md 를 읽고 스킬의 "③ scripts5.md (대본 5개)"만 수행해 {d}/scripts5.md 를 작성하세요. '
                       f'대상 채널: {fit or "가장 맞는 채널 1개를 골라 이유를 적을 것"}. reels/config.json 의 해당 채널 법규(law)·금지(ban)를 지킵니다. '
                       f'구조만 빌리고 내용은 우리 채널 분야로 새로 씁니다. 마지막에 비교 표를 넣습니다.')
    return base + (f'{d}/analysis.md 와 {d}/scripts5.md 를 읽고 스킬의 "④ plan.md (제작 기획)"만 수행해 {d}/plan.md 를 작성하세요. '
                   f'대상 채널: {fit or "scripts5.md 에 적힌 채널"}. 비교 표에서 추천된 1~2개 대본에 대해 컷 리스트·준비물·캡션·첫 프레임을 씁니다.')


# ---------------- 주간 63개 주제 ----------------
def weekly():
    out = {'channels': {}, 'csv': None, 'hooks': read(os.path.join(WORK_OUT, 'prev_hooks.md'))}
    for g in ('beauty', 'medical', 'life'):
        p = os.path.join(WORK_OUT, f'cand_{g}.json')
        if os.path.exists(p):
            try:
                out['channels'].update(json.load(open(p, encoding='utf-8')))
            except ValueError:
                pass
    csvs = sorted(glob.glob(os.path.join(WORK_OUT, '전체7개채널_63개주제_*.csv')))
    if csvs:
        with open(csvs[-1], encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        out['csv'] = {'name': os.path.basename(csvs[-1]), 'header': rows[0], 'rows': rows[1:]}
    return out


# ---------------- HTTP ----------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ('/', '/index.html'):
            return self.send(200, read(os.path.join(APP, 'index.html')), 'text/html; charset=utf-8')
        if path == '/api/refs':
            c = cfg()
            return self.send(200, {'refs': load_refs(), 'channels': list(c['channels']), 'statuses': STATUSES,
                                   'apify': bool(os.environ.get('APIFY_TOKEN')), 'claude': bool(shutil.which('claude'))})
        if path == '/api/weekly':
            return self.send(200, weekly())
        m = re.fullmatch(r'/api/job/(\w+)', path)
        if m:
            return self.send(200, JOBS.get(m.group(1)) or {'status': 'error', 'log': '없는 작업'})
        m = re.fullmatch(r'/api/ref/([\w-]+)', path)
        if m and safe_id(m.group(1)):
            rid = m.group(1)
            d = os.path.join(ANA, rid)
            ref = next((r for r in load_refs() if r['id'] == rid), None)
            meta = json.loads(read(os.path.join(d, 'meta.json'), '{}') or '{}')
            tr = json.loads(read(os.path.join(d, 'transcript.json'), '[]') or '[]')
            frames = sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, 'frames', '*.jpg')))
            return self.send(200, {'id': rid, 'ref': ref, 'meta': meta, 'transcript': tr, 'frames': frames,
                                   **{k: read(os.path.join(d, f)) for k, f in STEP_FILE.items()}})
        m = re.fullmatch(r'/frames/([\w-]+)/([\w.]+\.jpg)', path)
        if m and safe_id(m.group(1)):
            p = os.path.join(ANA, m.group(1), 'frames', m.group(2))
            if os.path.exists(p):
                return self.send(200, open(p, 'rb').read(), mimetypes.guess_type(p)[0] or 'image/jpeg')
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        except ValueError:
            return self.send(400, {'error': '잘못된 요청'})
        fit = body.get('fit') if body.get('fit') in cfg()['channels'] else None
        try:
            if path == '/api/start':  # 링크 → 보관함 추가 + 재료 내려받기
                url = resolve_short((body.get('url') or '').strip())
                rid = ref_id(url) if url.startswith('http') else safe_id(url)
                if not rid:
                    return self.send(400, {'error': '유튜브 · 틱톡 · 인스타그램(/reel/ · /p/) 영상 링크만 지원합니다.'})
                steps = []
                if url.startswith('http'):
                    add = py('reels/scripts/collect.py', 'add', url, '--region', 'KR' if body.get('region') == 'KR' else 'GLOBAL')
                    steps.append(('보관함에 추가', add + (['--fit', fit] if fit else [])))
                fetch = py('reels/scripts/fetch_ref.py', rid, '--frames')
                if body.get('cookies'):
                    fetch += ['--cookies-from-browser', 'chrome']
                steps.append(('대본·화면 내려받기 (yt-dlp · ffmpeg)', fetch))
                return self.send(200, {'job': run_job('fetch', steps, rid)['id'], 'ref': rid})
            if path == '/api/step':  # Claude 로 분석·대본·기획
                rid, step = safe_id(body.get('id')), body.get('step')
                if not rid or step not in STEP_FILE:
                    return self.send(400, {'error': '잘못된 요청'})
                label = {'analysis': '화면·대본 분석', 'scripts5': '대본 5개 작성', 'plan': '제작 기획 작성'}[step]
                job = run_job(step, [(f'{label} (Claude Code · 몇 분 걸립니다)', claude_cmd(step_prompt(step, rid, fit)))], rid)
                return self.send(200, {'job': job['id'], 'ref': rid})
            if path == '/api/collect':  # 유튜브 레퍼런스 수집
                argv = py('reels/scripts/collect.py', 'youtube', '--period', 'month' if body.get('period') == 'month' else 'week')
                if fit:
                    argv += ['--fit', fit]
                if body.get('region') in ('KR', 'GLOBAL'):
                    argv += ['--region', body['region']]
                return self.send(200, {'job': run_job('collect', [('유튜브 레퍼런스 수집', argv)])['id']})
            if path == '/api/set':  # 상태·채널 변경
                rid = safe_id(body.get('id'))
                if not rid:
                    return self.send(400, {'error': '잘못된 요청'})
                argv = py('reels/scripts/collect.py', 'set', rid)
                if body.get('status') in STATUSES:
                    argv += ['--status', body['status']]
                if fit:
                    argv += ['--fit', fit]
                r = subprocess.run(argv, cwd=ROOT, env=ENV, capture_output=True, text=True, encoding='utf-8', errors='replace')
                return self.send(200 if r.returncode == 0 else 400, {'ok': r.returncode == 0, 'out': (r.stdout + r.stderr)[-500:]})
        except RuntimeError as e:
            return self.send(500, {'error': str(e)})
        self.send(404, {'error': 'not found'})


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT') or 5180))
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(f'콘텐츠 스튜디오 실행 중: http://localhost:{a.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', a.port), H).serve_forever()
