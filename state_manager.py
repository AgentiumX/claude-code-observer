"""
Claude Code Observer - State Manager
Reads session state written by hook scripts and provides data to the viewer.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

# Sessions not updated within this window are considered stale and removed.
STALE_AFTER_HOURS = 48


class SessionState:
    """Manages Claude Code session state from the shared JSON file."""

    def __init__(self, remote_poller=None):
        self._state_dir = Path.home() / '.claude-observer'
        self._state_file = self._state_dir / 'sessions.json'
        self._last_mtime = 0
        self._cache = {'sessions': {}}
        self._remote_poller = remote_poller

    @property
    def state_file(self):
        return self._state_file

    def _read_file(self):
        """Read and parse the sessions JSON file."""
        try:
            mtime = self._state_file.stat().st_mtime
            if mtime == self._last_mtime:
                return self._cache
            with open(self._state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._cache = data
            self._last_mtime = mtime
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {'sessions': {}}

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

    def get_session_count(self):
        """Return total number of active sessions."""
        data = self._read_file()
        return len(data.get('sessions', {}))

    def get_waiting_count(self):
        """Return number of sessions waiting for human intervention."""
        sessions = self.get_sessions()
        return sum(1 for s in sessions if s.get('status') == 'waiting')

    def get_stale_ids(self):
        """Return IDs of stale sessions (not updated within STALE_AFTER_HOURS).

        Read-only, never writes. Process-liveness checks were removed: hooks run
        in a throwaway shell, so no PID we can capture identifies the live Claude
        Code process. Time since last update is the only reliable signal.
        """
        data = self._read_file()
        now = time.time()
        stale = []
        for sid, session in data.get('sessions', {}).items():
            try:
                updated = session.get('updated_at', '')
                dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                age_hours = (now - dt.timestamp()) / 3600
                if age_hours > STALE_AFTER_HOURS:
                    stale.append(sid)
            except (ValueError, TypeError):
                continue
        return stale

    def cleanup_stale(self):
        """One-time cleanup: remove stale sessions from file. Use only at startup."""
        stale_ids = self.get_stale_ids()
        if not stale_ids:
            return 0
        self._last_mtime = 0
        data = self._read_file()
        removed = 0
        for sid in stale_ids:
            if sid in data.get('sessions', {}):
                del data['sessions'][sid]
                removed += 1
        if removed:
            self._write_state(data)
        return removed

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

    def _write_state(self, state):
        """Write state back to file (for cleanup operations)."""
        try:
            tmp_file = self._state_file.with_suffix('.json.tmp')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            os.replace(str(tmp_file), str(self._state_file))
        except OSError:
            pass
