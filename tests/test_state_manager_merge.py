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