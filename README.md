# youtube-topic-kit — Cowork → Claude Code 이관 자료 (2026-11-15 정리)

Cowork 예약 작업 "유튜브 주제 리서치 리포트 자동 발행(매주 화 09:30)"을 Claude Code에서 그대로 실행하기 위한 자료 묶음. 마지막 발행은 2026-11-10(11월 2주차), 다음 회차는 **2026-11-17(화) = 11월 3주차**, 발행 후 건강한마케팅 페이지의 `<file ` 개수는 20개가 된다.

## 1. 준비 (한 번만)
```bash
unzip youtube-topic-kit.zip && cd youtube-topic-kit
claude mcp add --transport http notion https://mcp.notion.com/mcp   # 노션 MCP 연결
claude            # 시작 후 /mcp 에서 notion 로그인(건강한마케팅 페이지가 있는 워크스페이스)
```
화요일 리포트는 Python 3 표준 라이브러리만 쓴다. 레퍼런스·캐러셀 기능은 2-1의 설치가 추가로 필요하다.

## 2. 매주 화요일 — Claude Code 명령창에 붙여넣을 프롬프트
`KICKOFF_PROMPT.md` 내용을 그대로 붙여 넣는다(날짜만 바꿀 필요 없음 — 오늘 날짜로 계산함).

## 2-1. 레퍼런스 주제 찾기 · 릴스 분석 · 캐러셀 자동 제작 (2026-11-15 추가)
```bash
pip install yt-dlp playwright && playwright install chromium     # + ffmpeg, 선택: pip install faster-whisper
export APIFY_TOKEN=...                                           # 인스타 릴스 수집용(선택, apify.com). 없으면 유튜브만 + 링크 직접 추가
```
Claude Code 안에서 `/ref-collect`(주제 찾기) · `/ref-analyze <링크>`(레퍼런스 분석→대본 5개→제작 기획) · `/carousel-make`(캐러셀 PNG)를 쓰거나 `KICKOFF_REELS.md`를 붙여 넣는다.
- 인스타 계정·해시태그는 `reels/config.json`의 `instagram.accounts/hashtags`에 직접 채운다(비어 있음). 채널별 유튜브 검색어(국내·해외)도 같은 파일.
- 아침 7시 자동 실행(맥/리눅스 cron 예): `0 7 * * * cd /경로/youtube-topic-kit && claude -p "$(cat prompts/daily_refs.md)" --permission-mode acceptEdits >> reels/out/cron.log 2>&1` — 수집 → 캐러셀 후보 최대 5개 제작 → `reels/out/daily_날짜.md` 요약. 업로드는 하지 않는다(음원은 앱에서만, 의료·보험 문구는 사람 검수).
- 이 세션(클라우드)에서는 유튜브·인스타 접속이 막혀 **수집·다운로드 스크립트는 실제 네트워크로 돌려 보지 못했다**. 판정 로직(selftest)·캐러셀 렌더·보드 생성은 확인했다. 첫 실행 때 `collect.py youtube --fit 손해사정사`처럼 채널 하나로 먼저 돌려 볼 것.

## 3. 폴더
```
CLAUDE.md                      Claude Code가 자동으로 읽는 작업 메모(규칙 요약 + 환경 차이 + 실행 순서)
KICKOFF_PROMPT.md              매주 붙여넣는 시작 프롬프트
docs/RUNBOOK-자동발행.md        사양(절차·형식·주의사항·이력). 이 문서가 기준
docs/주간기획안-채널목록.md      채널 9개·담당 PD·기획안 양식·레퍼런스 검증 규칙
docs/RUNBOOK-핫주제.md          월요일 핫 주제 파이프라인(참고용, Cowork에서 계속 돌아감)
docs/발행 로그.md               8/28~11/10 회차 기록 + 실행 메모 (매 회차 append)
scripts/extract_page.py        fetch 결과 → health_raw.md / structure.txt / prev_titles.txt
scripts/check_dups.py          후보 vs 직전 제목 4-gram 유사도
scripts/gen.py                 CSV(UTF-8 BOM) + 회차 블록 + 페이지 파트 생성 (assert 포함)
work/topics.py                 회차마다 새로 쓰는 선정 파일(현재 11/10 예시)
work/out/                      실행 중 산출물 자리(비어 있음)
templates/research_common.md   리서치 서브에이전트 공통 지침(회차마다 날짜·훅·금지 목록 갱신)
templates/apply_common.md      업로드+노션 적용 에이전트 절차
reels/config.json              레퍼런스 수집 키워드(국내·해외)·인스타 계정·판정 기준·채널 포인트 색
reels/scripts/collect.py       수집·판정·상태 관리 (refs.jsonl)
reels/scripts/fetch_ref.py     레퍼런스 1개의 메타·대본·화면 캡처 내려받기
reels/scripts/carousel_render.py  스펙 JSON → 캐러셀 PNG + 캡션 (법규 표현 점검)
reels/scripts/dashboard.py     포착·검수 대기·촬영 대기 보드(HTML)
reels/specs/sample_claim-3years.json  캐러셀 스펙 예시
.claude/skills/                ref-collect · ref-analyze · carousel-make
KICKOFF_REELS.md               레퍼런스 작업 시작 프롬프트 / prompts/daily_refs.md 아침 자동 실행용
samples/2026-11-10/            11/10 회차 실제 산출물(후보 JSON·prev_titles·prev_hooks·CSV·회차 블록·발행 후 페이지 원문)
```

## 4. Cowork 쪽과의 관계
- Cowork 예약 작업은 그대로 두면 **화요일마다 둘 다 발행하게 된다**. Claude Code로 옮길 때는 Cowork 예약 작업(유튜브 주제 리서치 리포트 자동 발행)을 끄거나 삭제할 것. 핫 주제(월요일) 예약 작업은 별개.
- Cowork 프로젝트 문서 `claude/발행 로그.md`·`claude/RUNBOOK-자동발행.md`와 이 폴더의 `docs/`는 2026-11-15 시점에 같은 내용. 이후에는 한쪽만 갱신하거나, 회차 뒤에 Cowork 세션에 "docs/발행 로그.md 내용을 프로젝트 문서에 반영"이라고 시키면 된다.
- 노션 ID 고정값: 건강한마케팅 페이지 `3ca9025a-8e5c-81f2-bb1a-d63d29e07ca0` / 허브(건드리지 않음) `3c89025a-8e5c-8162-91a5-ee0049a5a9d2` / 발행 기록 DB(현재 미사용) `3b1e63d3957f4af38e6bc571ce9ca4d0` / 사월PD `3ca9025a-8e5c-8167-90f5-dfe1bd988211` · 라온PD `3ca9025a-8e5c-815e-8f5a-e78016d19bf0` · 덕PD `3ca9025a-8e5c-81fc-8e3a-f897f9dfa01d`(현재 미갱신).
