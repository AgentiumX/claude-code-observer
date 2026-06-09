/**
 * Claude Code Observer - Hook Helper
 * Processes hook events from Claude Code and writes session state.
 * Requires: Node.js (already installed with Claude Code)
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const STATE_DIR = path.join(os.homedir(), '.claude-observer');
const STATE_FILE = path.join(STATE_DIR, 'sessions.json');
const TMP_FILE = STATE_FILE + '.tmp';

function ensureStateDir() {
  if (!fs.existsSync(STATE_DIR)) {
    fs.mkdirSync(STATE_DIR, { recursive: true });
  }
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return { sessions: {} };
  }
}

function writeState(state) {
  ensureStateDir();
  fs.writeFileSync(TMP_FILE, JSON.stringify(state, null, 2), 'utf8');
  fs.renameSync(TMP_FILE, STATE_FILE);
}

function getProjectName(cwd) {
  if (!cwd) return 'Unknown';
  try {
    const { execSync } = require('child_process');
    const gitRoot = execSync('git rev-parse --show-toplevel', {
      cwd, encoding: 'utf8', timeout: 2000, stdio: ['pipe', 'pipe', 'pipe']
    }).trim();
    if (gitRoot) return path.basename(gitRoot);
  } catch {}
  return path.basename(cwd);
}

async function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => resolve(data));
    setTimeout(() => resolve(data), 3000);
  });
}

async function main() {
  const eventName = process.argv[2];
  const LOG = (msg) => process.stderr.write(`[observer:${eventName}] ${msg}\n`);

  if (!eventName) {
    LOG('ERROR: no event name');
    process.exit(1);
  }

  LOG('started');

  let input;
  try {
    const raw = await readStdin();
    LOG(`stdin length: ${raw.length}`);
    input = JSON.parse(raw);
  } catch (err) {
    LOG(`ERROR parsing stdin: ${err.message}`);
    process.exit(1);
  }

  const sessionId = input.session_id;
  if (!sessionId) {
    LOG('ERROR: no session_id');
    process.exit(1);
  }

  LOG(`session_id: ${sessionId}`);

  const cwd = input.cwd || '';
  const now = new Date().toISOString();
  const state = readState();

  switch (eventName) {
    case 'SessionStart': {
      const projectName = getProjectName(cwd);
      const title = input.session_title || sessionId.slice(0, 8);
      state.sessions[sessionId] = {
        id: sessionId,
        cwd: cwd,
        project_name: projectName,
        session_title: title,
        status: 'working',
        model: input.model || '',
        source: input.source || '',
        started_at: now,
        updated_at: now,
        last_tool: '',
        stop_reason: ''
      };
      break;
    }

    case 'Notification': {
      if (state.sessions[sessionId]) {
        state.sessions[sessionId].status = 'waiting';
        state.sessions[sessionId].updated_at = now;
        state.sessions[sessionId].notification_message = input.message || '';
      }
      break;
    }

    case 'Stop': {
      if (state.sessions[sessionId]) {
        state.sessions[sessionId].status = 'idle';
        state.sessions[sessionId].updated_at = now;
        state.sessions[sessionId].stop_reason = input.stop_reason || '';
        state.sessions[sessionId].notification_message = '';
      }
      break;
    }

    case 'SessionEnd': {
      delete state.sessions[sessionId];
      break;
    }

    case 'PreToolUse': {
      if (state.sessions[sessionId]) {
        const toolName = input.tool_name || '';
        LOG(`tool_name="${toolName}"`);
        if (toolName === 'AskUserQuestion') {
          state.sessions[sessionId].status = 'waiting';
          state.sessions[sessionId].updated_at = now;
          state.sessions[sessionId].notification_message = 'Waiting for user input';
          state.sessions[sessionId].last_tool = toolName;
          LOG(`set status=waiting (AskUserQuestion)`);
        } else {
          state.sessions[sessionId].status = 'working';
          state.sessions[sessionId].updated_at = now;
          state.sessions[sessionId].last_tool = toolName;
          LOG(`set status=working`);
        }
      }
      break;
    }

    case 'PostToolUse': {
      if (state.sessions[sessionId]) {
        const toolName = input.tool_name || '';
        if (toolName === 'AskUserQuestion') {
          // UserPromptSubmit fires when user responds in IDE, overwriting waiting.
          // Re-set waiting here so the card turns red after the response is received.
          state.sessions[sessionId].status = 'waiting';
          state.sessions[sessionId].updated_at = now;
          state.sessions[sessionId].notification_message = 'Waiting for user input';
          state.sessions[sessionId].last_tool = toolName;
        } else {
          state.sessions[sessionId].status = 'working';
          state.sessions[sessionId].updated_at = now;
          state.sessions[sessionId].last_tool = toolName;
        }
      }
      break;
    }

    case 'UserPromptSubmit': {
      if (state.sessions[sessionId]) {
        state.sessions[sessionId].status = 'working';
        state.sessions[sessionId].updated_at = now;
        state.sessions[sessionId].notification_message = '';
      }
      break;
    }

    case 'PermissionRequest': {
      if (state.sessions[sessionId]) {
        state.sessions[sessionId].status = 'waiting';
        state.sessions[sessionId].updated_at = now;
        state.sessions[sessionId].notification_message = 'Needs approval for ' + (state.sessions[sessionId].last_tool || 'tool');
      }
      break;
    }

    default:
      break;
  }

  writeState(state);
  LOG(`wrote ${Object.keys(state.sessions).length} sessions`);
}

main().catch(err => {
  process.stderr.write('Error: ' + err.message + '\n');
  process.exit(1);
});
