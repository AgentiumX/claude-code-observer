"""Claude Code Observer - 远程 VM 会话拉取（常驻 SSH 流）。"""

import json
import subprocess
import threading
import time

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


class RemotePoller:
    """维护各 VM 的会话快照（内存缓存），供 state_manager 合并。"""

    def __init__(self, remotes):
        self._remotes = remotes
        self._cache = {}      # name -> {session_id: session_dict(已含 source)}
        self._hidden = set()  # 用户本地隐藏的远程 session id
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._procs = {}
        self._threads = []

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