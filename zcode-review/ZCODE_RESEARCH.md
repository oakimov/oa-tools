# ZCode — Research Summary

**Date:** 2026-07-03 (base audit of 3.2.5); §7 plugin ABI follow-up 2026-07-19 (3.3.6)
**Source:** Reverse engineering of the ZCode macOS ARM64 application bundle (initially 3.2.5; plugin notes against 3.3.6 / `zcode-cli` 0.15.2)
**Application ID:** `dev.zcode.app`
**Developer:** Z.AI / Zhipu (智谱) — China-based AI company

---

## 1. Relationship to OpenCode

ZCode is a fork of OpenCode's backend architecture, with a custom frontend.

### Monorepo Structure (identical architecture)

| ZCode (`@zcode/*`) | OpenCode (`@opencode-ai/*`) |
|---|---|
| `@zcode/desktop` | `desktop` |
| `@zcode/client` | `client` |
| `@zcode/server` | `server` |
| `@zcode/ui` | `ui` / `app` |
| `@zcode/shared` | `core` |
| `@zcode/services` | (services layer) |
| `@zcode/rpc` | `protocol` |

Both use `electron-vite` with identical `out/main/`, `out/preload/`, `out/renderer/` output structure.

### Shared Dependency Signature (30+ matching libraries, many uncommon choices)

| Library | ZCode | OpenCode | Significance |
|---|---|---|---|
| `@lydell/node-pty` | v1.2.0-beta.10 | v1.2.0-beta.12 | Same **fork** of node-pty, not the original |
| `electron-updater` | v6.8.3 | v6.8.9 | Same update framework (Squirrel-based), vs Codex's Sparkle |
| `effect` | In code | Core architecture | Effect-TS structured concurrency — very distinctive |
| `hono` | ✅ | ✅ | HTTP web framework |
| `zod` | ✅ | ✅ | Schema validation |
| `zustand` | ✅ | ✅ | State management |
| `@xterm/xterm` | ✅ | ✅ | Terminal emulator |
| `@mermaid-js` | ✅ | ✅ | Diagrams |
| `@shikijs/shiki` | ✅ | ✅ | Syntax highlighting |
| `@radix-ui/*` | ✅ | ✅ | React UI primitives |
| `@dnd-kit` | ✅ | ✅ | Drag and drop |
| `framer-motion` | ✅ | ✅ | Animations |
| `cmdk` | ✅ | ✅ | Command menu |
| `lucide-react` | ✅ | ✅ | Icons |
| `ws` | ✅ | ✅ | WebSocket |
| `@opentelemetry/*` | ✅ | ✅ | Observability |

### Key Differences from OpenCode

| Aspect | ZCode | OpenCode |
|---|---|---|
| **Frontend framework** | React 19.2.5 | Solid.js (desktop) / TUI (terminal) |
| **UI paradigm** | Full graphical desktop app (Codex-like) | Terminal UI + Electron web shell |
| **Market** | Chinese (Z.AI, Zhipu, Lark, ARMS) | Global (open source) |
| **Auth** | Z.AI JWT, OAuth | Key-based, BYO provider |
| **Payment system** | Stripe, enterprise billing | None |
| **Agent integrations** | 17+ agents (Claude Code, Codex CLI, etc.) | None |

---

## 2. Telemetry — Detailed

ZCode has a **multi-layered, always-on telemetry system** with no visible opt-out. Data flows to two destinations.

### 2.1 Telemetry Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ZCode Electron App                                          │
│                                                              │
│  ┌──────────────┐    ┌──────────────────┐                    │
│  │ Renderer (UI) │───▶│ IPC Telemetry    │                    │
│  │              │    │ Channels:         │                    │
│  │ React 19     │    │ zcode:report-     │                    │
│  │              │    │  telemetry-event  │                    │
│  │              │    │ zcode:sync-       │                    │
│  │              │    │  telemetry-context │                    │
│  │              │    │ zcode:report-arms- │                    │
│  │              │    │  custom-event      │                    │
│  └──────────────┘    └───────┬──────────┘                    │
│                              │                               │
│  ┌───────────────────────────▼──────────────────────────┐    │
│  │             Main Process (Node.js + Electron)          │    │
│  │                                                       │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │    │
│  │  │ ARMS RUM    │  │ Custom Event │  │ Stability   │  │    │
│  │  │ @arms/rum-  │  │ Reporter     │  │ Monitor     │  │    │
│  │  │ electron    │  │ (zcode.z.ai) │  │ (crash,ANR, │  │    │
│  │  │ v0.0.3      │  │              │  │  freeze)    │  │    │
│  │  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  │    │
│  └─────────┼───────────────┼──────────────────┼─────────┘    │
│            │               │                  │              │
│            ▼               ▼                  ▼              │
│     Alibaba Cloud    Z.AI Servers    Z.AI Servers            │
│     ARMS RUM         (analytics)     (stability)             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Telemetry Channels (IPC Events)

