# 메신저 / 회의록 판별 규칙 추가

## Context
txt를 불러오거나 본문창에 붙여넣을 때 메신저와 회의록을 구분하려고 판별 규칙 두 개를 정하기로 했다. 지금은 `meeting_patterns` 기본값이 `[]`이고 메신저 판별 규칙은 없어서, 자동 판별은 Confluence URL만 된다(`doc/DECISIONS.md` 9절 보류 항목).

사용자가 준 샘플:
- **메신저** (양식 설명으로 받음. 닉네임 괄호는 없을 수 있음)
  ```
  [김상정 (Nickname)] 2026-09-28 00:59
  메신저 내용

  [김상정 (Nickname)] 2026-09-28 00:59
  메신저 내용2
  ```
- **회의록** (전사 txt 파일. **UTF-16 LE + BOM**, 줄바꿈 CRLF)
  ```
  발화자 1  (00:01)
  음성 녹음 중입니다.

  발화자 2  (00:04)
  음성 녹음입니다.
  ```
  - `발화자 N` 뒤 공백 2칸, `(MM:SS)` 경과 시간. 1시간을 넘으면 `(H:MM:SS)`일 것으로 추정(샘플에는 없음).
  - 파일 안에 날짜가 없다. 원본 파일명이 `…260928…`로 날짜(YYMMDD)를 포함하는 것으로 보인다(업로드 과정에서 한글 부분이 `_`로 바뀜).

입력 경로(사용자 설명):
- 회의록 녹취는 주로 **txt 파일**(드롭 / `txt 열기…`)로 들어온다.
- 메신저 대화는 주로 본문창에 **직접 붙여넣는다**. → 두 경로 모두에서 판별한다.

## 확인된 문제
1. **회의록 txt가 깨져서 읽힌다.** `decode_bytes`는 utf-8 → cp949만 시도하므로, UTF-16 파일은 cp949 `errors="replace"`로 디코딩돼 본문이 깨지고 판별도 실패한다. (이전 계획에서 "샘플 확인 뒤 처리"로 보류한 항목)
2. **메신저 헤더의 날짜가 우선순위 검색에 안 걸린다.** `extract_date`의 1단계(줄 맨 앞, `[`/`(` 허용)는 `[이름] 날짜` 형태를 못 잡는다. 지금은 2단계(본문 전체)에서 찾아서 결과는 맞지만, 본문 **어디든** `2026-10-01 배포 예정`처럼 날짜로 시작하는 줄이 있으면 1단계에서 그 날짜가 잡힌다.

## 변경 — `wiki_collector.py`

### 디코딩
- `decode_bytes`: BOM으로 먼저 분기한다.
  - `\xff\xfe` / `\xfe\xff` → `data.decode("utf-16", errors="replace")` (BOM이 byte order를 정함. 잘린/홀수 길이 파일에서 `UnicodeDecodeError`가 GUI 콜백까지 올라가지 않게 cp949 경로처럼 replace)
  - 그 외 기존대로 `utf-8-sig` → 실패 시 `cp949`
- `read_text_file`에서 디코딩 뒤 `\r\n`/`\r` → `\n`으로 정규화한다. 전사 파일이 CRLF라서 그대로 두면 raw md에 `\r\n`이 섞인다(`write_text`는 `\r`을 지우지 않음). 판별 정규식은 줄 끝을 `[ \t\r]*$`로 통일한다(복붙 텍스트 방어).

### 판별 규칙 (기본값)
- `meeting_patterns` 기본값:
  ```
  ^발화자 \d+[ \t]+\((?:\d+:)?\d{1,2}:\d{2}\)[ \t\r]*$
  ```
- 새 키 `messenger_patterns` 기본값:
  ```
  ^\[[^\]\n]+\][ \t]+\d{4}-\d{2}-\d{2}[ \t]+\d{1,2}:\d{2}[ \t\r]*$
  ```
  - `[ \t\r]*$`는 줄 끝 공백·CR만 흡수하고 다음 줄로 넘어가지 않는다.
- `detect_kind` 반환값에 `"messenger"` 추가. 순서: Confluence URL → 회의록 → 메신저 → `None`.
  - 공통 헬퍼 `_any_match(patterns, text)`로 잘못된 정규식 건너뛰기를 재사용한다.
  - 둘 다 매치되는 경우는 샘플상 없다고 보고 회의록을 우선한다(녹취가 wiki 대기 목록에 잘못 들어가는 쪽이 더 나쁨).
- 기존 `config.json`은 `load_config`가 **빠진 키만** 기본값으로 채운다. 그래서 `messenger_patterns`는 자동으로 들어가지만, 이미 `"meeting_patterns": []`가 저장된 config에는 새 기본값이 들어가지 않는다. → `load_config`에서 `meeting_patterns`가 **빈 리스트면** 기본값으로 채운다(사용자가 일부러 끄려면 매치되지 않는 패턴을 넣도록 README에 적음). 이 한 키만 예외로 둔다.

