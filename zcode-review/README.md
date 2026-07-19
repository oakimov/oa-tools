# ZCode Review

Security audit of ZCode (initially 3.2.5; plugin ABI follow-up 3.3.6 / 2026-07-19), a Chinese AI coding app forked from OpenCode’s architecture.

See **[ZCODE_RESEARCH.md](ZCODE_RESEARCH.md)** — origin, telemetry, network endpoints, privacy controls, providers, and **§7 plugin marketplace ABI** (public repos `glm-hammer`, `zcode-glm-fleet`).

**Bottom line:** Always-on telemetry to Chinese cloud infrastructure with no opt-out. Plugin system is Claude-/Codex-style `.zcode-plugin`, not `@opencode-ai/plugin`.
