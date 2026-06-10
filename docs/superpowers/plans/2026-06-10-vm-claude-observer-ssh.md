# VM Claude Code 会话经 SSH 汇总到宿主机 Observer — 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 VM（Ubuntu/Linux）上运行的 Claude Code 会话出现在宿主机（Windows）的 Observer 小部件中，与本地会话合并显示。

**架构：** VM 端复用现有 `claude_observer_helper.js` 写自己的 `~/.claude-observer/sessions.json`，新增一个 POSIX sh 包装脚本作为 hook 入口。宿主机 Observer 为每个 VM 起一个后台线程，维持一个常驻 ssh 进程（远程每秒 `cat` 一次文件并输出分隔符），持续解析并写入内存缓存；`state_manager` 合并本地文件 + 各 VM 缓存供 UI 渲染，远程卡片带来源徽标。

**技术栈：** Python 3（pywebview、标准库 subprocess/threading）、Node.js（既有 helper，零改动）、POSIX sh、Windows 自带 OpenSSH 客户端。测试：pytest（Python）、node:test（JS）。

---

## 文件结构

**新增：**
- `hooks/claude_observer_hook.sh` — VM 端 hook 入口（POSIX sh），事件名作参数，读 stdin 转交 helper.js。
- `remote_poller.py` — 常驻 SSH 流读取器。含纯函数 `build_ssh_command`、`parse_blocks` 与 `RemotePoller` 线程类。
- `remotes.example.json` — 配置示例，供用户复制到 `~/.claude-observer/remotes.json`。
- `tests/test_remote_poller.py` — poller 纯函数与隐藏逻辑测试。
- `tests/test_state_manager_merge.py` — 合并/dismiss 分支测试。
- `tests/test_hook_sh.py` — hook.sh 行为测试（事件名/stdin 透传/无 node 退出码）。

**修改：**
- `state_manager.py` — `SessionState` 接受可选 `remote_poller`；`get_sessions` 合并并给本地补 `source="local"`；`remove_session` 区分本地/远程。
- `observer.py` — `main()` 读配置、启动 poller、注入 `SessionState`；前端 `renderCard` 加来源徽标 + CSS。
- `requirements.txt` — 加 `pytest`（仅测试）。
- `README.md` — 新增「VM / 远程会话」配置章节。

**不改：**
- `hooks/claude_observer_helper.js` — 已跨平台，VM 上直接复用。

---

## 任务 1：VM 端 Linux hook 脚本

**文件：**
- 创建：`hooks/claude_observer_hook.sh`
- 测试：`tests/test_hook_sh.py`

对标 `hooks/claude_observer_hook.bat`：事件名作第一个参数，读 stdin，定位 node，运行 `node helper.js <event>` 并传入 stdin。POSIX sh 兼容（不用 bashism）。

- [ ] **步骤 1：编写失败的测试**

`tests/test_hook_sh.py`（用一个假的 `node` 把收到的参数和 stdin 落盘来验证透传；在非 Windows 上运行，Windows 上 skip）：

```python
import json, os, shutil, stat, subprocess, sys, tempfile
from pathlib import Path
import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "claude_observer_hook.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh hook")

def _run(tmp_path, event, stdin_text, with_node=True):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    capture = tmp_path / "capture.txt"
    if with_node:
        # 假 node：把 argv[2..] 和 stdin 写到 capture 文件
        fake = bindir / "node"
        fake.write_text(
            "#!/bin/sh\n"
            'printf "ARGS:%s\\n" "$*" > "%s"\n' % capture
            + 'cat >> "%s"\n' % capture
        )
        fake.chmod(0o755)
    env = dict(os.environ, PATH=str(bindir))  # 只让假 node 可见（with_node=False 时 PATH 无 node）
    proc = subprocess.run(
        ["sh", str(HOOK), event],
        input=stdin_text, capture_output=True, text=True, env=env,
    )
    return proc, capture

def test_passes_event_and_stdin_to_node(tmp_path):
    payload = json.dumps({"session_id": "abc", "cwd": "/x"})
    proc, capture = _run(tmp_path, "SessionStart", payload)
    assert proc.returncode == 0
    text = capture.read_text()
    assert "SessionStart" in text
    assert '"session_id": "abc"' in text

def test_missing_event_name_fails(tmp_path):
    bindir = tmp_path / "bin"; bindir.mkdir()
    proc = subprocess.run(["sh", str(HOOK)], input="", capture_output=True, text=True,
                          env=dict(os.environ, PATH=str(bindir)))
    assert proc.returncode != 0

def test_missing_node_fails(tmp_path):
    proc, _ = _run(tmp_path, "SessionStart", "{}", with_node=False)
    assert proc.returncode != 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_hook_sh.py -v`