### 날짜 추출
- `_first_date`의 anchored 접두어에 선택적 `[이름]` 블록을 허용한다:
  `^[ \t]*(?:\[[^\]\n]*\][ \t]*)?[\[(]?[ \t]*(?:<pat>)`
  → `[김상정 (Nickname)] 2026-09-28 00:59`가 1단계에서 잡혀, 본문 중간 줄의 날짜보다 헤더 날짜가 우선된다.
- 회의록 날짜: 본문에 날짜가 없으므로 **파일명에서** 추출한다. `load_txt`가 파일명을 제목칸에 넣으므로, `save_messenger` 안에서(이미 `title`을 받음) 본문에서 날짜를 못 찾으면 제목(=파일명)에서 찾는다. GUI(`save_now`)는 바꾸지 않는다.
  - `extract_date(body, …, default=None)` → 없으면 `extract_date(title, patterns + [YYMMDD 패턴], today)`.
  - YYMMDD 패턴: `(?<!\d)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?!\d)` → `y`가 두 자리면 `2000 + y`. 이 패턴은 **제목에만** 적용한다(본문의 6자리 숫자 오인 방지).
  - `_first_date`에서 `int(m.group("y"))`가 100 미만이면 2000을 더한다(YYMMDD용이라고 주석으로 밝힘. 기존 패턴은 `20\d{2}`라 영향 없음).
  - 메신저에도 같은 폴백이 적용되지만, 메신저는 헤더에 날짜가 있어 영향 없음.

### GUI
- **붙여넣기 판별 추가**: `self.body.bind("<<Paste>>", self.on_paste)`와 `<<PasteSelection>>`(X11 가운데 버튼)도 같은 핸들러에 바인딩. Windows에서는 Ctrl+V, Shift+Insert 모두 `<<Paste>>`로 들어온다.
  - `on_paste`는 기본 붙여넣기를 막지 않고(`return None`), `self.root.after_idle(self.detect_body_kind)`로 **붙여넣기가 끝난 뒤** 판별한다.
  - `detect_body_kind()`: 본문이 비었거나 공백뿐이면 아무것도 하지 않는다. 그 외에는 본문 전체(`get_body()`)에 `detect_kind`를 적용한다. `load_txt`와 같은 라벨/상태줄 로직을 공유하도록 `_apply_kind(kind, source_label)` 헬퍼로 뺀다. 라벨 dict는 기존 `confluence`/`meeting`에 `messenger`를 더한 전체를 쓴다(붙여넣은 URL 한 줄은 라디오가 Confluence로 바뀜. `on_save`도 URL이면 Confluence로 처리하므로 일치). 상태줄 예: "붙여넣음 (메신저로 판별)" / 판별 안 되면 "붙여넣음 (유형 판별 안 됨, 선택 유지)".
  - 본문 일부에 덧붙여 넣는 경우도 본문 전체로 판별한다(대화 헤더가 이미 있으면 결과는 같음).
  - 붙여넣은 텍스트의 `\r\n`은 Tk가 클립보드에서 `\n`으로 바꿔 주므로 따로 정규화하지 않는다(판별 정규식의 `[ \t\r]*$`가 남은 `\r`도 흡수).
  - 제목칸은 건드리지 않는다(붙여넣기에는 파일명이 없으므로 지금처럼 비어 있으면 저장 시 제목 제안).
  - 제목 제안 대기 중에는 라디오가 비활성이므로 판별 결과를 적용하지 않는다. `self.busy` 검사는 `after_idle` 콜백인 `detect_body_kind()` 안에서 하고, 건너뛸 때는 상태줄("제목 제안 중…")도 덮어쓰지 않는다. (busy 중에도 본문 Text는 활성이라 붙여넣기 자체는 된다)
  - 회의록 txt를 불러온 뒤 메신저 대화를 덧붙이면 본문 전체 기준·회의록 우선이라 `meeting`으로 남는다. DECISIONS 10절에 적는다.
- 키 입력으로 직접 타이핑하는 경우는 판별하지 않는다(매 키마다 판별하면 입력 도중 라디오가 바뀜).
- `load_txt`의 라벨 dict에 `"messenger": "메신저로"` 추가. 메신저로 판별되면 라디오가 `메신저`로 바뀐다(회의록을 골라 둔 상태에서 메신저 txt를 넣은 경우 교정). 이는 DECISIONS 9절의 "판별 결과가 회의록 선택을 메신저로 덮어쓰지 않음"을 **부분 변경**한다: 메신저 헤더 패턴이 명시적으로 매치될 때만 덮어쓰고, 회의록 패턴을 먼저 검사하므로 녹취가 메신저로 오판될 위험은 낮다. 패턴이 아무것도 안 맞으면 지금처럼 선택 유지.

