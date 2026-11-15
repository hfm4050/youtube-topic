# 유튜브 주제 리서치 리포트 자동 발행 — Claude Code 작업 메모

이 저장소는 Cowork(claude.ai 프로젝트 "유튜브 주제 서칭 자동화 ver2")에서 돌던 **화요일 63개 주제 리포트 발행 파이프라인**을 Claude Code에서도 실행할 수 있게 옮긴 것이다. 사양은 `docs/RUNBOOK-자동발행.md`가 전부이고, 이 파일은 요약 + Claude Code 환경 차이만 적는다.

## 꼭 지킬 것
- **비용 절감 모드(2026-11-03~)**: 노션 발행 대상은 `건강한마케팅 — 전체 채널` 페이지 **3ca9025a-8e5c-81f2-bb1a-d63d29e07ca0** 하나. 발행 기록 DB(3b1e63d3957f4af38e6bc571ce9ca4d0)에 행을 만들지 말고, 사월PD·라온PD·덕PD 페이지는 읽지도 갱신하지도 않는다. PD별 CSV도 없다. 허브 페이지(3c89025a…)는 건드리지 않는다.
- 페이지 구조: `# 📅 YYYY년 N월` H1 → `📁 N월 주제` 토글 → `📂 N월 K주차 (M/D 화)` 주차 토글(가장 최근만 ` · 최신`, 미발행 주차는 `— 예정` + 🗓️ 콜아웃) → `---` → 지난 달 토글들 → `---` → 푸터. 주차 = ISO식(1일이 월~목이면 그 주가 1주차). 월이 바뀌면 RUNBOOK 4-2절 3항.
- 적용은 **replace_content(p0: 헤더+이번 달) → insert_content(지난 달 토글 하나씩, end) → insert_content(푸터)**. 한 번에 replace하면 최상위 블록 순서가 뒤섞인다. `update_content`는 쓰지 않는다. p0에 자식 페이지 `<page url=…>`(12개)가 전부 들어 있어야 하며 `allow_deleting_content: true`는 절대 쓰지 않는다. insert가 오류로 끝나도 서버 반영될 수 있으니 재시도 전 fetch로 확인.
- CSV: UTF-8 BOM, 열 `채널,No,주제(가제),키워드,카테고리,형식,권장 길이,벤치마크 근거,핵심 스토리라인,구독자수,조회수,좋아요,댓글수`, 파일명 `전체7개채널_63개주제_{YYYY-MM-DD}_한글수정.csv`. 업로드는 `notion-create-attachment`의 `content`에 BOM(U+FEFF)+텍스트 직접 삽입, `content_type: text/csv`. 1시간 안에 페이지에 붙인다.
- 스타라인은 안면거상·리프팅·눈수술만(광대·윤곽·양악 금지). 담당 PD 표기: 양PD(구 정PD)·사월PD·라온PD·덕PD. 법규: 의료광고법(효과 보장·최상급·전후비교 금지), 화장품법(의약품 오인 금지), 보험(개별 약관 명시).
- 벤치마크 근거: 조회수만 높고 좋아요·댓글 낮은 영상 제외. 수치 없으면 참여 정황(반복 질문·시리즈 반복·기사 수치)을 적고, 정황도 없으면 근거로 쓰지 않는다. 수치·제목·URL을 지어내지 않는다.
- 노션 마크다운 본문에는 `~ | * _`를 `\~ \| \* \_`로 이스케이프(CSV에는 안 함). 컬러 글씨·장식 아이콘 금지, 강조는 `<b>`만.

## 폴더
- `docs/` — RUNBOOK-자동발행.md(사양), 주간기획안-채널목록.md(채널·기획안 규칙), RUNBOOK-핫주제.md(월요일 핫 주제 파이프라인, 참고), 발행 로그.md(회차 기록 — 매 회차 한 줄 + 실행 메모 append).
- `scripts/extract_page.py` — notion-fetch 결과 파일 → `work/out/health_raw.md`, `structure.txt`, `prev_titles.txt`(직전 2회차 126개 제목).
- `scripts/check_dups.py` — 후보 JSON vs 직전 제목 4-gram 유사도 표.
- `scripts/gen.py --date YYYY-MM-DD [--file file-upload://ID]` — CSV + 회차 블록 + 페이지 파트(p0/p1../footer) 생성, assert 포함.
- `work/topics.py` — 회차마다 새로 쓰는 선정 파일(SEL/TITLE/EVIDENCE/THEME). 현재 내용은 2026-11-10 예시.
- `templates/research_common.md` — 리서치 서브에이전트 공통 지침(날짜·시즌 훅·전면 금지 목록을 회차마다 갱신). `templates/apply_common.md` — 업로드+적용 에이전트 절차.
- `samples/2026-11-10/` — 11/10 회차 실제 산출물(후보 JSON 3개, prev_titles/prev_hooks, CSV, 회차 블록, 발행 후 페이지 원문). 형식 참고용.

