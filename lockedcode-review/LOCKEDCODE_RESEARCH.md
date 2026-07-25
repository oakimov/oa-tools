# LockedCode vs OpenCode — Research Summary

**Date:** 2026-07-25
**Sources:**
- OpenCode: https://github.com/anomalyco/opencode
- LockedCode: https://github.com/LockedCodeAI/lockedcode (`dev` branch, package v1.1.2)
- LockedCode claim (README): security-hardened fork of OpenCode that adds a comprehensive security layer between the LLM's intent and the agent's execution.

---

## 1. Relationship at a Glance

| | OpenCode | LockedCode |
|---|---|---|
| **Org** | anomalyco | LockedCodeAI |
| **Repo** | github.com/anomalyco/opencode | github.com/LockedCodeAI/lockedcode |
| **Stars (approx.)** | ~187k | **~5** |
| **Created** | 2025-04 | 2026-05-09 (public) |
| **Last push** | Active daily | 2026-05-18 (2 months stale) |
| **License** | MIT | MIT |
| **CLI binary** | `opencode` | `lockedcode` (`@lockedcode/cli` → `lockedcode` package) |
| **Config home** | `.opencode/` / `~/.config/opencode` | `.lockedcode/` + `.opencode/` (dual-directory) |
| **Package scope** | `@opencode-ai/*` | `lockedcode` (single package, internal `@opencode-ai/*` deps retained) |
| **Primary UX** | TUI + desktop/web | TUI-first (inherited OpenCode stack) |
| **Default model channel** | BYO / many providers | BYO (inherited, no added provider defaults) |
| **Stated product goal** | Open-source AI coding agent | Secure AI coding agent for corporate use with untrusted models |

LockedCode is **not** a clean-room rewrite. The monorepo layout, Bun/Turbo tooling, Effect-based core, OpenTUI Solid TUI, Hono server, plugin/MCP/LSP surfaces, and package names match OpenCode exactly. LockedCode adds `packages/opencode/src/security/` as the sole delta — the stated goal is to stay mergeable with upstream OpenCode.

### Critical distinction from other forks

Unlike **Kilo** (multi-client commercial gateway) or **MiMo** (long-horizon autonomy research), LockedCode's product bet is **security hardening for corporate teams using non-frontier models**. Its novel code clusters around confinement, scanning, DLP, audit, and policy — not around new agents, workflows, IDE integrations, or inference gateways.

---

## 2. Project Maturity

LockedCode is the **least mature** of the reviewed OpenCode forks:

| Signal | Value |
|---|---|
| **Stars** | ~5 |
| **Forks** | 0 |
| **Open issues** | 9 |
| **Closed issues** | 0 |
| **Commits after fork base** | One push from May 9–18 (phase 0 branding + skeleton), then silent |
| **npm package** | `lockedcode` registered, `npm i -g lockedcode@latest` in README — **published?** unknown |
| **Homebrew / Scoop** | README claims taps exist — unverified |
| **Tests** | Test suite inherited from OpenCode; no LockedCode-specific test results visible |
| **Audit done** | Internal SANDBOX-AUDIT dated 2026-05-15 found **critical violations** |

The Architecture doc describes 22 phases (LC-001 → LC-022) of which **only Phase 0** (branding, skeleton, docs) appears implemented. The skeleton `SecurityService` exists with working confinement checks, scanning, DLP, audit, policy, and trust stubs — but the **internal tool subsystems bypass confinement entirely** (templates, rules, policy loader), per the SANDBOX-AUDIT.

**Conclusion:** LockedCode is a promising architecture with early-stage, partially-implemented code. The design document is its strongest asset; the actual codebase is ahead of the roadmap (more modules exist than Phase 0 would imply) but behind the design's ambition (critical confinement gaps remain).

---

## 3. What LockedCode Kept from OpenCode

All original OpenCode capabilities are preserved with no modifications:

| Capability | Notes |
|---|---|
| Multi-provider LLM routing | 18+ provider SDKs inherited unchanged |
| Terminal UI (OpenTUI / Solid) | Primary surface |
| LSP / MCP / plugins | Full inheritance including `@opencode-ai/plugin` ABI |
| Permission system | Inherited `allow/ask/deny` ruleset |
| Skills / commands | Inherited discovery system |
| Sessions, tools, worktrees | Core agent loop untouched |
| Client/server architecture | `lockedcode serve`, desktop app, web app |
| Cloud console | Inherited `packages/console/` with PlanetScale/Stripe billing |
| VS Code extension | Inherited `sdks/vscode/` |