预期：FAIL（hook 脚本不存在）。注：此测试需在 Linux/macOS 或 WSL 下运行；纯 Windows 环境会 skip，需在 VM/WSL 里验证。

- [ ] **步骤 3：编写最少实现代码**

`hooks/claude_observer_hook.sh`：

```sh
#!/bin/sh
# Claude Code Observer - Hook entry point (Linux/POSIX)
# Usage: claude_observer_hook.sh <event_name>
# Reads JSON from stdin, passes to the shared Node.js helper.

EVENT_NAME="$1"
if [ -z "$EVENT_NAME" ]; then
  echo "Usage: claude_observer_hook.sh <event_name>" >&2
  exit 1
fi

# Optional debug log (mirror the .bat). Safe to remove once verified.
STATE_DIR="$HOME/.claude-observer"
mkdir -p "$STATE_DIR" 2>/dev/null
LOGFILE="$STATE_DIR/hook_debug.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Hook called: $EVENT_NAME" >> "$LOGFILE"

# Locate Node.js
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js not found in PATH" >&2
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Node.js not found" >> "$LOGFILE"
  exit 1
fi

# Helper lives next to this script.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HELPER="$SCRIPT_DIR/claude_observer_helper.js"

# stdin pipes straight through to node.
node "$HELPER" "$EVENT_NAME" 2>> "$LOGFILE"
exit 0
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_hook_sh.py -v`
预期：PASS（在 Linux/WSL）。同时 `chmod +x hooks/claude_observer_hook.sh`。

- [ ] **步骤 5：Commit**

```bash
git add hooks/claude_observer_hook.sh tests/test_hook_sh.py
git commit -m "feat: 新增 VM 端 POSIX sh hook 入口脚本"
```

---

## 任务 2：poller 纯函数（命令构造 + 流解析）

**文件：**
- 创建：`remote_poller.py`（先只放纯函数与常量）
- 测试：`tests/test_remote_poller.py`

把不依赖真实 SSH 的逻辑拆成纯函数，便于测试：`build_ssh_command(remote)` 构造 ssh 参数列表；`parse_blocks(buffer)` 按分隔符切出完整 JSON 块并返回 `(blocks, remaining)`。

- [ ] **步骤 1：编写失败的测试**

`tests/test_remote_poller.py`：

```python
from remote_poller import build_ssh_command, parse_blocks, DELIM

def test_build_ssh_command_full():
    remote = {"name": "vm1", "host": "10.0.0.5", "port": 2222,
              "user": "dev", "identity_file": "C:/keys/id_rsa"}
    cmd = build_ssh_command(remote)
    assert cmd[0] == "ssh"
    assert "-p" in cmd and "2222" in cmd
    assert "-i" in cmd and "C:/keys/id_rsa" in cmd
    assert "dev@10.0.0.5" in cmd
    assert "BatchMode=yes" in " ".join(cmd)
    assert cmd[-1].count(DELIM) == 1  # 远程循环命令里含分隔符

def test_build_ssh_command_minimal():
    cmd = build_ssh_command({"name": "vm", "host": "h", "user": "u"})
    assert "u@h" in cmd
    assert "-i" not in cmd      # 无 identity_file
    assert "-p" in cmd and "22" in cmd  # 默认端口

def test_parse_blocks_splits_on_delim():
    buf = '{"a":1}\n' + DELIM + '\n{"b":2}\n' + DELIM + '\n{"c'
    blocks, remaining = parse_blocks(buf)
    assert blocks == ['{"a":1}\n', '\n{"b":2}\n']
    assert remaining == '\n{"c'

def test_parse_blocks_no_complete_block():
    blocks, remaining = parse_blocks('{"partial":')
    assert blocks == []
    assert remaining == '{"partial":'
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_remote_poller.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'remote_poller'`。

