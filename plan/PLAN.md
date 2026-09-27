# Wiki Collector — 구현 계획

> 구현 세션은 이 문서와 `wiki_collelctor_prd.md`를 읽고 시작. 하단 TODO는 사내 PC에서 확인 후 config/프롬프트에 반영.

## Context
Windows PC의 llm-wiki는 `raw/` 폴더(삼성 브라우저 PRD, Confluence 회의록)를 Claude로 wiki 변환해 쓰고 있음.
여기에 메신저 대화(복붙 텍스트 / export txt)와 Confluence URL을 빠르게 raw에 넣고, 버튼 하나로 wiki 변환까지 돌리는 작은 Windows 데스크톱 앱이 필요함.
프로젝트 폴더는 PRD 외에 비어 있어서 새로 만듦.

## 스택
**Python 3 + tkinter(표준 라이브러리) + tkinterdnd2**, PyInstaller로 단일 `WikiCollector.exe`로 빌드.
- 가볍고(수 MB), 런타임 설치 필요 없음. Mac에서도 그대로 실행돼서 여기서 개발/테스트 가능.
- 외부 의존성은 드래그앤드롭용 `tkinterdnd2` 하나뿐. LLM 호출은 전부 CLI subprocess로 처리(SDK 없음).

## 파일
```
wiki_collector/
  wiki_collector.py      # 앱 전체 (~300줄, 단일 파일)
  config.json            # 첫 실행 때 생성; 경로와 CLI 명령 템플릿
  test_wiki_collector.py # 순수 로직 assert 체크
  build.bat              # pyinstaller --onefile --windowed ...
```

### config.json (exe 옆에 두고 직접 수정)
```json
{
  "raw_dir": "C:/llm-wiki/raw",
  "wiki_dir": "C:/llm-wiki",
  "title_cmd": "codex exec \"다음 메신저 대화의 제목을 20자 이내 한 줄로만 답해:\n{text}\"",
  "confluence_cmd": "claude -p \"/<confluence-skill> {url} 페이지 본문을 마크다운으로만 출력해\"",
  "wiki_cmd": "claude -p \"raw의 다음 파일들을 wiki로 변환해줘: {files}\""
}
```
- raw_dir/wiki_dir가 없으면 첫 실행 때 폴더 선택 창을 띄움.
- CLI 명령은 템플릿 문자열로 둠. 사내 Confluence 스킬 이름이나 ChatGPT CLI 종류(codex 등)가 바뀌어도 코드를 고칠 필요가 없음.

## UI (단일 창)
1. **제목** 입력칸, 옆에 `[자동 제안]` 버튼
2. **본문** 텍스트 영역 (복붙용). 이 영역이 txt 파일 드롭 대상이기도 함
3. **Confluence URL** 입력칸과 `[가져오기]` 버튼
4. `[raw에 저장]` 버튼
5. 하단: "대기 중인 신규 파일 N개" 표시와 `[Wiki로 변환]` 버튼, 상태 표시줄

## 동작

### 1·2. 입력
- 복붙: 텍스트 영역에 붙여넣으면 됨.
- 드롭: `.txt`를 읽어 텍스트 영역에 채우고, 제목칸에는 **파일명(확장자 제외)**을 넣음.
  인코딩은 `utf-8-sig`를 먼저 시도하고 실패하면 `cp949`로 읽음(한국어 Windows 메신저 export 대비).

### 4. 제목 자동 제안 (복붙일 때)
- 제목칸이 비어 있는 상태에서 저장하거나 `[자동 제안]`을 누르면 `title_cmd`를 실행하고 stdout 첫 줄을 제목칸에 넣음. 사용자가 수정할 수 있음.
- 앞부분 3000자 정도만 넘김. CLI가 실패하면 본문의 첫 비어있지 않은 줄로 대체함.

