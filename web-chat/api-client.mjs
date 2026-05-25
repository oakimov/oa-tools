// ── API Client ────────────────────────────────────────────────────────────────
// Shared by cli.mjs and web.mjs

export const DEFAULT_PROVIDER = 'openai';
export const DEFAULT_MODEL = {
  openai: 'gpt-4o',
  anthropic: 'claude-sonnet-4-20250514',
  responses: 'gpt-4o',
};
export const DEFAULT_SYSTEM = 'You are a helpful assistant.';
export const DEFAULT_TEMPERATURE = 0.7;
export const DEFAULT_MAX_TOKENS = 4096;
export const DEFAULT_TIMEOUT = 120_000;

export function buildHeaders(config) {
  const base = { 'Content-Type': 'application/json', Accept: 'application/json' };
  if (config.provider === 'google') {
    return { ...base, 'x-goog-api-key': config.apiKey };
  }
  if (config.provider === 'anthropic') {
    return {
      ...base,
      'x-api-key': config.apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    };
  }
  return { ...base, Authorization: `Bearer ${config.apiKey}` };
}

export function googleEndpoint(model, stream) {
  const base = 'https://generativelanguage.googleapis.com/v1';
  return stream
    ? `${base}/models/${model}:streamGenerateContent?alt=sse`
    : `${base}/models/${model}:generateContent`;
}

export function buildPayload(config, messages) {
  const topK = Number.isInteger(config.topK) && config.topK >= 0 ? config.topK : null;
  if (config.provider === 'google') {
    const contents = messages.map(m => ({
      role: m.role === 'assistant' ? 'model' : 'user',
      parts: [{ text: m.content }],
    }));
    const payload = { contents };
    if (config.system) payload.systemInstruction = { parts: [{ text: config.system }] };
    payload.generationConfig = {};
    if (config.temperature != null) payload.generationConfig.temperature = config.temperature;
    if (config.maxTokens != null) payload.generationConfig.maxOutputTokens = config.maxTokens;
    if (topK != null) payload.generationConfig.topK = topK;
    return payload;
  }
  if (config.provider === 'anthropic') {
    return {
      model: config.model,
      max_tokens: config.maxTokens ?? DEFAULT_MAX_TOKENS,
      messages,
      system: config.system ?? DEFAULT_SYSTEM,
      ...(config.temperature != null ? { temperature: config.temperature } : {}),
      ...(topK != null ? { top_k: topK } : {}),
      ...(config.stream ? { stream: true } : {}),
    };
  }
  if (config.provider === 'responses') {
    const input = [];
    if (config.system) input.push({ role: 'system', content: config.system });
    input.push(...messages);
    return {
      model: config.model,
      input,
      text: { format: { type: 'text' } },
      ...(config.temperature != null ? { temperature: config.temperature } : {}),
      ...(config.stream ? { stream: true } : {}),
    };
  }
  // OpenAI
  return {
    model: config.model,
    temperature: config.temperature ?? DEFAULT_TEMPERATURE,
    max_tokens: config.maxTokens ?? DEFAULT_MAX_TOKENS,
    messages: [
      ...(config.system ? [{ role: 'system', content: config.system }] : []),
      ...messages,
    ],
    stream: config.stream ?? true,
  };
}

export async function chatNonStreaming(config, messages) {
  const payload = buildPayload(config, messages);
  const headers = buildHeaders(config);
  const endpoint = config.provider === 'google' ? googleEndpoint(config.model, false) : config.url;
  const response = await fetch(endpoint, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(config.timeout ?? DEFAULT_TIMEOUT),
  });
  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    throw new Error(`API error ${response.status}: ${errorText}`);
  }
  const data = await response.json();
  if (config.provider === 'google') {
    return { text: data.candidates?.[0]?.content?.parts?.[0]?.text || '', data };
  }
  if (config.provider === 'anthropic') {
    return { text: data.content?.[0]?.text || '', data };
  }
  if (config.provider === 'responses') {
    return { text: data.output?.[0]?.content?.[0]?.text || '', data };
  }
  return { text: data.choices?.[0]?.message?.content || '', data };
}