- [ ] **步骤 3：编写最少实现代码**

`remote_poller.py`（仅本任务部分）：

```python
"""Claude Code Observer - 远程 VM 会话拉取（常驻 SSH 流）。"""

DELIM = "<<<OBSERVER_EOF>>>"

# VM 端循环命令：每秒输出一次 sessions.json 内容 + 分隔符。
_REMOTE_LOOP = (
    'while true; do '
    'cat ~/.claude-observer/sessions.json 2>/dev/null; '
    'echo "%s"; sleep 1; done' % DELIM
)


def build_ssh_command(remote):
    """根据 remote 配置构造常驻 ssh 命令的参数列表。"""
    cmd = ["ssh"]
    cmd += ["-p", str(remote.get("port", 22))]
    identity = remote.get("identity_file")
    if identity:
        cmd += ["-i", identity]
    cmd += [
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=2",
        "%s@%s" % (remote["user"], remote["host"]),
        _REMOTE_LOOP,
    ]
    return cmd


def parse_blocks(buffer):
    """按 DELIM 切出完整块。返回 (完整块列表, 剩余未完成文本)。"""
    parts = buffer.split(DELIM)
    remaining = parts.pop()  # 最后一段尚未遇到分隔符
    return parts, remaining
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_remote_poller.py -v`
预期：PASS（4 项）。

- [ ] **步骤 5：Commit**

```bash
git add remote_poller.py tests/test_remote_poller.py
git commit -m "feat: poller 的 ssh 命令构造与流分块纯函数"
```

---

## 任务 3：RemotePoller 类（缓存 + 隐藏逻辑）

**文件：**
- 修改：`remote_poller.py`（追加 `RemotePoller` 类）
- 测试：`tests/test_remote_poller.py`（追加）

`RemotePoller` 持有按 remote 名分桶的内存缓存、隐藏集和锁。本任务只实现**状态管理**方法（`_apply_block`、`get_sessions`、`hide`），不涉及线程/ssh，便于纯测试。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_remote_poller.py` 追加：

```python
import json
from remote_poller import RemotePoller

def _block(sessions):
    return json.dumps({"sessions": sessions})

def test_apply_block_tags_source_and_merges():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    p._apply_block("vm1", _block({"id1": {"id": "id1", "status": "working"}}))
    out = p.get_sessions()
    assert len(out) == 1
    assert out[0]["source"] == "vm1"
    assert out[0]["id"] == "id1"

def test_apply_block_replaces_previous_snapshot():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    p._apply_block("vm1", _block({"id1": {"id": "id1"}}))
    p._apply_block("vm1", _block({"id2": {"id": "id2"}}))
    ids = {s["id"] for s in p.get_sessions()}
    assert ids == {"id2"}  # 新快照整体替换

def test_invalid_block_keeps_last_snapshot():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    p._apply_block("vm1", _block({"id1": {"id": "id1"}}))
    p._apply_block("vm1", "not json")  # 解析失败
    assert {s["id"] for s in p.get_sessions()} == {"id1"}

