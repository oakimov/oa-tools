# CoStrict vs OpenCode — Research Summary

**Date:** 2026-08-11
**Sources:**
- OpenCode: https://github.com/anomalyco/opencode (~187k stars, TUI-first agent platform)
- CoStrict: https://github.com/zgsm-ai/costrict (`main`, tag **v3.0.19**, prior line v2.8.x)
- Upstream CoStrict is a fork of: https://github.com/RooCodeInc/Roo-Code
- Docs / product: https://costrict.ai , https://docs.costrict.ai
**CoStrict claim (README):** "Strict AI Coder for Enterprises — Free • Open Source • Private Deployment" by **Sangfor, Inc.** (Shenzhen cybersecurity / cloud vendor; orgs `zgsm-ai`, `zgsm-sangfor`).

---

## 1. Relationship at a Glance

| | OpenCode | CoStrict |
|---|---|---|
| **Org** | anomalyco | zgsm-ai (Sangfor, Inc.) |
| **Repo** | github.com/anomalyco/opencode | github.com/zgsm-ai/costrict |
| **Stars (approx.)** | ~187k | ~4.4k |
| **Created** | 2025-04 | 2025-04-10 |
| **License** | MIT | **Apache-2.0** (© 2025 Sangfor, Inc.) |
| **CLI binary** | `opencode` | `cos` (`@roo-code/cli`) |
| **Config home** | `.opencode/` / `~/.config/opencode` | `~/.costrict/` (+ `.costrict/.clientId`), project `.roo/` conventions, `.cospec/` strict docs |
| **Package scope** | `@opencode-ai/*` | `@roo-code/*` (fork keeps Roo namespaces) |
| **Primary UX** | TUI + growing desktop/web | **VS Code + JetBrains extension**, CLI, CoStrict Cloud |
| **Default model channel** | BYO / many providers | CoStrict provider (`Auto` server-routed) + BYO (Anthropic/OpenAI/OpenAI-compatible/local) |
| **Stated product goal** | Open-source AI coding agent | "Strict AI Coder for Enterprises" — quality-first, controllable, private deploy |
| **Agent lineage** | Own runtime | **Cline → Roo Code → CoStrict** (Roo fork, not OpenCode-based) |

CoStrict is **not** an OpenCode fork. It is a vendor fork of **Roo Code** (itself the Cline lineage), evidenced by: `sync-upstream.md` documenting `git remote add upstream RooCodeInc/Roo-Code` + `git merge upstream/main`, `.env.sample` (`ROO_CODE_API_URL`, `CLERK_BASE_URL`), package names (`@roo-code/cli`, `@roo-code/types`, `@roo-code/telemetry`, `@roo-code/core`, `@roo-code/vscode-shim`), `.roo/` + `.roomodes` + `.rooignore` project conventions, and Roo-shaped webview (`ClineProvider.ts`).

So "CoStrict vs OpenCode" is really **Roo Code's IDE-agent architecture + Sangfor enterprise product shell**, compared against OpenCode's independent TUI agent runtime. It shares almost no code with OpenCode; the comparison is product-level.

---

## 2. Lineage

```
Cline (2024, VS Code extension agent)
  └─ Roo Code (fork of Cline; modes, .roomodes, checkpoints)
       └─ CoStrict (Sangfor fork of Roo Code)
            • strict/vibe/plan workflow modes (server-assisted)
            • RAG code review (server-side indexing)
            • inline completion (local completion-agent)
            • CoStrict Cloud (zgsm.sangfor.com) + workspace trust hardening
```

CoStrict keeps Roo's core: VS Code/JetBrains webview UI, `ClineProvider` + `Task` loop, modes, MCP, skills, checkpoints, `ContextProxy` (per `AGENTS.md`), pnpm+Turborepo monorepo, `apps/cli` headless runner. Unlike OpenCode (Bun, Effect, OpenTUI/Solid, Hono server), CoStrict's stack is the Roo/React webview + Node extension host. **There is no OpenCode plugin ABI** (`@opencode-ai/plugin`) here — CoStrict is a Roo host (Claude-Code-style agent skills), a different plugin-hosting family from OpenCode/MiMo/Kilo, and the same general family as ZCode's marketplace but without a plugin marketplace ABI.

---

## 3. Monorepo Structure

