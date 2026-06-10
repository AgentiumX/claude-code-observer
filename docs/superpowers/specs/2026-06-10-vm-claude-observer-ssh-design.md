# 跨虚拟机汇总 Claude Code 会话到宿主机 Observer — 设计文档

- 日期：2026-06-10
- 状态：已批准设计，待编写实现计划
- 相关代码：`hooks/claude_observer_helper.js`、`hooks/*.bat`、`observer.py`、`state_manager.py`

## 背景与问题

部分项目运行在本地电脑的虚拟机（Ubuntu）上，开发者通过 IDE 的 SSH Remote 连接 VM 上的代码目录，因此实际运行的是 **VM 上的 Claude Code**。

当前 Observer 架构（纯本地）：

1. Claude Code 触发 hook → 调用 `.bat` 包装脚本 → 运行 `claude_observer_helper.js`（Node）。
2. helper 在「运行 Claude Code 的那台机器上」执行 `git rev-parse`、读取 cwd，然后原子写入 `~/.claude-observer/sessions.json`（tmp + rename）。
3. Observer（宿主机 Python/pywebview）每 800ms 读取该文件并渲染卡片。路径硬编码于 `state_manager.py`：`Path.home() / '.claude-observer' / 'sessions.json'`。

目标：让 VM 上的 Claude Code 会话也能出现在宿主机的 Observer 小部件里，并兼容大部分 Linux 系统。

**关键约束**：helper 必须在 VM 上运行（它要读 VM 的 git 仓库和 cwd），所以跨机器传输的只能是「VM 上那个 sessions.json 的内容」。

## 已确认的决策

| 决策项 | 选择 |
| --- | --- |
| 数据源场景 | **B：宿主机和 VM 都会跑 Claude Code**（多数据源合并） |
| 传输架构 | **方案 1：Observer 主动 SSH 拉取**（VM 端零网络配置、复用现有 SSH、天然支持多 VM、纯读取无写竞争） |
| VM 配置方式 | **完整连接信息**（host/port/user/identity_file 写在配置文件里） |
| 卡片来源标识 | **显示来源标签**（卡片上标明 local / 哪台 VM） |
| 远程卡片关闭行为 | **本地隐藏到下次拉取**（Observer 对 VM 只读，不回写） |
| 拉取频率 | **1 秒** |
| SSH 方式 | **常驻 SSH 流**（开一个常驻 ssh 进程，VM 端循环输出，避免每秒握手开销） |
| VM hook 形态 | **单脚本 + 事件名参数**（功能对齐 Windows 的 8 个 `.bat`，但更简洁） |

## 整体架构

```
┌─ Ubuntu VM (Claude Code 在这跑) ──────────────────────┐
│  hook 触发 → claude_observer_hook.sh <event>          │
│           → claude_observer_helper.js (完全复用)       │
│           → 写 VM 本地 ~/.claude-observer/sessions.json │
└───────────────────────────────────────────────────────┘
                      ▲ 常驻 ssh 进程：循环 cat + 分隔符 (只读)
                      │
┌─ Windows 宿主机 (observer.exe) ───────────────────────┐
│  remote_poller (每 VM 一个后台线程, 持续读流)          │
│    └─ 解析每块 JSON → 给 session 打 source 标签         │
│       → 写线程安全内存缓存                              │
│  state_manager.get_sessions()                          │
│    └─ 合并 [本地 sessions.json] + [各 VM 内存缓存]      │
│  HTML 卡片：source != "local" 时显示来源徽标            │
└────────────────────────────────────────────────────────┘
```

核心思路：**VM 端逻辑与本地完全一致**（写自己的 sessions.json），跨机器的工作全部由宿主机 Observer 通过 SSH 只读完成。

## 组件设计

### 组件 A：VM 端 Linux hook（`hooks/claude_observer_hook.sh`）

- 新增 POSIX `sh` 兼容脚本（不使用 bashism），对标现有 `claude_observer_hook.bat`。
- 职责：接收事件名作为第一个参数 → 读取 stdin → 定位 node → `node <helper> <event>` 并把 stdin 传入。
- 单脚本 + 事件名参数：hook 配置直接写 `claude_observer_hook.sh SessionStart`，无需 8 个独立脚本。
- 与 `.bat` 一致的行为：找不到 node 时报错退出；可保留一份可选的 debug 日志（写 `~/.claude-observer/hook_debug.log`）。
- 需要 `chmod +x`。

### 组件 B：`claude_observer_helper.js`（不改动）

- 已是跨平台实现：`os.homedir()`、`path`、`git rev-parse` 在 Linux 均正常工作。
- VM 上 helper 写入 VM 自己的 `~/.claude-observer/sessions.json`，与本地行为完全相同。
- **这是本方案最大的收益：核心逻辑零改动、零分叉。**

### 组件 C：宿主机配置（`~/.claude-observer/remotes.json`）

```json
{
  "remotes": [
    {
      "name": "ubuntu-vm",
      "host": "192.168.1.50",
      "port": 22,
      "user": "dev",
      "identity_file": "C:/Users/you/.ssh/id_rsa"
    }
  ]
}
```

- 文件不存在或 `remotes` 为空 → 不启动任何远程读取，Observer 退化为纯本地行为（向后兼容）。
- `identity_file` 可选；缺省时依赖 SSH agent / 默认 key。

### 组件 D：`remote_poller.py`（新增，常驻流读取器）

