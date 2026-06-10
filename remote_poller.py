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