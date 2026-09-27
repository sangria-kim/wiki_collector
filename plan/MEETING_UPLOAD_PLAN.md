# 회의 녹취(전사 txt) 업로드 추가

## Context
지금은 메신저 대화와 Confluence URL만 raw에 저장한다. 회의록을 만들려고 녹음 전사 txt를 올리면 raw에 저장되도록 한다. 회의록 생성은 나중에 별도 스킬과 연계하고, 이번에는 **업로드(저장)만** 만든다.
사용자 결정:
- 창 상단에 `메신저 / Confluence / 회의록` 라디오 버튼
- txt를 불러오면 내용을 보고 유형을 자동 판별. 판별 규칙은 나중에 샘플을 보고 정하므로 지금은 틀만 만든다
- 녹취 파일은 Wiki 변환 대기 목록에 **넣지 않음**

## 0. 계획 문서 보관
- 승인 뒤 첫 단계로 이 계획을 `plan/MEETING_UPLOAD_PLAN.md`에 덮어쓴다. `CLAUDE.md`는 이미 있으므로 수정하지 않는다.

## 변경 — `wiki_collector.py` (단일 파일 유지)

### 로직
- `DEFAULT_CONFIG`에 `"meeting_patterns": []` 추가: 본문이 이 정규식 중 하나에 매치되면 회의록으로 판별. 샘플을 받은 뒤 config나 기본값에 채운다.
- `detect_kind(text, cfg)` → `"confluence" | "meeting" | None`
  - `is_url(text, confluence_host)`이면 `"confluence"`
  - `meeting_patterns` 중 하나라도 `re.search`에 매치되면 `"meeting"`. 잘못된 정규식(`re.error`)은 그 패턴만 건너뛴다.
  - 둘 다 아니면 `None`(판별 안 됨). 메신저를 적극적으로 판별할 규칙이 아직 없으므로, 판별 안 됨이 사용자의 선택을 덮어쓰지 않게 한다.
- `save_messenger(raw_dir, title, body, date_patterns, now=None, source="messenger")`: `source`로 폴더(`raw/<source>/`)와 frontmatter `source`를 정한다. 회의록은 `source="meeting"` → `raw/meeting/YYYY-MM-DD_<제목>.md`. 날짜 추출, 파일명 규칙, 중복 처리는 그대로 재사용한다.

### GUI (`App`)
- 제목 행 위(row 0)에 `tk.Radiobutton` 3개와 `self.kind_var = tk.StringVar(value="messenger")`를 둔다. 기존 행은 한 칸씩 내린다(`rowconfigure(1)` → `rowconfigure(2)`).
- 라디오 3개를 `self.buttons`에 추가한다. 제목 제안(비동기) 대기 중에 유형이 바뀌지 않게 `set_busy`가 함께 비활성화한다.
- `load_txt`: 본문을 채운 뒤 `kind = detect_kind(text, self.cfg)`.
  - 결과가 있으면 `self.kind_var.set(kind)`, 상태줄 "불러옴: x.txt (회의록으로 판별)"
  - `None`이면 선택을 유지하고 상태줄 "불러옴: x.txt (유형 판별 안 됨, 선택 유지)"
- `on_save` 분기:
  - 본문이 URL 한 줄이거나 Confluence가 선택된 경우 → 기존 `fetch_confluence_url`. Confluence를 골랐는데 URL이 아니면 상태줄에 "Confluence URL 한 줄을 입력하세요"를 띄우고 멈춘다.
  - 메신저, 회의록 → 기존 흐름(제목이 비어 있으면 자동 제안 후 저장)
- `save_now`: `source=self.kind_var.get()`로 저장한다. `meeting`이면 `add_pending`을 호출하지 않고 상태줄 "회의록 저장: meeting/...". 저장에 성공하면 제목/본문을 비울 때 `self.kind_var.set("messenger")`로 되돌려, 다음 메신저 대화가 회의록으로 잘못 저장(대기 목록 누락)되지 않게 한다.
- 측면 안내 문구를 짧게 수정한다.

