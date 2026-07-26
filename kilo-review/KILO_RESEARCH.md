# Kilo Code vs OpenCode — Research Summary

**Date:** 2026-07-19  
**Sources:**
- OpenCode: https://github.com/anomalyco/opencode
- Kilo Code: https://github.com/Kilo-Org/kilocode (`main`, CLI version line **7.4.11**, `.opencode-version` **v1.17.4**)
- Docs / product: https://kilo.ai , legacy tree https://github.com/Kilo-Org/kilocode-legacy
**Kilo claim (README FAQ):** “Kilo CLI is a fork of OpenCode, enhanced to work within the Kilo agentic engineering platform.”

---

## 1. Relationship at a Glance

| | OpenCode | Kilo Code |
|---|---|---|
| **Org** | anomalyco | Kilo-Org |
| **Repo** | github.com/anomalyco/opencode | github.com/Kilo-Org/kilocode |
| **Stars (approx.)** | ~187k | ~26k |
| **Created** | 2025-04 | 2025-03-10 (extension era); OpenCode-based monorepo rebuild later |
| **License** | MIT | MIT (legacy extension tree was Apache-2.0) |
| **CLI binary** | `opencode` | `kilo` / `kilocode` (`@kilocode/cli`) |
| **Config home** | `.opencode/` / `~/.config/opencode` | `.kilo/` / `.kilocode/` / `~/.config/kilo` (no OpenCode dir fallback) |
| **Package scope** | `@opencode-ai/*` | `@kilocode/*` (shared tree still imports `@opencode-ai/core` etc. in places) |
| **Primary UX** | TUI + growing desktop/web | **VS Code + JetBrains + CLI + Cloud** (multi-client, one `kilo serve` backend) |
| **Default model channel** | BYO / many providers | Kilo Gateway (`api.kilo.ai`, OpenRouter-shaped) + BYO; default model id `kilo-auto/free` |
| **Stated product goal** | Open-source AI coding agent | All-in-one agentic engineering platform (IDE + CLI + cloud reviews / KiloClaw) |
| **Upstream sync** | — | Explicit regular merges + `kilocode_change` markers + CI guards |

Kilo is **not** a clean-room rewrite of the agent runtime. The CLI monorepo layout, Bun/Turbo tooling, Effect-based core, OpenTUI Solid TUI, Hono server, plugin/MCP/LSP surfaces, and CONTEXT.md epoch design match OpenCode. Kilo rebrands to `@kilocode/*` / `KILO_*`, isolates most product delta under `packages/opencode/src/kilocode/` and `packages/kilo-*`, and attaches IDE/cloud clients that speak HTTP+SSE via `@kilocode/sdk`.

### Dual lineage (important)

Kilo has **two stacked histories**:

1. **IDE lineage (2025):** Cline → Roo Code → Kilo Code VS Code extension (modes, diff edits, marketplace habits). That tree now lives as `kilocode-legacy` (Apache-2.0).
2. **Runtime lineage (2026):** OpenCode fork for CLI + **ground-up rebuild** of the VS Code extension on `kilo serve` (Solid webview, not the old in-process `Task.ts` loop). Documented in `packages/kilo-vscode/docs/opencode-migration-plan.md`.

So “Kilo vs OpenCode” is really: **OpenCode-shaped core + Kilo product shell**, with Roo/Cline product DNA surviving in modes/agents and IDE UX expectations.

---

## 2. What Kilo Kept from OpenCode

| Capability | Notes |
|---|---|
| Multi-provider LLM routing | Same OpenCode-style provider model; plus first-party Kilo Gateway plugin |
| Terminal UI (OpenTUI / Solid) | CLI primary surface; IDE clients are separate |
| LSP / MCP / plugins | Present; plugin package is `@kilocode/plugin` (OpenCode ABI shape) |
| Permission system | allow / ask / deny; autonomous `--auto` for CI |
| Skills / commands | Skill discovery; Kilo adds builtin skills + migrators from legacy paths |
| Sessions, tools, worktrees | Core agent loop still OpenCode-shaped |
| System-context / epoch design | Ships OpenCode-style `CONTEXT.md` (Kilo-branded wording) |
| Install script + npm global CLI | Parallel UX (`kilo.ai/cli/install`, `@kilocode/cli`) |

### Shared dependency / architecture signature

Both use Bun workspaces, Turbo, Effect, Hono, Zod, Solid/OpenTUI, `@lydell/node-pty`, drizzle/sqlite storage patterns, and similar CLI command sets (`run`, `serve`, models/providers, MCP, …).

