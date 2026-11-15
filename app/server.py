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
DOTENV = os.path.join(ROOT, '.env')   # 커밋 금지(.gitignore). APIFY_TOKEN 등 키 보관


def load_dotenv():
    if os.path.exists(DOTENV):
        for line in open(DOTENV, encoding='utf-8'):
            k, sep, v = line.strip().partition('=')
            if sep and k and not k.startswith('#'):
                ENV[k.strip()] = v.strip()


def save_dotenv(key, value):
    lines = [l.rstrip('\n') for l in open(DOTENV, encoding='utf-8')] if os.path.exists(DOTENV) else []
    lines = [l for l in lines if not l.startswith(key + '=')]
    if value:
        lines.append(f'{key}={value}')
        ENV[key] = value
    else:
        ENV.pop(key, None)
    open(DOTENV, 'w', encoding='utf-8').write('\n'.join(lines) + ('\n' if lines else ''))


def clean_list(v, strip):
    """화면에서 온 계정·해시태그 목록 정리: 문자열(줄·쉼표 구분)이나 배열 → 중복 없는 이름 배열."""
    if isinstance(v, str):
        v = re.split(r'[\s,]+', v)
    out = []
    for x in v or []:
        x = re.sub(r'^https?://(www\.)?instagram\.com/', '', str(x).strip()).strip('/').lstrip(strip).strip()
        if x and re.fullmatch(r'[\w.\-가-힣]+', x) and x not in out:
            out.append(x)
    return out[:50]


def to_hashtag(s):
    s = re.sub(r'(?i)\b(shorts?|youtube|유튜브|쇼츠|릴스|영상)\b', ' ', s)
    return re.sub(r'[^\w가-힣]', '', s).lower()[:30]


def kw_get(c, ch, plat):
    """채널의 플랫폼별 수집 키워드 {kr, global, inherited}. 인스타·틱톡이 비어 있으면 유튜브 키워드를 기본으로 보여 준다
    (인스타는 해시태그 형태로 변환). collect.py 의 plat_keywords 와 같은 규칙."""
    v = c['channels'][ch]
    yt = {'kr': list(v.get('kr', [])), 'global': list(v.get('global', []))}
    if plat == 'youtube':
        return {**yt, 'inherited': False}
    key = 'hashtags' if plat == 'instagram' else 'keywords'
    d = (v.get(plat) or {}).get(key) or {}
    own = {'kr': [x for x in (d.get('KR') or []) if str(x).strip()], 'global': [x for x in (d.get('GLOBAL') or []) if str(x).strip()]}
    if own['kr'] or own['global']:
        return {**own, 'inherited': False}
    if plat == 'instagram':
        conv = lambda L: list(dict.fromkeys(h for h in (to_hashtag(x) for x in L) if len(h) >= 2))
        return {'kr': conv(yt['kr']), 'global': conv(yt['global']), 'inherited': True}
    return {**yt, 'inherited': True}


def kw_set(c, ch, plat, kr, gl):
    v = c['channels'][ch]
    if plat == 'youtube':
        v['kr'], v['global'] = kr, gl
    else:
        v.setdefault(plat, {})['hashtags' if plat == 'instagram' else 'keywords'] = {'GLOBAL': gl, 'KR': kr}


def suggest_view(c):
    """추천 키워드 {채널: {youtube|instagram|tiktok: {kr, global}}}. 틱톡은 유튜브 추천 + 저장된 유튜브 키워드."""
    sg = json.loads(read(os.path.join(APP, 'keyword_suggestions.json'), '{}') or '{}')
    ig, out = sg.get('_instagram') or {}, {}
    for ch in c['channels']:
        yt = sg.get(ch) or {'kr': [], 'global': []}
        cur = kw_get(c, ch, 'youtube')
        merge = lambda a, b: list(dict.fromkeys(list(a) + list(b)))
        out[ch] = {'youtube': yt, 'instagram': ig.get(ch) or {'kr': [], 'global': []},
                   'tiktok': {'kr': merge(cur['kr'], yt.get('kr', [])), 'global': merge(cur['global'], yt.get('global', []))}}
    return out


PLATS = ('youtube', 'instagram', 'tiktok')


def ig_settings(c, fit):
    ig = (c['channels'][fit].get('instagram') if fit else c['instagram']) or {}
    return {k: {r: list((ig.get(k) or {}).get(r) or []) for r in ('GLOBAL', 'KR')} for k in ('accounts', 'hashtags')}
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
    return add_signals(refs)


