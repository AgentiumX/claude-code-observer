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