Kilo’s root still speaks OpenCode-adjacent tooling (`"sso": "aws sso login --sso-session=opencode"`, workspace deps on `@opencode-ai/script` / `@opencode-ai/core`) — strong fork evidence alongside `@kilocode/*` product packages.

---

## 3. Monorepo Structure Diff

### Packages

| OpenCode | Kilo Code | Notes |
|---|---|---|
| `opencode`, `plugin`, `sdk`, `ui`, `tui`, `core`, `llm`, `server`, … | Same core set (renamed where productized) | Shared lineage; Kilo tracks modern split packages more closely than MiMo’s fat tree |
| `desktop`, `web`, `console`, `enterprise`, `slack`, `stats`, `sdk-next`, … | Slimmer / replaced | Kilo puts product surfaces in `kilo-vscode`, `kilo-jetbrains`, `kilo-web-ui`, `kilo-console` |
| — | `kilo-gateway`, `kilo-telemetry`, `kilo-memory`, `kilo-sandbox`, `kilo-indexing`, `kilo-ui`, `kilo-i18n`, `kilo-docs` | First-party Kilo platform packages |
| `@opencode-ai/*` | `@kilocode/*` (+ residual `@opencode-ai/core`) | Namespace rename with merge-friendly core imports |

### Architecture: one backend, many clients

From Kilo `AGENTS.md`:

| Product | Package | Role |
|---|---|---|
| Kilo CLI | `packages/opencode/` → `@kilocode/cli` | Agent runtime, TUI, `kilo run`, `kilo serve` |
| VS Code | `packages/kilo-vscode/` | Bundles CLI; spawns/reuses one `kilo serve`; Agent Manager (multi-session + worktrees) |
| JetBrains | `packages/kilo-jetbrains/` | Native plugin client of same backend |
| SDK | `packages/sdk/` → `@kilocode/sdk` | Generated HTTP/SSE client |

### `packages/opencode/src` — Kilo-only top-level

| Module | Role |
|---|---|
| `kilocode/` | **~400 files** — almost all product delta (gateway hooks, sandbox policy, indexing, memory glue, migrators, claw, review, …) |
| `kilo-sessions` | Session portability / cloud session surfaces |
| `suggestion`, `shell`, … | Some extras / renames vs current OpenCode tree |

OpenCode-only in the compared checkout (not mirrored the same way): `event-manifest.ts` (newer event-system piece).

Kilo marks shared-file edits with `kilocode_change` (thousands of markers in `packages/opencode/src` outside `kilocode/`) and CI-enforces annotation + workflow allowlists so upstream merges stay tractable. That merge discipline is a **material difference from MiMo**, which tends to pile features into a lagging fat `packages/opencode` without the same upstream-sync machinery.

---

## 4. What Kilo Added / Improved (the real delta)

Kilo’s product bet is **multi-surface agentic engineering with a commercial gateway**, not Xiaomi-style long-horizon research harness alone. Novel code clusters around gateway auth, OS sandbox, project memory, codebase indexing, IDE clients, and cloud/session products.

### 4.1 Kilo Gateway (auth + routing + autocomplete)

`packages/kilo-gateway` — OpenRouter-compatible provider glued to Kilo accounts:

| Concern | Detail |
|---|---|
| API base | `https://api.kilo.ai` (`KILO_API_URL` override) |
| OpenRouter path | `${KILO_API_BASE}/api/openrouter` |
| Auth | Device-code OAuth / token; org id headers |
| Product extras | FIM / next-edit completions, profile/balance, org modes, cloud session list, KiloClaw status |
| Positioning | “500+ models”, zero markup on provider rates, Kilo Pass / credits as commercial layer |

Default authenticated model constant: `kilo-auto/free`. BYO keys remain supported (OpenCode-style providers).

Related endpoints seen in gateway constants:

- `https://chat.kiloapps.io` — chat REST
- `wss://events.kiloapps.io` — event service
- `https://ingest.kilosessions.ai` — session ingest (override `KILO_SESSION_INGEST_URL`)
- `https://app.kilo.ai` — console / org usage UI

### 4.2 Agents: OpenCode set + Kilo modes