### Shared dependency signature

Both use Bun workspaces, Turbo, Effect 4.0.0-beta.59, Hono 4.10.7, Zod 4.1.8, Solid/OpenTUI, `@lydell/node-pty`, Drizzle SQLite, tree-sitter, and the same 18+ provider SDKs.

LockedCode's `packages/opencode/package.json` still declares workspace dependencies on `@opencode-ai/plugin`, `@opencode-ai/script`, and `@opencode-ai/sdk` — explicit fork evidence alongside the `lockedcode` binary name.

### `.opencode/` directory retained

LockedCode ships the full `.opencode/` agent config directory with skills, commands, glossary, themes, and plugins — it is a **dual-config** tool that reads both `.opencode/` and `.lockedcode/` paths, unlike Kilo which dropped `.opencode/` fallback.

---

## 4. LockedCode-Specific Architecture

### 4.1 SecurityService — Root Interception Service

The entire security layer is one Effect service at `packages/opencode/src/security/index.ts`. It sits at three interception points:

```
LLM Output → Tool Selection → SecurityService (scan + confine + policy + trust) → Tool Execution
                                   ↓
                              Audit Trail (SQLite)
                                   ↓
                              Bus Events (TUI notifications)
```

**Interface (source-confirmed):**
- `scanContent(content, metadata)` → scan file writes via Semgrep/YARA/entropy/secrets/injection
- `scanCommand(command, metadata)` → structural command parsing + blocked-pattern detection
- `checkConfinement(path, operation, sessionId?)` → project-root jail enforcement
- `scanOutbound(content, filePath)` → DLP for secrets/PII before context leaves machine
- `evaluatePolicy(action, context)` → declarative YAML policy engine
- `scoreTrust(action, context)` → risk scoring (0–100) driving approval UX
- `recordAuditEvent(event)` → append-only audit trail

Two layers exist: `defaultLayer` (no bus dependency, pass-through) and `busLayer` (with BusService events for production).

### 4.2 Module Structure (source-confirmed)

```
packages/opencode/src/security/
├── index.ts              # SecurityService — root, 2 layers (plain + bus)
├── event.ts              # Typed bus events (ScanStarted, ActionBlocked, etc.)
├── types.ts              # SecurityConfig, ScanResult, ConfinementResult, etc.
├── config.ts             # Security config (strictness levels)
├── confinement/          # Project-root jail
│   ├── index.ts          # ConfinementService
│   ├── linux.ts          # Landlock + Bubblewrap
│   ├── macos.ts          # sandbox-exec
│   └── windows.ts        # Restricted tokens + job objects
├── scanning/             # Static scanning pipeline
│   ├── index.ts          # ScanningService
│   ├── semgrep.ts        # Semgrep integration
│   ├── yara.ts           # YARA integration
│   ├── entropy.ts        # Entropy analysis
│   └── command-analyzer.ts  # Structural command parsing (used in scanCommand)
├── dlp/                  # Outbound data loss prevention
│   ├── index.ts          # DLPService
│   ├── scanner.ts        # Secret + PII scanning
│   ├── redact.ts         # Redaction engine
│   └── policy.ts         # File-level sensitivity
├── injection/            # Prompt injection detection
│   ├── index.ts          # InjectionScanner
│   └── patterns.ts       # Pattern library
├── secrets/              # Secret detection in generated code
│   ├── index.ts          # SecretScanner
│   └── patterns.ts       # 50+ credential pattern definitions
├── audit/                # Audit trail
│   ├── index.ts          # AuditService
│   ├── schema.sql.ts     # SQLite tables (security_event, scan_result, policy_decision)
│   └── query.ts          # Query interface + retention
├── policy/               # Policy engine
│   ├── index.ts          # PolicyService
│   └── schema.ts         # Zod schema for lockedcode.yaml
├── trust/                # Trust scoring
│   └── index.ts          # TrustService
├── cascade/              # Multi-agent security cascade
│   └── index.ts          # CascadeService
├── airgap/               # Air-gap mode
├── compliance/           # Compliance report generation (SOC2, ISO 27001, HIPAA, FedRAMP)
├── dependency/           # Dependency vetting (typosquatting, post-install scripts)
├── license/              # License contamination detection
├── monitor/              # Runtime monitoring (eBPF syscall, process tree, network)
├── provenance/           # Model provenance tracking (per-file attribution)
├── quarantine/           # Rollback & quarantine
├── registry/             # Model registry & approval
├── rules/                # Custom rule authoring & testing
├── session/              # Session recording & replay
├── siem/                 # SIEM integration (CEF, OCSF, JSON-syslog)
├── tui/                  # TUI security indicators
└── __tests__/            # Tests
```

