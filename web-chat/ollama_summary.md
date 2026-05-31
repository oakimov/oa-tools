# Ollama Free Cloud Models Test Results

All 39 models from the `ollama-cloud` provider tested via the web-chat client against `https://ollama.com/v1/chat/completions` using a free tier `$OLLAMA_API_KEY`.

---

## ✅ Working (16 models)

| Model | Notes |
|-------|-------|
| gemma3:27b | |
| gemma3:12b | |
| gemma3:4b | |
| gemma4:31b | |
| qwen3-vl:235b | |
| qwen3-vl:235b-instruct | |
| qwen3-coder-next | |
| qwen3-coder:480b | |
| ministral-3:14b | |
| ministral-3:8b | |
| ministral-3:3b | |
| devstral-2:123b | |
| devstral-small-2:24b | |
| cogito-2.1:671b | |
| rnj-1:8b | |
| glm-4.7 | |

## 🔒 403 Forbidden (14 models)

All returned: *"this model requires a subscription, upgrade for access"*

| Model | Error |
|-------|-------|
| kimi-k2:1t | subscription required |
| kimi-k2-thinking | subscription required |
| kimi-k2.5 | subscription required |
| kimi-k2.6 | subscription required |
| deepseek-v3.2 | subscription required |
| deepseek-v3.1:671b | subscription required |
| deepseek-v4-flash | subscription required |
| deepseek-v4-pro | subscription required |
| gemini-3-flash-preview | subscription required |
| mistral-large-3:675b | subscription required |
| qwen3.5:397b | subscription required |
| minimax-m2.7 | subscription required |
| glm-5 | subscription required |
| glm-5.1 | subscription required |

## ❓ Other Failures (9 models)

HTTP 200 but response body was not valid JSON (empty or unexpected format).

| Model |
|-------|
| glm-4.6 |
| nemotron-3-super |
| nemotron-3-nano:30b |
| qwen3-next:80b |
| gpt-oss:20b |
| gpt-oss:120b |
| minimax-m2 |
| minimax-m2.1 |
| minimax-m2.5 |

---

## Summary

| Category | Count |
|----------|-------|
| Working | 16 |
| 403 (subscription) | 14 |
| Other failures | 9 |
| **Total** | **39** |
