"""
Claude Code Observer - Desktop Dashboard
A glassmorphism desktop widget that monitors Claude Code sessions.
"""

import sys
import json
import os
import ctypes

from state_manager import SessionState
from remote_poller import RemotePoller, load_remotes

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{margin:0;padding:0;box-sizing:border-box}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.15);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.25)}

html,body{
  width:100%;height:100%;overflow:hidden;
  background:rgba(10,10,20,1);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','SF Pro Display',Roboto,sans-serif;
  color:#fff;user-select:none;
}

#app{
  width:100%;height:100vh;
  display:flex;flex-direction:column;
  background:rgba(10,10,20,0.65);
  border:1px solid rgba(255,255,255,0.08);
  overflow:hidden;
}

/* Header */
.header{
  padding:14px 18px 10px;
  background:rgba(255,255,255,0.04);
  border-bottom:1px solid rgba(255,255,255,0.06);
  cursor:default;
}
.header-row{
  display:flex;align-items:center;gap:8px;
}
.logo{
  width:8px;height:8px;border-radius:50%;
  background:linear-gradient(135deg,#34C759,#30D158);
  box-shadow:0 0 8px rgba(52,199,89,0.5);
}
.title{
  font-size:13px;font-weight:600;letter-spacing:0.3px;
  color:rgba(255,255,255,0.9);flex:1;
}
.badge{
  font-size:10px;font-weight:500;
  padding:2px 8px;border-radius:8px;
  background:rgba(255,255,255,0.08);
  color:rgba(255,255,255,0.5);
}
.badge.has-waiting{
  background:rgba(255,69,58,0.2);
  color:#FF6961;
}
.close-btn{
  width:18px;height:18px;border-radius:50%;
  background:rgba(255,255,255,0.06);
  border:none;color:rgba(255,255,255,0.3);
  font-size:11px;line-height:18px;text-align:center;
  cursor:pointer;transition:all 0.2s;
}
.close-btn:hover{
  background:rgba(255,69,58,0.3);color:#FF6961;
}

/* Sessions container */
.sessions{
  flex:1;overflow-y:auto;
  padding:10px 12px 12px;
}

/* Empty state */
.empty{
  display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100%;
  color:rgba(255,255,255,0.25);font-size:13px;gap:8px;
}
.empty-icon{font-size:32px;opacity:0.5}

/* Session card */
.card{
  background:rgba(255,255,255,0.05);
  border-radius:14px;
  padding:12px 14px;
  margin-bottom:8px;
  border:1px solid rgba(255,255,255,0.06);
  transition:all 0.35s cubic-bezier(0.4,0,0.2,1);
  position:relative;
  overflow:hidden;
}
.card::before{
  content:'';position:absolute;
  left:0;top:0;bottom:0;width:3px;
  border-radius:14px 0 0 14px;
  transition:all 0.3s;
}

/* Status variants */
.card[data-status="working"]{
  background:rgba(52,199,89,0.04);
  border-color:rgba(52,199,89,0.12);
}
.card[data-status="working"]::before{background:#34C759}

.card[data-status="waiting"]{
  background:rgba(255,69,58,0.08);
  border-color:rgba(255,69,58,0.35);
  box-shadow:0 0 24px rgba(255,69,58,0.12),inset 0 0 12px rgba(255,69,58,0.03);
  animation:pulse-waiting 2s ease-in-out infinite;
}
.card[data-status="waiting"]::before{
  background:#FF453A;
  box-shadow:0 0 8px #FF453A;
}
@keyframes pulse-waiting{
  0%,100%{border-color:rgba(255,69,58,0.3);box-shadow:0 0 16px rgba(255,69,58,0.1)}
  50%{border-color:rgba(255,69,58,0.65);box-shadow:0 0 30px rgba(255,69,58,0.25)}
}

.card[data-status="idle"]{
  background:rgba(142,142,147,0.04);
  border-color:rgba(142,142,147,0.12);
}
.card[data-status="idle"]::before{background:#8E8E93}

.card[data-status="error"]{
  background:rgba(255,59,48,0.06);
  border-color:rgba(255,59,48,0.25);
  animation:pulse-error 1.5s ease-in-out infinite;
}
.card[data-status="error"]::before{
  background:#FF3B30;
  box-shadow:0 0 8px #FF3B30;
}
@keyframes pulse-error{
  0%,100%{border-color:rgba(255,59,48,0.25)}
  50%{border-color:rgba(255,59,48,0.55)}
}

/* Card content */
.card-project{
  font-size:12.5px;font-weight:600;
  color:rgba(255,255,255,0.88);
  margin-bottom:3px;
  display:flex;align-items:center;gap:6px;
}
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
.card-title{
  font-size:11px;font-weight:400;
  color:rgba(255,255,255,0.4);
  margin-bottom:8px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.card-meta{
  display:flex;align-items:center;gap:10px;
  font-size:10.5px;
}
.status-tag{
  display:inline-flex;align-items:center;gap:4px;
  padding:1px 7px;border-radius:5px;
  font-weight:500;font-size:10px;
}
.status-tag .dot{
  width:5px;height:5px;border-radius:50%;
}
.status-tag[data-status="working"]{
  background:rgba(52,199,89,0.15);color:#34C759;
}
.status-tag[data-status="working"] .dot{
  background:#34C759;
  animation:blink 1.8s ease-in-out infinite;
}
.status-tag[data-status="waiting"]{
  background:rgba(255,69,58,0.2);color:#FF6961;
  font-weight:700;
}
.status-tag[data-status="waiting"] .dot{
  background:#FF453A;
  animation:blink 0.6s ease-in-out infinite;
  box-shadow:0 0 6px #FF453A;
}
.status-tag[data-status="idle"]{
  background:rgba(142,142,147,0.12);color:#8E8E93;
}
.status-tag[data-status="idle"] .dot{background:#8E8E93}
.status-tag[data-status="error"]{
  background:rgba(255,59,48,0.18);color:#FF6961;
}
.status-tag[data-status="error"] .dot{
  background:#FF3B30;
  animation:blink 0.4s ease-in-out infinite;
}
@keyframes blink{
  0%,100%{opacity:1}50%{opacity:0.3}
}

.card-tool{
  color:rgba(255,255,255,0.3);
  font-family:'SF Mono','Cascadia Code',Consolas,monospace;
  font-size:10px;
}
.card-time{color:rgba(255,255,255,0.25)}
.card-cwd{
  color:rgba(255,255,255,0.18);font-size:9.5px;
  margin-top:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}

/* Waiting card notification message */
.card-notify{
  margin-top:6px;padding:5px 8px;
  background:rgba(255,69,58,0.08);
  border-radius:6px;
  font-size:10px;color:rgba(255,180,180,0.7);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}

/* Card dismiss button */
.card-close{
  position:absolute;top:8px;right:8px;
  width:18px;height:18px;border-radius:50%;
  background:rgba(255,255,255,0.06);
  border:none;color:rgba(255,255,255,0.35);
  font-size:11px;line-height:18px;text-align:center;
  cursor:pointer;opacity:0;
  transition:opacity 0.2s,background 0.2s,color 0.2s;
}
.card:hover .card-close{opacity:1}
.card-close:hover{
  background:rgba(255,69,58,0.3);color:#FF6961;
}
</style>
</head>
<body>
<div id="app">
  <div class="header" id="drag-area">
    <div class="header-row">
      <div class="logo"></div>
      <span class="title">Claude Observer</span>
      <span class="badge" id="badge">0 sessions</span>
      <button class="close-btn" onclick="pywebview.api.close_window()" title="Close">&#215;</button>
    </div>
  </div>
  <div class="sessions" id="sessions">
    <div class="empty">
      <div class="empty-icon">◇</div>
      <div>No active sessions</div>
      <div style="font-size:11px;opacity:0.6">Configure hooks to get started</div>
    </div>
  </div>
</div>

<script>
const STATUS_LABELS = {
  working: 'Working',
  waiting: '⚠ Needs Input',
  idle: 'Idle',
  error: 'Error'
};

let dragState = null;

document.getElementById('drag-area').addEventListener('mousedown', function(e) {
  if (e.target.classList.contains('close-btn')) return;
  dragState = { sx: e.screenX, sy: e.screenY };
  e.preventDefault();
});

document.addEventListener('mousemove', function(e) {
  if (!dragState) return;
  var dx = e.screenX - dragState.sx;
  var dy = e.screenY - dragState.sy;
  dragState.sx = e.screenX;
  dragState.sy = e.screenY;
  pywebview.api.move_window(dx, dy);
});

document.addEventListener('mouseup', function() {
  dragState = null;
});

function timeAgo(iso) {
  if (!iso) return '';
  var d = new Date(iso);
  var s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 5) return 'just now';
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderCard(s) {
  var status = s.status || 'idle';
  var label = STATUS_LABELS[status] || status;
  var tool = s.last_tool ? '<span class="card-tool">' + escapeHtml(s.last_tool) + '</span>' : '';
  var notify = '';
  if (status === 'waiting' && s.notification_message) {
    notify = '<div class="card-notify">💬 ' + escapeHtml(s.notification_message) + '</div>';
  }
  var source = (s.source && s.source !== 'local')
    ? '<span class="card-source">' + escapeHtml(s.source) + '</span>'
    : '';
  return '<div class="card" data-status="' + status + '">' +
    '<button class="card-close" data-id="' + escapeHtml(s.id || '') + '" title="Dismiss">&#215;</button>' +
    '<div class="card-project">' + escapeHtml(s.project_name || 'Unknown') + source + '</div>' +
    '<div class="card-title">' + escapeHtml(s.session_title || s.id || '') + '</div>' +
    '<div class="card-meta">' +
      '<span class="status-tag" data-status="' + status + '"><span class="dot"></span>' + label + '</span>' +
      tool +
      '<span class="card-time">' + timeAgo(s.updated_at) + '</span>' +
    '</div>' +
    notify +
    (s.cwd ? '<div class="card-cwd">' + escapeHtml(s.cwd) + '</div>' : '') +
  '</div>';
}

function updateUI(sessions) {
  var el = document.getElementById('sessions');
  var badge = document.getElementById('badge');
  var count = sessions.length;
  var waiting = sessions.filter(function(s){return s.status==='waiting'}).length;

  if (count === 0) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">◇</div>' +
      '<div>No active sessions</div>' +
      '<div style="font-size:11px;opacity:0.6">Waiting for Claude Code...</div></div>';
  } else {
    el.innerHTML = sessions.map(renderCard).join('');
  }

  badge.textContent = count + ' session' + (count !== 1 ? 's' : '');
  badge.className = 'badge' + (waiting > 0 ? ' has-waiting' : '');

  document.title = waiting > 0
    ? 'Claude Observer [' + waiting + ' needs input!]'
    : 'Claude Observer [' + count + ' sessions]';
}

async function refresh() {
  try {
    if (window.pywebview && window.pywebview.api) {
      var sessions = await pywebview.api.get_sessions();
      updateUI(sessions);
    }
  } catch(e) {}
}

// Delegated handler: dismiss a card when its close button is clicked.
document.getElementById('sessions').addEventListener('click', async function(e) {
  var btn = e.target.closest('.card-close');
  if (!btn) return;
  e.stopPropagation();
  var id = btn.getAttribute('data-id');
  if (!id) return;
  try {
    await pywebview.api.dismiss_session(id);
    refresh();
  } catch(e) {}
});

setInterval(refresh, 800);

window.addEventListener('pywebviewready', function() {
  refresh();
});

// Fallback if pywebviewready doesn't fire
setTimeout(refresh, 500);
</script>
</body>
</html>"""


class Api:
    """JavaScript API bridge for pywebview."""

    def __init__(self, state, window_ref):
        self._state = state
        self._window = window_ref

    def get_sessions(self):
        # Filter stale sessions in memory (read-only, never writes to file).
        # File cleanup is handled by Node hooks on SessionStart.
        stale_ids = set(self._state.get_stale_ids())
        sessions = self._state.get_sessions()
        if stale_ids:
            sessions = [s for s in sessions if s.get('id') not in stale_ids]
        return sessions

    def dismiss_session(self, session_id):
        # Remove a card from the dashboard. If the session is still active,
        # the next hook event will recreate it.
        return self._state.remove_session(session_id)

    def move_window(self, dx, dy):
        w = self._window[0]
        if w:
            w.move(w.x + int(dx), w.y + int(dy))

    def close_window(self):
        w = self._window[0]
        if w:
            w.destroy()


def main():
    import webview

    # Enable HiDPI on Windows
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    state_dir = os.path.join(os.path.expanduser('~'), '.claude-observer')
    remotes = load_remotes(os.path.join(state_dir, 'remotes.json'))
    poller = None
    if remotes:
        poller = RemotePoller(remotes)
        poller.start()
    state = SessionState(remote_poller=poller)
    state.cleanup_stale()  # Clean orphaned sessions on startup
    window_ref = [None]  # mutable ref for Api class
    api = Api(state, window_ref)

    # Get screen size for positioning
    screen = webview.screens[0] if webview.screens else None
    x_pos, y_pos = 100, 80
    if screen:
        x_pos = screen.width - 400
        y_pos = 80

    win = webview.create_window(
        'Claude Observer',
        html=HTML,
        width=360,
        height=520,
        x=x_pos,
        y=y_pos,
        frameless=True,
        easy_drag=False,
        on_top=True,
        resizable=True,
        min_size=(280, 200),
        js_api=api,
        transparent=True,
        vibrancy=True,
    )
    window_ref[0] = win

    webview.start(debug=False)


if __name__ == '__main__':
    main()
