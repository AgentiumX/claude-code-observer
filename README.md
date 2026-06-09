# Claude Code Observer

A desktop dashboard widget that monitors all your Claude Code sessions in real-time. Glassmorphism UI inspired by iOS 26 — sits on your desktop like a sticky note.

![Status](https://img.shields.io/badge/platform-Windows%207%2F10%2F11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Real-time monitoring** — See all active Claude Code sessions at a glance
- **4 status states** with distinct visual indicators:
  - 🟢 **Working** — Claude is actively processing
  - 🔴 **Needs Input** — Claude is waiting for your response (pulsing alert)
  - ⚪ **Idle** — Session paused or completed
  - 🔴 **Error** — Something went wrong
- **Glass morphism UI** — Frosted glass aesthetic, draggable, always-on-top
- **Zero install** — Single `.exe` file, no dependencies
- **Project-aware** — Shows project name + session title so you know which project each session belongs to

## Quick Start

### 1. Download

Download `ClaudeObserver.exe` from [Releases](../../releases) (or build from source, see below).

### 2. Configure Claude Code Hooks

Open your Claude Code settings file. You can find it at:
- **User settings:** `%APPDATA%\claude\settings.json`
- **Project settings:** `.claude/settings.json` in your project root

Add the hooks configuration. **Replace `/path/to/hooks` with the actual path to the `hooks` folder** from this project.

> ⚠️ **Important:** Use **forward slashes** (`/`) in the path. Claude Code uses bash internally, and backslashes (`\`) will be stripped, causing "command not found" errors.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_session_start.bat",
            "timeout": 30
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_notification.bat",
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_stop.bat",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_session_end.bat",
            "timeout": 30
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_pre_tool_use.bat",
            "timeout": 30
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_post_tool_use.bat",
            "timeout": 30
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/hooks/on_user_prompt.bat",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

> **Tip:** `timeout` is recommended — the hook involves a Node.js process that takes ~3 seconds. Default timeout may be too short.

### 3. Run

Double-click `ClaudeObserver.exe`. The widget appears on the right side of your screen.

### 4. Verify

Start a Claude Code session — you should see it appear on the dashboard within a few seconds.

## How It Works

```
Claude Code Session
      │
      │ (hook event fires, JSON on stdin)
      ▼
  hooks/*.bat ──► claude_observer_helper.js
                        │
                        │ (writes session state)
                        ▼
              ~/.claude-observer/sessions.json
                        │
                        │ (polls every 2s)
                        ▼
              ClaudeObserver.exe
              (glass UI dashboard)
```

1. **Hook scripts** (`.bat`) are triggered by Claude Code at key events
2. The **Node.js helper** (`claude_observer_helper.js`) parses the event data and writes to `~/.claude-observer/sessions.json`
3. The **Observer app** reads this file and displays sessions as cards

## Requirements

- **Claude Code** — The hook API requires Claude Code to be installed
- **Node.js** — Required by Claude Code (also used by the hook helper script)
- **Windows 10/11** — Full glass effect (WebView2). Windows 7 works with reduced visual effects.

## Building from Source

### Prerequisites

- Python 3.7+
- pip

### Build

```bash
# Install dependencies
pip install -r requirements.txt

# Build exe (Windows)
build.bat

# Or manually:
pyinstaller --onefile --windowed --name ClaudeObserver observer.py
```

The executable will be in `dist/ClaudeObserver.exe`.

### Development (without building)

```bash
pip install -r requirements.txt
python observer.py
```

## Hook Events Reference

| Hook Event | What It Tracks | Status Set |
|---|---|---|
| `SessionStart` | New session begins | `working` |
| `Notification` | Claude needs human input | `waiting` |
| `Stop` | Claude finished a turn | `idle` |
| `SessionEnd` | Session closed | _(removed)_ |
| `PreToolUse` | Claude about to use a tool | `working` |
| `PostToolUse` | Claude finished using a tool | `working` |
| `UserPromptSubmit` | User sent a message | `working` |

## Session Data

Session state is stored at:
```
%USERPROFILE%\.claude-observer\sessions.json
```

Each session entry contains:
- `id` — Claude Code session ID
- `project_name` — Git repo name or directory name
- `session_title` — Session title from Claude Code
- `status` — `working` | `waiting` | `idle` | `error`
- `cwd` — Working directory path
- `last_tool` — Most recently used tool name
- `started_at` / `updated_at` — Timestamps

Sessions inactive for 48+ hours are automatically cleaned up.

## Troubleshooting

**Sessions don't appear on the dashboard:**
1. Verify the hook paths in your `settings.json` are correct (use absolute paths)
2. Check that Node.js is in your PATH: `node --version`
3. Look for the state file: `type %USERPROFILE%\.claude-observer\sessions.json`
4. Check Claude Code's debug output for hook errors

**The widget doesn't start:**
- Make sure WebView2 Runtime is installed (pre-installed on Win10/11)
- Download: https://developer.microsoft.com/en-us/microsoft-edge/webview2/

**Glass effect doesn't look right on Windows 7:**
- Windows 7 uses a fallback renderer. The widget still works, but the frosted glass effect is simplified.

## License

MIT