| IPC Event | Purpose |
|---|---|
| `zcode:report-telemetry-event` | Report arbitrary analytics events |
| `zcode:sync-telemetry-context` | Sync telemetry context (user identity, device info) |
| `zcode:report-arms-custom-event` | Report custom ARMS events with arbitrary properties |

### 2.3 Hardware & Environment Data (sent to Alibaba Cloud ARMS)

Collected by `@arms/rum-electron` on every session, sent via:
```
POST https://proj-xtrace-7e235817c9b9381c22d8b743908d469f-cn-beijing.cn-beijing.log.aliyuncs.com/rum/web/v2
    ?workspace=default-cms-1936221977589032-cn-beijing
    &service_id=j2c03hoppk@7023210754a92ac5d1971
```

| Data Point | Source | Example |
|---|---|---|
| **Device MID** | Persistent UUID in `telemetry-state.json` | `"f47ac10b-58cc-4372-a567-0e02b2c3d479"` |
| **OS type** | `process.platform` | `"macOS"` / `"Windows"` / `"Linux"` |
| **OS version** | `os.release()` | `"24.6.0"` |
| **CPU brand** | `os.cpus()[0].model` | `"Apple"` / `"Intel(R) Core(TM) i7-..."` |
| **Hostname** | `os.hostname()` | `"MacBook-Pro.local"` |
| **Network type** | Active network interface | `"wifi"` / `"ethernet"` / `"cellular"` / `"offline"` |
| **Electron version** | `process.versions.electron` | `"34.2.0"` |
| **App version** | From package.json | `"3.2.5"` |
| **Build commit** | Build-time constant | `"9c3e1a15"` |

### 2.4 Stability & Crash Monitoring (sent to Z.AI servers + ARMS)

Always-on, tracks every crash, hang, and process exit:

| Event | Data Collected | Sent When |
|---|---|---|
| `perf_app_start` | Cold start duration | App launches |
| `perf_app_exit` | Exit code, exit reason, lifecycle scene | App quits |
| `perf_crash` | Crash kind (oom/js/native), exit_code, exit_reason, process_role, web_contents_id, window_id | A process crashes |
| `perf_anr` | duration_ms, window_id, web_contents_id | App stops responding (>5s) |
| `perf_freeze` | duration_ms, window_id, web_contents_id | App freezes (>30s) |
| `perf_process_exit` | exit_code, exit_reason, process_role, exit_kind, process_type, process_name | Any ZCode subprocess exits |
| `perf_resource_cpu` | CPU % per role (main/renderer/gpu/agent/utility_host) with mean/peak/p95 | Every 5 minutes |
| `perf_resource_memory` | Working set KB per role with mean/peak/p95 | Every 5 minutes |
| Render process gone | reason, exit_code, web_contents_type, URL of page | Renderer crashes |
| Child process gone | reason, exit_code, process_type, process_name | Any child process dies |

Every stability event includes the context envelope:
```json
{
  "event_name": "perf_crash",
  "device_mid": "<persistent-device-id>",
  "platform": "macos",
  "app_version": "3.2.5",
  "arms_env": "prod",
  "scene_lifecycle": "runtime"
}
```

### 2.5 Custom ARMS Events (sent to Alibaba Cloud ARMS)

Custom events with arbitrary properties, grouped by category:
- **Group:** `"stability"` — All stability/crash events
- **Group:** `"resource"` — All resource monitoring events
- **Name:** User-facing action or event name
- **Value:** Numeric metric value
- **Properties:** Any key-value pairs the app chooses to attach

### 2.6 User Identity Tracking

```json
// Local file: telemetry-state.json
{
  "deviceMid": "<persistent-uuid>",
  // Potentially: user-specific data
}

// Lock file: telemetry-state.lock  (prevents concurrent writes)
```