### 4.3 Additional root-level files

| File | Purpose |
|---|---|
| `rules/` | Bundled Semgrep YAML, YARA signatures, secret patterns, injection patterns |
| `LockedCode-Charter.md` | Vision, philosophy, V1/V2 feature inventory, non-goals |
| `LockedCode-Architecture.md` | **14,000+ word** canonical architecture specification (the most detailed architecture doc of any reviewed fork) |
| `LockedCode-Roadmap.md` | 22 tasks across 7 phases with dependency graph |
| `CONVENTIONS.md` | Binding engineering conventions for the project |
| `SANDBOX-AUDIT.md` | Internal confinement audit (found critical gaps) |
| `opencode-Audit.md` | OpenCode upstream codebase audit (captures base state) |
| `opencode-Scorecard.md` | OpenCode quality scorecard (74% overall) |
| `lockedcode-Audit.md` | (Mislabeled — contains the OpenCode audit, not lockedcode) |

---

## 5. The Delta: What LockedCode Adds

### 5.1 Directory Confinement (Project-Root Jail)

**Approach:** OS-level enforcement via Landlock (Linux), sandbox-exec (macOS), restricted tokens + job objects (Windows). Not application-level path checks — actual kernel-level confinement.

**Source-confirmed:** `packages/opencode/src/security/confinement/` contains index, linux, macos, windows modules. The `SecurityService.checkConfinement()` method exists, is wired into tool interceptions, and uses platform-specific backends.

**SANDBOX-AUDIT finding:** Confinement works for **user-facing tool operations** (reads/writes/edits). However, **internal subsystems bypass confinement**:
- Template system hardcodes `~/.lockedcode/templates/` with no confinement check (**CRITICAL**)
- Remote template fetching has no path-traversal validation on `entry.name` (**CRITICAL**)
- Custom rules loaded from `~/.lockedcode/custom-rules/` bypass checks (**HIGH**)
- Policy loaded from `~/.config/lockedcode/policy.json` bypasses checks (**MEDIUM**)
- Config variable expansion `{file:~/path}` reads arbitrary files (**MEDIUM**)

### 5.2 Static Scanning Pipeline

Seven parallel scanners on every file write:

| Scanner | Implementation | External dep? |
|---|---|---|
| Semgrep | CLI invocation with LLM-specific rulesets | semgrep binary (graceful degradation) |
| YARA | CLI invocation with bundled signatures | yara binary (graceful degradation) |
| Entropy | High-entropy string detection | None |
| Secrets | 50+ credential format patterns | None |
| Prompt injection | Pattern-based detection | None |
| Custom rules | Organization-defined JSON rules | None |
| License | Code fingerprinting against open-source bodies | None |

**Source-confirmed:** `scanContent()` exists, calls `scanning.scan()` which uses the scanning pipeline. `scanCommand()` uses `command-analyzer.ts` for structural parsing.

### 5.3 Shell Command Interception

Every shell proposal is structurally parsed (tree-sitter) before execution. Hard-blocked patterns:
- `curl | bash`, `wget -O- | sh` (remote execution)
- Crontab, systemctl, launchctl modifications
- SSH config and authorized_keys changes
- Shell profile writes (.bashrc, .zshrc)
- Raw network listeners (nc -l, socat, ncat)

**Source-confirmed:** `scanCommand()` in `index.ts` calls `analyzeCommand()` from `scanning/command-analyzer.ts`, merges findings with scanning pipeline results.

### 5.4 Outbound DLP

Scans file contents before they're sent to the LLM provider as context:
- Secret scanning (reuses secret patterns from scanning pipeline)
- PII detection (emails, phone numbers, SSNs, credit cards)
- File-level sensitivity policy (glob-based classification)
- Redaction mode (typed placeholders like `[REDACTED:aws_key]`)