### Top level
`src/` (VS Code extension core: `core/task`, `core/webview`, `core/costrict/`, `core/cs-cloud/`, `api/`, `services/`, `utils/`, `integrations/`), `packages/` (`core`, `cloud`, `telemetry`, `ipc`, `logger`, `types`, `vscode-shim`, `evals`, `build`, configs), `apps/` (`cli` = `@roo-code/cli`/`cos`, `vscode-e2e`, `vscode-nightly`, `web-evals`, `web-roo-code`), `webview-ui/` (Solid/React webview), `schemas/`, `scripts/`, `.roo/` (project modes).

### `src/core/costrict/` — CoStrict-only delta (Roo Code has none of this)
| Module | Role |
|---|---|
| `workflow/` | Strict-workflow engine: `.cospec` docs, section extraction, `Coworkflow*` code-lens/decoration/error-handler, `CospecDiffIntegration`, `CospecMetadataManager`, prompts (`requirements.md`, `design.md`, `run-tasks.md`, `retry-tasks.md`, `run-tests.md`) |
| `code-review/` | Server-side RAG code review lifecycle: `codeReviewService`, `gitCommitListener` (commit-time review), `HistoryManager`, `cloud/` + `classic/` report resolvers |
| `auto-complete/` | Inline completion provider → local `completion-agent` runtime |
| `base/` | CoStrict language/extension data, common constants, mode scaffolding |
| `auth/` | `CostrictAuthService` + `CostrictAuthConfig` (base URL `https://zgsm.sangfor.com`) |
| `telemetry/` | `RawTaskReporter` — raw conversation/diff upload when cloud-authed |
| `commit/`, `codelens/`, `notification/`, `error-code/`, `runtime-config/`, `wiki/` | Commit, code-lens, notification, error taxonomy, runtime/well-known config, wiki surfaces |
| `cs-cloud/` | CoStrict Cloud extension host (`src/core/cs-cloud/extension/`) |

`packages/telemetry` adds a first-party `costrictTelemetry/` (metrics recorder + CoStrict endpoint client) on top of Roo's PostHog client.

---

## 4. What CoStrict Keeps (Roo core / OpenCode-parity surface)

| Capability | Notes |
|---|---|
| Multi-provider LLM routing | Roo/OpenCode-class BYO; CoStrict adds first-party `costrict` provider |
| Modes | Roo modes: `code` (build), `architect`, `ask`, `debug`, `orchestrator`, `review`, `security-review`, `subreview`; custom modes via `.roomodes` |
| MCP integration | Standard MCP hosts, now gated by Workspace Trust (v3.0.19) |
| Skills / slash commands | Claude-Code-style skills + custom commands; OpenSpec `/openspec-init` |
| Sessions, tools, checkpoints, worktrees | Roo `Task` loop, checkpoints, context compression |
| `@file` / `@folder` mentions | Large-repo context inclusion |
| Multi-modal | Image context (CoStrict Cloud multimodal added v3.0.15) |
| IDE + CLI | VS Code / JetBrains extension + `cos` CLI (Roo `@roo-code/cli` headless runner via `@roo-code/vscode-shim`); CLI auth targets **Roo Code Cloud** (`app.roocode.com`), not CoStrict |

---

## 5. What CoStrict Added (the real delta)

### 5.1 Strict Mode (flagship — server-assisted workflow)

Two workflow channels selected per request via `prompt_mode` (`"strict" | "vibe" | "raw"`) sent to the CoStrict API in `extra_body` (`src/api/providers/costrict.ts`):

- **vibe** — natural-language "vibe coding": alternate clarifying questions + code gen. README default.
- **strict** — formal pipeline: **clarify requirements → architecture design → task decomposition → test / self-verify / self-repair**. Enforced with `.cospec/{feature}/` markdown docs (requirements.md, design.md, plan/task docs), a requirements-analyst agent prompt (`packages/types/src/costrict/prompt/i18n/en/requirements.ts`), and the workflow engine (`src/core/costrict/workflow/`). Includes "task-check" (acceptance check) and "subcoding" phases.
- **plan** — planning → step-by-step implementation.

Because `prompt_mode` is an **API parameter**, the strict pipeline is substantially executed **on CoStrict's server** when using the `costrict` provider — the extension sends the conversation and the server routes/structures it. With BYO providers the workflow is prompt+local-agent driven (`.cospec` docs, todo_list, ask_followup_question, attempt_completion). High token consumption (welcome copy: "Ideal for complex tasks (High token consumption)").

