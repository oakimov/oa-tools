# DeepSeek Harness — Research Summary

**Date:** 2026-08-15 (checkout at `0.1.0-rc.5`, `47f943859`; npm already at `0.1.0-rc.6`)
**Source:** https://github.com/deepseek-ai/deepseek-harness (`master`)
**Related repos:** https://github.com/cordiverse/cordis (upstream framework), https://github.com/cordiverse/paper, https://github.com/deepseek-harness/cordis, https://github.com/deepseek-harness/cosmokit, https://github.com/deepseek-harness/schemastery (managed forks), https://github.com/huoyaoyuan/windows-acl-restrict-poc (sandbox mechanism), https://github.com/microsoft/mxc (rejected sandbox option)
**Product page:** https://deepseek.com/harness · Community: GitHub Discussions + Discord
**Position vs the reviewed family:** OpenCode, MiMo, Kilo, ZCode, CoStrict are coding agents (CLIs/IDEs) that run model inference against hosted APIs. dsh is a **plugin-host agent harness framework** — Web UI + headless runner + automation servers + Python SDK + plugin authoring, released as a pre-1.0 developer preview (**"THERE WILL BE COMPATIBILITY-BREAKING CHANGES"** — README).

---

## 1. Relationship to the reviewed products

**dsh is not a fork.** It shares no runtime code with OpenCode (Effect/Hono/OpenTUI), Kilo/MiMo (OpenCode forks), ZCode (OpenCode backend fork), or CoStrict (Roo fork). It is an independent product by DeepSeek AI on a different framework (Cordis), in the same *product category* (agent harness with Web UI, headless run, plugin system, sandboxing, telemetry).

| Dimension | OpenCode-class (OC / MiMo / Kilo) | ZCode | CoStrict | **dsh** |
|---|---|---|---|---|
| **Lineage** | OpenCode (anomalyco) + forks | OpenCode backend fork | Cline → Roo fork | **Independent; Cordis-based** |
| **Host language** | TypeScript (Bun) | TypeScript (Electron) | TypeScript (VS Code ext) | **TypeScript (Node ≥ 22.19, pnpm)** |
| **Framework** | Homegrown core | OpenCode core | Roo core | **Cordis 4.0.0-rc.7 (vendored + patched)** |
| **Plugin model** | In-process npm (`@opencode-ai/plugin`) | Claude/Codex-style marketplace (`.zcode-plugin`) | Roo/Claude skills | **Cordis npm plugins** (services/events/effects) + Claude Code & Codex **hook bridges** |
| **Cleanest self-description** | TUI agent | Desktop agent | Strict enterprise coder | **"Everything is a Plugin"** |
| **Sandbox** | Permission prompts (no OS confinement) | n/a in review (no OS sandbox documented) | Workspace Trust (opt-in) | **OS-enforced defaults on Linux/macOS/Windows** |
| **Telemetry default** | Kilo PostHog on; MiMo metrics client on; OC opt-in-ish | Always-on (China) | PostHog + server channel on | **OFF (opt-in env)** |
| **Release state** | GA | GA | GA | **developer preview (rc line)** |

The "plugin host" comparison that matters: dsh's in-process TypeScript plugin runtime is the same *family* as OpenCode/MiMo/Kilo (npm packages registering typed hooks in-process) and the opposite of ZCode's subprocess marketplace and CoStrict's Roo skills — but the ABI is Cordis's (services, typed events, reversible effects), not `@opencode-ai/plugin`.

---

## 2. Timeline & launch data (as of 2026-08-15)