THUMBS = os.path.join(REELS, 'data', 'thumbs')   # 인스타·틱톡 썸네일 보관(원본 주소는 몇 시간 뒤 만료된다)
_thumb_lock = threading.Lock()


def thumb_path(rid):
    """썸네일 파일 경로를 돌려준다. 없으면 한 번 받아 둔다(실패하면 1시간 동안 다시 시도하지 않는다)."""
    p, miss = os.path.join(THUMBS, rid + '.jpg'), os.path.join(THUMBS, rid + '.none')
    if os.path.exists(p):
        return p
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 3600:
        return None
    os.makedirs(THUMBS, exist_ok=True)
    ref = next((r for r in load_refs() if r['id'] == rid), None)
    if not ref:
        return None

    def grab(url):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'})
        data = urllib.request.urlopen(req, timeout=20).read()
        if len(data) < 500:
            raise ValueError('빈 이미지')
        open(p, 'wb').write(data)

    with _thumb_lock:                       # 동시에 수십 장을 받지 않도록 한 장씩
        if os.path.exists(p):
            return p
        for attempt in ('stored', 'fresh'):
            try:
                url = ref.get('thumb')
                if attempt == 'fresh':      # 저장된 주소가 만료됐거나 없으면 yt-dlp 로 새 주소를 얻는다
                    r = subprocess.run(py('-m', 'yt_dlp', '--skip-download', '--no-warnings', '--print', 'thumbnail', ref['url']),
                                       capture_output=True, text=True, timeout=60, env=ENV, encoding='utf-8', errors='replace')
                    url = (r.stdout or '').strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else None
                if url and url.startswith('http'):
                    grab(url)
                    return p
            except Exception:
                pass
        open(miss, 'w').close()
    return None