def test_hide_excludes_until_next_pull():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    p._apply_block("vm1", _block({"id1": {"id": "id1"}}))
    assert p.hide("id1") is True
    assert p.get_sessions() == []           # 立即隐藏
    p._apply_block("vm1", _block({"id1": {"id": "id1"}}))  # 下次拉取仍在
    assert {s["id"] for s in p.get_sessions()} == {"id1"}  # 重现

def test_hide_unknown_id_returns_false():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    assert p.hide("nope") is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_remote_poller.py -v`
预期：新增 5 项 FAIL（`RemotePoller` 无 `_apply_block` 等）。

- [ ] **步骤 3：编写最少实现代码**

在 `remote_poller.py` 追加 import 与类：

```python
import json
import threading


class RemotePoller:
    """维护各 VM 的会话快照（内存缓存），供 state_manager 合并。"""

    def __init__(self, remotes):
        self._remotes = remotes
        self._cache = {}      # name -> {session_id: session_dict(已含 source)}
        self._hidden = set()  # 用户本地隐藏的远程 session id
        self._lock = threading.Lock()

    def _apply_block(self, name, text):
        """用一块完整 JSON 更新该 remote 的快照。解析失败则保留旧快照。"""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return
        sessions = data.get("sessions", {})
        snapshot = {}
        for sid, sess in sessions.items():
            sess = dict(sess)
            sess["source"] = name
            snapshot[sid] = sess
        with self._lock:
            self._cache[name] = snapshot
            # 隐藏集中、本次快照仍存在的 id 解除隐藏（下次拉取重现）。
            self._hidden -= set(snapshot.keys())

    def get_sessions(self):
        """返回所有 VM 的会话（已打 source 标签，已剔除隐藏项）。"""
        with self._lock:
            out = []
            for snapshot in self._cache.values():
                for sid, sess in snapshot.items():
                    if sid not in self._hidden:
                        out.append(sess)
            return out

    def hide(self, session_id):
        """本地隐藏一个远程会话卡片。返回该 id 是否存在于当前缓存。"""
        with self._lock:
            exists = any(session_id in snap for snap in self._cache.values())
            if exists:
                self._hidden.add(session_id)
            return exists
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_remote_poller.py -v`
预期：全部 PASS（含任务 2 的 4 项，共 9 项）。

- [ ] **步骤 5：Commit**

```bash
git add remote_poller.py tests/test_remote_poller.py
git commit -m "feat: RemotePoller 缓存与本地隐藏逻辑"
```

---

## 任务 4：RemotePoller 流消费 + 线程/ssh 生命周期

**文件：**
- 修改：`remote_poller.py`（追加 `_consume_stream`、`_run_remote`、`start`、`stop`）
- 测试：`tests/test_remote_poller.py`（追加 `_consume_stream` 测试）

`_consume_stream` 从一个可迭代的文本流逐行累积、切块、应用——这是可纯测试的接缝。`_run_remote` 负责起 ssh 子进程、退避重连；`start/stop` 管理线程。子进程部分不做单测（需真实 ssh），靠任务 8 端到端验证。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_remote_poller.py` 追加：

```python
from remote_poller import RemotePoller, DELIM

def test_consume_stream_applies_blocks():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    # 模拟 ssh stdout：分两次 yield，跨块边界
    chunks = [
        '{"sessions": {"id1": {"id": "id1"}}}\n' + DELIM + '\n',
        '{"sessions": {"id1": {"id": "id1"}, "id2": {"id": "id2"}}}\n' + DELIM + '\n',
    ]
    p._consume_stream("vm1", iter(chunks))
    ids = {s["id"] for s in p.get_sessions()}
    assert ids == {"id1", "id2"}  # 最后一块为准

def test_consume_stream_handles_split_across_chunks():
    p = RemotePoller([{"name": "vm1", "host": "h", "user": "u"}])
    # 一个块被拆到两次读取中
    chunks = ['{"sessions": {"id1":', ' {"id": "id1"}}}\n' + DELIM + '\n']
    p._consume_stream("vm1", iter(chunks))
    assert {s["id"] for s in p.get_sessions()} == {"id1"}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_remote_poller.py -k consume -v`