## Claude Code 환경 차이 (Cowork 대비)
- Notion MCP가 필요하다: `claude mcp add --transport http notion https://mcp.notion.com/mcp` 후 `/mcp`로 로그인. 도구 이름은 `mcp__notion__notion-fetch` 등(서버 별칭에 따라 `mcp__Notion__…`). RUNBOOK의 `notion-fetch`/`notion-create-attachment`/`notion-update-page`가 그것.
- Cowork의 `Projects` 도구(`claude/…` 문서)는 없다 → 같은 내용이 `docs/`에 있다. 발행 로그도 `docs/발행 로그.md`에 append.
- `PushNotification` 도구는 없다 → 결과는 터미널 보고로 끝낸다(필요하면 사용자가 Cowork 프로젝트 문서에 로그를 옮긴다).
- fetch 결과가 큰 경우 Claude Code는 tool_result를 세션 jsonl(`~/.claude/projects/<슬러그>/<세션>.jsonl`)에 남긴다 → `scripts/extract_page.py <jsonl>`로 추출. 또는 서브에이전트가 본문을 파일로 저장.
- 셸에서 외부 HTTP(curl)가 될 수 있지만, 유튜브 검증은 RUNBOOK 규칙(youtube-nocookie oEmbed + returnyoutubedislikeapi, ID 일치 시만) 그대로.
- 서브에이전트: Task 도구로 리서치 3개(성형·피부 / 의료 전문 / 생활·금융)를 **한 메시지에서 동시에**. 큰 본문(수만 자)을 출력하는 적용 에이전트는 sonnet 계열이 안정적이었다.

## 한 회차 실행 순서(요약)
1. 날짜·주차 확정(`python3 scripts/gen.py --date …`는 월/주차를 출력만 하고 멈춰도 됨 — cand 파일 없으면 에러).
2. 건강한마케팅 페이지 fetch → `scripts/extract_page.py` → `work/out/health_raw.md`·`prev_titles.txt`. 채널별 직전 2회차 훅과 연속 훅 경고를 `work/out/prev_hooks.md`에 쓴다(samples 참고).
3. `templates/research_common.md`를 이번 회차로 갱신해 `work/out/research_common.md`로 저장 → 리서치 서브에이전트 3개 동시 실행 → `work/out/cand_beauty.json`·`cand_medical.json`·`cand_life.json`(채널당 12개).
4. `scripts/check_dups.py`로 유사도·테마 겹침 확인 → `work/topics.py`의 SEL(6+3)·TITLE·EVIDENCE·THEME 작성 → `python3 scripts/gen.py --date …`(CSV 먼저 확인).
5. `templates/apply_common.md`대로: CSV 업로드(create-attachment) → `gen.py --file file-upload://ID` → replace_content(p0) → insert_content(지난 달 토글들, 푸터).
6. fetch로 검증(apply_common 5절 항목) → `docs/발행 로그.md`에 한 줄 + 실행 메모 append → 한 문단 보고.

## 레퍼런스·릴스·캐러셀 (2026-11-15 추가 — `reels/`)
화요일 63개 리포트와 별개로, **터진 레퍼런스에서 주제와 구조를 가져오는** 파이프라인. 원칙: 해외 먼저, 구조만 빌리고 내용은 우리 분야로 새로 쓴다(원문 번역·디자인 복제 금지), 수치·경험담을 지어내지 않는다, 업로드는 사람이 한다.
- 상태 흐름: 포착 → 검수대기(기준 통과) → 촬영대기(사람이 고름) → 완료/제외. 저장소 `reels/data/refs.jsonl`, 보드 `reels/out/dashboard.html`.
- `/ref-collect` — `reels/scripts/collect.py youtube|instagram|add|list|set|score` (yt-dlp, 인스타는 APIFY_TOKEN). 판정: 참여율 0.5% 미만 제외, 평소의 5배 이상 또는 대형 조회 통과, 10배+댓글 100이면 캐러셀 후보. 키워드·계정·기준은 `reels/config.json`.
- `/ref-analyze <링크|id>` — `reels/scripts/fetch_ref.py --frames`로 대본·화면을 받아 `reels/data/analysis/<id>/analysis.md`(첫 3초·대본 구조·화면·원문/번역·반응) → `scripts5.md`(같은 구조의 새 대본 5개) → `plan.md`(제작 기획).
- `/carousel-make` — 스펙 JSON(`reels/specs/`) → `reels/scripts/carousel_render.py` → 1080×1350 PNG + caption.txt (`reels/out/carousel/`). 법규 금지 표현·채널 금지 테마 자동 점검. 렌더 후 PNG를 직접 보고 확인.
- 아침 자동 실행 프롬프트: `prompts/daily_refs.md`. 수동 시작 프롬프트: `KICKOFF_REELS.md`.
- 설치: `pip install yt-dlp playwright && playwright install chromium`, ffmpeg, (선택) `pip install faster-whisper`.
- 화요일 리포트와의 연결: 검수대기·촬영대기 레퍼런스는 리서치 단계에서 `work/out/research_common.md`에 "이번 주 레퍼런스 훅"으로 넣어 후보 근거(벤치마크 근거 열)에 쓴다. 월요일 핫 주제(전 분야 300만+)와 달리 여기는 **우리 채널 분야 키워드·계정** 중심이다.
- 대시보드: `python app/server.py` → http://localhost:5180 (`app/index.html` 단일 화면, 표준 라이브러리 서버). 링크(인스타·틱톡·유튜브) → `collect.py add` + `fetch_ref.py --frames`, 분석·대본·기획은 `claude -p` 로 ref-analyze 스킬의 ②③④를 각각 실행해 `reels/data/analysis/<id>/*.md` 를 만든다. id 접두사: `yt_`·`ig_`·`tt_`.