### 5.2 Code Review (RAG, server-side)

`src/core/costrict/code-review/` — repository-wide indexing + RAG, **requires the `costrict` provider** (`checkApiProviderSupport()` rejects other providers). Runs as `review` / `security-review` / `subreview` modes that spawn a task instructing the agent to load a `review` / `security-review` skill; result report JSON is written into the workspace and issues are resolved with per-line `fix_code`. Issue triage (Accept / Reject / Ignore) is synced **back to the CoStrict server** (`updateIssueStatusAPI`), and accepting an issue applies the AI-generated fix via `WorkspaceEdit`. `gitCommitListener` triggers commit-time review. Security-review gets a 3-hour timeout; plain review 1 hour. Comment threads render in-editor (`ReviewComment`).

### 5.3 Code Completion

`src/core/costrict/auto-complete/` — inline completions served by a **local `completion-agent` runtime** (`http://localhost:<port>/completion-agent/api/v1/completions`), auto-launched via `ensureCompletionRuntimeReady()`; debounced 300 ms, 2 s timeout, per-completion `zgsm-client-id`. A local agent (not a direct cloud call) fronts completion; model/temperature come from the well-known config.

### 5.4 CoStrict Cloud / auth

`CostrictAuthService` (device-code login, token refresh), API base **`https://zgsm.sangfor.com`** (override `COSTRICT_BASE_URL`), endpoints under `/chat-rag/api/v1` (chat) and `/user-indicator/api/v1` (telemetry/raw store). **`Auto` model mode** — server selects the model per request (`x-select-llm` / `x-select-reason` headers). Model fallback manager handles deepseek-reasoner/v4, MiniMax, Qwen3, Qwen-VL, GLM, Grok, O1/O3/O4 family. Proxy mode: code transits CoStrict servers only to forward upstream (per PRIVACY.md, deleted immediately after forwarding).

### 5.5 Enterprise / security hardening

- **Workspace Trust Service** (`src/services/security/workspaceTrust.ts`, v3.0.19) — closes SRC-2026-4977/4978: project-scoped `.roo/mcp.json` stdio servers and `.roo/tools/*.js` dynamic imports now require explicit, persisted per-workspace approval with **command fingerprinting** (re-prompt on change). Not applied to user-configured global MCP or SSE/HTTP project servers.
- v3.0.18: fixed command injection, path traversal, SSRF; v3.0.15: replaced compromised `node-ipc` with `@node-ipc/node-ipc`.
- Private-deployment story (docs.costrict.ai/deployment), offline migration via history import/export, auto-cleanup history, Lite Mode to cut token consumption.

---

## 6. What OpenCode Has That CoStrict Does Not

| Area | OpenCode today | CoStrict |
|---|---|---|
| **Independent upstream** | Neutral, ~187k stars, huge PR/plugin community | Vendor fork of Roo Code; upstream gravity belongs to Roo |
| **TUI-first UX** | Native OpenTUI/Solid TUI | No native TUI; CLI is a headless extension runner (Ink TUI), primary UI is the IDE webview |
| **Plugin ABI** | `@opencode-ai/plugin` npm host (OpenCode/MiMo/Kilo class) | None — Roo-style extension, Claude-Code-style skills |
| **BYO-first neutrality** | No required account/gateway | CoStrict Cloud + PostHog defaults are the onboarding funnel; BYO still supported |
| **Desktop/web clients** | Growing first-party desktop/web | `apps/web-roo-code` is a marketing site, not a client |
| **Session/agent tooling breadth** | Rich CLI session/worktree tooling | Inherits Roo's task/session tooling; OpenCode's console/enterprise surfaces not mirrored |

---

## 7. Branding, Config, and Runtime Renames

