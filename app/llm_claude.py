#!/usr/bin/env python3
"""Claude Code CLI 를 한 번 실행하고 결과 글과 비용을 출력한다 (대시보드 서버가 호출).

  python app/llm_claude.py --model claude-opus-5-5 --prompt "…"

CLI 가 파일을 직접 읽고 쓴다(Read/Write). 마지막 줄에 `COST_JSON {...}` 을 찍어 서버가 건당 비용을 기록한다.
비용은 CLI 가 보고하는 API 환산 금액이다 — 구독 로그인으로 쓰면 요금제에 포함돼 따로 청구되지 않는다.
"""
import argparse, json, shutil, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument('--model', default='')
ap.add_argument('--prompt', required=True)
a = ap.parse_args()
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

exe = shutil.which('claude')
if not exe:
    sys.exit('claude CLI 를 찾지 못했습니다 (Claude Code 설치 필요).')
cmd = [exe, '-p', a.prompt, '--permission-mode', 'acceptEdits', '--allowedTools', 'Read,Write,Edit,Glob,Grep',
       '--output-format', 'json']
if a.model:
    cmd += ['--model', a.model]
r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL)
try:
    d = json.loads(r.stdout)
except ValueError:
    print((r.stdout or '') + (r.stderr or ''))
    sys.exit(r.returncode or 1)
if isinstance(d, list):                      # 일부 버전은 이벤트 배열을 돌려준다 → 마지막 result 이벤트
    d = next((x for x in reversed(d) if isinstance(x, dict) and x.get('type') == 'result'), {})
print(d.get('result') or '')
u = d.get('usage') or {}
cost = {'usd': d.get('total_cost_usd'), 'in': (u.get('input_tokens') or 0) + (u.get('cache_read_input_tokens') or 0) + (u.get('cache_creation_input_tokens') or 0),
        'out': u.get('output_tokens'), 'turns': d.get('num_turns'), 'model': a.model or 'CLI 기본값'}
print('COST_JSON ' + json.dumps(cost, ensure_ascii=False))
if d.get('is_error') or r.returncode:
    sys.exit(r.returncode or 1)