## 테스트 — `test_wiki_collector.py`
- `decode_bytes`: UTF-16 LE BOM / BE BOM 바이트 → 원문 복원, 홀수 길이 UTF-16 바이트 → 예외 없음. 기존 utf-8/cp949 케이스 유지.
- `read_text_file`: CRLF 파일 → `\n`만 남음.
- `detect_kind`: 샘플 메신저(닉네임 있음/없음) → `"messenger"`, 샘플 회의록(LF, CRLF, `(1:02:03)`) → `"meeting"`, `홍길동: 안녕` → `None`, 기존 URL 케이스 유지. 기존 "패턴이 비어 있으면 판별 안 됨" 케이스는 cfg에 `meeting_patterns: []`를 명시해 유지.
- `extract_date`: `[이름] 2026-09-28 00:59\n2026-10-01 배포` → `2026-09-28`.
- 파일명 날짜: `save_messenger(..., title="회의_260928_2", body=<날짜 없는 전사>, source="meeting")` → 파일명·frontmatter `date`가 `2026-09-28`. 본문의 6자리 숫자는 날짜로 쓰지 않음.
- `load_config`: 저장된 `meeting_patterns: []` → 기본값으로 채워짐.

## 문서
- README: 드롭 행을 "utf-8/UTF-16(BOM) → cp949", "메신저/회의록/Confluence 판별"로 갱신. config 표에 `messenger_patterns` 추가, `meeting_patterns` 기본값과 빈 리스트 처리 설명. 회의록 날짜는 파일명(YYMMDD)에서 가져오며, 제목을 바꾸면 오늘 날짜로 저장된다는 한계를 적는다.
- `doc/DECISIONS.md`에 10절 추가: 두 규칙, 판별 우선순위, 메신저 판별 시 라디오 교정(9절 결정 갱신), UTF-16 처리와 CRLF 정규화, 빈 `meeting_patterns` 자동 채움, 파일명 날짜 폴백. 9절 보류 항목 중 UTF-16을 해결로 표시.
- `plan/PLAN.md` TODO 5 체크.

## 건너뛴 것
- 직접 타이핑, 텍스트(파일이 아닌) 드래그앤드롭 시 판별: 주 입력 경로가 아니다. 필요하면 저장 직전 판별로 확장.
- 회의록 전용 제목 프롬프트, 발화자 이름 매핑: 회의록 스킬 연계 때.

## 검증
- Xvfb에서 GUI 시나리오: `root.clipboard_clear(); root.clipboard_append(sample)` → `body.focus_force(); body.event_generate("<<Paste>>")` → `root.update()` → `kind_var.get()` 확인.
  - 메신저 붙여넣기 → `messenger`, 회의록 라디오 상태에서 메신저 붙여넣기 → `messenger`로 교정, 회의록 txt 불러오기 → `meeting`
  - `busy=True`일 때 라디오·상태줄 유지, 빈 클립보드 붙여넣기 → 변화 없음
- `python test_wiki_collector.py` 전체 통과.
- 실제 샘플 파일(UTF-16)로 `read_text_file` → `detect_kind` == `"meeting"` 확인.

## 리뷰 반영
1. (필수) UTF-16 디코딩 오류 처리 → 반영: `errors="replace"`, 홀수 길이 테스트 추가.
2. (필수) 파일명 날짜 폴백 위치 → 반영: `save_now`가 아니라 `save_messenger` 안에서 처리하고 `save_messenger` 결과로 테스트.
3. (필수) 메신저 판별 시 라디오 덮어쓰기가 9절 결정과 충돌 → 반영: GUI 절과 DECISIONS 10절에 부분 변경 이유를 명시.
4. (권장) 제목을 바꾸면 회의록 날짜가 오늘로 떨어짐 → 반영: README에 한계로 적음.
5. (권장) CRLF가 raw md에 섞임 → 반영: `read_text_file`에서 `\n`으로 정규화.
6. (권장) 줄 끝 표기 불일치 → 반영: `[ \t\r]*$`로 통일.
7. (선택) y<100 보정 범위 → 반영: 주석으로 YYMMDD용임을 밝힘.

필수 제안은 모두 국소 수정이라 계획 구조가 바뀌지 않아 재리뷰는 하지 않았다.

### 2차 리뷰 (붙여넣기 판별 추가 후)
사용자 추가 요청(메신저는 주로 붙여넣기, 회의록은 주로 파일)으로 계획이 바뀌어 리뷰를 한 번 더 받았다. 필수 없음.
1. (권장) busy 검사 시점 → 반영: `after_idle` 콜백에서 검사, 상태줄 유지.
2. (권장) 빈 본문 붙여넣기 → 반영: 아무것도 하지 않음.
3. (권장) Confluence 라벨 누락 시 KeyError → 반영: 전체 dict 사용, 붙여넣기에서도 Confluence 판별 명시.
4. (권장) Xvfb 검증 절차 구체화 → 반영.
5. (선택) X11 `<<PasteSelection>>` → 반영: 같은 핸들러에 바인딩.
6. (선택) 덧붙여넣기 시 회의록 우선 → 반영: DECISIONS 10절에 기록.