- `TelemetryUserIdLoader` — Loads/stores user identity
- `ArmsUserIdentitySync` — Syncs identity to ARMS
- `ensureDesktopDeviceMidSync()` — Creates persistent device MID on first run, stored at `{configDir}/telemetry-state.json`
- The device MID is sent with every telemetry event

### 2.7 API Performance Tracking

Every outbound API call is tracked with:
- DNS resolution time
- TCP connection time
- TLS handshake time
- Time to first byte (TTFB)
- Download time
- Success/failure count
- Error kind breakdown
- Retry count
- Endpoint URL (normalized: host + path)

Sent to ARMS every monitoring cycle.

### 2.8 Process Resource Monitoring (continuous, 5-minute intervals)

Collects and reports per role:

| Metric | Granularity |
|---|---|
| CPU usage % | main, renderer, gpu, agent_node, utility_host, all |
| Working set (KB) | Same per-role breakdown |
| Mean / Peak / P95 / sample count | Statistical aggregates |
| Disk read/write rates | System-wide |
| Handle count / thread count | Per-process |
| GDI object count | Windows only |

### 2.9 Data NOT Collected

- **Arbitrary process snapshots** — No system-wide process listing
- **Filesystem contents** — No silent exfiltration of user files. File reads are for AI context only.
- **Crash dumps** — The crash capture system has `uploadToServer: false` by default (local only)
- **Keystrokes / clipboard** — No evidence of keylogging or clipboard monitoring

---

## 3. Network Endpoints

### Telemetry & Analytics
| Endpoint | Purpose | Provider |
|---|---|---|
| `*.aliyuncs.com/rum/web/v2?...` | ARMS RUM data | Alibaba Cloud |
| `https://zcode.z.ai/api/v1/event/report` | Custom analytics events | Z.AI |

### AI Inference
| Endpoint | Purpose | Provider |
|---|---|---|
| `https://api.z.ai` | Z.AI model API | Z.AI |
| `https://api.z.ai/api/anthropic` | Anthropic proxy via Z.AI | Z.AI / Anthropic |
| `https://open.bigmodel.cn/api/anthropic` | Anthropic proxy via Zhipu | Zhipu / Anthropic |
| `https://bigmodel.cn/login` | Zhipu auth | Zhipu |
| `https://chat.z.ai` | Z.AI chat | Z.AI |
| `https://zcode.z.ai` | Main service | Z.AI |
| `wss://zcode.z.ai/ws` | WebSocket | Z.AI |

### Authentication
| Endpoint | Purpose |
|---|---|
| `https://zcode.z.ai/api/v1/oauth/token` | OAuth token exchange |

---

## 4. Privacy Controls

**There are no privacy controls visible in the bundled code.**

- **No telemetry opt-out toggle** in settings
- **No privacy consent dialog** on first launch
- **No data collection disclosure** screen
- **No "anonymous usage data" setting**
- **No GDPR/CCPA-style consent mechanism**

