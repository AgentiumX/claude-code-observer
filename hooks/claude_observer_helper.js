/**
 * Claude Code Observer - Hook Helper
 * Processes hook events from Claude Code and writes session state.
 * Requires: Node.js (already installed with Claude Code)
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

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
    const gitRoot = execSync('git rev-parse --show-toplevel', {
      cwd, encoding: 'utf8', timeout: 2000, stdio: ['pipe', 'pipe', 'pipe']
    }).trim();
    if (gitRoot) return path.basename(gitRoot);
  } catch {}
  return path.basename(cwd);
}

// Return the existing session, or create a minimal one if it's missing.
// Hooks can fire without a prior SessionStart (e.g. hooks were configured
// mid-session), so events like Notification/PreToolUse must still surface a
// card instead of being silently dropped.
function ensureSession(state, sessionId, cwd, now) {
  let session = state.sessions[sessionId];
  if (!session) {
    session = {
      id: sessionId,
      cwd: cwd,
      project_name: getProjectName(cwd),
      session_title: sessionId.slice(0, 8),
      status: 'working',
      model: '',
      source: '',
      started_at: now,
      updated_at: now,
      last_tool: '',
      stop_reason: '',
      notification_message: ''
    };
    state.sessions[sessionId] = session;
  }
  return session;
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
        stop_reason: '',
        notification_message: ''
      };
      break;
    }

    case 'Notification': {
      // Fires when Claude needs the user: an option choice or a tool-permission
      // prompt. This is the real signal for "needs input" (there is no
      // PermissionRequest hook). Auto-create the card if SessionStart was missed.
      const session = ensureSession(state, sessionId, cwd, now);
      session.status = 'waiting';
      session.updated_at = now;
      session.notification_message = input.message || 'Waiting for input';
      break;
    }

    case 'Stop': {
      const session = ensureSession(state, sessionId, cwd, now);
      session.status = 'idle';
      session.updated_at = now;
      session.stop_reason = input.stop_reason || '';
      session.notification_message = '';
      break;
    }

    case 'SessionEnd': {
      delete state.sessions[sessionId];
      break;
    }

    case 'PreToolUse': {
      const session = ensureSession(state, sessionId, cwd, now);
      const toolName = input.tool_name || '';
      LOG(`tool_name="${toolName}"`);
      if (toolName === 'AskUserQuestion') {
        session.status = 'waiting';
        session.notification_message = 'Waiting for user input';
        LOG('set status=waiting (AskUserQuestion)');
      } else {
        session.status = 'working';
        LOG('set status=working');
      }
      session.updated_at = now;
      session.last_tool = toolName;
      break;
    }

    case 'PostToolUse': {
      const session = ensureSession(state, sessionId, cwd, now);
      const toolName = input.tool_name || '';
      session.status = 'working';
      session.updated_at = now;
      session.last_tool = toolName;
      break;
    }

    case 'UserPromptSubmit': {
      const session = ensureSession(state, sessionId, cwd, now);
      session.status = 'working';
      session.updated_at = now;
      session.notification_message = '';
      break;
    }

    case 'PermissionRequest': {
      // A permission dialog appeared: Claude needs the user to approve a tool
      // (e.g. an MCP tool or a Bash command not on the allow list). Real Claude
      // Code hook event. This is the primary "needs your decision" signal.
      const session = ensureSession(state, sessionId, cwd, now);
      const toolName = input.tool_name || session.last_tool || 'tool';
      session.status = 'waiting';
      session.updated_at = now;
      session.last_tool = toolName;
      session.notification_message = 'Needs approval for ' + toolName;
      LOG(`set status=waiting (PermissionRequest for ${toolName})`);
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
