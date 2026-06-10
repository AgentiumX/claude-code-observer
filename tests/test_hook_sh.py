import json, os, subprocess, sys
from pathlib import Path
import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "claude_observer_hook.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh hook")

def _run(tmp_path, event, stdin_text, with_node=True):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    capture = tmp_path / "capture.txt"
    if with_node:
        # Fake node: write argv and stdin to capture file
        fake = bindir / "node"
        fake.write_text(
            "#!/bin/sh\n"
            f'printf "ARGS:%s\\n" "$*" > "{capture}"\n'
            f'cat >> "{capture}"\n'
        )
        fake.chmod(0o755)
    # Prepend fake node dir so it takes priority over real node;
    # keep existing PATH so standard tools (date, dirname) remain available.
    new_path = str(bindir) + os.pathsep + os.environ.get("PATH", "")
    env = dict(os.environ, PATH=new_path)
    if not with_node:
        # Remove any directories containing a real 'node' from PATH
        env["PATH"] = _path_without_node(env["PATH"])
    proc = subprocess.run(
        ["sh", str(HOOK), event],
        input=stdin_text, capture_output=True, text=True, env=env,
    )
    return proc, capture

def _path_without_node(path):
    """Remove directories from PATH that contain a 'node' executable."""
    kept = []
    for d in path.split(os.pathsep):
        # Skip empty entries
        if not d:
            continue
        node_path = os.path.join(d, "node")
        # On POSIX, also check for node.exe (Windows Node on WSL)
        if os.path.isfile(node_path) or os.path.isfile(node_path + ".exe"):
            continue
        kept.append(d)
    return os.pathsep.join(kept)

def test_passes_event_and_stdin_to_node(tmp_path):
    payload = json.dumps({"session_id": "abc", "cwd": "/x"})
    proc, capture = _run(tmp_path, "SessionStart", payload)
    assert proc.returncode == 0
    text = capture.read_text()
    assert "SessionStart" in text
    assert '"session_id": "abc"' in text

def test_missing_event_name_fails(tmp_path):
    bindir = tmp_path / "bin"; bindir.mkdir()
    # Keep standard PATH so sh itself can be found, but remove any node
    env = dict(os.environ, PATH=_path_without_node(os.environ.get("PATH", "")))
    proc = subprocess.run(["sh", str(HOOK)], input="", capture_output=True, text=True,
                          env=env)
    assert proc.returncode != 0

def test_missing_node_fails(tmp_path):
    proc, _ = _run(tmp_path, "SessionStart", "{}", with_node=False)
    assert proc.returncode != 0
