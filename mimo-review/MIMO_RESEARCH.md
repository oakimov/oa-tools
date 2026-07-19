# MiMo Code vs OpenCode — Research Summary

**Date:** 2026-07-19  
**Sources:**
- OpenCode local checkout: `/Users/mitra/Projects/opencode-research` (anomalyco/opencode, `dev` branch)
- MiMo Code: https://github.com/XiaomiMiMo/MiMo-Code (v0.1.x line, MIT + use restrictions)
**MiMo claim (README):** fork of OpenCode that keeps core capabilities and adds long-horizon harness features.

---

## 1. Relationship at a Glance

| | OpenCode | MiMo Code |
|---|---|---|
| **Org** | anomalyco | Xiaomi MiMo |
| **Repo** | github.com/anomalyco/opencode | github.com/XiaomiMiMo/MiMo-Code |
| **Stars (approx.)** | ~187k | ~12k |
| **Created** | 2025-04 | 2026-06-10 (public) |
| **License** | MIT | MIT + [USE_RESTRICTIONS.md](https://github.com/XiaomiMiMo/MiMo-Code/blob/main/USE_RESTRICTIONS.md) |
| **CLI binary** | `opencode` | `mimo` (`@mimo-ai/cli`) |
| **Config home** | `.opencode/` / `~/.config/opencode` | `.mimocode/` / `~/.config/mimocode` |
| **Package scope** | `@opencode-ai/*` | `@mimo-ai/*` (still has residual `opencode` paths) |
| **Primary UX** | TUI + desktop/web (actively growing) | TUI-first (docs say Web/App not the focus) |
| **Default model channel** | BYO / many providers | MiMo Auto (free limited-time) + Xiaomi OAuth |
| **Stated product goal** | Open-source AI coding agent | Long-horizon coding; “models and agents co-evolve” |

MiMo is **not** a clean-room rewrite. The monorepo layout, Bun/Turbo tooling, Effect-based core, OpenTUI Solid TUI, Hono server, plugin/MCP/LSP surfaces, and many package names match OpenCode’s architecture. Xiaomi rebranded namespaces, pinned an older-ish OpenCode-shaped tree, then layered a large harness for memory and multi-step autonomy.

---

## 2. What MiMo Kept from OpenCode

Inherited capabilities MiMo still advertises / ships:

| Capability | Notes |
|---|---|
| Multi-provider LLM routing | Same OpenCode-style provider model; BYO OpenAI-compatible APIs |
| Terminal UI (OpenTUI / Solid) | Primary surface; Tab agents |
| LSP / MCP / plugins | Present; Claude Code / Codex / OpenCode skill inheritance toggles |
| Permission system | allow / ask / deny; `--dangerously-skip-permissions` |
| Skills / commands | Skill discovery; MiMo adds large builtin catalog |
| Sessions, tools, worktrees | Core agent loop still OpenCode-shaped |
| Install script + npm global CLI | Parallel to OpenCode’s install UX |
| Desktop / web / console packages | Present in tree, but MiMo AGENTS.md says **TUI is the supported focus** |

### Shared dependency / architecture signature

Both use Bun workspaces, Turbo, Effect, Hono, Zod, Solid/OpenTUI, `@lydell/node-pty`, drizzle/sqlite storage patterns, and similar CLI command sets (`mcp`, `run`, `serve`, `models`, `providers`, `github`, `pr`, …).

MiMo’s root `package.json` still reports `"name": "opencode"` and repository URL `anomalyco/opencode` in places — strong fork evidence alongside `@mimo-ai/*` workspace deps.

---

## 3. Monorepo Structure Diff

### Packages

| OpenCode (`opencode-research`) | MiMo Code | Notes |
|---|---|---|
| `opencode`, `plugin`, `sdk`, `ui`, `web`, `desktop`, `console`, `enterprise`, `slack`, … | Same core set | Shared lineage |
| `core`, `protocol`, `schema`, `server`, `client`, `llm`, `tui`, `session-ui`, `sdk-next`, … | **Absent / folded** | Upstream OpenCode has been splitting packages; MiMo still looks more monolithic around `packages/opencode` |
| — | `shared`, `extensions` | MiMo-specific packaging |
| `@opencode-ai/*` | `@mimo-ai/*` | Namespace rename |

OpenCode has moved faster toward a multi-package core (`core`, `protocol`, `llm`, separate `tui`). MiMo’s tree is closer to an earlier “fat `packages/opencode`” layout, with Xiaomi features living inside that package.

### `packages/opencode/src` top-level — MiMo-only modules

These directories exist in MiMo and **not** in current OpenCode `packages/opencode/src`:

| Module | Role |
|---|---|
| `memory/` | SQLite FTS5 persistent memory service |
| `workflow/` | Deterministic multi-agent workflow runtime |
| `task/` | Tree-shaped task tracking (`T1`, `T1.1`, …) |
| `cron/` | Scheduled / recurring prompt loops |
| `metrics/` | Usage analytics client → Xiaomi (`tracking.miui.com`) |
| `history/`, `inbox/`, `actor/`, `team/` | Session/history/coordination extras |
| `file/`, `shell/`, `pty/`, `npm/`, `global/`, `flag/` | Some of these exist elsewhere in modern OpenCode (`core`); in MiMo they stay under the CLI package |

### OpenCode-only (in current tree, not mirrored the same way in MiMo)

| Module | Role |
|---|---|
| `background/` | Background work orchestration |
| `image/` | Image handling as a first-class module |
| `event-manifest.ts`, `event-v2-bridge.ts` | Newer event-system migration pieces |

---

## 4. What MiMo Added / Improved (the real delta)

MiMo’s product bet is **long-horizon continuity**. Most novel code clusters around memory, checkpoints, autonomous stop conditions, and structured multi-agent pipelines.

### 4.1 Persistent memory (SQLite FTS5)

OpenCode: session history + compaction; no first-class project memory module in `packages/opencode/src/memory`.

MiMo layers:

| Artifact | Purpose |
|---|---|
| `MEMORY.md` | Cross-session project knowledge / rules / decisions |
| `checkpoint.md` | Structured session state snapshots |
| `notes.md` | Scratch pad for agents |
| `tasks/<id>/progress.md` | Per-task progress logs |

Memory is injected on resume so the agent does not re-learn the project from scratch. Migrations under `packages/opencode/migration/*memory_fts*` implement FTS indexing/triggers.

### 4.2 Checkpoint-driven context management

MiMo session code adds a large checkpoint subsystem absent from current OpenCode session tree:

- `checkpoint.ts`, `checkpoint-writer` agent prompt
- `checkpoint-align`, `checkpoint-context`, `checkpoint-paths`, `checkpoint-progress-reconcile`, `checkpoint-retry`, `checkpoint-templates`, `checkpoint-validator`
- Budgeted injection (`budgeted-read.ts`) so memory/checkpoint/notes don’t blow the context window

Xiaomi’s design (blog + docs): trigger checkpoints well below context limit (~20% / 45% / 70% of budget), incremental updates, then **rebuild** context from checkpoint + memory + recent turns when approaching the limit — instead of only summarizing/compacting transcript.

OpenCode’s approach remains closer to compaction/epoch-based system context (see OpenCode `CONTEXT.md`); MiMo adds an explicit disk-backed checkpoint writer subagent with path-scoped write permissions.

### 4.3 Agents: OpenCode set + MiMo compose/max

| Agent | OpenCode | MiMo |
|---|---|---|
| `build` | ✅ default full access | ✅ |
| `plan` | ✅ read-only-ish | ✅ |
| `general` / `explore` / compaction helpers | ✅ | ✅ (explore etc.) |
| `compose` | ❌ | ✅ orchestration / specs-driven mode |
| `max` | ❌ | ✅ Max Mode primary agent (`max-mode.ts`) |

MiMo agent prompts added: `checkpoint-writer.txt`, `dream.txt`, `distill.txt` (not in OpenCode).

### 4.4 `/goal` — stop-condition judge

`session/goal.ts`: user sets a stop condition; the main run loop refuses to stop until an **independent judge model** reads the transcript and returns `{ ok, impossible?, reason }`. Prevents optimistic early exits on long autonomous runs.

OpenCode has no equivalent first-class goal/judge loop in the session package.

### 4.5 Max Mode (best-of-N)

`session/max-mode.ts`: parallel propose-only candidates (default **N=5**), then judge selection. Experimental config: `experimental.maxMode`.

This is a harness-level reasoning fan-out, not present as a built-in OpenCode session mode.

### 4.6 Compose mode + workflows

**Compose agent** — interactive specs-driven development with skills for plan / implement / TDD / review / verify / merge. Config: `config/compose.ts` (`docs/compose` output dir).

**Workflows** — deterministic JS scripts orchestrating agents (sandboxed, phase sequences, retries, parallel worktrees). Built-ins:

| Workflow | Phases (summary) |
|---|---|
| `compose` | Brainstorm → Design → Implement → Verify → Review → Report → Merge |
| `deep-research` | Brief → Plan → Research → Reflect → Write → Review |
| `fact-check` | Plan → Search → Extract → Group → Crosscheck → Report |

Custom workflows: `.mimocode/workflows/*.js`. DB migrations: `workflow_run`, `workflow_script_sha`, timeouts.

OpenCode has skills and agents, but **not** this first-class workflow runtime + TUI workflow tree (`dialog-workflows.tsx`, `workflow-tree.tsx`, `server/routes/instance/workflows.ts`).

### 4.7 Dream & Distill (self-improvement)

| Command | Behavior |
|---|---|
| `/dream` | Scan recent traces → merge/dedupe into project memory; drop stale entries. Auto ~every 7 days |
| `/distill` | Mine repeated manual workflows → package as reusable skills / subagents / commands |

Supporting code: `session/auto-dream.ts`, agent prompts `dream.txt` / `distill.txt`.

OpenCode does not ship these as built-in slash commands / session services.

### 4.8 Task tree

`task/` + progress files: hierarchical tasks (`T1`, `T1.1`, …) tied into checkpoints so progress survives resume. Complements compose/workflows.

### 4.9 Builtin skills catalog (much larger)

MiMo ships a large `.bundle` of official skills, including:

- Office/media: `docx-official`, `pdf-official`, `pptx-official`, `xlsx-official`, `html-to-video-pipeline`
- Research: `arxiv`, `deep-research`, `super-research`, `research-paper-writing`
- Meta: `evolve`, `loop`, `skill-creator`, `mimocode-docs`
- Design: `design-blueprint`, `frontend-design`, `product-design`
- Compatibility bundles: `claude-code`, `codex`
- Analytics: `data-analytics` (+ nested workflows)

OpenCode’s skill surface is thinner (`skill/discovery.ts` + user/project skills); it does not ship this Xiaomi office/research/evolve catalog.

Env killswitches: `MIMOCODE_DISABLE_BUILTIN_SKILLS`, `MIMOCODE_DISABLE_OFFICIAL_SKILLS`, plus Claude/Codex/OpenCode skill inheritance flags.

### 4.10 Voice input

Real-time voice via TenVAD + MiMo ASR (`/voice`). Tied to MiMo platform models (`mimo-v2.5-asr`); optional OpenRouter/custom relays for control model. Requires `sox`.

OpenCode has no equivalent first-party ASR voice loop.

### 4.11 Import / ecosystem bridges

MiMo session imports: `claude-import.ts`, `codex-import.ts`, `opencode-import.ts` — migrate auth/config from peer tools. First-run also offers Claude Code credential import.

Flags extensively control Claude Code env/skills/MCP/commands inheritance (`MIMOCODE_DISABLE_CLAUDE_CODE*`, `MIMOCODE_MIMO_ONLY`).

### 4.12 Cron / loop

`cron/` + `loop` skill: schedule recurring prompts. OpenCode lacks the same top-level cron module in `packages/opencode/src`.

### 4.13 Harness docs (Xiaomi research packaging)

`docs/harness/` and `docs/compose/` document MiMo-specific designs:

- Agent Multi-Skill Workflow Orchestration
- MiMo Orchestrator Mode
- MiMo Token Efficient Mode
- Mix of Harness and Hand-off

This is product/research documentation OpenCode does not mirror.

---

## 5. What OpenCode Has That MiMo Does Not Emphasize / Match

| Area | OpenCode today | MiMo |
|---|---|---|
| **Desktop / web product** | Active (`dev:desktop`, `dev:web`, desktop releases) | Packages exist; AGENTS.md: **no Web/App support focus** |
| **Package modularization** | Split `core` / `protocol` / `llm` / `server` / `tui` / … | Mostly still fat `packages/opencode` |
| **Upstream velocity** | Very high star/PR volume; rapid refactors | Fork; features land as Xiaomi additions |
| **Neutral branding / BYO-first** | Open-source agent, no default Chinese cloud funnel | MiMo Auto + Xiaomi OAuth as primary onboarding |
| **System-context rewrite** | Large `CONTEXT.md` epoch/system-context design | Checkpoint/memory design instead (different bet) |
| **Stats / console cloud** | Broader anomalyco console/stats infra in tree | Slimmer; Xiaomi platforms for hosted services |

MiMo is **opinionated ahead of OpenCode** on long-horizon memory/workflows; OpenCode is **ahead on modular core + multi-surface product** and remains the upstream community hub.

---

## 6. Branding, Config, and Runtime Renames

| Concern | OpenCode | MiMo |
|---|---|---|
| Env prefix | `OPENCODE_*` | `MIMOCODE_*` |
| Config schema host | opencode.ai docs | `https://mimo.xiaomi.com/mimocode/config.json` |
| Data dir | XDG `opencode` | XDG `mimocode` (`MIMOCODE_HOME`) |
| npm package | `opencode-ai` | `@mimo-ai/cli` |
| Install | `opencode.ai/install` | `mimo.xiaomi.com/install` |
| Default agents UX | build / plan | build / plan / **compose** (+ max) |

Notable MiMo flags (beyond OpenCode’s `OPENCODE_DISABLE_*` set):

- `MIMOCODE_ENABLE_ANALYSIS` — analytics **on by default**; set `false` to disable
- `MIMOCODE_MIMO_ONLY` — pure-mimo mode; disables Claude inheritance paths
- `MIMOCODE_DISABLE_BUILTIN_SKILLS` / `…_OFFICIAL_SKILLS` / `…_EXTERNAL_SKILLS`
- `MIMOCODE_DANGEROUSLY_SKIP_PERMISSIONS`
- Retry / n-gram / empty-step recovery tunables for long runs

---

## 7. Network / Telemetry / Privacy (secondary, but material)

Not the main product delta, but relevant when comparing forks:

| | OpenCode | MiMo |
|---|---|---|
| Analytics | No Xiaomi endpoint; OTEL available for local/tracing use | `packages/opencode/src/metrics` → `https://tracking.miui.com/track/v4/o` |
| Default | Community open-source posture | Analytics enabled unless `MIMOCODE_ENABLE_ANALYSIS=false` |
| Hosted inference | BYO | MiMo Auto / Xiaomi platform (code may leave the machine) |
| Extra legal | MIT | MIT + use restrictions (military, high-risk autonomy, etc.) + MiMo ToS for hosted services |

Compared to ZCode (closed Electron fork with always-on Alibaba ARMS + no opt-out), MiMo is **more transparent** (open source, documented env opt-out) but still **defaults to Xiaomi telemetry** and steers users toward Xiaomi-hosted models.

---

## 8. Session Package Diff (concrete file-level signal)

**Present in MiMo session/, absent in current OpenCode session/:**

`auto-dream`, `checkpoint*` family, `goal`, `max-mode`, `budgeted-read`, `trajectory`, `try-best-detector`, `claude-import` / `codex-import` / `opencode-import`, `cron-bridge`, `classify`, `prune`, `skill-search-reminder`, …

**Present in OpenCode session/, not mirrored the same way in MiMo:**

`llm/` subdirectory (provider-turn modularization), `message-error.ts`, `reminders.ts`, `tools.ts` — signs of upstream refactor MiMo has not fully tracked.

---

## 9. Summary: Changed vs Improved

### Changed (fork deltas)

1. **Rebrand** — CLI, packages, config paths, schemas, install CDN → Xiaomi/MiMo  
2. **Default funnel** — MiMo Auto / Xiaomi OAuth instead of pure BYO  
3. **Legal** — additional use restrictions + hosted ToS  
4. **Tree shape** — lagging OpenCode’s package split; features piled into `packages/opencode`  
5. **Telemetry** — Xiaomi metrics endpoint, on by default with env opt-out  

### Improved / net-new for long-horizon work

1. **Persistent memory + FTS** — project memory that survives sessions  
2. **Checkpoint writer + context rebuild** — structured state vs transcript-only compaction  
3. **`/goal` judge loop** — reduces premature stop on autonomous tasks  
4. **Compose agent + workflow runtime** — specs pipelines and deterministic multi-agent scripts  
5. **Max Mode** — parallel best-of-N with judge  
6. **Dream / Distill** — memory hygiene and workflow extraction  
7. **Task trees + cron/loop** — progress and recurrence  
8. **Large builtin skill/workflow catalog** — office, research, evolve, Claude/Codex bridges  
9. **Voice** — first-party ASR path for MiMo users  
10. **Harness docs** — explicit long-horizon design writeups  

### Not improved (OpenCode still stronger)

1. Multi-surface product (desktop/web) and modular core architecture  
2. Community scale / upstream contribution path  
3. Neutral, non-vendor-default positioning  

---

## 10. Bottom Line

MiMo Code is an **OpenCode fork specialized into a long-horizon coding harness**: memory, checkpoints, compose/workflows, goal judging, max-mode, and self-maintenance (`/dream`, `/distill`), wrapped in Xiaomi branding and model defaults.

If OpenCode is a general open agent platform, MiMo is that platform **opinionated for multi-hour / multi-hundred-step runs** and co-evolution with Xiaomi’s MiMo models — at the cost of fork drift, vendor defaults, and Xiaomi-side telemetry/hosted inference.
