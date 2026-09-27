# wiki_collector
llm-wiki에 추가할 raw 자료들을 수집

메신저 대화(복붙 / export txt), 회의 녹취(전사 txt), Confluence 페이지를 llm-wiki의 `raw/` 폴더에 저장하고, 버튼 하나로 Claude CLI를 불러 wiki 변환까지 실행하는 작은 Windows 데스크톱 앱입니다.

## 실행

```
pip install tkinterdnd2          # 드래그앤드롭용 (없어도 'txt 열기…' 버튼으로 동작)
python wiki_collector.py
```

- 처음 실행하면 스크립트(또는 exe) 옆에 `config.json`이 생성되고 raw 폴더와 llm-wiki 폴더를 고르는 창이 뜹니다.
- 다른 config 파일로 실행하려면 환경변수 `WIKI_COLLECTOR_CONFIG`에 경로를 지정합니다.

## exe 빌드 (Windows)

```
build.bat      → dist\WikiCollector.exe
```

## 사용

| 동작 | 결과 |
| --- | --- |
| 본문에 붙여넣기 → `raw에 저장` | `raw/messenger/YYYY-MM-DD_<제목>.md`. 제목이 비어 있으면 `title_cmd`로 자동 제안한 뒤 저장. 붙여넣으면 본문 전체로 유형(Confluence URL / 회의록 / 메신저)을 판별해 상단 라디오를 바꿈 |
| `.txt`를 창 어디에나 드롭 (또는 `txt 열기…`) | 본문이 채워지고 제목칸에 파일명이 들어감 (UTF-16(BOM) → utf-8 → cp949 순서로 디코딩, CRLF는 LF로). 내용으로 유형(Confluence URL / `meeting_patterns` → 회의록 / `messenger_patterns` → 메신저)을 판별해 상단 라디오를 바꾸고, 판별되지 않으면 선택을 유지 |
| 상단 `회의록` 선택 → `raw에 저장` | `raw/meeting/YYYY-MM-DD_<제목>.md`. 날짜는 본문 → 제목(불러온 파일명의 `YYMMDD`) → 오늘 순서라, 제목을 바꾸면 오늘 날짜로 저장될 수 있음. Wiki 변환 대기 목록에는 넣지 않음. 저장 뒤 라디오는 `메신저`로 돌아감 |
| 본문에 Confluence URL 한 줄만 넣고 → `raw에 저장` | `raw/confluence/<pageId>_<제목>.md`. 같은 pageId가 있으면 덮어쓰기(업데이트), 실패하거나 빈 출력이면 저장하지 않음 |
| `Wiki로 변환` | 대기 목록(`raw/.wiki_collector_pending.json`)의 파일을 `wiki_cmd`로 변환. 성공하면 목록을 비우고, "미분류:" 줄은 결과 창 위쪽에 따로 표시 |

## config.json

| 키 | 설명 |
| --- | --- |
| `raw_dir`, `wiki_dir` | raw 폴더, wiki 변환을 실행할 작업 폴더(cwd) |
| `title_cmd` / `title_prompt` | 제목 제안 명령과 프롬프트 (`{text}` = 본문 앞 `title_max_chars`자) |
| `confluence_cmd` / `confluence_prompt` | Confluence 읽기 명령과 프롬프트 (`{url}`) |
| `confluence_host` | 비어 있지 않으면 이 host가 들어간 URL만 Confluence로 처리 |
| `confluence_require_heading` | true면 출력이 `# 제목`으로 시작할 때만 저장 (에러 문구 저장 방지) |
| `wiki_cmd` / `wiki_prompt` | wiki 변환 명령과 프롬프트 (`{files}` = raw 기준 상대경로 목록, `{raw_dir}`) |
| `*_timeout` | 초 단위 (제목 60, Confluence 180, wiki 1800) |
| `date_patterns` | 메신저 대화 날짜 추출용 정규식 목록 (named group `y`, `m`, `d`) |
| `meeting_patterns` | 회의록 판별용 정규식 **리스트** (줄 단위 `^` 매치, 잘못된 정규식은 무시). 기본값은 전사 형식 `발화자 1  (00:01)`. 빈 리스트면 기본값으로 채움(끄려면 매치되지 않는 패턴을 넣음) |
| `messenger_patterns` | 메신저 판별용 정규식 리스트. 기본값은 헤더 형식 `[이름 (닉네임)] 2026-09-28 00:59`(닉네임 생략 가능). 회의록 판별이 먼저 적용됨 |

명령 템플릿 규칙:
- `*_cmd`에 `{prompt}`가 없으면 렌더링된 `*_prompt`를 **stdin으로** 넘깁니다 (기본값. 긴 본문과 줄바꿈도 안전).
- `*_cmd`에 `{prompt}`(또는 `{text}`/`{url}`/`{files}`)가 있으면 그 자리에 큰따옴표를 이스케이프해서 인라인으로 넣습니다. Windows에서는 줄바꿈이 공백으로 바뀌고, cmd 명령줄 길이 제한(8191자)이 적용됩니다.

로컬 테스트용 stub 예시:
```json
"title_cmd": "python -c \"print('테스트 제목')\"",
"confluence_cmd": "python -c \"print('# 테스트 페이지\\n본문')\"",
"wiki_cmd": "python -c \"import sys; print(sys.stdin.read())\""
```

## 테스트

```
python test_wiki_collector.py
```

구현 중에 임의로 판단한 내용은 [DECISIONS.md](doc/DECISIONS.md)에 정리되어 있습니다.