export async function* chatStreaming(config, messages) {
  const payload = buildPayload(config, messages);
  const headers = buildHeaders(config);
  if (config.provider === 'google' || config.provider === 'anthropic') {
    headers['Accept'] = 'text/event-stream';
  }

  const endpoint = config.provider === 'google' ? googleEndpoint(config.model, true) : config.url;
  const response = await fetch(endpoint, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(config.timeout ?? DEFAULT_TIMEOUT),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    throw new Error(`API error ${response.status}: ${errorText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        if (config.provider === 'google') {
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            if (jsonStr === '[DONE]') return;
            try {
              const obj = JSON.parse(jsonStr);
              if (obj.error) throw new Error(obj.error.message || 'Google API error');
              const text = obj.candidates?.[0]?.content?.parts?.[0]?.text;
              if (text) yield text;
            } catch (e) {
              if (!(e instanceof SyntaxError)) throw e;
            }
          }
        } else if (config.provider === 'anthropic') {
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            if (jsonStr === '[DONE]') return;
            try {
              const obj = JSON.parse(jsonStr);
              if (obj.type === 'content_block_delta' && obj.delta?.type === 'text_delta') {
                yield obj.delta.text;
              }
            } catch {}
          }
        } else if (config.provider === 'responses') {
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            if (jsonStr === '[DONE]') return;
            try {
              const obj = JSON.parse(jsonStr);
              if (obj.type === 'response.output_text.delta' && obj.delta) {
                yield obj.delta;
              }
            } catch {}
          }
        } else {
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            if (jsonStr === '[DONE]') return;
            try {
              const obj = JSON.parse(jsonStr);
              if (obj.choices?.[0]?.delta?.content) {
                yield obj.choices[0].delta.content;
              }
            } catch {}
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Detect provider type from an API endpoint URL.
 */
export function detectProvider(url) {
  if (!url) return 'openai';
  const u = url.toLowerCase();
  if (u.includes('googleapis.com') || u.includes('generativelanguage')) return 'google';
  if (u.includes('anthropic.com')) return 'anthropic';
  if (u.includes('/responses')) return 'responses';
  if (u.includes('openai.com') || u.includes('api.openai')) return 'openai';
  return 'openai';
}

/**
 * Parse the models.dev/api.json endpoint to extract providers and models.
 */
export async function fetchModelCatalog() {
  const response = await fetch('https://models.dev/api.json', {
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error(`Models API: ${response.status}`);
  const data = await response.json();
  return normalizeModelCatalog(data);
}

function normalizeModelCatalog(raw) {
  // Array of model objects
  if (Array.isArray(raw)) {
    const providers = {};
    for (const entry of raw) {
      const pid = entry.provider || entry.provider_id || 'unknown';
      if (!providers[pid]) {
        providers[pid] = { id: pid, name: entry.provider_name || pid, base_url: entry.base_url || '', env: [], npm: '', models: [] };
      }
      providers[pid].models.push({
        id: entry.id || entry.model || entry.model_id,
        name: entry.name || entry.id || entry.model || 'unknown',
        npm: entry.provider?.npm || '',
        deprecated: entry.status === 'deprecated',
      });
    }
    return { providers: Object.values(providers) };
  }

  // Flat { provider_id: { id, name, api, models: { model_id: {...} } } } format
  if (raw && typeof raw === 'object' && !raw.providers && !raw.models) {
    const entries = Object.entries(raw).filter(
      ([_, p]) => p && typeof p === 'object' && p.id && p.name
    );
    if (entries.length > 0) {
      const providers = entries.map(([id, p]) => ({
        id: p.id || id,
        name: p.name || id,
        base_url: p.api || p.base_url || '',
        env: Array.isArray(p.env) ? p.env : [],
        npm: p.npm || '',
        models: p.models && typeof p.models === 'object'
          ? Object.values(p.models).map(m => ({
              id: m.id || m.model || 'unknown',
              name: m.name || m.id || m.model || 'unknown',
              npm: m.provider?.npm || '',
              deprecated: m.status === 'deprecated',
            }))
          : [],
      }));
      return { providers };
    }
  }

  // { providers: { ... } } format
  if (raw.providers) {
    const providers = Object.entries(raw.providers).map(([id, p]) => ({
      id,
      name: p.name || id,
      base_url: p.base_url || '',
      env: Array.isArray(p.env) ? p.env : [],
      npm: p.npm || '',
      models: Array.isArray(p.models)
        ? p.models.map(m => (typeof m === 'string' ? { id: m, name: m, npm: '' } : { id: m.id || m.model, name: m.name || m.id || m.model, npm: m.provider?.npm || '', deprecated: m.status === 'deprecated' }))
        : [],
    }));
    return { providers };
  }

  // { models: [...] } format
  if (raw.models && Array.isArray(raw.models)) {
    return normalizeModelCatalog(raw.models);
  }

  return { providers: [] };
}
