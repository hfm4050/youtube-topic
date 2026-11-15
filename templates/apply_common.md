# 노션 페이지 갱신 절차 (유튜브 기획 리포트 페이지 — 단순 콘텐츠 교체 작업)

대상 페이지 ID: `3ca9025a-8e5c-81f2-bb1a-d63d29e07ca0` ("건강한마케팅 — 전체 채널")
도구: ToolSearch로 `select:mcp__Notion__notion-create-attachment,mcp__Notion__notion-update-page` 로드.
질문하지 말고 순서대로 끝까지 진행. 모든 update-page 호출에 `allow_async: false`.

## 1. CSV 업로드
- `work/out/csv_body.txt`를 Read 도구로 전체 읽는다(약 45KB, 64줄; 필요하면 offset/limit로 나눠 읽되 전부 읽을 것).
- `notion-create-attachment` 호출: `filename` = `전체7개채널_63개주제_{DATE}_한글수정.csv`, `content_type` = `text/csv`, `content` = **BOM 문자 `﻿`(U+FEFF)를 첫 글자로 넣은 뒤** 파일 내용 전체를 그대로(한 글자도 바꾸지 말고, 줄 순서·따옴표 그대로).
- 응답의 `file-upload://{id}` 값을 `work/out/upload_full.txt`에 저장(Bash echo). 업로드는 수 분 내 만료되므로 바로 2단계로.

## 2. 페이지 파트 생성
- Bash: `python3 scripts/gen.py --date {DATE} --file "file-upload://{id}"` (위에서 받은 값 그대로). 출력에 `OK` 가 있어야 한다.
- 생성 파일: `work/out/p0_head.md`(헤더+이번 달), `p1_past.md`…(지난 달 토글, 최신 달부터), 마지막 `p{n}_footer.md`(푸터) — gen.py 출력의 parts 목록 순서대로.

## 3. 분할 적용 (순서 엄수, 각각 끝난 뒤 다음)
1. `p0_head.md`를 Read 하고 `notion-update-page` `command: replace_content`, `new_str` = 파일 내용 **전체 그대로**. 이 파트에는 `<page url="…">` 블록(11/10 기준 12개)이 들어 있고 페이지의 자식 페이지 전부가 여기 포함되므로 `allow_deleting_content`는 넣지 않는다(기본 false). 만약 "child content would be deleted" 오류가 나면 p0_head.md의 `<page url=` 개수가 health_raw.md 와 같은지 확인하고, 빠진 게 있으면 보고하고 중단(절대 allow_deleting_content: true 로 재시도하지 말 것).
2. `p1_past.md` Read → `command: insert_content`, `position: {"type":"end"}`, `content` = 파일 전체.
3. 나머지 `p{k}_past.md` 를 순서대로 같은 방식 insert_content end.
4. 마지막 `p{n}_footer.md` 같은 방식 insert_content end.
5. **각 insert 호출이 오류/중단으로 끝났으면 재시도 전에 반드시 notion-fetch 로 그 토글이 이미 들어갔는지 확인**(11/3 교훈: 중단된 호출도 서버 반영 → 토글 중복). 중복됐으면 1번 replace_content 부터 다시.
- 각 호출 결과의 warnings 를 기록. 실패하면 같은 파트를 1회 재시도.
- Read 출력의 줄번호 접두어는 제거하고 원문만 넣는다. 파일 끝 개행 유무는 중요하지 않다.

## 4. 보고
최종 메시지에: 업로드 ID, 각 단계 성공/실패·warnings, 재시도 횟수. 페이지 본문은 메시지에 넣지 않는다.

## 5. 적용 후 검증 (별도 에이전트 또는 메인)
notion-fetch(include_file_urls: true) → 본문을 파일로 저장(scripts/extract_page.py 재사용 가능, --work 를 다른 폴더로) → 검사: `<toggle>` 짝(이전 +4), `<file ` 개수(이전 +1, 전부 서명 URL), ` · 최신` 1개(이번 주차), `# 📅` 1개, `<page url=` 개수 유지, 최상위 순서(헤더 → --- → H1 → 이번 달 토글 → --- → 지난 달 토글들 → --- → 주의 → 파일 안내), 이번 주차 토글 안 구성, 예정 콜아웃 제거, `work/out/full_filled.md` 와 diff(`<file source=` 줄·빈 줄 제외) 0줄.
