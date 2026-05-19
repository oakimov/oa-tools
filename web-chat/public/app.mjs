const state = {
  providers: [],
  messages: [],
  streaming: false,
  theme: localStorage.getItem('theme') || 'light',
  showDeprecated: localStorage.getItem('showDeprecated') === 'true',
};

const $ = (s) => document.querySelector(s);
const el = {
  settingsPanel: $('#settingsPanel'),
  settingsToggle: $('#settingsToggle'),
  themeToggle: $('#themeToggle'),
  apiUrl: $('#apiUrl'),
  providerSelect: $('#providerSelect'),
  modelSelect: $('#modelSelect'),
  modelInput: $('#modelInput'),
  apiKey: $('#apiKey'),
  temperature: $('#temperature'),
  temperatureVal: $('#temperatureVal'),
  topK: $('#topK'),
  topKVal: $('#topKVal'),
  maxTokens: $('#maxTokens'),
  systemPrompt: $('#systemPrompt'),
  chatInner: $('#chatInner'),
  emptyState: $('#emptyState'),
  messageInput: $('#messageInput'),
  sendBtn: $('#sendBtn'),
};

const KNOWN_ENDPOINTS = {
  openai: 'https://api.openai.com/v1/chat/completions',
  anthropic: 'https://api.anthropic.com/v1/messages',
  responses: 'https://api.openai.com/v1/responses',
};

// npm package → known API base URL (for providers missing base_url in catalog)
const NPM_BASE_URLS = {
  "@ai-sdk/mistral": "https://api.mistral.ai/v1",
  "@ai-sdk/togetherai": "https://api.together.xyz/v1",
  "@ai-sdk/perplexity": "https://api.perplexity.ai/v1",
  "@ai-sdk/groq": "https://api.groq.com/openai/v1",
  "@ai-sdk/xai": "https://api.x.ai/v1",
  "@ai-sdk/deepinfra": "https://api.deepinfra.com/v1/openai",
  "@ai-sdk/cohere": "https://api.cohere.ai/v1",
  "@ai-sdk/cerebras": "https://api.cerebras.ai/v1",
  "@ai-sdk/google": "https://generativelanguage.googleapis.com/v1",
};

function endpointSuffix(npm) {
  if (!npm) return '/chat/completions';
  const n = npm.toLowerCase();
  if (n.includes('anthropic') || n.includes('vertex-ai')) return '/messages';
  return '/chat/completions';
}

function catalogProvider(pid) {
  return state.providers.find(p => p.id === pid);
}

function modelNpm(pid, mid) {
  const cp = catalogProvider(pid);
  if (!cp) return null;
  const m = cp.models.find(x => x.id === mid);
  return (m && m.npm) || null;
}

function completeEndpoint(pid, mid) {
  const known = KNOWN_ENDPOINTS[pid];
  if (known) return known;

  const cp = catalogProvider(pid);
  if (!cp) return '';
  let url = cp.base_url;
  if (!url) {
    url = NPM_BASE_URLS[cp.npm] || '';
  }
  if (!url) return '';

  url = url.replace(/\/+$/, '');
  if (/\/chat\/completions$|\/messages$|\/responses$/.test(url)) return url;

  const mnpm = mid ? modelNpm(pid, mid) : null;
  const effective = mnpm || cp.npm;
  return url + endpointSuffix(effective);
}

function detectProviderFromUrl(url) {
  if (!url) return null;
  const u = url.toLowerCase();
  if (u.includes('anthropic.com')) return 'anthropic';
  if (u.includes('/responses')) return 'responses';
  if (u.includes('openai.com')) return 'openai';
  return null;
}

function matchProviderFromCatalog(url, providers) {
  if (!url || !providers.length) return null;
  let best = null, bestLen = 0;
  for (const p of providers) {
    if (p.base_url && url.startsWith(p.base_url) && p.base_url.length > bestLen) {
      best = p;
      bestLen = p.base_url.length;
    }
  }
  return best;
}

function updateProviderFromUrl(url) {
  const cm = matchProviderFromCatalog(url, state.providers);
  const ud = detectProviderFromUrl(url);
  const pid = cm ? cm.id : (ud || el.providerSelect.value);
  el.providerSelect.value = pid;
  populateModelSelect(pid);
  updateApiKeyHint(pid);
}

function populateModelSelect(providerId) {
  const sel = el.modelSelect;
  sel.innerHTML = '<option value="">Select a model…</option>';
  const provider = catalogProvider(providerId);
  if (provider && provider.models.length) {
    const filtered = state.showDeprecated ? provider.models : provider.models.filter(m => !m.deprecated);
    if (filtered.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = '(no models)';
      sel.appendChild(opt);
      return;
    }
    const sorted = [...filtered].sort((a, b) => a.name.localeCompare(b.name));
    for (const m of sorted) {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.name;
      sel.appendChild(opt);
    }
    if (!el.modelInput.value) {
      el.modelInput.value = sorted[0].id;
    }
  }
}
function onProviderChange() {
  const pid = el.providerSelect.value;
  el.apiUrl.value = completeEndpoint(pid);
  populateModelSelect(pid);
  updateApiKeyHint(pid);
  autoFillApiKey(pid);
  saveSettings();
}

