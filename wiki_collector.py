"""Wiki Collector — 메신저 대화 / Confluence 페이지를 llm-wiki raw 폴더에 모으고 wiki 변환을 실행하는 작은 데스크톱 앱.

구성
- 상단: 순수 로직 (config, 파일명/경로 규칙, pending 목록, CLI 실행). GUI 없이 테스트 가능.
- 하단: tkinter GUI (App). tkinterdnd2가 있으면 txt 드래그앤드롭을 지원.
"""

import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
except ImportError:  # 로직 테스트만 돌리는 환경
    tk = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    TkinterDnD = None

APP_NAME = "Wiki Collector"
PENDING_FILE = ".wiki_collector_pending.json"
IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

# 명령 템플릿 규칙
# - *_cmd 안에 {prompt}가 있으면 *_prompt를 렌더링해 그 자리에 (따옴표 이스케이프 후) 넣는다.
# - *_cmd 안에 {prompt}가 없으면 렌더링한 *_prompt를 stdin으로 넘긴다. (명령줄 길이 제한/줄바꿈 문제 회피)
# - *_cmd 안에 {text}/{url}/{files}/{raw_dir}를 직접 써도 된다(이스케이프 후 치환).
DEFAULT_CONFIG = {
    "raw_dir": "",
    "wiki_dir": "",
    "title_cmd": "codex exec -",
    "title_prompt": "다음 메신저 대화의 제목을 20자 이내 한 줄로만 답해. 다른 설명은 쓰지 마.\n\n{text}",
    "title_max_chars": 3000,
    "title_timeout": 60,
    "confluence_cmd": "claude -p",
    "confluence_prompt": "/<confluence-skill> {url} 페이지 본문을 마크다운으로만 출력해. 설명이나 인사말 없이 본문만 출력해.",
    "confluence_timeout": 180,
    "wiki_cmd": "claude -p --permission-mode acceptEdits",
    "wiki_prompt": (
        "raw 폴더({raw_dir})의 다음 파일들을 wiki에 반영해줘 (경로는 raw 폴더 기준):\n"
        "{files}\n\n"
        "규칙:\n"
        "1. confluence/ 아래 파일은 기존 raw → wiki 변환 방식대로 wiki 문서로 변환하거나, "
        "이미 변환된 문서가 있으면 갱신해.\n"
        "2. messenger/ 아래 파일(메신저 대화)은 새 wiki 페이지로 만들지 마. 대신:\n"
        "   a. 대화 내용과 관련된 wiki의 feature 문서를 찾아.\n"
        "   b. 그 문서의 \"논의 이력\" 섹션(없으면 문서 끝에 새로 만들어)에 "
        "\"### YYYY-MM-DD 메신저 논의 — <제목>\" 항목을 추가해. "
        "날짜는 파일 frontmatter의 date 값을 쓰고, 항목에는 결정 사항 / 논의 요지 / 미결 사항을 요약하고 "
        "raw 원본 파일 경로를 링크해.\n"
        "   c. 관련 문서를 확실히 찾지 못하면 추측해서 넣지 말고, 마지막 출력에 \"미분류: <파일>\" 한 줄로 표시해.\n"
        "3. 작업이 끝나면 변경한 wiki 파일 목록과 미분류 목록을 짧게 출력해."
    ),
    "wiki_timeout": 1800,
    # 메신저 대화 날짜 추출용 정규식 (named group y, m, d). 앞에서부터 시도해서 본문에서 가장 먼저 나오는 매치를 씀.
    "date_patterns": [
        r"(?P<y>20\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})",
        r"(?P<y>20\d{2})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일",
    ],
}


def app_dir():
    """config.json을 둘 위치: exe(PyInstaller) 옆, 아니면 스크립트 옆."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def load_config(path):
    """config.json을 읽고 빠진 키는 기본값으로 채운다. 파일이 없으면 기본값으로 생성."""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    else:
        save_config(path, cfg)
    return cfg


def save_config(path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 텍스트 / 파일명 규칙
# ---------------------------------------------------------------------------

def decode_bytes(data):
    """메신저 export txt 디코딩: utf-8(BOM 포함) → 실패 시 cp949."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949", errors="replace")


def read_text_file(path):
    with open(path, "rb") as f:
        return decode_bytes(f.read())