预期：FAIL（`_consume_stream` 不存在）。

- [ ] **步骤 3：编写最少实现代码**

在 `remote_poller.py` 顶部补 import，并给 `RemotePoller` 追加方法：

```python
import subprocess
import time
```

```python
    # --- 追加到 RemotePoller 类内 ---

    def _consume_stream(self, name, stream):
        """从文本流（ssh stdout 的可迭代对象）读取并应用完整块。"""
        buffer = ""
        for chunk in stream:
            if not chunk:
                continue
            buffer += chunk
            blocks, buffer = parse_blocks(buffer)
            for block in blocks:
                if block.strip():
                    self._apply_block(name, block)

    def _run_remote(self, remote):
        """常驻：起 ssh 流，断开则退避重连，直到 stop()。"""
        name = remote["name"]
        cmd = build_ssh_command(remote)
        backoff = 1
        while not self._stop.is_set():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
                self._procs[name] = proc
                self._consume_stream(name, iter(proc.stdout.readline, ""))
                proc.wait()
            except OSError:
                pass
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 10)  # 1→2→4→8→10 上限

    def start(self):
        """为每个 remote 起一个守护线程。"""
        self._stop = threading.Event()
        self._procs = {}
        self._threads = []
        for remote in self._remotes:
            t = threading.Thread(target=self._run_remote, args=(remote,), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        """请求停止并终止所有 ssh 子进程。"""
        self._stop.set()
        for proc in self._procs.values():
            try:
                proc.terminate()
            except OSError:
                pass
```

并在 `__init__` 末尾补充线程相关字段初始化：

```python
        self._stop = threading.Event()
        self._procs = {}
        self._threads = []
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_remote_poller.py -v`
预期：全部 PASS（11 项）。

- [ ] **步骤 5：Commit**

```bash
git add remote_poller.py tests/test_remote_poller.py
git commit -m "feat: RemotePoller 流消费与 ssh 线程生命周期"
```

---

## 任务 5：state_manager 合并本地 + 远程

**文件：**
- 修改：`state_manager.py`（`__init__`、`get_sessions`、`remove_session`）
- 测试：`tests/test_state_manager_merge.py`

`SessionState` 接受可选 `remote_poller`。`get_sessions` 给本地会话补 `source="local"`，再并入 poller 的远程会话，统一按 `updated_at` 排序。`remove_session` 先尝试删本地，命中即返回；否则交给 poller `hide`。

- [ ] **步骤 1：编写失败的测试**

`tests/test_state_manager_merge.py`：

```python
import json
from state_manager import SessionState


class FakePoller:
    def __init__(self, sessions):
        self._sessions = sessions
        self.hidden = []
    def get_sessions(self):
        return list(self._sessions)
    def hide(self, sid):
        self.hidden.append(sid)
        return any(s["id"] == sid for s in self._sessions)


def _write_local(tmp_path, sessions):
    d = tmp_path / ".claude-observer"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions.json").write_text(json.dumps({"sessions": sessions}))


def _state(tmp_path, monkeypatch, poller=None):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return SessionState(remote_poller=poller)


def test_local_sessions_tagged_local(tmp_path, monkeypatch):
    _write_local(tmp_path, {"L1": {"id": "L1", "updated_at": "2026-06-10T10:00:00"}})
    st = _state(tmp_path, monkeypatch)
    out = st.get_sessions()
    assert out[0]["source"] == "local"


def test_merges_local_and_remote_sorted(tmp_path, monkeypatch):
    _write_local(tmp_path, {"L1": {"id": "L1", "updated_at": "2026-06-10T10:00:00"}})
    poller = FakePoller([{"id": "R1", "source": "vm1", "updated_at": "2026-06-10T11:00:00"}])
    st = _state(tmp_path, monkeypatch, poller)
    out = st.get_sessions()
    assert [s["id"] for s in out] == ["R1", "L1"]  # 新的在前


def test_remove_local_session_deletes_file_entry(tmp_path, monkeypatch):
    _write_local(tmp_path, {"L1": {"id": "L1", "updated_at": "2026-06-10T10:00:00"}})
    poller = FakePoller([])
    st = _state(tmp_path, monkeypatch, poller)
    assert st.remove_session("L1") is True
    assert poller.hidden == []  # 本地命中，不调用 poller


def test_remove_remote_session_calls_poller_hide(tmp_path, monkeypatch):
    _write_local(tmp_path, {})
    poller = FakePoller([{"id": "R1", "source": "vm1", "updated_at": "2026-06-10T11:00:00"}])
    st = _state(tmp_path, monkeypatch, poller)
    assert st.remove_session("R1") is True
    assert poller.hidden == ["R1"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_state_manager_merge.py -v`