function syncEndpointForModel(mid) {
  if (!mid) return;
  el.apiUrl.value = completeEndpoint(el.providerSelect.value, mid);
}

function onModelSelect() {
  const mid = el.modelSelect.value;
  if (!mid) return;
  el.modelInput.value = mid;
  syncEndpointForModel(mid);
  saveSettings();
}


const NPM_ENV_HINTS = {
  "@ai-sdk/mistral": "MISTRAL_API_KEY",
  "@ai-sdk/togetherai": "TOGETHER_API_KEY",
  "@ai-sdk/perplexity": "PERPLEXITY_API_KEY",
  "@ai-sdk/groq": "GROQ_API_KEY",
  "@ai-sdk/xai": "XAI_API_KEY",
  "@ai-sdk/deepinfra": "DEEPINFRA_API_KEY",
  "@ai-sdk/cohere": "COHERE_API_KEY",
  "@ai-sdk/cerebras": "CEREBRAS_API_KEY",
};
const KNOWN_ENV_HINTS = {
  openai: 'OPENAI_API_KEY',
  anthropic: 'ANTHROPIC_API_KEY',
  responses: 'OPENAI_API_KEY',
};

function updateApiKeyHint(pid) {
  const known = KNOWN_ENV_HINTS[pid];
  if (known) { el.apiKey.placeholder = 'sk-... or $' + known; return; }
  const cp = catalogProvider(pid);
  if (cp && cp.env && cp.env.length > 0) {
    el.apiKey.placeholder = 'API key or $' + cp.env[0];
  } else {
    el.apiKey.placeholder = 'sk-... or $ENV_VAR_NAME';
  }
}

function autoFillApiKey(pid) {
  if (el.apiKey.value && !el.apiKey.value.startsWith("$")) return;
  const known = KNOWN_ENV_HINTS[pid];
  if (known) { el.apiKey.value = "$" + known; el.apiKey.type = "text"; return; }
  const cp = catalogProvider(pid);
  if (cp && cp.env && cp.env.length > 0) {
    el.apiKey.value = "$" + cp.env[0]; el.apiKey.type = "text"; return;
  }
  const npmHint = cp && NPM_ENV_HINTS[cp.npm];
  if (npmHint) {
    el.apiKey.value = "$" + npmHint; el.apiKey.type = "text";
  }
}

function applyTheme(t) {
  state.theme = t;
  document.body.classList.toggle('dark', t === 'dark');
  el.themeToggle.textContent = t === 'dark' ? '\u2600\ufe0f' : '\u{1f319}';
  localStorage.setItem('theme', t);
}
function toggleTheme() { applyTheme(state.theme === 'dark' ? 'light' : 'dark'); }

function toggleSettings() {
  const open = el.settingsPanel.classList.contains('open');
  el.settingsPanel.classList.toggle('open', !open);
  el.settingsPanel.classList.toggle('collapsed', open);
}

function addMessage(role, text, isStreaming) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  if (isStreaming) div.classList.add('streaming');
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'U' : 'A';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  div.append(avatar, bubble);
  el.emptyState.style.display = 'none';
  el.chatInner.appendChild(div);
  requestAnimationFrame(() => { el.chatInner.parentElement.scrollTop = el.chatInner.parentElement.scrollHeight; });
  return { el: div, bubble };
}

function updateStreamingMessage(bubble, text) {
  bubble.textContent = text;
  const c = el.chatInner.parentElement;
  if (c.scrollHeight - c.scrollTop - c.clientHeight < 100) c.scrollTop = c.scrollHeight;
}

function finalizeStreaming(el_) { el_.classList.remove('streaming'); }

function showError(msg) {
  const { bubble } = addMessage('assistant', '\u274c ' + msg);
  bubble.closest('.msg').classList.add('error');
}

async function loadCatalog() {
  try {
    const res = await fetch('/api/providers');
    const data = await res.json();
    state.providers = data.providers || [];
    const sorted = [...state.providers].filter(p => p.id && p.name).sort((a, b) => a.name.localeCompare(b.name));
    for (const p of sorted) {
      if (![...el.providerSelect.options].some(o => o.value === p.id)) {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name;
        el.providerSelect.appendChild(opt);
      }
    }
    populateModelSelect(el.providerSelect.value);
    updateApiKeyHint(el.providerSelect.value);
    if (el.apiUrl.value) updateProviderFromUrl(el.apiUrl.value);
  } catch {}
}