| Concern | OpenCode | CoStrict |
|---|---|---|
| Env prefix | `OPENCODE_*` | `ROO_*` / `COSTRICT_*` / `DISABLE_USER_INDICATOR` |
| Config schema | opencode.ai | costrict.ai docs; Roo config (`~/.costrict/`), `COSTRICT_BASE_URL` |
| Data dirs | XDG `opencode` | `~/.costrict/` (client id, legacy telemetry cleanup), `.costrict/` per-workspace review reports |
| npm/CLI | `opencode-ai` / `opencode` | `@roo-code/cli` / `cos` |
| Install | `opencode.ai/install` | VS Code marketplace (`zgsm-ai.zgsm`), JetBrains plugin (`zgsm-sangfor/costrict-for-jetbrains`), CLI tarball |
| Default agent/mode | `build` | `code` (Roo) + `strict` / `plan` workflow |
| Cloud auth | optional | CoStrict Cloud (`zgsm.sangfor.com`) + CLI uses Roo Code Cloud (`app.roocode.com`) |

---

## 8. Network / Telemetry / Privacy

**Two telemetry channels plus a raw-store uploader.** This is the most privacy-relevant part of CoStrict.

### 8.1 PostHog product analytics (inherited from Roo Code)

| | Detail |
|---|---|
| Package | `@roo-code/telemetry` → `PostHogTelemetryClient` (`posthog-node`) |
| Host | **`https://ph.roocode.com`** (Roo Code's PostHog project, not CoStrict's own) |
| Default | Enabled when VS Code telemetry level = `all` **and** user opt-in; distinct id = client machine id (`~/.costrict/.clientId`, derived from `vscode.env.machineId`) |
| Redaction | Excludes `TASK_MESSAGE` and `LLM_COMPLETION` events; filters `repositoryUrl`, `repositoryName`, `defaultBranch` git properties |
| Opt-out | Settings toggle + VS Code telemetry off |

### 8.2 CoStrict telemetry (server-controlled)

`packages/telemetry/src/costrictTelemetry/` (`CostrictTelemetryClient`, `MetricsRecorder`) — batches anonymous usage/indicator metrics to the CoStrict backend every **20 min** (default):
- `GET ${COSTRICT_BASE_URL}/user-indicator/api/v1/control` — **the server can remotely flip telemetry on/off and set the report interval** (`applyTelemetryControl`). Server-controlled telemetry.
- `POST /user-indicator/api/v1/indicators/batch-report` — batch upload.

Requires a `costrictAccessToken` (Bearer). `DISABLE_USER_INDICATOR=1` disables.

### 8.3 RawStore / RawTaskReporter — raw conversation + diff upload (critical)

When authenticated to CoStrict Cloud, `RawTaskReporter` (`src/core/costrict/telemetry/rawTaskReporter.ts` → `CostrictRawStoreClient`) uploads **raw task data**, and **does not follow the generic telemetry opt-in** (source: "Raw-store reporting currently follows Costrict auth availability rather than the generic telemetry opt-in"):

- `POST /user-indicator/api/v1/raw-store/task-conversation` — per-request: `task_id`, `request_id`, sender, `prompt_mode`, mode, model, start/end/process time, TTFT, token counts, cost, **`request_content` (user prompt), `response_content` (AI reply), `user_input`, and the full code `diff` (text + line count)**.
- `POST /user-indicator/api/v1/raw-store/task-summary` — `user_id`, `user_name`, **`client_id` (machine id)**, `repo_addr` (git remote URL), `repo_branch`, `work_dir`, OS, totals.
- `POST /user-indicator/api/v1/raw-store/commit` — commit data.

So in CoStrict Cloud mode, prompts, responses, and **actual code diffs** leave the machine to `zgsm.sangfor.com`, keyed to the user account. Kill switch is only the env var `DISABLE_USER_INDICATOR=1`.

### 8.4 Provider request metadata

Even for plain chat, the CoStrict provider sends headers: `zgsm-project-path` (**local workspace path**, URL-encoded), `zgsm-client-id` (machine id), `x-user-id`, `zgsm-task-id`, `zgsm-prompt-tags`, `zgsm-provider`, `agent-type` (mode), `x-caller`; plus `repo` (git remote URL) in the request body — to `zgsm.sangfor.com`.

### 8.5 Privacy policy posture

`PRIVACY.md`: code/files go to chosen provider; CoStrict Cloud proxy does not store code (deleted after forwarding); API keys stored locally; telemetry claimed anonymous (no PII/code/prompts) — **but the RawStore uploader (§8.3) contradicts that claim in Cloud mode**, and the welcome-screen copy itself hedges: "No code, prompts, or personal information is ever sent **(unless you connect to CoStrict)**." PostHog host is Roo Code's (`ph.roocode.com`), so opt-out disables both PostHog and (via settings) the batch metrics; the raw store ignores that toggle.