预期：FAIL（`SessionState.__init__` 不接受 `remote_poller`）。

- [ ] **步骤 3：编写最少实现代码**

修改 `state_manager.py`。`__init__`（约 19-23 行）加参数：

```python
    def __init__(self, remote_poller=None):
        self._state_dir = Path.home() / '.claude-observer'
        self._state_file = self._state_dir / 'sessions.json'
        self._last_mtime = 0
        self._cache = {'sessions': {}}
        self._remote_poller = remote_poller
```

替换 `get_sessions`（约 43-48 行）：

```python
    def get_sessions(self):
        """Return active sessions (local + remote), newest first."""
        data = self._read_file()
        sessions = []
        for s in data.get('sessions', {}).values():
            s = dict(s)
            s['source'] = 'local'
            sessions.append(s)
        if self._remote_poller is not None:
            sessions.extend(self._remote_poller.get_sessions())
        sessions.sort(key=lambda s: s.get('updated_at', ''), reverse=True)
        return sessions
```

替换 `remove_session`（约 97-109 行）：

```python
    def remove_session(self, session_id):
        """Dismiss a card. Local sessions are deleted from the file; remote
        sessions are hidden in-memory via the poller until the next pull."""
        self._last_mtime = 0
        data = self._read_file()
        if session_id in data.get('sessions', {}):
            del data['sessions'][session_id]
            self._write_state(data)
            return True
        if self._remote_poller is not None:
            return self._remote_poller.hide(session_id)
        return False
```

注意：`get_stale_ids` / `cleanup_stale` 只作用于本地文件，无需改动（远程快照的过期由 VM 端 SessionEnd + poller 快照替换自然处理）。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_state_manager_merge.py -v`
预期：PASS（5 项）。

- [ ] **步骤 5：Commit**

```bash
git add state_manager.py tests/test_state_manager_merge.py
git commit -m "feat: state_manager 合并本地与远程会话"
```

---

## 任务 6：配置加载 + observer 接线

**文件：**
- 修改：`remote_poller.py`（追加 `load_remotes`）
- 修改：`observer.py`（`main()` 读配置、启动 poller、注入 `SessionState`）
- 创建：`remotes.example.json`
- 测试：`tests/test_remote_poller.py`（追加 `load_remotes` 测试）

`load_remotes(path)` 读 `remotes.json`：不存在/为空/格式错 → 返回 `[]`（退化为纯本地）。`observer.main()` 据此决定是否启动 poller。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_remote_poller.py` 追加：

