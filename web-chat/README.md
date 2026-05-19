# Web Chat

A ChatGPT-like web interface and CLI client for OpenAI, Anthropic, and OpenAI-compatible API providers.

## Features

- **Web UI** — Streamed chat responses, dark/light theme, model auto-discovery via [models.dev](https://models.dev)
- **CLI client** — Interactive and single-prompt modes with streaming support
- **Auto-detection** — Provider and model endpoint derived from the API URL and catalog metadata (`npm` package, per-model compatibility)
- **Multi-provider** — OpenAI, Anthropic, and any OpenAI-compatible provider from the catalog

## Usage

### Web UI

```bash
node web.mjs             # default port 3000
PORT=8080 node web.mjs   # custom port
```

Open http://localhost:3000, configure the API endpoint and key, then start chatting.

### CLI

```bash
# Interactive mode
export API_KEY=sk-...
node cli.mjs

# Single prompt
node cli.mjs --prompt "Hello" --model gpt-4o

# All options
node cli.mjs --help
```

## Files

| File | Purpose |
|------|---------|
| `cli.mjs` | Standalone CLI chat client |
| `web.mjs` | Web UI server |
| `api-client.mjs` | Shared API client (streaming, payload, headers) |
| `public/` | Frontend assets (HTML, CSS, JS) |