async function sendMessage() {
  const text = el.messageInput.value.trim();
  if (!text || state.streaming) return;
  const url = el.apiUrl.value.trim();
  const apiKey = el.apiKey.value.trim();
  if (!url || !apiKey) { showError('Enter API endpoint and API key in settings.'); return; }
  const model = el.modelInput.value.trim() || el.modelSelect.value || 'gpt-4o';
  const config = { url, apiKey, provider: el.providerSelect.value, model, temperature: parseFloat(el.temperature.value), topK: parseInt(el.topK.value, 10) || 40, maxTokens: parseInt(el.maxTokens.value, 10) || 4096, system: el.systemPrompt.value.trim() || '', stream: true };
  addMessage('user', text);
  el.messageInput.value = '';
  el.messageInput.style.height = 'auto';
  state.streaming = true;
  el.sendBtn.disabled = true;
  el.sendBtn.classList.add('loading');
  el.sendBtn.textContent = '\u22ef';
  state.messages.push({ role: 'user', content: text });
  const messages = state.messages.slice();
  const { bubble } = addMessage('assistant', '', true);
  try {
    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...config, messages }) });
    if (!res.ok) { const err = await res.json().catch(() => ({ error: res.statusText })); throw new Error((err.error || res.statusText) + " (HTTP " + res.status + ")"); }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', full = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        const t = line.trim();
        if (t.startsWith('data: ')) {
          try {
            const ev = JSON.parse(t.slice(6));
            if (ev.text !== undefined) { full += ev.text; updateStreamingMessage(bubble, full); }
            if (ev.message) throw new Error(ev.message);
          } catch(e) { if (!(e instanceof SyntaxError)) throw e; }
        }
      }
    }
    finalizeStreaming(bubble.closest('.msg'));
    state.messages.push({ role: 'assistant', content: full });
  } catch (err) { showError(err.message); finalizeStreaming(bubble.closest('.msg')); }
  finally { state.streaming = false; el.sendBtn.disabled = false; el.sendBtn.classList.remove('loading'); el.sendBtn.textContent = '\u27a4'; el.messageInput.focus(); }
}

function autoResize() {
  el.messageInput.style.height = 'auto';
  el.messageInput.style.height = Math.min(el.messageInput.scrollHeight, 120) + 'px';
}

function init() {
  applyTheme(state.theme);
  const saved = JSON.parse(localStorage.getItem('chatSettings') || '{}');
  if (saved.apiUrl) el.apiUrl.value = saved.apiUrl;
  if (saved.apiKey) { el.apiKey.value = saved.apiKey; el.apiKey.type = saved.apiKey.startsWith("$") ? "text" : "password"; }
  if (saved.model) el.modelInput.value = saved.model;
  if (saved.provider) el.providerSelect.value = saved.provider;
  if (saved.temperature != null) { el.temperature.value = saved.temperature; el.temperatureVal.textContent = saved.temperature; }
  if (saved.topK != null) { el.topK.value = saved.topK; el.topKVal.textContent = saved.topK; }
  if (saved.maxTokens) el.maxTokens.value = saved.maxTokens;
  if (saved.system) el.systemPrompt.value = saved.system;
  el.themeToggle.addEventListener('click', toggleTheme);
  el.settingsToggle.addEventListener('click', toggleSettings);
  el.apiUrl.addEventListener('input', () => { updateProviderFromUrl(el.apiUrl.value); saveSettings(); });
  el.providerSelect.addEventListener('change', onProviderChange);
  el.modelSelect.addEventListener('change', onModelSelect);
  el.modelInput.addEventListener('input', () => { syncEndpointForModel(el.modelInput.value.trim()); saveSettings(); });
  el.modelInput.addEventListener('change', () => { syncEndpointForModel(el.modelInput.value.trim()); saveSettings(); });
  el.apiKey.addEventListener('input', () => { el.apiKey.type = el.apiKey.value.startsWith('$') ? 'text' : 'password'; saveSettings(); });
  el.temperature.addEventListener('input', () => { el.temperatureVal.textContent = el.temperature.value; saveSettings(); });
  el.topK.addEventListener('input', () => { el.topKVal.textContent = el.topK.value; saveSettings(); });
  el.maxTokens.addEventListener('input', saveSettings);
  el.systemPrompt.addEventListener('input', saveSettings);
  el.showDeprecated = document.getElementById('showDeprecated');
  if (el.showDeprecated) {
    el.showDeprecated.checked = state.showDeprecated;
    el.showDeprecated.addEventListener('change', () => {
      state.showDeprecated = el.showDeprecated.checked;
      localStorage.setItem('showDeprecated', state.showDeprecated);
      populateModelSelect(el.providerSelect.value);
    });
  }
  el.messageInput.addEventListener('input', autoResize);
  el.messageInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
  el.sendBtn.addEventListener('click', sendMessage);
  loadCatalog();
}

function saveSettings() {
  localStorage.setItem('chatSettings', JSON.stringify({ apiUrl: el.apiUrl.value, apiKey: el.apiKey.value, model: el.modelInput.value, provider: el.providerSelect.value, temperature: el.temperature.value, topK: el.topK.value, maxTokens: el.maxTokens.value, system: el.systemPrompt.value }));
}

document.addEventListener('DOMContentLoaded', init);
