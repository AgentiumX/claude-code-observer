"""
Claude Code Observer - State Manager
Reads session state written by hook scripts and provides data to the viewer.
"""

import json
import os
import time
from pathlib import Path


class SessionState:
    """Manages Claude Code session state from the shared JSON file."""

    def __init__(self):
        self._state_dir = Path.home() / '.claude-observer'
        self._state_file = self._state_dir / 'sessions.json'
        self._last_mtime = 0
        self._cache = {'sessions': {}}

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
        """Return list of active sessions, sorted by updated_at (newest first)."""
        data = self._read_file()
        sessions = list(data.get('sessions', {}).values())
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

    def cleanup_stale(self, max_age_hours=24):
        """Remove sessions that haven't been updated in max_age_hours."""
        data = self._read_file()
        now = time.time()
        to_remove = []
        for sid, session in data.get('sessions', {}).items():
            try:
                updated = session.get('updated_at', '')
                # Parse ISO timestamp
                from datetime import datetime
                dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                age_hours = (now - dt.timestamp()) / 3600
                if age_hours > max_age_hours:
                    to_remove.append(sid)
            except (ValueError, TypeError):
                continue
        for sid in to_remove:
            del data['sessions'][sid]
        if to_remove:
            self._write_state(data)
        return len(to_remove)

    def _write_state(self, state):
        """Write state back to file (for cleanup operations)."""
        try:
            tmp_file = self._state_file.with_suffix('.json.tmp')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            os.replace(str(tmp_file), str(self._state_file))
        except OSError:
            pass