| Fact | Value |
|---|---|
| Public repo created | 2026-08-13 (mirror; GitHub Issues/PRs **disabled** — community via Discussions + Discord) |
| Git history begins | 2026-06-10 → **~2 months of pre-public, agent-driven development** |
| Commits at review | **12,293**; merge history references PR numbers up to ~#2521 (internal review flow before the mirror) |
| Stars / forks | **~114k / ~11k within ~2 days** of public launch (checked 2026-08-15) |
| Version | repo `0.1.0-rc.5`; npm already published `0.1.0-rc.6` (`@deepseek-ai/dsh`) |
| License | MIT; `THIRD_PARTY_NOTICES.md` generated |
| Topics | `ai-agents`, `cordis`, `dsh`, `dsh-plugin` |
| Top commit authors | Tianyi Cui (5,235), Yichen Jiang (1,361), imccyu (1,297), Chinesezjc (587), Turtle (585), Hypatia May (478), _Kerman (477), creatixchu (457) — heavy multi-agent development cadence |

---

## 3. Architecture — "everything is a plugin"

Design premise from the paper [*A Programming Paradigm for Spatiotemporal Composability*](https://github.com/cordiverse/paper) (cordiverse): plugins contribute **services, typed events, and reversible effects** to a shared context; registrations are effects that unwind on unload. There is *no privileged core*: the model adapter, tool registry, session store, approval policy, settings, credentials, and telemetry are all plugins. Any behavior can be replaced from configuration.

### Key primitives

| Primitive | Meaning |
|---|---|
| **Profile** | Named composition under the harness home (`$DSH_HOME/profiles/<name>`) — ordered bundle stack + user `cordis.patch.yml` + home patch + `--patch` overlays |
| **Bundle** | Distribution format: `cordis.patch.yml` + code (npm packages). `dsh-base` is the first layer of every profile; `dsh-web-app` / `dsh-headless` specialize it |
| **Seam** | Swappable capability with three roles: **Service Definition** (interface) / **Service Provider** (impl) / **Consumer** (usually a model-facing tool). Swap the provider → the whole capability moves (e.g. FS + Bash + PTY + LSP point at one sandbox) |
| **Session log** | Append-only `SessionEvent` stream: the model-visible source of truth. "Model-visible means logged" — a runtime invariant; fork/resume/telemetry/persistence all derive from it |
| **Turn / step** | step = one model request + its tool calls; turn = zero or more steps with a durable start/end |

### Event domains

- **Session events** (`turn/*`, `step/*`, `user/message`, `assistant/*`, `tool/*`) — durable, replayed.
- **Agent events** (`agent/*`) — live observations/interceptions carrying the live `Agent`.
- **Capability events** (`fs/*`, `tools/*`, `telemetry/*`) — attach policy/adapters to seams without importing the loop.

### Configuration model

YAML `cordis.yml` rows are patched by id in layer order; a patch replaces a row's *whole* config (no deep merge). Expressions like `!!js` evaluate lazily (e.g. `disabled: !!js process.platform === 'win32'` selects the bash-vs-pwsh shell stack per platform; `mode: !!js process.env.DSH_TELEMETRY_MODE || 'DISABLED'`). `dsh --profile web --dump-config` prints the exact booted tree — every row is patchable by the user.

---

## 4. The plugin model

### 4.1 Cordis plugins (first-class)

- npm packages declaring a `name`/`inject`/`apply` namespace plugin (or service plugins); context key via `ctx.<key>`; typed events via declaration merging.
- Discovery/lifecycle: renders, HMR, loader/include/group — all vendored from Cordis, with DeepSeek's own hardening (transactional config reconciliation, lazy config resolution, durable write retries, teardown races fixed — documented as a 18-point local-modification log in the vendor README).
- Authoring docs: full bilingual tutorial, plugin cookbook, "add a package/tool/LLM adapter/conversation node" guides, and a `dsh-plugin` GitHub topic for discoverability.

### 4.2 Claude Code / Codex compatibility bridges

`dsh-hooks-claude-code` / `dsh-hooks-codex` run a **command-hook subset** of existing `hooks.json` configs on the harness's canonical interception points, with per-event stdin payloads, `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PROJECT_DIR}` (and Codex equivalents) substitution, and typed decision mapping. The README is explicit: a native Cordis plugin can do everything the bridge does, more powerfully; the bridge exists purely as a migration path. (Adoption path — not a compatibility parity layer.)

### 4.3 Self-modification (demonstration, not default)

`examples/web-cordis` + `@deepseek-ai/dsh-tool-cordis`: five model-facing tools (`cordis_inspect/define/run/stop/undefine`) that let the agent **inspect the live runtime and mount/unmount model-authored plugins in memory** via a `vm` sandbox. Explicit trust stance: "The sandbox isolates globals but is not a security boundary … Treat this toolset like bash access." Session-scoped, dies with the process, never writes config — a research demo (demo command), not part of the shipped default bundles.

### 4.4 Plugin-host comparison vs the reviewed family

| | OC / MiMo / Kilo | ZCode | CoStrict | **dsh** |
|---|---|---|---|---|
| Runtime ABI | `@opencode-ai/plugin` in-process | `.zcode-plugin` marketplace, subprocess | Roo skills/modes | **Cordis in-process** (+ hook bridges) |
| Extension points | classic/v2 hooks | 7 Claude-style events | modes/skills | typed events + services + effects (richest surface) |
| Hot-reload | plugin dir watch | marketplace install | extension reload | **HMR incl. transactional config reload, per-fiber** |
| Reversibility | unload | — | — | **registrations are effects; unload unwinds** |
| Model-visible introspection | — | — | — | `cordis_inspect` + generated catalogs teach the model the live API |

---

## 5. Monorepo map (219 `@deepseek-ai/dsh-*` packages + vendored framework)

- **`packages/core/*`** — session (event-sourced store), system-prompt, tools (registry + guarded pipeline), agent, agent-loop, scope.
- **`packages/<capability>/*`** — llm (+ `llm-deepseek`, `llm-pi-ai`, `token-meter`), web (search/fetch providers + tools), shell (bash/pwsh + sandbox wraps), subprocess, terminal, fs, lsp, skill, e2b, mcp-client, compaction, subagent (incl. `subagent-acp`, `subagent-claude-code`), workflow, todo, plan, goal, jobs, schedule, spill, hooks, context.
- **`packages/security/*`** — sandbox seam + `sandbox-local` (platform runners), `sandbox-policy` (mode/root resolution), `sandbox-windows-acl` (win32 rung), permission-presets, user-approval, tool-ask-user, credentials, settings, guard (loop hygiene + tool timeouts).
- **`packages/platform/*`** — session (telemetry, projection, titles), identity (anonymous UUID), api gateway (`api/gateway`, `api/remotes`), host (`apiproxy`, webserver), client (React 18 web client modules `client/*`), sdk (JSON-RPC server + TS client), acp (Agent Client Protocol server), boot, bundle (`base`/`web-app`/`headless`), typert (type-graph generator + runtime registry), typert protocol/gateway for `@Remote` method calls.
- **`vendor/`** — Cordis family vendored at pinned commits and **rescoped to `@deepseek-ai/*`** (published with the harness): `cordis` 4.0.0-rc.7, `cosmokit`, `schemastery`, loader/include/group/timer/hmr/logger-console. Fork copies live at `deepseek-harness/cordis` and `deepseek-harness/cosmokit`; every divergence from upstream is logged (18 entries incl. transactionality and lifecycle-hardening fixes).
- **`native/landlock-run`** — `@deepseek-ai/node-addon-landlock-run` C++ launcher (Landlock restriction) + platform packages (npm optional deps).
- **`python/`** — `deepseek-harness-sdk` (`deepseek_harness`, PyPI) driving a bundled runtime (`deepseek-harness-runtime-bin`) over newline-delimited JSON-RPC on stdio; CI builds a packaged exe/runtime for the SDK.
- **`apps/`** — `cli` (the `dsh` launcher: `--profile web|headless`, `dsh plugin`), `web` (Vite/React 18 frontend).
- **`examples/`** — runnable leaves: `headless-agent`, `jsonrpc-agent`, `acp-agent`, `mcp-memory`, `web-cordis`, `web-schedule`.
- **`docs/`** — architecture, catalogs, cookbook, postmortems, agent-lifecycle diagrams; all bilingual (en/zh pairs gated by `verify-translation-pairing`). Generated catalogs (`config-catalog`, `tool-catalog`, `event-producer-consumer`, `module-graph`, `persistence-catalog`, `cordis-api`) are freshness-gated — docs cannot drift from code.
- **`.agents/`** — agent workflows: skills (code review, pre-push checks, stacked-PR merging, doc-sync, translation, archive agent notes, …) and **Agent Notes** (`implemented/{architecture,feature,process,…}`, `proposed`, `rejected`, `archived`) — the design-record system (hundreds of notes; >500 feature + >380 architecture notes in the implemented set at review time). Every notable decision links to its note.

---

## 6. Security architecture

The strongest security posture of the six reviewed products — **OS-enforced containment is the shipped default**, not an opt-in hardening feature.

| Mechanism | Platform | Detail |
|---|---|---|
| **runners (chained)** | Linux | prefers working `bwrap`, else **Landlock** via the native addon; Landlock partial-ABI cases report `enforcement: 'partial'`, never overclaimed |
| **Seatbelt** | macOS | `sandbox-exec` profile, allow-default with `(deny file-write*)` + explicit write allow-lists (workspace, `/tmp`, per-user temp); canonicalized roots; functional probe fails closed (`SANDBOX_UNAVAILABLE`) |
| **Restricted-token ACL** | Windows | Node/koffi port of `windows-acl-restrict-poc`: `WRITE_RESTRICTED` token where deterministic workspace SID + random per-session temp SID gate writes; reports `partial` honestly (Everyone inheritance, hard links); rejects workspace over the temp root |
| **Fail-closed** | all | Unsupported platform/unusable runner → `SANDBOX_UNAVAILABLE`; execution never silently falls through unconfined |
| **Permissions** | all | Shipped defaults: `sandbox-policy.mode = workspace-write` (env `DSH_PERMISSION_MODE` can switch to `read-only`/`danger-full-access`), approval `ask` (→ `never` only in danger-full-access). Presets: `read-only`, `workspace-write`, `danger-full-access`, switchable per session, logged as durable events |
| **Policy prompt** | model | Each request sees the current mode + workspace root (`sandbox:policy` context contribution); the loop logs the full runtime-context snapshot as a sourced message |
| **Spill seam** | all | oversized tool outputs go to private (0700) random-named files (`spill-local`) with opaque branded locators; reads not authorized by storage (backend contract) |
| **Env scrubbing** | all | spawned commands drop `*KEY*/*SECRET*/*TOKEN*/*PASSWORD*`; temp files `'wx'`/`0o600`, symlink-safe unlink discipline (documented "defensive patterns") |
| **Credentials** | all | `credentials` capability: env/`.env` references resolved per request — no secret in config files |
| **E2B** | opt-in | `e2b` POC package + CI workflow: remote Linux sandbox (disposable, per-sandbox HOME), FS/Subprocess adapters inhabit the same remote world |

Context: OpenCode/MiMo/Kilo gate writes by prompt only; CoStrict's Workspace Trust is opt-in for MCP/custom tools; ZCode was not assessed for OS sandboxing in its review. dsh enforces file effects at the OS layer before a model can act.

---

## 7. Telemetry, network & privacy

**This is the only product of the six reviewed whose telemetry export is off by default.** Telemetry is a plugin like everything else.

### 7.1 The seam and its modes

`dsh-session-telemetry` defines the `SessionTelemetrySink` contract + a capture coordinator; `dsh-session-telemetry-otel` is the (only) backend. Sharing status is disclosed to the user on every `/feedback` acknowledgement: `full` | `feedback-only` | `disabled`.

- **`DSH_TELEMETRY_MODE`** — `FULL` (every record, immediately), `FEEDBACK_ONLY` (nothing leaves until a `feedback/record` event releases the session-log prefix — feedback-as-consent), unset/anything else → **`DISABLED`** (no SDK pipeline constructed at all).
- **`DSH_TELEMETRY_DISABLED`** — any value including `0`/`false` → patches the row off process-wide ("config cannot disable a row").
- Default endpoint when an uploading mode is chosen: **`https://harness-telemetry.deepseeksvc.com/v1/logs`** (OTLP/HTTP, gzip), overridable via `DSH_TELEMETRY_OTLP_URL`.
- Uploaded records = complete deep-copied `event.data`: user/assistant text, tool arguments **and results (command output, file contents)**, full system prompt + tool schemas, todos, compaction summaries, hook stderr, and the session `cwd` (a local path).
- **No built-in redaction rules**: the `session-telemetry/record` waterfall ships empty; without a mounted rule, exports are the raw captured copy (README warns of exactly this). Fail-closed per record — a throwing rule withholds that one record.

### 7.2 What is structurally absent

- **Provider credentials never appear** — adapter API keys are constructor parameters, not session events, so they cannot be in the log or the exports.
- **No crash dumps, no system-wide process data, no keystrokes/clipboard** — telemetry vocabulary is the session log + operational markers (`agent-error`, `shutdown`); crash detection is *inference* from a missing `shutdown` marker in FULL mode.

### 7.3 Identity

- Per-harness-home anonymous UUID at `$DSH_HOME/.anonymous-user-id` (random v4; delete to reset; never derived from hostname/address/git).
- Reported to OTel as Resource `user.id` **and to DeepSeek's own model API as the `x-deepseek-harness-user-id` header on every request** (via `dsh-llm-deepseek`), independent of telemetry mode. Explicitly documented. Everything else (endpoints, keys) is user-configured.

### 7.4 Network endpoints (defaults at review time)

| Endpoint | Purpose | When |
|---|---|---|
| `https://api.deepseek.com/chat/completions` | DeepSeek model API (default provider; key required) | user runs a session |
| any OpenAI-compatible base URL | custom providers (`llm-pi-ai` route config) | user-configured |
| `https://harness-telemetry.deepseeksvc.com/v1/logs` | OTLP logs | **only if** `DSH_TELEMETRY_MODE` set to an uploading mode |
| `http://127.0.0.1:3080` | Web UI (localhost) | `dsh web` |
| stdio JSON-RPC / ACP | headless, Python SDK, automation | local processes |

### 7.5 Privacy controls — and lack of them

Controls: env-var opt-out that cannot be overridden by config; per-mode disclosure in the feedback UI; anonymous identity that resets by file deletion; all provider endpoints user-specified (no mandatory cloud account — headless runs on `DEEPSEEK_API_KEY` alone). Gaps: no built-in redaction rules (deployment must mount them); the DeepSeek-provider identity header is always-on when talking to DeepSeek; telemetry config is env-file level, not a Settings toggle in the Web UI.

---

## 8. Providers & model channel

| Provider | Detail |
|---|---|
| `llm-deepseek` | Default adapter; `PUBLIC_BASE_URL = https://api.deepseek.com`; key from env/credentials; sends `x-deepseek-harness-user-id` header |
| `llm-pi-ai` | Generic multi-provider adapter built on `@earendil-works/pi-ai` — provider profiles keyed by route; inherits a catalog's endpoint/protocol or declares its own (OpenAI-compatible gateway, self-hosted server); credential references per route |
| Others | no bundled Google/Anthropic/OpenAI entry-point plugins; any OpenAI-compatible endpoint is reachable through pi-ai routing — BYO-key model, no cloud account or login needed |

---

## 9. Product surfaces

| Surface | Entry point | Notes |
|---|---|---|
| **Web UI** | `npx @deepseek-ai/dsh web` (port 3080) | workspace picker, model settings, permission switcher, sessions, plugins inventory, settings via `$DSH_HOME/settings.yaml` hot-reload |
| **Headless** | `dsh --profile headless "task"` | one fresh persisted session, final answer, exit; CI-friendly |
| **ACP server** | `dsh-acp` | Agent Client Protocol over JSON-RPC stdio (automation-only; permission answers policy-resolvable) |
| **JSON-RPC server + TS client** | `dsh-sdk` | programmatic control of the harness |
| **Python SDK** | PyPI `deepseek-harness-sdk` (+ `deepseek-harness-runtime-bin` with bundled runtime binaries) | drives the harness as a subprocess over stdio JSON-RPC; turns API |
| **API gateway** | Typert + `api/remotes` | `@Remote`/`@RemoteScope` method contracts generated from type graphs for the web client (host/client build split) |
| **Demo surfaces** | `web-cordis` (self-modifying plugins, port 3081), `web-schedule`, `mcp-memory` | show capability seams; need `DEEPSEEK_API_KEY` |

---

## 10. Engineering posture

- **Agents are first-class contributors**: AGENTS.md-driven, CLAUDE.md symlink, agent skills for review/PR-stack/doc gates, Agent Notes as the design record (proposed → implemented with dates; rejected/archived trails), postmortems (`docs/postmortem/0001…0004`), and CI that reviews agent-written docs.
- **Verification machinery**: ~35 `verify-*`/`gen-*` gates (catalogs, docs, module graphs, i18n pairing, vendored links, package invariants, config ownership), jscpd duplication gate, knip+publint+constraints "hygiene" gate, **per-file 100% branch/line coverage gate** (`test:coverage` in CI, not the ordinary suite), keyless snapshot-replay tests (`vitest.snapshot`), real-API e2e gated on `DEEPSEEK_API_KEY`, Windows coverage through Wine CI, and a release pipeline that verifies packed installs and npm baselines.
- **Bilingual docs** (English + Chinese with `.i18n.yaml` pairing files; machine-translation gates; VitePress site) — the only deeply bilingual product in the reviewed set besides ZCode's Chinese-first UI.
- **Docs cannot drift**: generated catalogs + JSDoc-extracted API reference are gated; "docs are the deliverable" is enforced by `dsh-doc-sync`.

---

## 11. Summary

| Category | Finding |
|---|---|
| **Origin** | Independent, from-scratch; Cordis-powered; no code shared with the OpenCode family |
| **Framework** | Vendored, rescoped, and **hardened** Cordis (documented 18-divergence log; transactional loader; HMR with config rollback) |
| **Plugin model** | Cordis in-process npm plugins (services/events/effects) + Claude/Codex hook-config bridges; self-modification demo; richest extension surface of the six, no marketplace ABI yet |
| **Sandbox** | OS-enforced on Linux (bwrap→Landlock), macOS (Seatbelt), Windows (restricted-token ACL); default workspace-write + ask; fail-closed |
| **Telemetry** | **Off by default**; opt-in `FULL`/`FEEDBACK_ONLY` via env; no default redaction rules; anonymous per-home UUID reaching DeepSeek API as a header regardless |
| **Providers** | DeepSeek API default + pi-ai multi-provider routing; BYO key; no cloud account required |
| **Product state** | Developer preview (rc line on npm); breaking changes promised; ~114k stars in 2 days; Issues/PRs off on GitHub (Discussions + Discord) |
| **Process** | Agent-note design records, ~35 doc/code gates, per-file 100% coverage, bilingual en/zh docs, postmortems — an unusually discipline-heavy young codebase |
| **Posture vs family** | Not a fork like MiMo/Kilo/ZCode/CoStrict, not an OpenCode-ecosystem peer; a DeepSeek-native framework with the most distinctive defaults (sandbox on, telemetry off) and the most explicit "we will break you" cadence |