```python
from remote_poller import load_remotes

def test_load_remotes_missing_file(tmp_path):
    assert load_remotes(tmp_path / "nope.json") == []

def test_load_remotes_valid(tmp_path):
    p = tmp_path / "remotes.json"
    p.write_text('{"remotes": [{"name": "vm1", "host": "h", "user": "u"}]}')
    out = load_remotes(p)
    assert len(out) == 1 and out[0]["name"] == "vm1"

def test_load_remotes_malformed_returns_empty(tmp_path):
    p = tmp_path / "remotes.json"
    p.write_text("{ not json")
    assert load_remotes(p) == []

def test_load_remotes_skips_incomplete_entries(tmp_path):
    p = tmp_path / "remotes.json"
    p.write_text('{"remotes": [{"name": "ok", "host": "h", "user": "u"}, {"name": "bad"}]}')
    out = load_remotes(p)
    assert [r["name"] for r in out] == ["ok"]  # 缺 host/user 的被丢弃
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_remote_poller.py -k load_remotes -v`
预期：FAIL（`load_remotes` 不存在）。

- [ ] **步骤 3：编写最少实现代码**

在 `remote_poller.py` 顶部补 `from pathlib import Path`，并追加：

```python
def load_remotes(path):
    """读取 remotes.json。缺失/格式错/不完整条目均安全处理，返回有效 remote 列表。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []
    out = []
    for r in data.get("remotes", []):
        if r.get("name") and r.get("host") and r.get("user"):
            out.append(r)
    return out
```

修改 `observer.py`。顶部 import 区（约第 11 行后）加：

```python
from remote_poller import RemotePoller, load_remotes
```

在 `main()` 中，把 `state = SessionState()`（约 433 行）替换为：

```python
    state_dir = os.path.join(os.path.expanduser('~'), '.claude-observer')
    remotes = load_remotes(os.path.join(state_dir, 'remotes.json'))
    poller = None
    if remotes:
        poller = RemotePoller(remotes)
        poller.start()
    state = SessionState(remote_poller=poller)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_remote_poller.py -v`
预期：全部 PASS（15 项）。再 `python -c "import observer"` 确认无导入错误（注意：导入 `webview` 在缺依赖环境可能失败，仅验证语法可用 `python -m py_compile observer.py`）。

- [ ] **步骤 5：创建配置示例**

`remotes.example.json`：

```json
{
  "remotes": [
    {
      "name": "ubuntu-vm",
      "host": "192.168.1.50",
      "port": 22,
      "user": "dev",
      "identity_file": "C:/Users/you/.ssh/id_rsa"
    }
  ]
}
```

- [ ] **步骤 6：Commit**

```bash
git add remote_poller.py observer.py remotes.example.json tests/test_remote_poller.py
git commit -m "feat: 加载 remotes.json 并在 observer 启动时拉起 poller"
```

---

## 任务 7：前端来源徽标

**文件：**
- 修改：`observer.py`（内嵌 HTML：加 CSS `.card-source` + `renderCard` 注入徽标）

当 `s.source` 存在且不等于 `"local"` 时，在卡片项目名旁显示来源徽标。前端逻辑改动小，靠任务 8 实机验证。

- [ ] **步骤 1：加 CSS**

在 `.card-project` 样式块之后（约第 159 行后）追加：

```css
.card-source{
  display:inline-block;
  margin-left:6px;
  padding:1px 6px;
  font-size:10px;
  border-radius:6px;
  background:rgba(100,180,255,0.18);
  color:rgba(140,200,255,0.95);
  vertical-align:middle;
}
```

- [ ] **步骤 2：改 renderCard 注入徽标**

在 `renderCard` 中（约第 310 行），`return '<div class="card"...` 之前加：

```javascript
  var source = (s.source && s.source !== 'local')
    ? '<span class="card-source">' + escapeHtml(s.source) + '</span>'
    : '';
```

并把项目名那行（约第 320 行）改为追加徽标：

```javascript
    '<div class="card-project">' + escapeHtml(s.project_name || 'Unknown') + source + '</div>' +
```

- [ ] **步骤 3：语法检查**

运行：`python -m py_compile observer.py`
预期：无报错（HTML 是字符串，确认 Python 语法完整）。

- [ ] **步骤 4：Commit**

