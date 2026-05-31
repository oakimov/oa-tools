# Web Chat

A ChatGPT-like web interface and CLI client for OpenAI, Anthropic, and OpenAI-compatible API providers.

## Features

- **Web UI** — Streamed chat responses with markdown rendering, dark/light theme, model auto-discovery via [models.dev](https://models.dev)
- **CLI client** — Interactive and single-prompt modes with streaming support
- **Auto-detection** — Provider and model endpoint derived from the API URL and catalog metadata (`npm` package, per-model compatibility)
- **Multi-provider** — OpenAI, Anthropic, and any OpenAI-compatible provider from the catalog
- **Markdown rendering** — Chat messages rendered with full markdown (code blocks, headings, links, etc.)

## Usage

### Web UI

```bash
node web.mjs             # default port 3000
PORT=8080 node web.mjs   # custom port
```

Open http://localhost:3000 in your browser.

**Settings panel** (gear icon):
- **API URL** — Full endpoint URL (e.g. `https://api.openai.com/v1/chat/completions`)
- **Provider** — Auto-detected from URL, or select from the catalog dropdown
- **Model** — Picked from the provider's model list, or type any custom model ID
- **API Key** — Paste your key or use `$ENV_VAR_NAME` to resolve from server environment
- **Temperature / Top-K / Max Tokens** — Adjust generation parameters
- **System Prompt** — Set context for the assistant

**Shortcuts:**
- `Enter` — Send message
- `Shift+Enter` — Newline in input
- Theme toggle (moon/sun icon) — Switch dark/light mode

The provider catalog is fetched automatically from [models.dev](https://models.dev). When you change the URL, the provider and model list update accordingly.

### CLI

```bash
# Interactive mode — requires API_KEY env var
export API_KEY=sk-...
node cli.mjs

# Single prompt (non-interactive)
node cli.mjs --prompt "Hello" --model gpt-4o

# Pipe mode (read prompt from stdin)
echo "Explain quantum computing" | node cli.mjs

# Custom provider / endpoint
node cli.mjs --provider anthropic --model claude-sonnet-4-20250514

# Disable streaming for raw JSON output
node cli.mjs --no-stream --prompt "Hi"

# All options
node cli.mjs --help
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | — | API key (required) |
| `API_PROVIDER` | `openai` | Provider: `openai`, `anthropic`, `responses` |
| `API_URL` | provider default | Full endpoint URL |
| `MODEL_NAME` | provider default | Model identifier |
| `SYSTEM_MESSAGE` | `You are a helpful assistant.` | System prompt |

**Interactive commands** (type `/help` inside the CLI):

| Command | Description |
|---------|-------------|
| `/model <name>` | Switch model |
| `/provider <name>` | Switch provider |
| `/url <url>` | Change API endpoint |
| `/api-key <key>` | Update API key |
| `/system <text>` | Change system prompt |
| `/temperature <n>` | Set temperature (0.0–2.0) |
| `/max-tokens <n>` | Set max tokens |
| `/stream on\|off` | Toggle streaming |
| `/reset` | Clear conversation history |
| `/status` | Show current configuration |
| `/quit` / `/exit` | Exit |

### Qwen API Proxy

A standalone proxy that forwards OpenAI-compatible requests to [qwen.aikit.club](https://qwen.aikit.club), using a Qwen access token extracted from [chat.qwen.ai](https://chat.qwen.ai). No API keys required — just a free Qwen account.

```bash
node qwen-proxy.mjs            # default port 4000
PORT=5000 node qwen-proxy.mjs  # custom port
```

#### Authentication

1. Open http://localhost:4000 in your browser
2. Click **"Open chat.qwen.ai"** and sign in to your Qwen account
3. Drag the **"Get Qwen Token"** bookmarklet to your browser's bookmarks bar
4. While still on the Qwen page, click the bookmarklet — it copies your access token and redirects back to the proxy page
5. The token is auto-detected from the URL hash and saved

**Manual fallback:** Run `copy(localStorage.getItem('token'))` in Qwen's dev console (`F12`), then paste into the proxy form.

#### Usage with any OpenAI client

Once authenticated, the proxy exposes standard OpenAI endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completions (streaming and non-streaming) |
| `/v1/models` | GET | List available Qwen models |
| `/v1/images/generations` | POST | Image generation |
| `/v1/images/edits` | POST | Image editing |
| `/v1/videos/generations` | POST | Video generation |
| `/auth` | GET/POST | View or update token |
| `/forget` | GET | Clear saved token |
| `/status` | GET | Auth status |

**Example with curl:**

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.7-max","messages":[{"role":"user","content":"Hello"}]}'
```

**Example with web-chat:**
1. Start the proxy: `node qwen-proxy.mjs`
2. Start the web UI: `node web.mjs` (different terminal)
3. In the web UI settings, set URL to `http://localhost:4000/v1/chat/completions` and any placeholder for API key

**Token validation and auto-refresh:**
- On submission, the token is validated against `qwen.aikit.club/v1/validate` — the returned (potentially refreshed) token is saved, not the raw input.
- The proxy runs a background check every 30 minutes. If the token's JWT `exp` is within 6 hours, it calls `qwen.aikit.club/v1/refresh` to extend the session.
- On a 401 response from the upstream, the proxy attempts one refresh before declaring the token expired.
- The token is cached in `~/.qwen-token.json` and persists across restarts.

## Files

| File | Purpose |
|------|---------|
| `cli.mjs` | Standalone CLI chat client |
| `web.mjs` | Web UI server |
| `api-client.mjs` | Shared API client (streaming, payload, headers) |
| `qwen-proxy.mjs` | OpenAI-compatible proxy for Qwen API |
| `public/` | Frontend assets (HTML, CSS, JS) |
| `ollama_summary.md` | Ollama Cloud model test results |
