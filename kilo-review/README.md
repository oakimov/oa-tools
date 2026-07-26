# Kilo Code Review

Comparison of [Kilo Code](https://github.com/Kilo-Org/kilocode) against upstream [OpenCode](https://github.com/anomalyco/opencode), with cross-notes vs MiMo and ZCode.

See **[KILO_RESEARCH.md](KILO_RESEARCH.md)** — dual lineage (Cline/Roo → OpenCode rebuild), what Kilo kept, what it added, telemetry/gateway posture, and how it differs from OpenCode / peer forks today.

**Bottom line:** Kilo is a commercial open-source agentic platform whose **CLI is an actively maintained OpenCode fork** (`@kilocode/cli`, `kilocode_change` merge discipline), powering VS Code, JetBrains, CLI, and cloud clients — productized around Kilo Gateway (zero-markup routing), sandbox, memory, and indexing, not a long-horizon-only harness (MiMo) or a closed China Electron fork (ZCode).

**Telemetry:** PostHog **on by default**, with first-party opt-out — see [KILO_RESEARCH.md §7.1](KILO_RESEARCH.md#71-posthog-product-analytics) (`experimental.openTelemetry: false` and/or `KILO_TELEMETRY_LEVEL=off`).