**Source-confirmed:** `scanOutbound()` calls `dlp.scanOutbound()`. Redaction engine exists in `dlp/redact.ts`.

### 5.5 Prompt Injection Detection

Files ingested as context are scanned for embedded manipulation instructions:
- Role-override attempts ("Ignore previous instructions")
- System prompt markers
- Unicode tricks (invisible chars, bidirectional overrides)
- Encoded instructions (base64 in comments)
- Dependency metadata poisoning

**Source-confirmed:** `injection/` directory exists with `index.ts` and `patterns.ts`.

### 5.6 Audit Trail

Append-only SQLite audit log with content hashing:
- `security_event` table: type, severity, action_taken, content_hash, session/message/tool IDs
- `scan_result` table: per-finding results linked to events
- `policy_decision` table: policy evaluation results and overrides
- Configurable retention (default 90 days)

**Source-confirmed:** `audit/` directory has `index.ts`, `schema.sql.ts` with all three tables, and `query.ts`.

### 5.7 Policy Engine

Declarative YAML configuration at `lockedcode.yaml`:
- Three strictness levels (strict / standard / permissive)
- Path, command, network, dependency, model, and sensitivity rule categories
- Hierarchy: built-in → XDG global → project → session override
- Zod-validated schema with sensible defaults

**Source-confirmed:** `policy/` directory with `index.ts` (PolicyService) and `schema.ts` (Zod schema).

### 5.8 Trust Scoring

Risk scores (0–100) drive approval UX:
- Low-risk actions (file rename): auto-approve
- Medium-risk actions (shell commands): log with notification
- High-risk actions (outside-project paths): require explicit approval
- Critical-risk actions (curl|bash): hard block
- Session-level trust decay and per-model trust history

**Source-confirmed:** `trust/` directory with `index.ts`. Score thresholds referenced in policy schema.

### 5.9 V2+ Features (Deferred but Module Structure Exists)

The Architecture doc marks these as V2, but **all have directory stubs** in the codebase:

| Feature | Directory | Architecture doc status |
|---|---|---|
| Model provenance | `provenance/` | V2 deferred |
| Model registry | `registry/` | V2 deferred |
| Dependency vetting | `dependency/` | V2 deferred |
| SIEM integration | `siem/` | V2 deferred |
| Compliance reports | `compliance/` | V2 deferred |
| License detection | `license/` | V2 deferred |
| Session replay | `session/` | V2 deferred |
| Custom rule authoring | `rules/` | V2 deferred |
| Rollback & quarantine | `quarantine/` | V2 deferred |
| Runtime monitoring | `monitor/` | V2 deferred |
| Air-gap mode | `airgap/` | Phase 5 |
| TUI security indicators | `tui/` | Phase 6 |

This is unusual — deferred features having full directory stubs suggests either **automated scaffolding** or a **design-document-first** approach where the repo was populated from the architecture doc before implementation.

### 5.10 Telemetry

**None detected.** This is the most significant finding for the OCP comparison:

| Fork | Telemetry |
|---|---|
| **ZCode** | Always-on Alibaba ARMS + Z.AI servers, no opt-out |
| **Kilo** | PostHog US, on by default, opt-out via config/env |
| **MiMo** | Xiaomi metrics (`tracking.miui.com`), on by default, env opt-out |
| **LockedCode** | **No telemetry endpoint, no analytics package, no phone-home detected** |

LockedCode deliberately ships **no** analytics, no PostHog, no tracking endpoints. The Charter explicitly states "no cloud dependencies, no update checks, no telemetry, no phone-home" as an air-gap mode requirement. The Architecture doc mentions `@opentelemetry/*` as inherited from OpenCode (for local tracing, not telemetry shipping).

### 5.11 Default Providers

**None added.** LockedCode inherits OpenCode's 18+ provider SDKs unchanged. There is no LockedCode gateway, no default model, no auto-routing. The product is BYO-model by design — you choose a model (frontier or self-hosted) and the security layer treats it as untrusted.

---

## 6. What OpenCode Has That LockedCode Does Not Emphasize / Match