| Agent | OpenCode | Kilo |
|---|---|---|
| `build` | ✅ default | Renamed to **`code`** (alias `build` → `code`) |
| `plan` | ✅ | ✅ (patched) |
| `general` / `explore` / compaction helpers | ✅ | ✅ |
| `ask` | ❌ / different | ✅ read-only Q&A primary |
| `debug` | ❌ | ✅ troubleshooting primary |
| `orchestrator` | ❌ | ✅ delegates waves of explore/general subagents |
| `scout` | ❌ | ✅ Kilo explore-adjacent helper |
| `review` | product surface | Code-review flows / suggest tool (telemetry tags `feature: code_reviews`) |

Orchestrator prompt is explicit multi-agent wave planning (dependency classification, parallel tool calls, no direct file edits). This is the Roo/Cline “modes” product idea reimplemented on OpenCode agents.

### 4.3 Project memory (`@kilocode/kilo-memory`)

First-class memory package (not present as OpenCode `packages/kilo-memory`):

| Artifact | Purpose |
|---|---|
| `project.md` | Durable project knowledge |
| `environment.md` | Environment facts |
| `corrections.md` | User corrections |
| Index / state / decisions / sessions | Capture, recall, digest, token budgets |

Features: selective capture (turn-close / explicit), redaction, recall indexing, `/memory` command catalog (`show`, `edit`, remember/forget ops). Effect HTTP API + service wiring under `kilocode/memory`.

Closest peer: **MiMo’s FTS memory + checkpoints** — different design (MiMo: checkpoint writer + MEMORY.md rebuild; Kilo: structured markdown sources + digest/recall package). OpenCode remains compaction/epoch-first without this package.

### 4.4 OS sandbox (`@kilocode/kilo-sandbox`)

Seatbelt (macOS) / Bubblewrap (Linux) style confinement around tool execution:

- Filesystem allowlists / writable paths
- Network destination policy + proxy/relay
- Mutation worker protocol
- Per-session enable preference + config defaults

Product framing: permissions decide *whether* a tool runs; sandbox decides *what it can touch* while running. OpenCode has permissions; Kilo adds this OS-level confinement layer as a first-class package.

### 4.5 Codebase indexing (`@kilocode/kilo-indexing`)

Tree-sitter based indexing + embeddings (LanceDB / Qdrant), background/manual triggers, worktree overlay, Kilo embedding model catalog. Telemetry events cover started/completed/file-count/retry/error. Complements grep/glob rather than replacing OpenCode search tools.

### 4.6 IDE clients + Agent Manager

- **VS Code** rebuild: Solid webview + message protocol; CLI owns agent/MCP/session; extension owns VS Code APIs, auth mediation, Agent Manager.
- **Agent Manager:** multi-session orchestration panel with git worktree isolation (shared single `kilo serve` per host).
- **JetBrains** native plugin in-tree.
- Legacy parity still tracked (marketplace UI stubs, some settings tabs, semantic search ownership TBD) — see migration plan.

### 4.7 Cloud / ops surfaces

Product README lists: cloud agents (`app.kilo.ai/cloud`), automated PR reviews, **KiloClaw** always-on agent, background processes / daemon hooks in `kilocode/`. These are platform features beyond OpenCode’s open CLI focus.

### 4.8 Migrators & ecosystem bridges

Under `kilocode/`: `rules-migrator`, `modes-migrator`, `mcp-migrator`, `workflows-migrator`, `ignore-migrator`, legacy auth migration from `~/.kilocode/cli/config.json`. Skills discover `.kilo` / `.kilocode` / VS Code globalStorage paths. Explicit break: **no fallback to `.opencode` config dirs** (documented).

### 4.9 Plugin ABI

`@kilocode/plugin` exports the same conceptual surface as `@opencode-ai/plugin` (hooks, tools, TUI, workspace adapters) with Kilo SDK types (`createKiloClient`). Practical implication for OPHP-style work: **Kilo is an OpenCode-plugin-class host** (unlike ZCode’s Claude-/Codex-style `.zcode-plugin` marketplace). Community issues (e.g. oh-my-openagent) treat Kilo CLI as a near-drop-in plugin target with config path differences.

---

## 5. What OpenCode Has That Kilo Does Not Emphasize / Match

| Area | OpenCode today | Kilo |
|---|---|---|
| **Neutral BYO-first brand** | Community hub, no required gateway | Gateway + Pass are primary onboarding; BYO still works |
| **Upstream community scale** | ~187k stars, huge PR volume | Fork + commercial org; syncs upstream rather than being upstream |
| **anomalyco console/stats/desktop breadth** | Broader in-tree cloud/console | Replaced by Kilo cloud/apps stack |
| **Long-horizon research packaging** | — | Not MiMo-depth (no `/goal` judge, max-mode N, dream/distill, compose workflow runtime as Xiaomi ships them) |
| **Pure TUI focus** | Strong | Split attention across IDE + CLI + cloud |

