# ZCode Review

Security and architecture notes on ZCode (initially 3.2.5; plugin ABI follow-up 3.3.6 / 2026-07-19), for comparison with OpenCode, MiMo, and Kilo.

See **[ZCODE_RESEARCH.md](ZCODE_RESEARCH.md)** — origin, telemetry, network endpoints, privacy controls, providers, and **§7–§9 plugin model vs OpenCode/MiMo/Kilo**.

**Bottom line:** Always-on telemetry to Chinese cloud infrastructure with no opt-out. Plugin system is Claude-/Codex-style `.zcode-plugin` — not the `@opencode-ai/plugin` runtime that OpenCode, MiMo, and Kilo share.
