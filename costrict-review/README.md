# CoStrict Review

Comparison of [CoStrict](https://github.com/zgsm-ai/costrict) (Sangfor) against upstream [OpenCode](https://github.com/anomalyco/opencode), with cross-notes vs MiMo, Kilo, and ZCode.

See **[COSTRICT_RESEARCH.md](COSTRICT_RESEARCH.md)** — lineage (Cline → Roo Code → CoStrict, **not** an OpenCode fork), Strict Mode workflow, server-side RAG code review, completion agent, CoStrict Cloud, workspace-trust hardening, and the two-channel + raw-store telemetry posture.

**Bottom line:** CoStrict is a vendor (Sangfor) fork of **Roo Code** for enterprise governance — "Strict AI Coder for Enterprises" — differentiated by a server-assisted strict engineering workflow (requirements → design → tasks → test/self-repair via `.cospec/` docs), repo-wide RAG code review, local-agent inline completion, and real security hardening (Workspace Trust for project MCP/custom tools). It shares **no runtime code with OpenCode** and has **no OpenCode-class plugin ABI**; the comparison is product-level.

**Telemetry:** PostHog **on by default** (`ph.roocode.com`), plus a **server-controlled** CoStrict metrics channel (`zgsm.sangfor.com/user-indicator/...`), plus a **raw conversation + code-diff uploader** in CoStrict Cloud mode that does **not** follow the telemetry opt-in. Most aggressive default-data posture of the four reviewed forks after ZCode — see [COSTRICT_RESEARCH.md §8](COSTRICT_RESEARCH.md#8-network--telemetry--privacy). `DISABLE_USER_INDICATOR=1` + settings opt-out + BYO provider (no Cloud login) is the way to keep data local.
