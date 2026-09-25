"""순수 로직 assert 체크. 실행: python test_wiki_collector.py"""

import datetime
import json
import os
import sys
import tempfile

import wiki_collector as wc

NOW = datetime.datetime(2026, 9, 25, 10, 0)
PY = f'"{sys.executable}"'


def test_page_id():
    assert wc.extract_page_id("https://c.example.com/pages/viewpage.action?pageId=12345") == "12345"
    assert wc.extract_page_id("https://c.example.com/spaces/BR/pages/987654/Some+Title") == "987654"
    assert wc.extract_page_id("https://c.example.com/display/BR/pages/55") == "55"
    h = wc.extract_page_id("https://c.example.com/display/BR/Some+Page")
    assert h.startswith("h") and len(h) == 13
    assert h == wc.extract_page_id(" https://c.example.com/display/BR/Some+Page ")


def test_sanitize():
    assert wc.sanitize_filename('a\\b/c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert wc.sanitize_filename("  제목. ") == "제목"
    assert wc.sanitize_filename("") == "untitled"
    assert len(wc.sanitize_filename("가" * 200)) == 80


def test_unique_and_find():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.md")
        assert wc.unique_path(p) == p
        open(p, "w").close()
        assert wc.unique_path(p) == os.path.join(d, "x_2.md")
        open(os.path.join(d, "x_2.md"), "w").close()
        assert wc.unique_path(p) == os.path.join(d, "x_3.md")

        conf = os.path.join(d, "confluence")
        os.makedirs(conf)
        for name in ("123_A.md", "1234_B.md", "123_C.md"):
            open(os.path.join(conf, name), "w").close()
        found = [os.path.basename(f) for f in wc.find_confluence_files(d, "123")]
        assert found == ["123_A.md", "123_C.md"], found


def test_decode():
    s = "안녕하세요 [오후 3:21] 홍길동"
    assert wc.decode_bytes(s.encode("utf-8")) == s
    assert wc.decode_bytes(b"\xef\xbb\xbf" + s.encode("utf-8")) == s
    assert wc.decode_bytes(s.encode("cp949")) == s


def test_extract_date():
    pats = wc.DEFAULT_CONFIG["date_patterns"]
    assert wc.extract_date("[2026. 9. 1] x", pats, "D") == "D"  # 공백 섞인 형식은 기본 패턴에 없음
    assert wc.extract_date("2026-09-03 10:00 a\n2026-09-04 b", pats, "D") == "2026-09-03"
    assert wc.extract_date("2026년 8월 7일 목요일\n2026-09-04", pats, "D") == "2026-08-07"
    assert wc.extract_date("2026/13/40 잘못된 날짜 2026.2.5", pats, "D") == "2026-02-05"
    assert wc.extract_date("날짜 없음", pats, "D") == "D"


def test_is_url():
    assert wc.is_url("  https://c.example.com/pages/viewpage.action?pageId=1 \n")
    assert not wc.is_url("https://a.com 참고하세요")
    assert not wc.is_url("대화\nhttps://a.com")
    assert not wc.is_url("ftp://a.com")


def test_titles():
    assert wc.clean_title('제목: "탭 그룹 동기화 논의"') == "탭 그룹 동기화 논의"
    assert wc.clean_title("**북마크 정리**") == "북마크 정리"
    assert wc.fallback_title("\n\n  첫 줄입니다  \n둘째") == "첫 줄입니다"
    assert wc.fallback_title("   ") == "메신저 대화"


def test_code_fence_and_md_title():
    assert wc.strip_code_fence("```markdown\n# T\nbody\n```\n") == "# T\nbody"
    assert wc.strip_code_fence("# T\n```py\nx\n```") == "# T\n```py\nx\n```"
    assert wc.markdown_title("intro\n# 페이지 제목\n## sub") == "페이지 제목"


def test_save_messenger():
    with tempfile.TemporaryDirectory() as raw:
        body = "2026-09-20 10:00 홍길동: 안녕\n김철수: \"네\""
        p1 = wc.save_messenger(raw, "탭/그룹: 논의", body, wc.DEFAULT_CONFIG["date_patterns"], NOW)
        assert os.path.basename(p1) == "2026-09-20_탭_그룹_ 논의.md", p1
        p2 = wc.save_messenger(raw, "탭/그룹: 논의", body, wc.DEFAULT_CONFIG["date_patterns"], NOW)
        assert os.path.basename(p2) == "2026-09-20_탭_그룹_ 논의_2.md"
        fm = wc.read_frontmatter(p1)
        assert fm == {"source": "messenger", "title": "탭/그룹: 논의", "date": "2026-09-20",
                      "collected_at": "2026-09-25T10:00"}, fm
        assert wc.read_text_file(p1).endswith(body + "\n")
        p3 = wc.save_messenger(raw, "", "날짜 없는 대화\n...", [], NOW)
        assert os.path.basename(p3) == "2026-09-25_날짜 없는 대화.md"


def test_save_confluence():
    with tempfile.TemporaryDirectory() as raw:
        url = "https://c.example.com/pages/viewpage.action?pageId=777"
        p, st, old = wc.save_confluence(raw, url, "```markdown\n# 스펙 v1\n본문\n```", NOW)
        assert st == "new" and old == [] and os.path.basename(p) == "777_스펙 v1.md"
        fm = wc.read_frontmatter(p)
        assert fm["page_id"] == "777" and fm["url"] == url and fm["title"] == "스펙 v1"

        # 같은 페이지, 같은 제목 → 덮어쓰기
        p2, st, old = wc.save_confluence(raw, url, "# 스펙 v1\n수정된 본문", NOW)
        assert p2 == p and st == "updated" and old == []
        assert "수정된 본문" in wc.read_text_file(p)

        # 제목 변경 → rename (파일 1개 유지)
        p3, st, old = wc.save_confluence(raw, url, "# 스펙 v2\n본문", NOW)
        assert st == "updated" and old == [p]
        assert [os.path.basename(f) for f in wc.find_confluence_files(raw, "777")] == ["777_스펙 v2.md"]

        # 제목 헤딩이 없으면 기존 제목 유지
        p4, st, _ = wc.save_confluence(raw, url, "헤딩 없는 본문", NOW)
        assert p4 == p3

        # 빈 본문은 거부, 기존 파일 보존
        for empty in ("", "   \n", "```\n\n```"):
            try:
                wc.save_confluence(raw, url, empty, NOW)
                assert False, "빈 본문이 저장됨"
            except ValueError:
                pass
        assert "헤딩 없는 본문" in wc.read_text_file(p4)


def test_pending():
    with tempfile.TemporaryDirectory() as raw:
        assert wc.load_pending(raw) == []
        a = os.path.join(raw, "messenger", "a.md")
        b = os.path.join(raw, "confluence", "1_B.md")
        b2 = os.path.join(raw, "confluence", "1_B2.md")
        wc.add_pending(raw, a, "new")
        wc.add_pending(raw, b, "new")
        wc.add_pending(raw, b, "updated")          # new로 유지
        items = wc.add_pending(raw, b2, "updated", replaces=[b])  # rename → 경로 교체, new 유지
        assert items == [{"path": "messenger/a.md", "status": "new"},
                         {"path": "confluence/1_B2.md", "status": "new"}], items
        assert wc.load_pending(raw) == items  # 파일로 저장/로드
        c = os.path.join(raw, "confluence", "2_C.md")
        wc.add_pending(raw, c, "updated")
        assert wc.pending_counts(wc.load_pending(raw)) == (2, 1)
        # 경로 문자열만 있는 형식도 읽음
        with open(os.path.join(raw, wc.PENDING_FILE), "w", encoding="utf-8") as f:
            json.dump(["messenger/x.md"], f)
        assert wc.load_pending(raw) == [{"path": "messenger/x.md", "status": "new"}]
        # 깨진 파일 → 빈 목록
        with open(os.path.join(raw, wc.PENDING_FILE), "w", encoding="utf-8") as f:
            f.write("{broken")
        assert wc.load_pending(raw) == []


def test_fill_and_build_command():
    assert wc.fill("a {x} {unknown} {{json}}", {"x": 1}) == "a 1 {unknown} {{json}}"
    # {prompt}/{placeholder}가 없으면 stdin
    cmd, stdin = wc.build_command("claude -p", "hi {url}", {"url": "U"})
    assert cmd == "claude -p" and stdin == "hi U"
    # {prompt}가 있으면 인라인 + 이스케이프
    cmd, stdin = wc.build_command('tool "{prompt}"', 'say "{text}"', {"text": "x"})
    assert stdin is None
    assert cmd == ('tool "say \\"x\\""'), cmd
    # 구형(PLAN) 형식: cmd에 {text} 직접
    cmd, stdin = wc.build_command('codex exec "제목: {text}"', None, {"text": 'a"b'})
    assert stdin is None and cmd == 'codex exec "제목: a\\"b"'


def test_run_cli_and_flows():
    # 실제 쉘 명령 실행 (python을 stub CLI로 사용)
    code, out, _ = wc.run_cli(f'{PY} -c "import sys; print(sys.stdin.read().upper())"', "abc")
    assert code == 0 and out.strip() == "ABC"
    # 자식의 자식까지 종료되어 바로 반환되는지 (sleep 30을 기다리지 않음)
    import time
    t = time.time()
    code, _, err = wc.run_cli(f'{PY} -c "import time; time.sleep(30)" && echo done', timeout=0.5)
    assert code == -1 and "시간 초과" in err and time.time() - t < 10

    cfg = dict(wc.DEFAULT_CONFIG)
    cfg["title_cmd"] = f'{PY} -c "print(\'제목: 스텁 제목\')"'
    assert wc.suggest_title(cfg, "본문 첫 줄") == ("스텁 제목", True)
    cfg["title_cmd"] = f'{PY} -c "import sys; sys.exit(1)"'
    assert wc.suggest_title(cfg, "\n본문 첫 줄\n") == ("본문 첫 줄", False)

    cfg["confluence_cmd"] = f'{PY} -c "print(\'# 제목\\n본문\')"'
    md, err = wc.fetch_confluence(cfg, "https://x/pages/1")
    assert md and md.startswith("# 제목") and err == ""
    cfg["confluence_cmd"] = f'{PY} -c "print()"'
    assert wc.fetch_confluence(cfg, "u") == (None, "출력이 비어 있습니다.")
    cfg["confluence_cmd"] = f'{PY} -c "import sys; sys.stderr.write(\'login required\'); sys.exit(2)"'
    assert wc.fetch_confluence(cfg, "u") == (None, "login required")

    with tempfile.TemporaryDirectory() as d:
        cfg["raw_dir"], cfg["wiki_dir"] = d, d
        cfg["wiki_cmd"] = f'{PY} -c "import sys; print(sys.stdin.read())"'
        ok, out = wc.run_wiki(cfg, [{"path": "messenger/a.md", "status": "new"}])
        assert ok and "- messenger/a.md" in out and d in out
        assert wc.unclassified_lines("x\n미분류: messenger/a.md\n- 미분류: b.md\n  c. \"미분류: <파일>\" 표시") \
            == ["미분류: messenger/a.md", "- 미분류: b.md"]
        cfg["wiki_cmd"] = f'{PY} -c "import sys; sys.exit(3)"'
        ok, out = wc.run_wiki(cfg, [])
        assert not ok and out == "종료 코드 3"


def test_config():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "config.json")
        cfg = wc.load_config(p)
        assert os.path.exists(p) and cfg["confluence_timeout"] == 180
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"raw_dir": "R", "confluence_timeout": 300}, f)
        cfg = wc.load_config(p)
        assert cfg["raw_dir"] == "R" and cfg["confluence_timeout"] == 300 and cfg["wiki_cmd"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} tests passed")