### 3. 저장 규칙 (메신저, Confluence 공통)
- 경로: `raw/messenger/YYYY-MM-DD_<제목>.md`, `raw/confluence/<pageId>_<제목>.md`
- 파일명에서 `\/:*?"<>|`는 `_`로 바꿈. 같은 이름이 있으면 `_2`, `_3`을 붙임(메신저만).
- 파일 상단 frontmatter:
  ```
  ---
  source: messenger | confluence
  title: ...
  url: ...            # confluence만
  page_id: ...        # confluence만
  collected_at: 2026-09-25T10:00
  ---
  ```
- ⚠ PRD의 "같은 규칙"은 기존 raw 폴더 규칙을 말하는 것일 수 있음. 기존 파일명 예시를 받으면 여기에 맞춤(아래 확인 필요 항목 참고).

### 5·6. Confluence URL
- URL에서 pageId를 추출함: `pageId=123` 또는 `/pages/123/` 패턴. 둘 다 없으면 URL 해시를 키로 씀.
- 중복 확인: `raw/confluence/<pageId>_*.md` glob으로 찾음. 파일명 자체가 인덱스라 별도 DB는 두지 않음.
- `confluence_cmd`(사내 스킬을 부르는 claude CLI)를 실행하고 stdout을 본문으로 받음.
  - 사내 스킬은 CDP로 브라우저를 띄우고 로그인 쿠키로 Confluence에 접속해 페이지를 읽음. 그래서 실행 중에 브라우저 창이 뜨는 게 정상이고 시간이 수십 초 걸릴 수 있음.
    `timeout`을 넉넉히(기본 180초, config로 조정) 주고, 상태 표시줄에 "Confluence 읽는 중…"을 띄움.
  - 쿠키가 만료됐거나 로그인이 안 된 상태면 CLI가 실패하거나 빈 출력을 냄. 이 경우 파일을 저장하지 않고 "브라우저에서 Confluence 로그인 후 재시도"라고 안내함(빈 본문으로 덮어쓰면 기존 내용이 사라지므로 반드시 막아야 함).
  - 기존 파일이 있으면 같은 파일을 덮어쓰고(제목이 바뀌었으면 rename) 상태 표시줄에 "업데이트"라고 표시함.
  - 없으면 신규로 저장하고 "신규 추가"라고 표시함.
- 어느 쪽이든 결과는 대기 목록에 추가함(업데이트된 페이지도 wiki에 다시 반영해야 하므로).

### 7. Wiki 변환
- 대기 목록은 `raw/.wiki_collector_pending.json`에 저장된 파일 경로 배열. 앱을 재시작해도 유지됨.
- `[Wiki로 변환]`을 누르면 `messagebox.askyesno("신규 3개, 업데이트 1개 파일을 wiki로 변환할까요?")`로 다시 물어봄.
- 예를 누르면 `wiki_dir`를 cwd로 해서 `wiki_cmd`를 실행함({files}에는 raw 기준 상대경로 목록이 들어감).
  종료코드가 0이면 대기 목록을 비우고, 실패하면 목록을 유지하고 stderr를 보여줌.
- **메신저 대화는 해당 feature 문서에 반영**: 메신저 파일은 새 wiki 페이지로 만들지 않음. `wiki_cmd` 프롬프트에서 Claude에게 다음을 지시함.
  1. 대화 내용과 관련된 wiki의 feature 문서를 찾음.
  2. 그 문서의 "논의 이력" 섹션에 `### YYYY-MM-DD 메신저 논의 — <제목>` 항목을 추가함. 항목에는 결정 사항, 논의 요지, 미결 사항을 요약하고 raw 원본 경로를 링크함.
  3. 관련 문서를 못 찾으면 추측해서 넣지 않고, 결과 출력에 "미분류: <파일>"로 표시함. 앱은 이 내용을 결과 창에 보여줌.
  - 날짜는 frontmatter의 대화 날짜를 씀. 드롭한 export 파일은 파일 안의 첫 타임스탬프를 쓰고, 없으면 collected_at을 씀.
  - 프롬프트 템플릿은 config의 `wiki_cmd`에 있음. 실제 섹션 이름과 형식은 사내 wiki 구조를 확인한 뒤 확정함(TODO 1).