- 每个 remote 启动一个后台线程（`daemon=True`），与 800ms 的 UI 刷新循环完全隔离，**绝不阻塞 UI**。
- 每个线程维持一个常驻 ssh 进程，远程执行循环命令（VM 端无需安装额外脚本）：

  ```
  ssh -p <port> -i <identity_file> \
      -o BatchMode=yes -o ConnectTimeout=5 \
      -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
      <user>@<host> \
      'while true; do cat ~/.claude-observer/sessions.json 2>/dev/null; echo "<<<OBSERVER_EOF>>>"; sleep 1; done'
  ```

- 持续读取 stdout，按分隔符 `<<<OBSERVER_EOF>>>` 切块；每块解析为 JSON，给其中每个 session 注入 `source: "<name>"`，写入线程安全内存缓存（按 remote name 分桶）。
- 进程退出（VM 关机 / 断网 / SSH 失败）→ 按指数退避重连（如 1s→2s→5s→10s 上限）；重连期间**保留上次成功快照**，避免卡片闪烁。
- `BatchMode=yes` 确保永不卡在密码提示。
- 单条解析失败只丢弃该块，不影响线程存活。

### 组件 E：`state_manager.py`（改动）

- 持有 `RemotePoller` 引用（或其内存缓存）。
- `get_sessions()`：合并「本地 sessions.json（标 `source: "local"`）」+「各 VM 内存缓存」，统一排序返回。
- session id 为 UUID，跨机器天然不冲突。
- `dismiss_session(id)`：
  - 来源为 `local` → 沿用现有逻辑，从本地文件删除。
  - 来源为远程 → 加入内存「隐藏集」`hidden_ids`；该 id 在下次该 remote 成功拉取并仍存在时从隐藏集清除（即「隐藏到下次拉取」，若 session 仍活跃则卡片重现）。
- 现有 48h stale 过滤逻辑对合并后的所有 session 一并生效；不可达 VM 的旧快照最终被清掉。

### 组件 F：前端 HTML（`observer.py` 内嵌 HTML，小改）

- 卡片渲染：当 `session.source && session.source !== "local"` 时，显示一个小徽标展示来源名（如 `ubuntu-vm`）。
- 改动局限于卡片渲染那一小段，不动布局主体。

## 数据流

1. VM 上 Claude Code 触发 hook → `claude_observer_hook.sh <event>` → `helper.js` → 写 VM 的 `sessions.json`。
2. 宿主机 `remote_poller` 线程的常驻 ssh 每秒收到一份 VM `sessions.json` 内容 → 解析 → 打 `source` 标签 → 写内存缓存。
3. UI 每 800ms 调 `get_sessions()` → 合并本地文件 + 各 VM 缓存 → 渲染（远程卡片带来源徽标）。

## 错误处理

| 场景 | 行为 |
| --- | --- |
| VM 关机 / 网络中断 | ssh 进程退出 → 退避重连；保留上次快照；`updated_at` 不再更新，最终被 48h stale 逻辑清除 |
| SSH 需要密码 / key 失效 | `BatchMode=yes` 立即失败 → 进入退避重连，不阻塞 |
| 某块 JSON 解析失败 | 丢弃该块，线程继续 |
| `remotes.json` 缺失 / 为空 / 格式错误 | 不启动远程读取，退化为纯本地，记录一次告警 |
| VM 上 node 缺失 | hook 脚本报错退出（与 `.bat` 行为一致），不影响 Observer |

## 安全

- Observer 对 VM **只读**（仅 `cat`），不修改 VM 上任何文件。
- 不存储任何凭据；仅在配置中引用用户已有的 SSH key 路径。
- 复用用户既有的 SSH 信任关系，不新增攻击面（无需在 VM 上开端口或放新密钥）。

## 测试策略

- **helper.js（VM 逻辑）**：在 Linux 上对每个事件喂 stdin JSON，断言 `sessions.json` 内容正确（复用现有行为，回归验证）。
- **hook.sh**：验证事件名参数透传、stdin 透传、node 缺失时的退出码。
- **remote_poller**：用本地 `sh` 模拟「循环 cat + 分隔符」的流，验证分块解析、source 注入、断流重连、退避、快照保留。
- **state_manager 合并**：构造本地 + 多远程缓存，验证合并、排序、source 标签、dismiss 的本地/远程分支与隐藏集清除。
- **端到端（手动）**：实际连一台 Ubuntu VM，跑一次 Claude Code 会话，确认宿主机卡片出现并带来源徽标；VM 关机后卡片按预期保留再清除。

## 兼容性

- VM hook 用 POSIX `sh`，兼容 Ubuntu 及大部分 Linux 发行版。
- 常驻流命令仅依赖 `cat`/`sleep`/`while`，均为 coreutils 标准件。
- 宿主机依赖 Windows 自带 OpenSSH 客户端（Win10 1809+ 默认提供）。

## 配置说明（交付时写入 README）

1. **VM 端**：把 `hooks/` 目录（含 `claude_observer_hook.sh` + `claude_observer_helper.js`）放到 VM 上某路径；`chmod +x claude_observer_hook.sh`。
2. **VM 的 Claude Code hook 配置**（`~/.claude/settings.json` 或项目级）：每个事件指向 `/path/to/hooks/claude_observer_hook.sh <EventName>`。
3. **宿主机**：在 `~/.claude-observer/remotes.json` 填入 VM 的连接信息；确保宿主机能免密 ssh 到 VM（`ssh user@host` 可直接登录）。
4. 启动 observer.exe，VM 会话即出现在小部件中。

## 范围之外（YAGNI）

- 不做 VM→宿主机反向推送、共享文件夹方案。
- 不做远程会话的回写删除（已选择只读 + 本地隐藏）。
- 不做配置热加载（启动时读一次 remotes.json 即可；如需改配置重启 observer）。
- 不做 UI 上的 remote 管理界面（手工编辑 JSON）。