The only related UI strings found are:
- `settings.dataBaseDir*` — Controls where local data files are stored (not what's sent)
- `diagnostics.*` — Diagnostic info display (view-only, no send control)

The ARMS RUM SDK is initialized with the config:
```javascript
{
  perf: true,         // Performance monitoring
  webvitals: true,    // Web vitals tracking
  exception: true,    // Exception tracking
  whiteScreen: true,  // White screen detection
  api: true,          // API performance
  staticResource: true,// Static resource tracking
  click: true,        // Click tracking
  longTask: true      // Long task tracking
}
```
All features enabled, no user-facing toggle.

---

## 5. Supported Inference Providers

ZCode's bundled model catalog (`models_catalog_china_llm_zcode_2026-06-03.json`, schema `zcode.model-providers.v1`) contains **10 providers**, all Chinese:

| Provider ID | Company | Models |
|---|---|---|
| `zai` | Z.AI (Zhipu AI) | 21 |
| `zai-coding-plan` | Z.AI Coding Plan | 21 |
| `bigmodel` | BigModel / 智谱 (Zhipu) | 21 |
| `bigmodel-coding-plan` | BigModel Coding Plan | 21 |
| `deepseek` | DeepSeek | 2 |
| `qwen-alibaba-model-studio-cn` | Qwen / Alibaba Cloud (China) | 6 |
| `qwen-alibaba-model-studio-intl` | Qwen / Alibaba Cloud (Intl) | 6 |
| `moonshot-kimi` | Moonshot AI / Kimi | 8 |
| `minimax` | MiniMax | 8 |
| `xiaomi-mimo` | Xiaomi MiMo | 5 |

Notable **absences** from the catalog: OpenAI, Anthropic, Google, Meta (Llama via any provider).

### Agent Integrations (not inference providers — importable external agents)

ZCode can integrate with these external CLI tools:
- `agent.claudeCode` — Claude Code (Anthropic)
- `agent.codexCli` — Codex CLI (OpenAI)
- `agent.openCode` — OpenCode
- `agent.windsurf` — Windsurf (Codeium)
- `agent.trae` / `agent.traeCn` — Trae (ByteDance)
- `agent.qwenCode` — Qwen Code (Alibaba)
- `agent.continue` — Continue.dev
- `agent.roo` — Roo Code
- `agent.goose` — Goose (Block)
- `agent.augment` — Augment
- `agent.codeBuddy` — CodeBuddy
- `agent.kiroCli` — Kiro CLI
- `agent.qode` / `agent.qodeCn` — Qode

---

## 6. Summary

| Category | Finding |
|---|---|
| **Origin** | Fork of OpenCode's backend/server architecture |
| **UI** | Custom React 19 application, visually inspired by Codex |
| **Telemetry** | Always-on, no opt-out. Sends hardware info, performance data, crashes, network timing, resource usage |
| **Telemetry destination** | Alibaba Cloud ARMS + Z.AI servers (both in China) |
| **Crash dumps** | Local-only by default, can be remotely enabled |
| **File exfiltration** | No evidence of silent scanning. Workspace files are sent to AI providers as part of normal model inference |
| **Default providers** | All Chinese (Z.AI, Zhipu, DeepSeek, Qwen, Moonshot, MiniMax, Xiaomi) |
| **Privacy controls** | None found |
| **Process monitoring** | Self-only (app's own processes), not system-wide |
| **Plugin ABI** | Claude-/Codex-style marketplace (`.zcode-plugin`), **not** `@opencode-ai/plugin` — see §7 |

---

## 7. Plugin ecosystem & ABI research (2026-07-19)

**Goal:** complete the ZCode plugin picture after official docs + 3.3.6 binary exam left the authoring ABI undocumented.

**Sources:**
- Official docs: `https://zcode.z.ai/en/docs/plugin` (end-user Beta marketplace UX; no `plugin.json` schema)
- Public GitHub plugins / marketplaces (sample repos listed below)
- Community reverse-engineering handbook: `ashelylinluo/zcode-plugin-swarm` → `ZCode开发手册.md`
- Community migration notes: `phoben/agent-skills` → `skills/claude-to-zcode/references/zcode-plugin-spec.md`
- Engine-verified notes in `tmdgusya/glm-hammer` README (against `zcode-cli` 0.15.2 / `zcode.cjs`)

### 7.1 Primary samples inspected

| Repo | Role | Why it matters |
|------|------|----------------|
| **[tmdgusya/glm-hammer](https://github.com/tmdgusya/glm-hammer)** | Single-plugin harness | Real hooks (`type: "process"`), skills, agents; engine-verified event list |
| **[jhlee0409/zcode-glm-fleet](https://github.com/jhlee0409/zcode-glm-fleet)** | Third-party **marketplace** | Root `.zcode-plugin/marketplace.json` + multiple `plugins/*/.zcode-plugin/plugin.json` |
| Also useful | `yxhpy/zcode-codex-leader`, `younghai/lazyz`, `WcpDDD/zcode-task-monitor`, `9ycrooked/zcode-plugins` | Dual Claude/Codex/ZCode manifests, MCP/`userConfig`, install provenance (`.zcode-plugin-seed.json`) |

**Other public ZCode plugin-ish repos found (not deep-inspected):** `Sapontop/Zcode-Plugins`, `Maatq1544/agentmemory-zcode-plugin`, `taobaoaz/arkpilot`, `macgaf/rtk-zcode-bridge`, `ricardopera/en-prompt`, `thanhndv212/zcode-opencode-importer` (imports OpenCode **sessions**, not OC npm plugins), etc.

### 7.2 Manifest discovery order

Confirmed across glm-hammer / fleet / handbook:

1. `.zcode-plugin/plugin.json` (**preferred / native**)
2. `.claude-plugin/plugin.json` (Claude Code compat)
3. `.codex-plugin/plugin.json` (Codex compat)

Many repos ship **two or three** manifests so one tree installs on Claude Code, Codex, and ZCode. ZCode priority is native first.

Marketplace catalog file shapes observed:
- `.zcode-plugin/marketplace.json` (glm-hammer, glm-fleet)
- repo-root `marketplace.json` (lazyz, 9ycrooked/zcode-plugins)
- Claude-style `.claude-plugin/marketplace.json` / `.agents/plugins/marketplace.json`

Typical marketplace entry: `{ name, owner, plugins: [{ name, source, description, ... }] }` where `source` is a relative path (`./` or `./plugins/...`).

Install provenance artifact (post-install): `.zcode-plugin-seed.json` with `hash`, `marketplace`, `plugin`, `pluginVersion`, `source` (`filesystem` / …), `version`.

### 7.3 `plugin.json` shape (from live plugins + handbook)

**Required / common metadata:** `name` (regex roughly `^[a-z0-9][a-z0-9._-]{0,127}$`), `version`, `description`, optional `author` / `license` / `homepage` / `repository` / `keywords`.

**Extension-point fields** (relative paths under plugin root):

| Field | Meaning | Executable? |
|-------|---------|-------------|
| `skills` | dir of `*/SKILL.md` | yes |
| `commands` | dir of `*.md` slash commands | yes |
| `hooks` | dir/`hooks.json` **or** inline object/array | yes |
| `mcpServers` | inline map **or** path to `.mcp.json` | yes |
| `agents` | dir of agent `.md` | **often diagnostic / not auto-run**; handbook + glm-hammer say prefer project `.zcode/agents` for real use |
| `lspServers` | LSP defs | **UI/diagnostic-only today** (glm-hammer) |
| `userConfig` | typed settings (`string`/`boolean`/`number` + default/description) | config UI / `${user_config.*}` interpolation |
| `interface` | Codex-ish display metadata | optional |

**Convention:** some plugins omit path fields and rely on auto-discovery of `skills/`, `hooks/`, `commands/` (glm-hammer metadata-only manifest still ships those dirs; zcode-codex-leader ZCode manifest omits `hooks` intentionally so auto-discovered `hooks/hooks.json` is not double-registered).

**Standard layout:**

```text
my-plugin/
├── .zcode-plugin/plugin.json
├── skills/<name>/SKILL.md
├── commands/<name>.md
├── agents/<name>.md          # often display-only
├── hooks/hooks.json
├── hooks/<scripts…>
└── (optional) dist/ for MCP host entrypoints
```

### 7.4 Hooks ABI (Claude-compatible, ZCode engine)

**Exactly 7 events** (glm-hammer engine verification + handbook):

`SessionStart` → `UserPromptSubmit` → `PreToolUse` → `PermissionRequest` → tool → `PostToolUse` | `PostToolUseFailure` → `Stop`

**Not supported:** `SessionEnd`, `PreCompact`, `Notification`, `SubagentStop` (common Claude misconceptions).

Hook entry styles seen in the wild:
- `type: "process"` + `command`/`args`/`timeoutMs`/`statusMessage` (glm-hammer; preferred cross-platform)
- `type: "command"` + shell string (task-monitor, codex-leader; often still uses `${CLAUDE_PLUGIN_ROOT}`)

Matchers: case-sensitive regex; tool-name aliases like `Write`/`Edit` ← `ApplyPatch` noted by glm-hammer.

I/O contract: stdin JSON (`session_id`, `cwd`, `hook_event_name`, …); stdout must be a **strict schema** (extra keys fail). Typical outputs: `additionalContext`, Stop `decision`/`reason`, PreToolUse `permissionDecision` / `updatedInput`.

Env substitution (dual prefix; ZCode does **not** shell out to Claude Code):

| Preferred | Compat |
|-----------|--------|
| `${ZCODE_PLUGIN_ROOT}` | `${CLAUDE_PLUGIN_ROOT}` |
| `${ZCODE_PROJECT_DIR}` | `${CLAUDE_PROJECT_DIR}` |
| `${ZCODE_SESSION_ID}` | `${CLAUDE_SESSION_ID}` |
| `${user_config.<key>}` | — |

Runtime paths (handbook / installers):
- Registry: `~/.zcode/cli/config.json` (`plugins` map)
- Cache: `~/.zcode/cli/plugins/cache/`
- Marketplaces: `~/.zcode/cli/plugins/marketplaces/`
- Engine artifact (read-only): `ZCode.app/.../Resources/glm/zcode.cjs`
- Session DB used by some plugins: `~/.zcode/cli/db/db.sqlite`

### 7.5 What official docs add vs repos

Docs confirm: Beta marketplace; components Skill / Command / Agent / MCP / Hook / LSP; custom sources = GitHub `owner/repo`, Git URL, or local path; built-ins `document-skills`, `skill-creator`, `android-emulator`, `ios-simulator`, `restore-legacy-sessions`; plugin config under Advanced info.

Docs **still omit** `plugin.json` schema, hook event list, and install cache layout — those come from community plugins + handbook.

### 7.6 How ZCode’s plugin system differs from OpenCode / MiMo / Kilo

OpenCode, MiMo, and Kilo share one plugin class: **in-process npm packages** that import `@opencode-ai/plugin` (or Kilo’s equivalent) and register TypeScript hooks inside the host.

ZCode’s marketplace is a different class — closer to Claude Code / Codex: a **directory of markdown skills/commands plus subprocess hooks**, declared in `.zcode-plugin/plugin.json`.

| Dimension | OpenCode / MiMo / Kilo | ZCode |
|-----------|------------------------|-------|
| Package unit | npm package | Git/local marketplace plugin dir |
| Manifest | `package.json` + TS `Hooks` / v2 kit | `.zcode-plugin/plugin.json` |
| Hooks | in-process classic/v2 API | subprocess Claude-style event hooks |
| Skills/commands | secondary / parallel config surface | first-class markdown components |
| Host openness | open CLI (MiMo/Kilo are OpenCode-class forks) | closed Electron + `zcode.cjs` |

**Comparison takeaway:** ZCode does **not** load OpenCode npm plugins. Its public plugins show a Claude-/Codex-adjacent marketplace, not OpenCode-class plugin compatibility. LazyZ even audits **against** `@opencode-ai/*` imports in vendored harness code.

ZCode can still **import** some OpenCode *assets* (skills, commands, MCP config from `opencode.json`) via its UI — that is migration of files/config, not shared plugin runtime. Details in §8–§9.

### 7.7 Sample manifests (abbreviated)

**glm-hammer** (metadata + conventional dirs; hooks in `hooks/hooks.json`):

```json
{
  "name": "glm-hammer",
  "version": "0.6.0",
  "description": "Forge-and-hammer engineering harness…",
  "repository": "https://github.com/tmdgusya/glm-hammer"
}
```

**glm-fleet plugin** (explicit paths):

```json
{
  "name": "glm-verify-spine",
  "version": "0.1.0",
  "skills": "skills",
  "hooks": "hooks"
}
```

**Marketplace** (`jhlee0409/zcode-glm-fleet`):

```json
{
  "name": "zcode-glm-fleet",
  "plugins": [
    { "name": "glm-design-fleet", "source": "./plugins/glm-design-fleet" },
    { "name": "glm-verify-spine", "source": "./plugins/glm-verify-spine" }
  ]
}
```

---

## 8. Plugin runtime vs OpenCode / MiMo / Kilo (2026-07-19)

**Comparison question:** Does ZCode share OpenCode’s `@opencode-ai/plugin` runtime the way MiMo and Kilo do — or did it drop that and keep something else?

**Finding:** Across **3.3.3 and 3.3.6**, ZCode never ships an in-process OpenCode npm plugin loader. The “Legacy plugin management has been retired” message is about an old **desktop-host marketplace management IPC** (Claude-/Codex-style), not OpenCode plugins. MiMo/Kilo remain OpenCode-class hosts; ZCode does not.

### 8.1 What “Legacy plugin management has been retired” actually is

In `@zcode/desktop` `out/host/index.js` (both 3.3.3 and 3.3.6):

- `createPluginsService` → stub
- `getOverview` returns empty lists + `capability: { supported: false }` (`createRetiredOverview`)
- mutators (`addMarketplace`, `installPlugin`, `setPluginEnabled`, …) throw
  **`Legacy plugin management has been retired in ZCode Agent mode`**

That API shape (marketplaces / available / installed) matches **Claude-/Codex-style marketplace management**, not `@opencode-ai/plugin`. Agent-mode marketplace loading remains **live** in `Resources/glm/zcode.cjs` (`.zcode-plugin` / `.claude-plugin` / `.codex-plugin` / even `.cursor-plugin` manifest discovery; subprocess hooks).

### 8.2 3.3.3 → 3.3.6 delta (plugin-relevant)

| Signal | 3.3.3 | 3.3.6 |
|--------|-------|-------|
| Retired `createPluginsService` stub | yes | yes |
| `importPluginsForAgent` / OpenCode path table | yes | yes |
| Host `marketplace.json` string refs | 0 | 4 (host sync/marketplace helpers grew) |
| `@opencode-ai/plugin` / `.opencode/plugins` **loader** | **0** | **0** |
| `zcode.cjs` `@opencode-ai/` | n/a (same engine family) | **0** |

OpenCode mentions in host are **agent config / provider / import** surfaces (`opencode.json`, skills/commands/plugins **import roots**, Zen `OPENCODE_API_KEY` provider env in engine) — not an npm plugin runtime.

### 8.3 The misleading `.opencode/plugins` importer

Host **does** scan OpenCode-looking plugin directories for **manual import**:

- project: `.opencode/plugins`
- global: `~/.config/opencode/plugins`

…via `getExternalPluginRoots` → `collectPluginPaths` → `importPluginsForAgent`.

But `findPluginManifestPath` only accepts:

1. `.zcode-plugin/plugin.json`
2. `.claude-plugin/plugin.json`
3. `.codex-plugin/plugin.json`

It does **not** accept OpenCode npm packages (`package.json` + `import "@opencode-ai/plugin"`). So this is a **path convenience** for Claude-/Codex-/ZCode marketplace trees that happen to live under OpenCode directories — **not** support for OpenCode’s npm plugin API. Import copies/symlinks into ZCode plugin dirs and registers `plugins.dirs` in ZCode config.

Parallel importers exist for OpenCode **skills**, **commands**, and **MCP** from `opencode.json` — again config/asset migration, not in-process OC hooks.

### 8.4 Side-by-side with OpenCode-class hosts

| Capability | OpenCode / MiMo / Kilo | ZCode |
|------------|------------------------|-------|
| Install / run `@opencode-ai/plugin` (or Kilo-shaped) npm packages | Yes | **No** |
| Load OpenCode-format local plugins under `.opencode` | Yes | Manual import only accepts marketplace manifests (`.zcode-plugin` / `.claude-plugin` / `.codex-plugin`) |
| Classic / v2 in-process plugin provider API | Yes | **No** |
| Claude-/Codex-style marketplace plugins | Not the primary model | **Yes** (live in `zcode.cjs`) |
| Import OpenCode skills / commands / MCP config | N/A (native) | Yes (manual UI) — files/config only |

**Punchline for cross-product comparison:** OpenCode, MiMo, and Kilo are one plugin ecosystem. ZCode is another. Shared branding / `opencode.json` import paths do not mean shared plugin ABI.

Optional historical note: a pre–Agent-mode build (research base mentioned 3.2.5) was not found on public CDNs (`cdn.codegeex.cn` / `cdn.zcode-ai.com` `…/electron/releases` lacked `latest-mac.yml`). Even if an older desktop PluginsService was richer, evidence still points at marketplace ABI, not `@opencode-ai/plugin`.

---

## 9. What actually ports between OpenCode and ZCode (2026-07-19)

**Comparison question:** If someone uses OpenCode (or MiMo/Kilo) and also ZCode, what moves across — and what does not?

**Finding:** ZCode’s built-in importer can bring over **markdown skills, commands, and MCP server config**. It cannot bring over **in-process OpenCode npm plugins** (hooks/tools/auth/TUI). That gap is structural, not a missing checkbox.

### 9.1 What ZCode’s importer already moves (manual UI only)

Host settings-sync import pipeline (`intent === "manualImport"`), categories: `skills` | `commands` | `plugins` | `mcpServers`.

| Category | OpenCode roots scanned | Acceptance / transform | Install action |
|----------|------------------------|------------------------|----------------|
| **Skills** | project `.opencode/skills`; global `~/.config/opencode/skills` | dirs/`SKILL.md`-style discovery (same family as Claude) | symlink/copy into ZCode skill target roots |
| **Commands** | `.opencode/commands`; `~/.config/opencode/commands` | markdown command files | symlink/copy into ZCode command roots |
| **Plugins** | `.opencode/plugins`; `~/.config/opencode/plugins` | **only** if child dir has `.zcode-plugin` / `.claude-plugin` / `.codex-plugin` `plugin.json` | copy/symlink + append `plugins.dirs` in ZCode config |
| **MCP** | `.opencode/opencode.json`; `~/.config/opencode/opencode.json` (`format: "mcpJson"`) | read `mcp` map; `nge()` rewrites OC `command: string[]` + `type: "local"|"remote"` → ZCode `command`/`args` + `type: "stdio"|"http"`; strips some timeout fields | merge into ZCode `mcp.servers` |

**Not imported:** npm package entrypoints, classic `Hooks`, `v2/promise` / `v2/effect` registration, custom `tool()` definitions, auth/provider hooks, TUI plugins.

Gate: discovery/import runs only for **manualImport** + selected categories — not an always-on dual-scan of OC npm plugins.

### 9.2 Format overlap (why skills/commands often move)

**Skills:** Both ecosystems use Claude-ish `skills/<name>/SKILL.md` with YAML `name` + `description`. OpenCode also allows flat `*.md` and optional `slash` frontmatter (`packages/core/src/skill.ts`). ZCode handbook: **only** `name` + `description` are supported; extra Claude/OC fields are ignored or should be stripped.

**Commands:** OpenCode loads `{command,commands}/**/*.md` with frontmatter → `template` = body (`ConfigCommand.Info`: `name`, `template`, optional `description`, `agent`, `model`, `subtask`). ZCode commands are markdown slash commands; richer OC fields (`model` / `agent` / `subtask`) are **not** portable 1:1 — body + description are the safe subset.

**MCP:** Structural mapping already exists in-product (`tge`/`nge`). Local argv arrays and remote URLs are the main cases; exotic OC MCP shapes may still need hand fixes.

### 9.3 Portability matrix (comparison)

OpenCode “plugins” in `opencode.json` are primarily **in-process JS modules** (`Plugin` → `Hooks`). Filesystem skills/commands are a **parallel** config surface. MiMo/Kilo keep that in-process plugin model; ZCode only overlaps on the filesystem/MCP side.

| OpenCode / MiMo / Kilo surface | Moves to ZCode? |
|--------------------------------|-----------------|
| Repo/user `SKILL.md` trees | Yes (good fit) |
| Repo/user command `*.md` | Yes (subset of frontmatter) |
| `opencode.json` `mcp` | Yes (mostly done in-app) |
| npm plugin that only registers hooks/tools/auth | **No** |
| npm plugin that also vendors `skills/` / `commands/` | Partial (files only) |
| v2 programmatic skill/command drafts | **No** (requires running host) |
| Rewrite of classic/v2 hooks → ZCode subprocess `hooks.json` | **Not equivalent** (different event model, I/O, capabilities) |

**Comparison takeaway:** Across products, markdown skills/commands/MCP are the shared-ish layer. The OpenCode/MiMo/Kilo **plugin ABI** stops at ZCode’s door.

### 9.4 Live case study — this machine’s OpenCode config (2026-07-19)

Verified against `~/.config/opencode/opencode.json` + sibling dirs (secrets intentionally omitted from notes):

| Asset | Present? | ZCode Import outcome |
|-------|----------|----------------------|
| `skills/` (global) | **Missing** | Nothing to import |
| `commands/` (global) | **Missing** | Nothing to import |
| `plugins/` (global) | **Missing** | No marketplace trees under OC plugin roots |
| `mcp` map | **Yes** — mix of `type: "local"` (argv) and `type: "remote"` (URL + headers); several `enabled: false` | **Good fit** for in-app MCP import (`mcpJson` / `nge()`) |
| `plugin[]` | **Yes** — one absolute path to `cursor-opencode-provider` `dist/index.js` | **Does not move** — classic/v2 `Hooks` provider plugin; no `skills/` / `commands/` / `.zcode-plugin` in that package |

**Punchline for this workstation:** the only registered OpenCode “plugin” is exactly the class that does not port to ZCode. MCP servers would import; no global markdown skills/commands existed to move.