```bash
git add observer.py
git commit -m "feat: 远程会话卡片显示来源徽标"
```

---

## 任务 8：端到端验证 + README 文档

**文件：**
- 修改：`README.md`（新增「远程 / VM 会话」章节）

- [ ] **步骤 1：跑全部单测**

先把 pytest 加入 `requirements.txt`（仅测试用）并安装：

```bash
echo "pytest>=7.0" >> requirements.txt
pip install pytest
```

运行：`python -m pytest tests/ -v`
预期：全部 PASS。清理：确认无临时文件残留。

- [ ] **步骤 2：端到端手动验证（需一台 Ubuntu VM）**

1. 把 `hooks/`（含 `claude_observer_hook.sh` + `claude_observer_helper.js`）拷到 VM，`chmod +x claude_observer_hook.sh`。
2. VM 的 `~/.claude/settings.json` 配置各 hook 指向 `/path/to/hooks/claude_observer_hook.sh <EventName>`（见步骤 3 README 内容）。
3. 宿主机 `~/.claude-observer/remotes.json` 填入该 VM 连接信息；确认 `ssh user@host` 可免密登录。
4. 启动 observer，在 VM 上跑一次 Claude Code 会话。
   - 预期：宿主机出现该会话卡片，带 VM 来源徽标。
   - 关闭 VM 卡片：消失，下次拉取若会话仍活跃则重现。
   - VM 关机：卡片保留上次快照，最终被 48h stale 清除。

- [ ] **步骤 3：写 README 章节**

在 `README.md` 末尾追加：

````markdown
## 远程 / 虚拟机会话（SSH 汇总）

如果你的 Claude Code 运行在虚拟机（Ubuntu/Linux）上，可让其会话汇总到宿主机的 Observer。

### VM 端

1. 把本仓库的 `hooks/` 目录拷到 VM（需含 `claude_observer_hook.sh` 和 `claude_observer_helper.js`）。
2. 赋予执行权限：

   ```bash
   chmod +x /path/to/hooks/claude_observer_hook.sh
   ```

3. 在 VM 的 `~/.claude/settings.json` 配置 hook，每个事件指向脚本并带事件名参数：

   ```json
   {
     "hooks": {
       "SessionStart":    [{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh SessionStart" }] }],
       "Notification":    [{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh Notification" }] }],
       "Stop":            [{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh Stop" }] }],
       "SessionEnd":      [{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh SessionEnd" }] }],
       "PreToolUse":      [{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh PreToolUse" }] }],
       "PostToolUse":     [{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh PostToolUse" }] }],
       "UserPromptSubmit":[{ "hooks": [{ "type": "command", "command": "/path/to/hooks/claude_observer_hook.sh UserPromptSubmit" }] }]
     }
   }
   ```

### 宿主机端

1. 确认宿主机能免密 SSH 登录 VM（`ssh user@host` 可直接进）。
2. 创建 `~/.claude-observer/remotes.json`（参考仓库根目录 `remotes.example.json`）：

   ```json
   {
     "remotes": [
       { "name": "ubuntu-vm", "host": "192.168.1.50", "port": 22,
         "user": "dev", "identity_file": "C:/Users/you/.ssh/id_rsa" }
     ]
   }
   ```

3. 启动 `ClaudeObserver.exe`。VM 会话会带来源徽标出现在小部件中。

> Observer 对 VM 只读（仅 `cat` 会话文件），不修改 VM 上任何内容；不存储凭据，仅复用你已有的 SSH key。
````

- [ ] **步骤 4：Commit**

```bash
git add README.md
git commit -m "docs: 远程/VM 会话 SSH 汇总配置说明"
```

---

## 附录：依赖

`requirements.txt` 追加（仅测试用，不影响打包）：

```
pytest>=7.0
```

打包的 PyInstaller 配置无需改动：`remote_poller.py` 是顶层模块会被自动收集，subprocess/threading 是标准库。