def sanitize_filename(name, max_len=80):
    """Windows 파일명 금지 문자 \\/:*?"<>|와 제어문자를 _로 바꾸고, 끝의 점/공백을 제거."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name.strip())
    name = re.sub(r"\s+", " ", name)[:max_len].rstrip(" .")
    return name or "untitled"


def unique_path(path):
    """같은 이름이 있으면 _2, _3 …을 붙인다."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


def extract_page_id(url):
    """Confluence URL에서 pageId 추출. 없으면 URL 해시(12자리)를 키로 쓴다."""
    m = re.search(r"[?&]pageId=(\d+)", url) or re.search(r"/pages/(\d+)(?:/|$|\?|#)", url)
    if m:
        return m.group(1)
    return "h" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:12]


def extract_date(text, patterns, default):
    """본문에서 가장 먼저 나오는 날짜(YYYY-MM-DD)를 찾는다. 없으면 default."""
    best = None
    for pat in patterns:
        for m in re.finditer(pat, text):
            try:
                d = datetime.date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
            except (ValueError, IndexError):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), d)
            break  # 패턴별 첫 유효 매치만 보면 됨
    return best[1].isoformat() if best else default


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def clean_title(line, max_len=50):
    """CLI가 돌려준 제목 한 줄 정리: '제목:' 접두어, 마크다운 기호, 감싼 따옴표 제거."""
    line = re.sub(r"^(제목|title)\s*[:：]\s*", "", line.strip(), flags=re.I)
    line = line.strip("#*` ").strip("\"'“”‘’「」 ")
    return line[:max_len]


def fallback_title(body):
    return clean_title(first_line(body), 30) or "메신저 대화"


def strip_code_fence(text):
    """출력 전체가 ```markdown ... ``` 로 감싸져 있으면 벗겨낸다."""
    m = re.match(r"^\s*```[\w-]*\n(.*)\n```\s*$", text, re.S)
    return m.group(1) if m else text


def is_url(text):
    """본문이 http(s) URL 한 줄뿐이면 True → Confluence 가져오기로 처리."""
    return bool(re.fullmatch(r"https?://\S+", text.strip()))


def markdown_title(md):
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else ""


def yaml_str(value):
    """frontmatter 값: 따옴표로 감싼 문자열(JSON 문자열은 유효한 YAML)."""
    return json.dumps(str(value), ensure_ascii=False)