def add_signals(refs):
    """평소 대비 급등 표시용 값. views_x = 수집 때 계산한 배수(outlier), comment_x = 같은 플랫폼 보관함 중앙값 대비 댓글 비율 배수."""
    group = lambda r: 'youtube' if r.get('platform', '').startswith('youtube') else r.get('platform')
    rate = lambda r: (r['comments'] / r['views']) if r.get('views') and r['views'] >= 1000 and r.get('comments') is not None else None
    by = {}
    for r in refs:
        if rate(r) is not None:
            by.setdefault(group(r), []).append(rate(r))
    med = {g: sorted(v)[len(v) // 2] for g, v in by.items() if len(v) >= 8}
    try:
        cfg_thr = cfg()['thresholds']['min_views_for_outlier']
    except Exception:
        cfg_thr = {}
    vby = {}
    for r in refs:
        if r.get('views'):
            vby.setdefault(group(r), []).append(r['views'])
    vmed = {g: sorted(v)[len(v) // 2] for g, v in vby.items() if len(v) >= 8}
    for r in refs:
        m, x = med.get(group(r)), rate(r)
        r['comment_x'] = round(x / m, 1) if m and x is not None and (r.get('comments') or 0) >= 50 else None
        # 계정의 평소 조회수를 모르는 항목(outlier 없음)은 같은 플랫폼 보관함 중앙값 대비 배수를 따로 둔다
        vm = vmed.get(group(r))
        r['views_x'] = round(r['views'] / vm, 1) if r.get('outlier') is None and vm and r.get('views') else None
        # 배지용: 조회 배수는 최소 조회수(국내 1만·해외 5만, config thresholds)를 넘을 때만 의미 있다
        mv = cfg_thr.get(r.get('region') or 'KR', 10000)
        r['views_ok'] = bool(r.get('views') and r['views'] >= mv)
        r['has_thumb'] = bool(r.get('thumb')) or os.path.exists(os.path.join(THUMBS, r['id'] + '.jpg'))
    return refs


# ---------------- 백그라운드 작업 (진행률 · 남은 시간) ----------------
STATS = os.path.join(REELS, 'data', 'job_stats.json')   # 단계별 실제 소요 시간 기록 → 다음 예상 시간에 반영
EST = {'add': 8, 'fetch': 45, 'analysis': 300, 'scripts5': 240, 'plan': 180, 'instagram': 180, 'yt_query': 35, 'ig_query': 45, 'tt_query': 40}


def est_for(key, default=None):
    """같은 종류 작업의 최근 실제 소요 시간 평균(없으면 기본값)."""
    try:
        hist = json.load(open(STATS, encoding='utf-8')).get(key) or []
    except (OSError, ValueError):
        hist = []
    return round(sum(hist) / len(hist)) if hist else (default or EST.get(key, 60))


def record(key, sec):
    try:
        d = json.load(open(STATS, encoding='utf-8'))
    except (OSError, ValueError):
        d = {}
    d[key] = (d.get(key) or [])[-4:] + [round(sec, 1)]
    os.makedirs(os.path.dirname(STATS), exist_ok=True)
    json.dump(d, open(STATS, 'w', encoding='utf-8'))


def step(label, argv, key=None, est=None, units=0, unit_re=None, env=None, cost_key=None):
    """작업 단계. units·unit_re 가 있으면 출력 줄 수로 진행률을 세고, 없으면 예상 시간으로 추정한다."""
    return {'label': label, 'argv': argv, 'key': key, 'est': est or est_for(key), 'units': units,
            'unit_re': unit_re, 'env': env, 'done_units': 0, 'state': 'todo', 'took': None, 'cost': None, 'cost_key': cost_key}


def run_job(kind, steps, ref=None, stop_on_error=True):
    """steps: step(...) 목록을 순서대로 실행. 하나라도 실패하면 멈춘다(stop_on_error=False 면 건너뜀)."""
    jid = uuid.uuid4().hex[:10]
    job = JOBS[jid] = {'id': jid, 'kind': kind, 'ref': ref, 'status': 'running', 'log': '', 'started': time.time(),
                       'ended': None, 'steps': steps, 'cur': 0, 'step_started': time.time()}

    def work():
        for i, st in enumerate(steps):
            job['cur'], job['step_started'], st['state'] = i, time.time(), 'run'
            job['log'] += f"\n▶ {st['label']}\n"
            rx = re.compile(st['unit_re']) if st['unit_re'] else None
            try:
                p = subprocess.Popen(st['argv'], cwd=ROOT, env=st['env'] or ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
                for line in p.stdout:
                    job['log'] = (job['log'] + line)[-12000:]
                    if line.startswith('COST_JSON '):   # LLM 래퍼가 찍는 건당 비용
                        try:
                            st['cost'] = json.loads(line[10:])
                        except ValueError:
                            pass
                        job['log'] = job['log'][:-len(line)]
                    if rx and rx.search(line):
                        st['done_units'] += 1
                rc = p.wait()
            except Exception as e:  # 실행 파일 없음 등
                rc = -1
                job['log'] += f'\n✖ {e.__class__.__name__}: {e}\n'
            st['took'] = time.time() - job['step_started']
            if rc == 0:
                st['state'] = 'done'
                if st['cost_key'] and st['cost'] and st['cost'].get('usd') is not None:
                    record('cost:' + st['cost_key'], st['cost']['usd'])
                if st['key'] and not st['units']:
                    record(st['key'], st['took'])
                elif st['key'] and st['done_units']:
                    record(st['key'], st['took'] / st['done_units'])
                continue
            st['state'] = 'fail'
            if not stop_on_error:
                job['log'] += '  (이 링크는 건너뜀)\n'
                continue
            job['status'], job['ended'] = 'error', time.time()
            if 'authenticate' in job['log'] or 'OAuth' in job['log'] or 'API key' in job['log']:
                job['log'] += '\n※ Claude 인증이 없습니다. 오른쪽 위 「API 키 설정」에서 Anthropic API 키를 등록하거나, 터미널(cmd)에서 claude 실행 후 /login 하세요.\n'
            job['log'] += f'\n✖ 실패 (종료 코드 {rc})\n'
            return
        job['status'], job['ended'] = 'done', time.time()
        job['log'] += '\n✔ 완료\n'

    threading.Thread(target=work, daemon=True).start()
    return job


def job_view(job):
    """화면용 요약: 단계 상태, 진행률(0~1), 남은 시간(초, 모르면 None)."""
    now = job['ended'] or time.time()
    steps, total, done, eta, over = job['steps'], 0.0, 0.0, 0.0, False
    for st in steps:
        w = st['est'] * (st['units'] or 1)
        total += w
        if st['state'] in ('done', 'fail'):
            done += w
        elif st['state'] == 'run':
            el = now - job['step_started']
            if st['units']:
                frac = min(st['done_units'] / st['units'], 0.99)
                eta += (el / frac * (1 - frac)) if frac >= 0.08 else max(w - el, 0)
            else:
                frac = min(el / w, 0.95)
                over = el > w
                eta += max(w - el, 0)
            done += w * frac
        else:
            eta += w
    fin = job['status'] != 'running'
    return {'id': job['id'], 'kind': job['kind'], 'ref': job['ref'], 'status': job['status'], 'log': job['log'],
            'elapsed': round(now - job['started']), 'progress': 1 if job['status'] == 'done' else round(done / total, 3) if total else 0,
            'eta': 0 if fin else (None if over and len(steps) - job['cur'] == 1 else round(eta)), 'over': over and not fin,
            'steps': [{'label': st['label'], 'state': st['state'], 'units': st['units'], 'done_units': st['done_units'],
                       'took': round(st['took']) if st['took'] else None, 'cost': st['cost']} for st in steps],
            'cost_usd': round(sum((st['cost'] or {}).get('usd') or 0 for st in steps), 4) if any(st['cost'] for st in steps) else None}


def clean_env():
    """claude CLI 용 환경: 데스크톱 앱이 넣은 세션 변수를 빼고 .env 의 키만 넘긴다."""
    return {k: v for k, v in ENV.items() if not re.match(r'(CLAUDE|ANTHROPIC_BASE_URL|ANTHROPIC_AUTH|AI_AGENT$|BAGGAGE$)', k)}


def claude_logged_in():
    exe = shutil.which('claude')
    if not exe:
        return False
    try:
        r = subprocess.run([exe, 'auth', 'status'], env=clean_env(), capture_output=True, text=True, timeout=20,
                           encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL)
        return bool(json.loads(r.stdout).get('loggedIn'))
    except Exception:
        return False


KEYS = {'APIFY_TOKEN': r'[\w\-~.]{10,200}', 'ANTHROPIC_API_KEY': r'sk-ant-[\w\-]{20,300}', 'OPENAI_API_KEY': r'sk-(?!ant-)[\w\-]{20,300}'}


def yt_query_count(c, fit, region):
    n = 0
    for ch, v in c['channels'].items():
        if fit and ch != fit:
            continue
        n += sum(len(v.get(k, [])) for reg, k in (('KR', 'kr'), ('GLOBAL', 'global')) if not region or reg == region)
    if not fit:
        n += sum(len(c['hot_any_field'][k]) for reg, k in (('KR', 'kr'), ('GLOBAL', 'global')))
    return max(n, 1)


def py(*args):
    return [sys.executable, *args]


def models_cfg():
    return json.load(open(os.path.join(APP, 'models.json'), encoding='utf-8'))


_cli = {'at': 0, 'ok': False}
def claude_ready():
    """Claude 를 쓸 수 있나: CLI 로그인(60초 캐시) 또는 등록한 Anthropic API 키."""
    if ENV.get('ANTHROPIC_API_KEY'):
        return True
    if time.time() - _cli['at'] > 60:
        _cli.update(at=time.time(), ok=claude_logged_in())
    return _cli['ok']


def models_view():
    """모델 목록 + 단계별 건당 예상 비용(실측 평균이 있으면 그것, 없으면 가정 토큰 × 단가)."""
    c = models_cfg()
    try:
        hist = json.load(open(STATS, encoding='utf-8'))
    except (OSError, ValueError):
        hist = {}
    ready = {'claude': claude_ready(), 'openai': bool(ENV.get('OPENAI_API_KEY'))}
    out = []
    for m in c['models']:
        per = {}
        for st, (tin, tout) in c['assumed_tokens'][m['engine']].items():
            h = hist.get(f"cost:{m['id']}:{st}") or []
            per[st] = {'usd': round(sum(h) / len(h), 4) if h else round((tin * m['in'] + tout * m['out']) / 1e6, 4), 'measured': len(h)}
        out.append({**m, 'ready': ready[m['engine']], 'per': per})
    return {'models': out, 'default': c['default'], 'usd_krw': c.get('usd_krw'), 'checked': c.get('checked'),
            'claude_billing': 'api' if ENV.get('ANTHROPIC_API_KEY') else 'subscription'}


def llm_step(label, stepname, rid, fit, model):
    m = next((x for x in models_cfg()['models'] if x['id'] == model), None)
    if not m:
        raise RuntimeError('알 수 없는 모델입니다.')
    ck = f'{model}:{stepname}'
    if m['engine'] == 'openai':
        if not ENV.get('OPENAI_API_KEY'):
            raise RuntimeError('ChatGPT(OpenAI) API 키가 없습니다. 오른쪽 위 「API 키 설정」에서 등록해 주세요.')
        argv = py('app/llm_openai.py', stepname, rid, '--model', model) + (['--fit', fit] if fit else [])
        return step(f"{label} · {m['label']}", argv, key=f'{stepname}@openai', est=est_for(f'{stepname}@openai', 90), cost_key=ck)
    if not shutil.which('claude'):
        raise RuntimeError('claude CLI 를 찾지 못했습니다 (Claude Code 설치 필요).')
    argv = py('app/llm_claude.py', '--model', model, '--prompt', step_prompt(stepname, rid, fit))
    return step(f"{label} · {m['label']}", argv, key=stepname, env=clean_env(), cost_key=ck)


def step_prompt(step, rid, fit):
    d = f'reels/data/analysis/{rid}'
    base = (f'.claude/skills/ref-analyze/SKILL.md 와 CLAUDE.md 의 "레퍼런스·릴스·캐러셀" 절을 읽고 따르세요. '
            f'대상 레퍼런스 폴더: {d}/ (meta.json, transcript.txt, frames/). 질문하지 말고 끝까지 완료하세요. '
            f'수치·경험담·대본을 지어내지 않습니다. 셸 명령은 쓰지 않고 Read/Write 만 사용합니다. ')
    if step == 'analysis':
        return base + (f'스킬의 "② analysis.md (화면·대본 분석)"만 수행해 {d}/analysis.md 를 작성하고, '
                       f'같은 내용을 app/analysis_schema.md 의 스키마대로 {d}/analysis.json 에도 저장하세요(유효한 JSON, frames 의 file 은 실제 파일명만). '
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
                                   'brands': {k: v.get('brand') for k, v in c['channels'].items()},
                                   'keywords': {ch: {pl: kw_get(c, ch, pl) for pl in PLATS} for ch in c['channels']},
                                   'apify': bool(ENV.get('APIFY_TOKEN')), 'claude': bool(shutil.which('claude')),
                                   'suggest': suggest_view(c),
                                   'instagram': {'': ig_settings(c, None), **{ch: ig_settings(c, ch) for ch in c['channels']}}})
        if path == '/api/models':
            return self.send(200, models_view())
        if path == '/api/keys':
            return self.send(200, {'keys': {k: bool(ENV.get(k)) for k in KEYS}, 'claude_cli': claude_logged_in(), 'claude_installed': bool(shutil.which('claude'))})
        if path == '/api/weekly':
            return self.send(200, weekly())
        m = re.fullmatch(r'/api/job/(\w+)', path)
        if m:
            j = JOBS.get(m.group(1))
            return self.send(200, job_view(j) if j else {'status': 'error', 'log': '없는 작업', 'steps': [], 'progress': 0})
        m = re.fullmatch(r'/api/ref/([\w-]+)', path)
        if m and safe_id(m.group(1)):
            rid = m.group(1)
            d = os.path.join(ANA, rid)
            ref = next((r for r in load_refs() if r['id'] == rid), None)
            meta = json.loads(read(os.path.join(d, 'meta.json'), '{}') or '{}')
            tr = json.loads(read(os.path.join(d, 'transcript.json'), '[]') or '[]')
            frames = sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, 'frames', '*.jpg')))
            try:
                aj = json.loads(read(os.path.join(d, 'analysis.json'), 'null') or 'null')
            except ValueError:
                aj = None
            return self.send(200, {'id': rid, 'ref': ref, 'meta': meta, 'transcript': tr, 'frames': frames, 'analysis_json': aj,
                                   **{k: read(os.path.join(d, f)) for k, f in STEP_FILE.items()}})
        m = re.fullmatch(r'/thumb/([\w-]+)', path)
        if m and safe_id(m.group(1)):
            tp = thumb_path(m.group(1))
            if tp:
                body = open(tp, 'rb').read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                return self.wfile.write(body)
            return self.send(404, {'error': 'no thumbnail'})
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
                    steps.append(step('보관함에 추가', add + (['--fit', fit] if fit else []), key='add'))
                fetch = py('reels/scripts/fetch_ref.py', rid, '--frames')
                if body.get('cookies'):
                    fetch += ['--cookies-from-browser', 'chrome']
                steps.append(step('대본·화면 내려받기', fetch, key='fetch'))
                return self.send(200, {'job': run_job('fetch', steps, rid)['id'], 'ref': rid})
            if path == '/api/step':  # Claude 로 분석·대본·기획
                rid, stepname = safe_id(body.get('id')), body.get('step')
                if not rid or stepname not in STEP_FILE:
                    return self.send(400, {'error': '잘못된 요청'})
                label = {'analysis': '화면·대본 분석', 'scripts5': '대본 5개 작성', 'plan': '제작 기획 작성'}[stepname]
                job = run_job(stepname, [llm_step(label, stepname, rid, fit, body.get('model') or models_cfg()['default'])], rid)
                return self.send(200, {'job': job['id'], 'ref': rid})
            if path == '/api/rate':  # 원화 표시용 환율 저장
                try:
                    rate = float(body.get('usd_krw'))
                except (TypeError, ValueError):
                    rate = 0
                if not 500 <= rate <= 5000:
                    return self.send(400, {'error': '환율은 500~5000 사이 숫자로 입력해 주세요.'})
                pth = os.path.join(APP, 'models.json')
                c = json.load(open(pth, encoding='utf-8'))
                c['usd_krw'] = round(rate, 1)
                c['usd_krw_note'] = '원화 표시용 환율. ' + time.strftime('%Y-%m-%d') + ' 대시보드에서 직접 입력한 값.'
                json.dump(c, open(pth, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                return self.send(200, {'ok': True, 'usd_krw': c['usd_krw']})
            if path == '/api/keys':  # 토큰·API 키 등록/삭제 (.env — 값은 화면에 되돌려 주지 않는다)
                for k, pat in KEYS.items():
                    if k in body:
                        v = str(body.get(k) or '').strip()
                        if v and not re.fullmatch(pat, v):
                            return self.send(400, {'error': f'{k} 형식이 올바르지 않습니다.'})
                        save_dotenv(k, v)
                return self.send(200, {'ok': True, 'keys': {k: bool(ENV.get(k)) for k in KEYS}})
            if path == '/api/keywords':  # 채널별·플랫폼별 수집 키워드 저장
                plat = body.get('platform') if body.get('platform') in PLATS else 'youtube'
                if not fit:
                    return self.send(400, {'error': '고객 채널을 먼저 선택해 주세요.'})
                def kws(v):
                    out = []
                    for x in v if isinstance(v, list) else []:
                        x = re.sub(r'\s+', ' ', str(x)).strip()[:60]
                        if plat == 'instagram':          # 해시태그: # 과 공백 제거
                            x = re.sub(r'[#\s]', '', x)
                        if x and x not in out:
                            out.append(x)
                    return out[:20]
                p = os.path.join(REELS, 'config.json')
                c = json.load(open(p, encoding='utf-8'))
                kw_set(c, fit, plat, kws(body.get('kr')), kws(body.get('global')))
                json.dump(c, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                return self.send(200, {'ok': True, 'platform': plat, **kw_get(c, fit, plat)})
            if path == '/api/instagram':  # 인스타 수집 설정 저장 (토큰은 .env, 계정·해시태그는 config.json)
                if 'token' in body:
                    tok = str(body.get('token') or '').strip()
                    if tok and not re.fullmatch(r'[\w\-~.]{10,200}', tok):
                        return self.send(400, {'error': '토큰 형식이 올바르지 않습니다.'})
                    save_dotenv('APIFY_TOKEN', tok)
                if 'accounts' in body or 'hashtags' in body:
                    p = os.path.join(REELS, 'config.json')
                    c = json.load(open(p, encoding='utf-8'))
                    tgt = c['channels'][fit] if fit else c
                    ig = tgt.setdefault('instagram', {})
                    for key, strip in (('accounts', '@'), ('hashtags', '#')):
                        if key in body:
                            ig[key] = {r: clean_list((body[key] or {}).get(r), strip) for r in ('GLOBAL', 'KR')}
                    json.dump(c, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                return self.send(200, {'ok': True, 'apify': bool(ENV.get('APIFY_TOKEN')), 'settings': ig_settings(cfg(), fit)})
            if path == '/api/bulk':  # 링크 여러 개를 보관함에 한 번에 추가 (토큰 불필요)
                urls = []
                for u in re.split(r'\s+', str(body.get('urls') or '')):
                    u = resolve_short(u.strip())
                    if u.startswith('http') and ref_id(u) and u not in urls:
                        urls.append(u)
                if not urls:
                    return self.send(400, {'error': '인스타그램 /reel/ · /p/, 틱톡, 유튜브 영상 링크를 한 줄에 하나씩 넣어 주세요.'})
                reg = 'KR' if body.get('region') == 'KR' else 'GLOBAL'
                steps = [step(f'링크 {i}', py('reels/scripts/collect.py', 'add', u, '--region', reg) + (['--fit', fit] if fit else []), key='add')
                         for i, u in enumerate(urls[:30], 1)]
                return self.send(200, {'job': run_job('bulk', steps, stop_on_error=False)['id'], 'count': len(steps)})
            if path == '/api/collect' and body.get('platform') == 'instagram':  # 인스타 계정·해시태그 수집 (Apify)
                if not ENV.get('APIFY_TOKEN'):
                    return self.send(400, {'error': 'Apify 토큰이 없습니다. 먼저 토큰을 저장해 주세요.'})
                argv = py('reels/scripts/collect.py', 'instagram') + (['--fit', fit] if fit else [])
                c = cfg()
                pools = ([c['instagram']] if not fit else []) + [v.get('instagram') or {} for ch, v in c['channels'].items() if not fit or ch == fit]
                n = sum(len((c['instagram'].get('hashtags') or {}).get(r) or []) + (1 if (c['instagram'].get('accounts') or {}).get(r) else 0) for r in ('GLOBAL', 'KR')) if not fit else 0
                for ch in c['channels']:
                    if fit and ch != fit:
                        continue
                    kw = kw_get(c, ch, 'instagram')
                    ig = c['channels'][ch].get('instagram') or {}
                    n += len(kw['kr']) + len(kw['global']) + sum(1 for r in ('GLOBAL', 'KR') if (ig.get('accounts') or {}).get(r))
                if not n:
                    return self.send(400, {'error': '수집할 인스타그램 해시태그나 계정이 없습니다. 키워드를 추가하고 저장해 주세요.'})
                st = step(f'인스타그램 릴스 수집 · 해시태그·계정 {n}묶음', argv, key='ig_query', units=n, unit_re=r'^\[(KR|GLOBAL)\] ')
                return self.send(200, {'job': run_job('collect', [st])['id']})
            if path == '/api/collect' and body.get('platform') == 'tiktok':  # 틱톡 키워드 수집 (Apify)
                if not ENV.get('APIFY_TOKEN'):
                    return self.send(400, {'error': 'Apify 토큰이 없습니다. 「API 키 설정」에서 먼저 등록해 주세요.'})
                c = cfg()
                n = sum(len(kw_get(c, ch, 'tiktok')[k]) for ch in c['channels'] if not fit or ch == fit for k in ('kr', 'global'))
                if not n:
                    return self.send(400, {'error': '수집할 틱톡 키워드가 없습니다. 키워드를 추가하고 저장해 주세요.'})
                argv = py('reels/scripts/collect.py', 'tiktok') + (['--fit', fit] if fit else [])
                st = step(f'틱톡 영상 수집 · 키워드 {n}개', argv, key='tt_query', units=n, unit_re=r'^\[(KR|GLOBAL)\] ')
                return self.send(200, {'job': run_job('collect', [st])['id']})
            if path == '/api/collect':  # 유튜브 레퍼런스 수집
                argv = py('reels/scripts/collect.py', 'youtube', '--period', body.get('period') if body.get('period') in ('day', 'week', 'month', 'year') else 'week')
                if fit:
                    argv += ['--fit', fit]
                if body.get('region') in ('KR', 'GLOBAL'):
                    argv += ['--region', body['region']]
                n = yt_query_count(cfg(), fit, body.get('region') if body.get('region') in ('KR', 'GLOBAL') else None)
                st = step(f'유튜브 레퍼런스 수집 · 키워드 {n}개', argv, key='yt_query', units=n, unit_re=r'^\[(KR|GLOBAL)\] ')
                return self.send(200, {'job': run_job('collect', [st])['id']})
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
    load_dotenv()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(f'콘텐츠 스튜디오 실행 중: http://localhost:{a.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', a.port), H).serve_forever()