| Area | OpenCode today | LockedCode |
|---|---|---|
| **Upstream activity** | Very high PR volume, daily releases | Fork base `dcdbdb2` from pre-May 2026; no visible upstream merge since |
| **Community scale** | ~187k stars, massive ecosystem | ~5 stars, no community |
| **Package modularity** | Split `core` / `protocol` / `llm` / `tui` | Fat `packages/opencode` (closer to older tree shape) |
| **Desktop/web product** | Active development | Inherited packages exist, not LockedCode-specific |
| **Plugin ABI support** | `@opencode-ai/plugin` | Inherited unchanged (+ plugin lockdown default) |
| **Long-horizon features** | No equivalent | Not MiMo-depth (no goal judge, max-mode, dream/distill, compose workflows) |
| **IDE productization** | Growing VS Code extension | Inherited SDK only |

---

## 7. Branding, Config, and Runtime Renames

| Concern | OpenCode | LockedCode |
|---|---|---|
| Env prefix | `OPENCODE_*` | `OPENCODE_*` and `LOCKEDCODE_*` (dual) |
| Config schema host | opencode.ai | lockedcode.ai |
| Data dir | XDG `opencode` | XDG `lockedcode` (`.opencode/` still read for backward compat) |
| npm package | `opencode-ai` | `lockedcode` |
| CLI binary | `opencode` | `lockedcode` |
| Install | `opencode.ai/install` | `lockedcode.ai` (README: install links **not yet working**) |
| Default agents | build / plan | **Same** (no new LockedCode agents) |
| Plugin default | Enabled | **Disabled by default** (`--allow-plugins` flag required) |

LockedCode env flags (confirmed or described):
- `OPENCODE_PURE` — disables plugins (inherited)
- No `LOCKEDCODE_*` env overrides detected in source (minimal env surface)

---

## 8. The SANDBOX-AUDIT Findings (Important)

An internal audit dated 2026-05-15 found **critical gaps in the confinement model**. The audit is remarkably transparent for such an early-stage project — it's committed to the repo alongside the charter.

**The core issue:** Confinement is enforced on user-facing tool operations (read/write/edit/shell) but **entirely absent** from the tool's own internal subsystems:

| # | Subsystem | Escapes To | Severity | Recommendation |
|---|---|---|---|---|
| 1 | Template system | `~/.lockedcode/templates/` | **CRITICAL** | Route through confinement or remove home-dir access |
| 2 | Remote template fetch | `entry.name` path traversal | **CRITICAL** | Validate `entry.name`, add integrity verification |
| 3 | Custom rules loader | `~/.lockedcode/custom-rules/` | **HIGH** | Remove or gate home-dir access |
| 4 | Policy loader | `~/.config/lockedcode/policy.json` | **MEDIUM** | Require explicit user consent |
| 5 | Config variable expansion | `{file:~/path}` reads arbitrary files | **MEDIUM** | Apply `Confinement.checkPath()` |
| 6 | CLI database | `~/.local/share/lockedcode/*.db` | **LOW** | Document intentional home-dir paths |