Kilo is **ahead of OpenCode** on IDE productization, gateway commerce, sandbox package, and indexing/memory packages; OpenCode remains **ahead as the neutral upstream** and multi-surface open desktop experiments.

---

## 6. Branding, Config, and Runtime Renames

| Concern | OpenCode | Kilo |
|---|---|---|
| Env prefix | `OPENCODE_*` | `KILO_*` (`KILO=1` set at bootstrap) |
| Config schema | opencode.ai | `https://app.kilo.ai/config.json` (TUI schema `app.kilo.ai/tui.json`) |
| Data / config dirs | XDG `opencode` | `kilo` / `.kilo` / `.kilocode` (+ VS Code `kilocode.kilo-code` globalStorage) |
| npm package | `opencode-ai` | `@kilocode/cli` |
| Install | `opencode.ai/install` | `kilo.ai/cli/install` / brew `Kilo-Org/tap/kilo` |
| Default agent | `build` | `code` |
| Client tag | — | `KILO_CLIENT` = `cli` \| `vscode` \| `jetbrains` |

Notable flags / knobs:

- `KILO_CONFIG` / `KILO_CONFIG_DIR` / `KILO_CONFIG_CONTENT`
- `KILO_TELEMETRY_LEVEL` (`all` vs disabled path); config `experimental.openTelemetry !== false` enables PostHog at CLI spawn
- `KILO_API_URL`, `KILO_CHAT_URL`, `EVENT_SERVICE_URL`, `KILO_SESSION_INGEST_URL`
- `KILO_DISABLE_PROJECT_CONFIG`, machine id override `KILO_MACHINE_ID`
- Runtime HTTP: telemetry `setEnabled` so VS Code can push consent changes after spawn

Security-relevant Kilo hardening in shared config: untrusted project config cannot expand `{env:}`; `{file:}` limited to project root (symlink/escape rejection) — called out in CLI docs.

---

## 7. Network / Telemetry / Privacy

More transparent than ZCode; still **telemetry on by default**.

### 7.1 PostHog product analytics

| | Detail |
|---|---|
| Package | `@kilocode/kilo-telemetry` (`posthog-node`) |
| Host | `https://us.i.posthog.com` |
| Default | **Enabled** (`Telemetry.init` uses `cfg.experimental?.openTelemetry !== false`, so missing/`true` ⇒ on) |
| Identity | Persistent machine id at `{XDG data}/kilo/telemetry-id` (typically `~/.local/share/kilo/telemetry-id`); on Kilo auth, identify+alias to email / org id |
| Opt-out | Config + env + runtime `POST /telemetry/setEnabled` (VS Code propagates `vscode.env.isTelemetryEnabled`) |

**Events tracked (enumerated in code):** CLI start/exit; session start/end/message; LLM completion metadata (provider, model, tokens, cost — not prompt bodies in the event enum); command/tool/agent used; plan followup; suggestion shown/accepted; indexing lifecycle; share create/delete; MCP connect/error; remote connection; auth success/logout; feedback; errors; `Telemetry Disabled`.

#### How to disable (verified in source)

**Naming caveat:** config key `experimental.openTelemetry` gates **PostHog** in CLI bootstrap, not the separate `OTEL_EXPORTER_OTLP_*` exporters.

1. **Config (persistent)** — in `~/.config/kilo/kilo.json` (or `kilo.jsonc` / `config.json`):

```json
{
  "experimental": {
    "openTelemetry": false
  }
}
```

2. **Environment (wins when set)** — `KILO_TELEMETRY_LEVEL`:
   - unset → use config flag above
   - `all` → force enabled
   - any other value (e.g. `off`) → force disabled

```bash
export KILO_TELEMETRY_LEVEL=off
```

3. **VS Code** — turn off VS Code telemetry; extension skips `/telemetry/capture` and calls `/telemetry/setEnabled`. Still set env/config for the spawned `kilo serve` if you want spawn-time opt-out.

4. **Optional network** — sinkhole `us.i.posthog.com` (do not block `api.kilo.ai` / `app.kilo.ai` for telemetry alone).

OPHP companion write-up (local monorepo): `opencode-plugin-compat/docs/guides/kilocode-telemetry-disable.md`.