def build_frontmatter(fields):
    lines = ["---"]
    for k, v in fields.items():
        if v is None or v == "":
            continue
        lines.append(f"{k}: {yaml_str(v) if k in ('title', 'url') else v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def read_frontmatter(path):
    """frontmatter의 key: value를 dict로 (간단 파서)."""
    out = {}
    try:
        text = read_text_file(path)
    except OSError:
        return out
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if v.startswith('"'):
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            out[k.strip()] = v
    return out


def now_str(now=None):
    return (now or datetime.datetime.now()).strftime("%Y-%m-%dT%H:%M")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------

def save_messenger(raw_dir, title, body, date_patterns, now=None):
    """raw/messenger/YYYY-MM-DD_<제목>.md 로 저장하고 경로를 반환."""
    now = now or datetime.datetime.now()
    title = title.strip() or fallback_title(body)
    date = extract_date(body, date_patterns, now.date().isoformat())
    path = unique_path(os.path.join(raw_dir, "messenger", f"{date}_{sanitize_filename(title)}.md"))
    fm = build_frontmatter({"source": "messenger", "title": title, "date": date,
                            "collected_at": now_str(now)})
    write_text(path, fm + body.rstrip() + "\n")
    return path


def find_confluence_files(raw_dir, page_id):
    pattern = os.path.join(glob.escape(os.path.join(raw_dir, "confluence")), f"{page_id}_*.md")
    return sorted(glob.glob(pattern))


def save_confluence(raw_dir, url, markdown, now=None):
    """Confluence 본문 저장. 반환 (path, status, old_paths). status는 'new' 또는 'updated'.

    본문이 비어 있으면 ValueError — 기존 파일을 빈 내용으로 덮어쓰지 않기 위함.
    """
    markdown = strip_code_fence(markdown or "").strip()
    if not markdown:
        raise ValueError("Confluence 본문이 비어 있습니다.")
    page_id = extract_page_id(url)
    existing = find_confluence_files(raw_dir, page_id)
    title = markdown_title(markdown)
    if not title and existing:
        title = read_frontmatter(existing[0]).get("title", "")
    title = title or page_id
    path = os.path.join(raw_dir, "confluence", f"{page_id}_{sanitize_filename(title)}.md")
    fm = build_frontmatter({"source": "confluence", "title": title, "url": url.strip(),
                            "page_id": page_id, "collected_at": now_str(now)})
    write_text(path, fm + markdown + "\n")
    old = [p for p in existing if os.path.normcase(os.path.abspath(p)) != os.path.normcase(os.path.abspath(path))]
    for p in old:  # 제목이 바뀐 경우: 새 이름으로 쓰고 옛 파일 삭제 (= rename)
        os.remove(p)
    return path, ("updated" if existing else "new"), old


# ---------------------------------------------------------------------------
# 대기 목록 (raw/.wiki_collector_pending.json)
# ---------------------------------------------------------------------------

def rel_to_raw(raw_dir, path):
    return os.path.relpath(path, raw_dir).replace(os.sep, "/")


def load_pending(raw_dir):
    """[{"path": raw 기준 상대경로, "status": "new"|"updated"}, ...]"""
    p = os.path.join(raw_dir, PENDING_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for item in data:
        if isinstance(item, str):  # 경로만 있는 형식도 허용
            item = {"path": item, "status": "new"}
        out.append(item)
    return out


def save_pending(raw_dir, items):
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, PENDING_FILE), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add_pending(raw_dir, path, status, replaces=()):
    """대기 목록에 추가. 이미 있는 경로면 status 유지(new가 update로 바뀌지 않게), replaces 경로는 새 경로로 대체."""
    items = load_pending(raw_dir)
    rel = rel_to_raw(raw_dir, path)
    drop = {rel_to_raw(raw_dir, p) for p in replaces}
    prev = [i for i in items if i["path"] == rel or i["path"] in drop]
    if any(i["status"] == "new" for i in prev):
        status = "new"
    items = [i for i in items if i not in prev]
    items.append({"path": rel, "status": status})
    save_pending(raw_dir, items)
    return items


def pending_counts(items):
    new = sum(1 for i in items if i["status"] == "new")
    return new, len(items) - new


# ---------------------------------------------------------------------------
# CLI 실행
# ---------------------------------------------------------------------------

def shell_escape(value):
    """큰따옴표 안에 넣을 값 이스케이프. Windows(cmd)는 줄바꿈도 명령을 끊으므로 공백으로 바꾼다."""
    value = str(value)
    if IS_WINDOWS:
        return value.replace("\r", "").replace("\n", " ").replace('"', '\\"')
    return re.sub(r'(["\\$`])', r"\\\1", value)


def fill(template, values, escape=False):
    """{name} 치환. str.format과 달리 모르는 중괄호는 그대로 둔다(프롬프트에 JSON 예시 등이 있어도 안전)."""
    def rep(m):
        key = m.group(1)
        if key not in values:
            return m.group(0)
        return shell_escape(values[key]) if escape else str(values[key])
    return re.sub(r"\{(\w+)\}", rep, template)


def build_command(cmd_tpl, prompt_tpl, values):
    """(명령 문자열, stdin 입력 또는 None) 반환."""
    prompt = fill(prompt_tpl or "", values)
    if "{prompt}" in cmd_tpl or any("{%s}" % k in cmd_tpl for k in values):
        return fill(cmd_tpl, dict(values, prompt=prompt), escape=True), None
    return cmd_tpl, prompt


def run_cli(cmd, stdin_text=None, cwd=None, timeout=None):
    """shell=True로 실행 (Windows에서 claude.cmd 등을 찾으려면 필요). 반환 (returncode, stdout, stderr)."""
    # Python 기반 CLI(sgpt 등)가 Windows 파이프에 cp949로 출력하지 않도록 UTF-8 강제
    kwargs = {"env": dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")}
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True  # timeout 때 프로세스 그룹째 종료하기 위함
    try:
        p = subprocess.Popen(
            cmd, shell=True, cwd=cwd or None,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", **kwargs)
    except OSError as e:
        return -1, "", str(e)
    try:
        out, err = p.communicate(stdin_text, timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        kill_tree(p)
        p.communicate()
        return -1, "", f"시간 초과 ({timeout}초)"


def kill_tree(p):
    """shell=True면 cmd.exe/sh 아래 실제 CLI(node 등)가 남아 파이프를 붙잡으므로 트리째 종료."""
    try:
        if IS_WINDOWS:
            subprocess.run(f"taskkill /F /T /PID {p.pid}", shell=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        p.kill()


def suggest_title(cfg, body):
    """title_cmd로 제목 제안. 실패하면 본문 첫 줄. 반환 (title, used_cli)."""
    text = body[: int(cfg.get("title_max_chars", 3000))]
    cmd, stdin = build_command(cfg["title_cmd"], cfg.get("title_prompt"), {"text": text})
    code, out, _ = run_cli(cmd, stdin, timeout=cfg.get("title_timeout", 60))
    title = clean_title(first_line(out)) if code == 0 else ""
    return (title, True) if title else (fallback_title(body), False)


def fetch_confluence(cfg, url):
    """confluence_cmd 실행. 반환 (markdown 또는 None, 에러 메시지)."""
    cmd, stdin = build_command(cfg["confluence_cmd"], cfg.get("confluence_prompt"), {"url": url.strip()})
    code, out, err = run_cli(cmd, stdin, timeout=cfg.get("confluence_timeout", 180))
    if code != 0:
        return None, (err or out).strip() or f"종료 코드 {code}"
    if not strip_code_fence(out).strip():
        return None, "출력이 비어 있습니다."
    return out, ""


def run_wiki(cfg, items):
    """wiki_cmd 실행. 반환 (성공 여부, 출력)."""
    files = "\n".join(f"- {i['path']}" for i in items)
    values = {"files": files, "raw_dir": cfg["raw_dir"]}
    cmd, stdin = build_command(cfg["wiki_cmd"], cfg.get("wiki_prompt"), values)
    code, out, err = run_cli(cmd, stdin, cwd=cfg["wiki_dir"], timeout=cfg.get("wiki_timeout", 1800))
    if code == 0:
        return True, out
    return False, (err.strip() + ("\n\n" + out.strip() if out.strip() else "")) or f"종료 코드 {code}"


def unclassified_lines(output):
    """'미분류: <파일>' 줄 (앞의 목록 기호/굵게 표시는 허용)."""
    return [ln.strip() for ln in output.splitlines() if re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?미분류\s*[:：]", ln)]


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root, cfg, cfg_path):
        self.root, self.cfg, self.cfg_path = root, cfg, cfg_path
        self.busy = False
        root.title(APP_NAME)
        root.geometry("640x560")
        root.minsize(480, 420)

        pad = {"padx": 8, "pady": 4}
        frm = tk.Frame(root)
        frm.pack(fill="both", expand=True, **pad)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(1, weight=1)

        # 1. 제목
        tk.Label(frm, text="제목").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        tk.Entry(frm, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", **pad)
        self.btn_suggest = tk.Button(frm, text="자동 제안", command=self.on_suggest)
        self.btn_suggest.grid(row=0, column=2, sticky="ew", **pad)

        # 2. 본문: 메신저 대화 또는 Confluence URL 한 줄
        dnd = "창 어디에나 txt 드롭 가능" if TkinterDnD else "txt 열기 버튼 사용"
        tk.Label(frm, text="본문").grid(row=1, column=0, sticky="nw", pady=6)
        self.body = scrolledtext.ScrolledText(frm, wrap="word", undo=True, height=12)
        self.body.grid(row=1, column=1, sticky="nsew", **pad)
        side = tk.Frame(frm)
        side.grid(row=1, column=2, sticky="n", **pad)
        self.btn_open = tk.Button(side, text="txt 열기…", command=self.on_open_txt)
        self.btn_open.pack(fill="x")
        tk.Label(side, text=f"({dnd})\n\nConfluence URL만 한 줄 넣으면 페이지를 가져옵니다",
                 fg="gray", wraplength=100, justify="left").pack(fill="x", pady=4)

        # 4. raw에 저장 (본문이 URL 한 줄이면 Confluence 가져오기)
        self.btn_save = tk.Button(frm, text="raw에 저장", command=self.on_save)
        self.btn_save.grid(row=2, column=1, sticky="e", **pad)

        # 5. 하단: 대기 목록 + 변환
        bottom = tk.Frame(root)
        bottom.pack(fill="x", **pad)
        self.pending_var = tk.StringVar()
        tk.Label(bottom, textvariable=self.pending_var).pack(side="left")
        self.btn_wiki = tk.Button(bottom, text="Wiki로 변환", command=self.on_wiki)
        self.btn_wiki.pack(side="right")
        self.status_var = tk.StringVar(value="준비")
        tk.Label(root, textvariable=self.status_var, anchor="w", relief="sunken", bd=1).pack(fill="x", side="bottom")

        self.buttons = [self.btn_suggest, self.btn_open, self.btn_save, self.btn_wiki]
        if TkinterDnD:
            self.register_drop(root)
        self.refresh_pending()

    def register_drop(self, widget):
        """창 전체에서 드롭되도록 root와 모든 하위 위젯을 드롭 대상으로 등록."""
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self.on_drop)
        for child in widget.winfo_children():
            if not isinstance(child, tk.Toplevel):
                self.register_drop(child)

    # --- 공통 ---
    def status(self, msg):
        self.status_var.set(msg)

    def refresh_pending(self):
        new, upd = pending_counts(load_pending(self.cfg["raw_dir"]))
        total = new + upd
        detail = f" (신규 {new}, 업데이트 {upd})" if upd else ""
        self.pending_var.set(f"대기 중인 파일 {total}개{detail}")
        if not self.busy:
            self.btn_wiki.config(state="normal" if total else "disabled")

    def set_busy(self, busy, msg=None):
        self.busy = busy
        for b in self.buttons:
            b.config(state="disabled" if busy else "normal")
        if msg:
            self.status(msg)
        if not busy:
            self.refresh_pending()

    def run_async(self, msg, work, done):
        """work()를 스레드에서 실행하고 결과를 done(result)로 UI 스레드에서 받는다."""
        if self.busy:
            return
        self.set_busy(True, msg)
        box = []  # worker 결과. tkinter는 스레드 안전하지 않으므로 UI 스레드에서 root.after로 polling

        def worker():
            try:
                box.append((work(), None))
            except Exception as e:  # noqa: BLE001 - 어떤 오류든 UI에 표시
                box.append((None, e))

        def poll():
            if box:
                self._finish(done, *box[0])
            else:
                self.root.after(100, poll)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, poll)

    def _finish(self, done, res, err):
        self.set_busy(False)
        if err is not None:
            self.status(f"오류: {err}")
            messagebox.showerror(APP_NAME, str(err))
        else:
            done(res)

    # --- 입력 ---
    def load_txt(self, path):
        try:
            text = read_text_file(path)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"파일을 읽을 수 없습니다:\n{e}")
            return
        self.body.delete("1.0", "end")
        self.body.insert("1.0", text)
        self.title_var.set(os.path.splitext(os.path.basename(path))[0])
        self.status(f"불러옴: {os.path.basename(path)}")

    def on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        txts = [p for p in paths if p.lower().endswith(".txt")]
        if not txts:
            self.status(".txt 파일만 드롭할 수 있습니다.")
            return event.action
        self.load_txt(txts[0])
        if len(txts) > 1:
            self.status(f"첫 번째 파일만 불러왔습니다: {os.path.basename(txts[0])}")
        return event.action

    def on_open_txt(self):
        path = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if path:
            self.load_txt(path)

    def get_body(self):
        return self.body.get("1.0", "end").rstrip("\n")

    # --- 제목 제안 ---
    def on_suggest(self, then=None):
        body = self.get_body()
        if not body.strip():
            self.status("본문이 비어 있습니다.")
            return

        def done(res):
            title, used_cli = res
            self.title_var.set(title)
            self.status("제목 제안 완료" if used_cli else "제목 CLI 실패 → 본문 첫 줄을 제목으로 사용")
            if then:
                then()
        self.run_async("제목 제안 중…", lambda: suggest_title(self.cfg, body), done)

    # --- 저장: 본문이 URL 한 줄이면 Confluence, 아니면 메신저 ---
    def on_save(self):
        body = self.get_body()
        if not body.strip():
            self.status("본문이 비어 있습니다.")
            return
        if is_url(body):
            self.fetch_confluence_url(body.strip())
            return
        if not self.title_var.get().strip():
            self.on_suggest(then=self.save_now)  # 제목 제안 후 저장
            return
        self.save_now()

    def save_now(self):
        body, title = self.get_body(), self.title_var.get().strip()
        raw = self.cfg["raw_dir"]
        try:
            path = save_messenger(raw, title, body, self.cfg.get("date_patterns", []))
            add_pending(raw, path, "new")
        except OSError as e:
            messagebox.showerror(APP_NAME, f"저장 실패:\n{e}")
            return
        self.title_var.set("")
        self.body.delete("1.0", "end")
        self.refresh_pending()
        self.status(f"저장: {rel_to_raw(raw, path)}")

    # --- Confluence ---
    def fetch_confluence_url(self, url):
        raw = self.cfg["raw_dir"]

        def work():
            md, err = fetch_confluence(self.cfg, url)
            if md is None:
                return None, err
            path, st, old = save_confluence(raw, url, md)
            add_pending(raw, path, st, replaces=old)
            return (path, st), ""

        def done(res):
            result, err = res
            if result is None:
                self.status("Confluence 읽기 실패 — 브라우저에서 Confluence 로그인 후 재시도")
                messagebox.showwarning(
                    APP_NAME, "Confluence 페이지를 읽지 못했습니다. 파일은 저장하지 않았습니다.\n"
                              "브라우저에서 Confluence 로그인 후 다시 시도하세요.\n\n" + err[-1500:])
                return
            path, st = result
            self.body.delete("1.0", "end")
            self.status(f"{'업데이트' if st == 'updated' else '신규 추가'}: {rel_to_raw(raw, path)}")
        self.run_async("Confluence 읽는 중… (브라우저 창이 뜰 수 있고 수십 초 걸릴 수 있습니다)", work, done)

    # --- Wiki 변환 ---
    def on_wiki(self):
        raw = self.cfg["raw_dir"]
        items = load_pending(raw)
        missing = [i for i in items if not os.path.exists(os.path.join(raw, i["path"]))]
        if missing:  # 사용자가 탐색기에서 지운 파일은 목록에서 뺀다
            items = [i for i in items if i not in missing]
            save_pending(raw, items)
            self.refresh_pending()
        if not items:
            self.status("변환할 파일이 없습니다.")
            return
        new, upd = pending_counts(items)
        if not messagebox.askyesno(APP_NAME, f"신규 {new}개, 업데이트 {upd}개 파일을 wiki로 변환할까요?"):
            return

        def done(res):
            ok, out = res
            if ok:
                # 변환 중에 추가된 항목은 남긴다
                sent = {i["path"] for i in items}
                save_pending(raw, [i for i in load_pending(raw) if i["path"] not in sent])
                self.refresh_pending()
                unc = unclassified_lines(out)
                self.status("Wiki 변환 완료" + (f" — 미분류 {len(unc)}개" if unc else ""))
            else:
                self.status("Wiki 변환 실패 — 대기 목록은 유지됩니다")
            self.show_result("Wiki 변환 결과" if ok else "Wiki 변환 실패", out)
        self.run_async("Wiki 변환 중… (시간이 걸릴 수 있습니다)", lambda: run_wiki(self.cfg, items), done)

    def show_result(self, title, text):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("640x420")
        unc = unclassified_lines(text)
        if unc:
            tk.Label(win, text="미분류 (관련 문서를 찾지 못함):\n" + "\n".join(unc),
                     fg="#b00020", justify="left", anchor="w").pack(fill="x", padx=8, pady=4)
        tk.Button(win, text="닫기", command=win.destroy).pack(side="bottom", pady=4)
        box = scrolledtext.ScrolledText(win, wrap="word")
        box.pack(fill="both", expand=True, padx=8, pady=4)
        box.insert("1.0", text or "(출력 없음)")
        box.config(state="disabled")


def ensure_dirs(root, cfg, cfg_path):
    """raw_dir / wiki_dir가 없으면 폴더 선택 창을 띄우고 config에 저장. 취소하면 False."""
    changed = False
    for key, label in (("raw_dir", "raw 폴더"), ("wiki_dir", "llm-wiki 폴더 (wiki 변환 시 작업 폴더)")):
        if cfg.get(key) and os.path.isdir(cfg[key]):
            continue
        messagebox.showinfo(APP_NAME, f"{label}를 선택하세요.")
        path = filedialog.askdirectory(title=label)
        if not path:
            return False
        cfg[key] = path
        changed = True
    if changed:
        save_config(cfg_path, cfg)
    return True


def main():
    if tk is None:
        sys.exit("tkinter가 없습니다. tkinter가 포함된 Python으로 실행하세요.")
    if IS_WINDOWS:
        try:  # 고해상도 화면에서 글자 번짐 방지
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    cfg_path = os.environ.get("WIKI_COLLECTOR_CONFIG") or os.path.join(app_dir(), "config.json")
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    try:
        cfg = load_config(cfg_path)
    except (OSError, ValueError) as e:
        root.withdraw()
        messagebox.showerror(APP_NAME, f"config.json을 읽을 수 없습니다:\n{cfg_path}\n\n{e}")
        return
    if not ensure_dirs(root, cfg, cfg_path):
        root.destroy()
        return
    App(root, cfg, cfg_path)
    root.mainloop()


if __name__ == "__main__":
    main()