### 8.6 How to minimize data leaving the machine

1. Use a BYO provider (Anthropic/OpenAI/OpenRouter/local) instead of the `costrict` provider.
2. Do not log into CoStrict Cloud (raw-store upload requires `costrictAccessToken`).
3. Disable telemetry in settings + VS Code telemetry.
4. Set `export DISABLE_USER_INDICATOR=1` (kills batch metrics + raw store).
5. Override/block endpoints: `zgsm.sangfor.com`, `ph.roocode.com` (sinkhole). Completion runs on localhost; nothing to block there.

### 8.7 Comparison snapshot

| | OpenCode | CoStrict | MiMo | Kilo | ZCode |
|---|---|---|---|---|---|
| Lineage | Own runtime | **Cline→Roo fork** | OpenCode fork | OpenCode fork | Cline-derived Electron |
| License | MIT | Apache-2.0 (Sangfor) | MIT + use-restr. | MIT | closed |
| Telemetry | Community posture; OTEL avail. | **PostHog on-by-default + CoStrict server telemetry w/ remote control + raw conv/diff upload on Cloud** | Xiaomi metrics on-by-default | PostHog US on-by-default | Alibaba/Z.AI no opt-out |
| Default inference | BYO | CoStrict Cloud (`Auto`) funnel + BYO | MiMo Auto | Kilo Gateway + BYO | Chinese catalog |
| Plugin host | `@opencode-ai/plugin` | none (Roo skills) | OC-class fork | `@kilocode/plugin` (OC-class) | `.zcode-plugin` |
| Standout | neutral hub, TUI | strict-mode workflow, RAG review, enterprise/private deploy | long-horizon harness | multi-client platform + gateway | closed China fork |

---

## 9. Summary: Changed vs Improved

### Changed (fork / product deltas vs Roo Code upstream)

1. **Rebrand** — CoStrict naming, `~/.costrict/`, marketplace ids `zgsm-ai.zgsm`, `cos` CLI
2. **Strict/vibe/plan workflow** — server-assisted pipeline on top of Roo modes
3. **CoStrict Cloud** — `zgsm.sangfor.com`, `Auto` model routing, proxy mode, `user-indicator` backend
4. **RAG code review** — server-side repo indexing + issue sync back to server
5. **Telemetry stack** — added server-controlled CoStrict channel + raw conversation/diff uploader on top of Roo PostHog
6. **Completion agent** — local `completion-agent` runtime

### Improved / net-new

1. Strict-mode engineering workflow (requirements → design → tasks → test/self-repair) with `.cospec` docs
2. Repo-wide RAG code review with AI `fix_code` + in-editor issue triage
3. Workspace Trust Service (project MCP + custom tools gating) — genuinely novel hardening vs OpenCode/Roo
4. Inline completion via isolated local runtime
5. Enterprise private-deployment positioning, history import/export, Lite Mode
6. Security patch cadence (v3.0.15–3.0.19: command injection, path traversal, SSRF, node-ipc)

### Not improved (OpenCode or peers still stronger)

1. OpenCode: neutral upstream + plugin ecosystem + native TUI
2. OpenCode/MiMo/Kilo: OpenCode-class plugin ABI
3. Privacy posture: PostHog on-by-default, server-controlled telemetry, and Cloud-mode raw diff/conversation upload make CoStrict **the least private-by-default** of the four reviewed forks after ZCode

---

## 10. Bottom Line

CoStrict is **Roo Code + Sangfor's enterprise product shell** — not an OpenCode fork, and sharing no runtime code with it. Its differentiation is a **strict engineering workflow** (requirements → design → tasks → test/self-repair) driven partly by the CoStrict server, a **server-side RAG code review**, inline completion through a local agent, and an **enterprise/private-deployment** story with real security hardening (Workspace Trust, patch cadence).

If OpenCode is the neutral general agent platform, MiMo the long-horizon harness, and Kilo the multi-client commercial gateway platform, CoStrict is the **IDE-first, quality-gated, enterprise-governance agent** — at the cost of a Cloud+telemetry funnel that, in Cloud mode, uploads raw conversations and code diffs to Sangfor's servers, and a plugin-host gap versus the OpenCode-class forks.
