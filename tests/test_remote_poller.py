import json
from remote_poller import build_ssh_command, parse_blocks, DELIM, RemotePoller


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