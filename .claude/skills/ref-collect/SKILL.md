---
name: ref-collect
description: 유튜브(롱폼·쇼츠)·인스타 릴스에서 국내·해외 '터진' 레퍼런스를 모아 검수 대기 목록을 만든다. "레퍼런스 수집", "주제 찾기", "소재 크롤링", "이번 주 터진 영상" 요청에 사용.
---

# 레퍼런스 수집 → 검수 대기

목적: 감으로 주제를 짜내지 않고, **이미 반응이 검증된 영상**에서 주제와 구조를 가져온다. 해외를 먼저 본다(국내 콘텐츠는 해외 파생이 많다).

## 순서
1. `python3 reels/scripts/collect.py youtube --period week` (특정 채널만: `--fit 유이선생`, 해외만: `--region GLOBAL`). 키워드·기준은 `reels/config.json`.
2. 인스타: `APIFY_TOKEN`이 있으면 `python3 reels/scripts/collect.py instagram`. 없으면 건너뛰고 그 사실을 보고한다. 사용자가 준 링크는 `collect.py add <url> --fit <채널>`.
3. `python3 reels/scripts/collect.py list --status 검수대기`로 통과분을 본다.
4. 통과분마다 한 줄 판단을 붙인다 — `collect.py set <id> --topic "한국어 한 줄 주제" --fit <우리 채널> --note "왜 터졌나 / 우리 채널로 옮기면"`.
   - 우리 채널에 못 옮기는 것(정치·혐오·의료 분야에 부적절한 상금·탈락 연출 등)과 채널 금지 테마(스타라인: 광대·윤곽·양악)는 `--status 제외`.
   - `촬영대기`로 올리는 것은 **사람이 고른다**. 추천만 하고 상태는 바꾸지 않는다(사용자가 시키면 바꾼다).
5. `python3 reels/scripts/dashboard.py` → `reels/out/dashboard.html` 갱신.
6. 보고: 수집 수 · 검수 대기 수(국내/해외, 플랫폼별) · 캐러셀 후보(🎠) · 채널별 추천 3개씩(배수·조회·한 줄 이유) · 못 얻은 것.

## 판정 기준 (collect.py judge)
- 제외: 참여율 (좋아요+댓글)÷조회 < 0.5% — 광고·부풀리기 의심.
- 통과: 평소의 5배 이상(채널 중앙값 조회수 대비, 없으면 구독자 대비) + 최소 조회(국내 1만·해외 5만), 또는 대형 조회(국내 30만·해외 100만).
- 캐러셀 후보: 통과 + 10배 이상 + 댓글 100 이상 → `/carousel-make` 대상.
- 수치를 못 얻은 항목은 null. **지어내지 않는다.** 검수 때 영상 페이지에서 확인한다.

## 주의
- 인스타 계정·해시태그는 `reels/config.json`의 `instagram.accounts/hashtags`에 사용자가 직접 본 것만 넣는다. 모르는 핸들을 추측해 넣지 않는다.
- 유튜브 검색 기간 필터(`period_sp`)가 0건이면 스크립트가 일반 검색으로 대체한다 — 이때 오래된 영상이 섞이므로 `uploaded`를 확인한다.
- 월요일 핫 주제 리포트(docs/RUNBOOK-핫주제.md)의 채택 영상과 겹치면 note에 "핫 주제 #N"이라고 적는다.
