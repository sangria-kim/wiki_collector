# wiki_collector
llm-wiki에 추가할 raw 자료들을 수집

메신저 대화(복붙 / export txt)와 Confluence 페이지를 llm-wiki의 `raw/` 폴더에 저장하고, 버튼 하나로 Claude CLI를 불러 wiki 변환까지 실행하는 작은 Windows 데스크톱 앱입니다.

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
| 본문에 붙여넣기 → `raw에 저장` | `raw/messenger/YYYY-MM-DD_<제목>.md`. 제목이 비어 있으면 `title_cmd`로 자동 제안한 뒤 저장 |
| `.txt`를 본문에 드롭 (또는 `txt 열기…`) | 본문이 채워지고 제목칸에 파일명이 들어감 (utf-8 → cp949 순서로 디코딩) |
| Confluence URL → `가져오기` | `raw/confluence/<pageId>_<제목>.md`. 같은 pageId가 있으면 덮어쓰기(업데이트), 실패하거나 빈 출력이면 저장하지 않음 |
| `Wiki로 변환` | 대기 목록(`raw/.wiki_collector_pending.json`)의 파일을 `wiki_cmd`로 변환. 성공하면 목록을 비우고, "미분류:" 줄은 결과 창 위쪽에 따로 표시 |

## config.json

| 키 | 설명 |
| --- | --- |
| `raw_dir`, `wiki_dir` | raw 폴더, wiki 변환을 실행할 작업 폴더(cwd) |
| `title_cmd` / `title_prompt` | 제목 제안 명령과 프롬프트 (`{text}` = 본문 앞 `title_max_chars`자) |
| `confluence_cmd` / `confluence_prompt` | Confluence 읽기 명령과 프롬프트 (`{url}`) |
| `wiki_cmd` / `wiki_prompt` | wiki 변환 명령과 프롬프트 (`{files}` = raw 기준 상대경로 목록, `{raw_dir}`) |
| `*_timeout` | 초 단위 (제목 60, Confluence 180, wiki 1800) |
| `date_patterns` | 메신저 대화 날짜 추출용 정규식 목록 (named group `y`, `m`, `d`) |

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

구현 중에 임의로 판단한 내용은 [DECISIONS.md](DECISIONS.md)에 정리되어 있습니다.