**Impact:** An adversary who can write to `~/.lockedcode/` (via the template system's unconfined access) can:
1. Inject malicious rules into the scanning pipeline (rules loader has no confinement)
2. Modify global policy to disable security features (policy loader has no confinement)
3. Plant prompt injection patterns in custom rules that get compiled at runtime

The audit includes concrete recommendations for each finding. The project has not pushed since the audit was committed.

---

## 9. Comparison Snapshot

| | OpenCode | Kilo | MiMo | ZCode | LockedCode |
|---|---|---|---|---|---|
| **Source** | Open MIT | Open MIT | Open MIT + restrictions | Closed Electron | Open MIT |
| **Stars** | ~187k | ~26k | ~12k | ? | **~5** |
| **Maturity** | Mature, daily active | Mature, active | Young, active | Mature, active | **Pre-release** (2mo stale) |
| **Telemetry** | None/OTEL | PostHog, on by default | Xiaomi, on by default | ARMS+Z.AI, no opt-out | **None deliberate** |
| **Default inference** | BYO | Kilo Gateway | MiMo Auto / Xiaomi | Chinese catalog | **BYO (inherited)** |
| **Plugin host class** | `@opencode-ai/plugin` | `@kilocode/plugin` (OC-class) | OC-class fork | `.zcode-plugin` (marketplace) | **`@opencode-ai/plugin` (inherited OC-class)** |
| **Plugin default** | Enabled | Enabled | Enabled | Enabled | **Disabled by default** (`--allow-plugins`) |
| **Security layer** | OpenCode's own permission system | Sandbox, memory, indexing | Memory, checkpoint, goal | None (marketplace ABI only) | **Comprehensive: confinement, scanning, DLP, audit, policy, SIEM** |
| **Unique strength** | Community hub, neutral upstream | Multi-client IDE + Gateway | Long-horizon autonomy | China market + 17 agents | **Security-hardened for corporate "untrusted model" use** |

---

## 10. Summary: Changed vs Improved

### Changed (fork deltas)

1. **Rebrand** — CLI, npm package, config paths, domain → LockedCode
2. **Security interception** — every tool invocation passes through SecurityService
3. **Plugin lockdown** — external plugins default `off` (pure mode)
4. **Confidentiality posture** — no telemetry, no phone-home, air-gap by design
5. **Server auth** — random auth token generated on startup by default
6. **No mDNS** — server never advertises on network (unchanged from OpenCode? OpenCode does have mDNS via `bonjour-service`)

### Improved / net-new relative to stock OpenCode

1. **OS-level project-root jail** — Landlock (Linux), sandbox-exec (macOS), restricted tokens (Windows)
2. **Seven-scanner static analysis pipeline** — Semgrep, YARA, entropy, secrets, injection, custom rules, license
3. **Shell command structural analysis** — tree-sitter parsing, hard-blocked patterns, path extraction
4. **Outbound DLP** — secrets and PII scanning before content reaches the LLM
5. **Prompt injection detection** — scanning ingested files for manipulation attempts
6. **Immutable, content-hashed audit trail** — with SIEM export and compliance reporting
7. **Declarative policy engine** — YAML config with hierarchy and sensible defaults
8. **Trust scoring** — risk-driven approval UX with session decay and per-model history
9. **Multi-agent security cascade** — policies inherited, no privilege escalation
10. **Model provenance tracking** — per-file attribution of which model wrote what
11. **Model registry with approval/blocking** — centralized control
12. **Custom rule authoring SDK** — organization-specific scanning rules with test framework
13. **Dependency vetting** — typosquatting detection across 9 package managers
14. **Rollback & quarantine** — automated response for post-write security issues
15. **Runtime monitoring** — eBPF syscall analysis (V2)
16. **License contamination detection** — copyleft detection in generated code
17. **Air-gap mode** — fully offline with bundled rule sets
18. **Architecture documentation** — the most detailed design doc of any reviewed fork (14k+ words)

### Not improved (compared to other forks)

1. **Community** — tiny project, no visible contributors, no issue activity
2. **Upstream sync** — no visible merge discipline (no `kilocode_change` markers, no CI guards)
3. **Product breadth** — no Kilo-style IDE clients, no MiMo-style long-horizon harness
4. **Implementation gaps** — SANDBOX-AUDIT critical findings unaddressed; repo stale 2 months
5. **Security layer completeness** — all modules exist as directory stubs but only core SecurityService, confinement, scanning, DLP, audit, policy, and trust have meaningful implementation; the remaining 12+ modules may be scaffolding only

---

## 11. Bottom Line

LockedCode is an **OpenCode fork re-architected for adversarial-model threat modeling**: OS-level confinement, multi-scanner analysis, outbound DLP, immutable audit, and declarative policy — treating every LLM output as potentially compromised.

Its architecture document is the most thorough design of any reviewed fork. The codebase has module stubs for every feature described, with meaningful implementation in the core 8 modules (confinement, scanning, DLP, injection, secrets, audit, policy, trust). However, the project is at **pre-release maturity**: 5 stars, 0 forks, 2 months stale, with a committed internal audit documenting critical confinement gaps in its own subsystems, and at least 12 of 20+ security module directories may be empty or near-empty scaffolding.

If OpenCode is the general open agent platform, Kilo is the multi-client commercial gateway, MiMo is the long-horizon research harness, and ZCode is the Chinese closed ecosystem — LockedCode is the **security-first, trust-no-model** fork. Its value proposition is compelling for a specific audience (corporate teams with non-frontier models) but its current execution has not yet delivered on the architecture's ambition.

**For OCP plugin compatibility:** LockedCode is the best host class among all reviewed forks — it inherits `@opencode-ai/plugin` **unchanged** from OpenCode (unlike ZCode's `.zcode-plugin` marketplace ABI). A LockedCode build would run OpenCode npm plugins with zero ABI adaptation. The only caveat is plugin lockdown: plugins default to `--allow-plugins` opt-in, which is a LockedCode-specific policy decision, not an ABI incompatibility.