### 7.2 Privacy policy posture

Repo `PRIVACY.md` (CLI-focused): code/prompts go to **chosen model providers**; Kilo claims not to store that content; API keys local. Does **not** deeply document PostHog event schema in that short file — product privacy pages on kilo.ai cover broader apps (Sentry, AppsFlyer, etc. for companion apps).

### 7.3 Comparison snapshot

| | OpenCode | Kilo | MiMo | ZCode |
|---|---|---|---|---|
| Source | Open MIT | Open MIT | Open MIT + use restrictions | Closed Electron |
| Telemetry | Community posture; OTEL available | PostHog US, **on by default**, opt-out | Xiaomi metrics, on by default, env opt-out | Alibaba ARMS + Z.AI, **no opt-out found** |
| Default inference | BYO | Gateway funnel + BYO | MiMo Auto / Xiaomi | Chinese catalog (Z.AI/Zhipu/…) |
| Plugin host class | `@opencode-ai/plugin` | `@kilocode/plugin` (OC-class) | OC-class fork | `.zcode-plugin` (Claude/Codex-class) |

---

## 8. Session / Agent Package Diff (concrete signal)

**Kilo-owned under `packages/opencode/src/kilocode/` (high-signal dirs):**

`agent/`, `agent-manager/`, `sandbox/`, `memory/`, `indexing*`, `gateway`-adjacent `provider/`, `review/`, `claw/`, `cloud-session`, `background-process/`, `daemon/`, `session-import` / `session-export` / `session-portability`, migrators, `permission/`, `skills/`, `console/`, …

**Shared agents file still OpenCode-shaped**, with Kilo patches: rename build→code, inject ask/debug/orchestrator/scout, agent requirements gating (e.g. VS Code extension requirements), reference injection.

**CONTEXT.md:** present in both; Kilo’s copy is OpenCode’s system-context epoch design (not MiMo’s checkpoint-writer alternative).

---

## 9. Summary: Changed vs Improved

### Changed (fork / product deltas)

1. **Rebrand** — CLI, packages, config paths, schemas, install CDN → Kilo  
2. **Default funnel** — Kilo Gateway / Pass / auto-free routing instead of pure BYO  
3. **Config isolation** — dropped `.opencode` fallback; `.kilo` / `.kilocode` only  
4. **Agent naming** — `build` → `code`; added ask/debug/orchestrator  
5. **Telemetry** — first-party PostHog package, on by default with opt-out  
6. **Clients** — VS Code + JetBrains + cloud as first-class consumers of `kilo serve`  

### Improved / net-new relative to stock OpenCode

1. **Upstream merge discipline** — `kilocode_change`, kilo-named directories, CI guards (fork hygiene MiMo lacks)  
2. **Kilo Gateway** — account, org, zero-markup multi-model routing, FIM/edit endpoints  
3. **OS sandbox package** — seatbelt/bubblewrap confinement beyond permission prompts  
4. **Project memory package** — capture/recall/digest with `/memory`  
5. **Codebase indexing** — tree-sitter + vector stores  
6. **Orchestrator / modes** — multi-agent wave orchestration from Roo/Cline DNA  
7. **IDE Agent Manager** — multi-session worktree orchestration  
8. **Platform surfaces** — cloud agents, code reviews, KiloClaw  
9. **OpenCode-compatible plugin ABI under Kilo SDK** — best peer for OPHP-style plugins among China-adjacent products (vs ZCode)  

### Not improved (OpenCode or MiMo still stronger)

1. OpenCode: neutral upstream gravity and community contribution path  
2. MiMo: long-horizon harness depth (`/goal`, max-mode, compose workflows, dream/distill, checkpoint rebuild)  
3. Pure local-first narrative: Gateway + PostHog defaults pull toward Kilo’s cloud  

---

## 10. Bottom Line

Kilo Code is an **OpenCode fork specialized into a multi-client commercial agent platform**: same Effect/TUI/server DNA, aggressive upstream sync, then layered Gateway commerce, OS sandbox, memory, indexing, and IDE/cloud clients — with product DNA still carrying Cline/Roo modes.

If OpenCode is the general open agent platform and MiMo is that platform opinionated for multi-hour autonomous runs under Xiaomi, Kilo is that platform **opinionated for “agentic engineering everywhere you work”** (VS Code, JetBrains, CLI, cloud) under Kilo’s gateway and telemetry defaults — at the cost of fork drift risk (mitigated by merge tooling) and vendor-shaped onboarding.