## 문서
- README 사용 표: 회의록 행을 추가한다(`raw/meeting/…`, 대기 목록 제외). config 표에 `meeting_patterns`(정규식 리스트, 기존 `config.json`에는 직접 추가)를 추가한다.
- DECISIONS.md: 라디오 + 자동 판별 틀, 판별 안 되면 선택 유지, 저장 뒤 메신저로 복귀, 녹취는 pending에서 제외, 판별 규칙은 샘플을 받은 뒤 정함. 3절의 "제목 입력칸은 메신저 전용" 문구를 회의록도 포함하도록 고친다.

## 건너뛴 것
- 회의록 스킬 연계, 전용 `meeting_title_prompt`: 스킬을 연계할 때 추가한다.
- `fallback_title`의 기본 제목 분기("회의록"): GUI는 불러올 때 파일명으로 제목을 채우므로 거의 쓰이지 않는다.
- UTF-16 전사 txt 디코딩: `decode_bytes`는 UTF-8/cp949만 처리한다. 샘플을 받을 때 인코딩을 확인하고, UTF-16이면 BOM 분기를 추가한다.

## 검증
- `test_wiki_collector.py`에 추가:
  - `test_detect_kind`: URL은 confluence, `meeting_patterns=[r"^회의록"]`일 때 해당 본문은 meeting, 그 외는 None, 패턴이 비어 있으면 None, 잘못된 정규식(`"["`)은 예외 없이 건너뜀
  - `test_save_messenger`에 `source="meeting"` 케이스를 추가해 `meeting/` 경로와 frontmatter를 확인한다
  - `test_config`에 `cfg["meeting_patterns"] == []` 한 줄
- `python test_wiki_collector.py` 통과
- GUI 수동 확인: `python wiki_collector.py`, stub `title_cmd`(README 예시) 사용
  - 회의록을 선택하고 txt를 불러온 뒤 저장 → 선택이 유지되고 `raw/meeting/`에 파일이 생기며 대기 목록 수는 그대로, 저장 뒤 라디오가 메신저로 돌아간다
  - 메신저 저장, Confluence URL 저장은 기존과 똑같이 동작한다
  - Confluence를 고르고 일반 텍스트를 저장하면 안내 문구가 뜨고 저장되지 않는다

## 리뷰 반영
1. (필수) 0절 이미 처리됨, CLAUDE.md 덮어쓰기 위험 → **반영**: 0절을 계획 보관만 남기고 CLAUDE.md 수정 제거.
2. (필수) 판별 결과가 사용자의 회의록 선택을 메신저로 덮어씀 → **반영**: `detect_kind`가 판별 못 하면 `None`, `load_txt`는 선택 유지. 테스트 기대값 변경.
3. (권장) 잘못된 정규식 / 문자열 값 → **반영(일부)**: `re.error`는 패턴별로 건너뜀. 미반영: 문자열 값 자동 감싸기 — README에 리스트로 명시하는 것으로 충분.
4. (권장) 제목 제안 대기 중 라디오 변경 → **반영**: 라디오를 `self.buttons`에 추가.
5. (권장) 저장 뒤 회의록 선택이 남음 → **반영**: 저장 성공 시 메신저로 복귀.
6. (선택) `fallback_title` 인자 → **반영(삭제)**: 실사용이 거의 없어 변경에서 빼고 `건너뛴 것`에 기록.
7. (선택) config 호환 검증 → **반영**: `test_config` 한 줄, README에 기존 config 직접 추가 안내.
8. (선택) UTF-16 인코딩 → **미반영**: 실제 전사 도구 인코딩이 확인되지 않음. `건너뛴 것`에 기록하고 샘플 확인 때 처리.

필수 제안 반영으로 바뀐 부분은 `detect_kind` 반환값과 `load_txt` 분기뿐이라 계획이 크게 바뀌지 않았다고 보고 재리뷰는 하지 않았다.
