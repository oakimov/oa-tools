# MiMo Code Review

Comparison of [MiMo Code](https://github.com/XiaomiMiMo/MiMo-Code) (Xiaomi) against upstream [OpenCode](https://github.com/anomalyco/opencode), with cross-notes vs Kilo and ZCode.

See **[MIMO_RESEARCH.md](MIMO_RESEARCH.md)** — architecture lineage, what MiMo kept, what it added/changed, and how it differs from OpenCode / peer forks today.

**Bottom line:** MiMo is a TUI-first OpenCode fork optimized for long-horizon agent work (memory, checkpoints, compose/workflows, `/goal`, max-mode, dream/distill), rebranded to `@mimo-ai/*` with Xiaomi-hosted defaults — not a ground-up rewrite. Plugin host class matches OpenCode/Kilo (in-process npm plugins), not ZCode’s `.zcode-plugin` marketplace.