### 공통 구현 메모
- 모든 CLI 호출은 `subprocess.run(cmd, shell=True, cwd=..., capture_output=True, encoding="utf-8", creationflags=CREATE_NO_WINDOW)`로 함. `shell=True`여야 Windows에서 `claude.cmd`를 찾을 수 있음.
- CLI 호출은 `threading.Thread`에서 돌리고 결과는 `root.after`로 UI에 반영함(UI 멈춤 방지). 그동안 버튼은 비활성화함.
- 템플릿 치환 시 `{text}`/`{url}` 값에 들어 있는 큰따옴표는 이스케이프함. 긴 본문은 명령줄 길이 제한(8191자)에 걸리므로 `{text}` 대신 stdin으로 넘기는 방식도 지원함(`title_cmd`에 `{text}`가 없으면 stdin으로 넘김).

## 생략한 것
- 설정 GUI: config.json을 직접 수정하면 됨. 자주 바꾸게 되면 추가.
- 파일 목록/이력 뷰어: 탐색기로 확인하면 됨.
- 트레이 상주, 단축키: 필요하면 추가.

## TODO (사내 PC에서 확인 후 보완)
- [ ] **1. 사내 wiki md 구조 확인**: feature 문서의 위치와 파일명 규칙, frontmatter, 섹션 구성(기존 "논의 이력"류 섹션이 있는지)을 확인함. 그 결과로 `wiki_cmd` 프롬프트의 매칭 기준(feature명/태그/파일명)과 추가할 섹션 이름·형식을 확정함.
- [ ] **2. Confluence 스킬 호출 확인**: 스킬 이름, `claude -p`로 부를 수 있는지, 출력 형태(stdout 마크다운인지 파일로 쓰는지), 소요 시간을 확인하고 `confluence_cmd`와 timeout을 확정함.
- [ ] **3. 제목 제안용 ChatGPT CLI 명령 확인**(예: `codex exec`, `sgpt`)하고 `title_cmd`를 확정함.
- [ ] **4. 기존 raw 폴더의 파일명·폴더 규칙** 예시 1~2개를 보고 저장 규칙을 맞춤.
- [ ] **5. 메신저 export txt 샘플**을 보고 타임스탬프 형식을 확인해 대화 날짜 추출 규칙을 확정함.

위 항목은 전부 config.json이나 프롬프트 템플릿만 고치면 반영되도록 만듦(코드 수정 최소화).

## 검증
- `python test_wiki_collector.py`: pageId 추출, 파일명 정리, 중복 파일 찾기, cp949/utf-8 디코딩, 대기 목록 저장/로드를 assert로 확인.
- Mac에서 `python wiki_collector.py` 실행 후 수동 확인. 이때 config의 CLI 명령은 `echo` 스텁으로 바꿔 둠.
  - 복붙 저장 → 제목 제안 → md 생성 확인
  - txt 드롭 → 파일명이 제목으로 들어가는지 확인
  - 같은 Confluence URL 두 번 → 두 번째는 "업데이트"로 뜨고 파일이 1개만 있는지 확인
  - 변환 버튼 → 확인창 개수 확인 → 예 → 대기 목록 비워지는지 확인
  - Confluence CLI가 실패하거나 빈 출력을 낼 때 기존 파일이 덮어써지지 않는지 확인
- 사내 PC에서 테스트용 feature 문서 1개로 메신저 대화를 변환해 봄 → 해당 문서의 논의 이력에 날짜별 요약이 추가되는지, 관련 없는 대화는 "미분류"로 나오는지 확인.
- Windows에서 `build.bat`로 exe를 만든 뒤 실제 claude/codex CLI로 한 번 끝까지 실행해 봄.
