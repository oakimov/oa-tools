#!/usr/bin/env node
import http from 'http';
import fs from 'fs';
import path from 'path';
import os from 'os';

const TOKEN_FILE = path.join(os.homedir(), '.qwen-token.json');
const TARGET = 'https://qwen.aikit.club';
const PORT = parseInt(process.env.PORT || process.argv[2] || '4000', 10);

let cachedToken = null;

function readTokenCache() {
  try {
    const data = JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf-8'));
    if (data.token) {
      const exp = data.expiresAt ? data.expiresAt - 120_000 : Infinity;
      if (Date.now() < exp) return data.token;
    }
  } catch {}
  return null;
}

function writeTokenCache(token) {
  let expiresAt = null;
  try {
    const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
    if (payload.exp) expiresAt = payload.exp * 1000;
  } catch {}
  fs.writeFileSync(TOKEN_FILE, JSON.stringify({ token, expiresAt, updatedAt: Date.now() }));
  return expiresAt;
}

function getToken() {
  if (cachedToken) return cachedToken;
  cachedToken = readTokenCache();
  return cachedToken;
}

function setToken(token) {
  writeTokenCache(token);
  cachedToken = token;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
    req.on('error', reject);
  });
}

async function validateToken(token) {
  try {
    const res = await fetch(`${TARGET}/v1/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.access_token || token;
  } catch { return null; }
}

async function refreshToken(token) {
  try {
    const res = await fetch(`${TARGET}/v1/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.access_token || null;
  } catch { return null; }
}

async function handleRefresh(req, res) {
  const token = getToken();
  if (!token) {
    res.writeHead(400, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ ok: false, error: 'No token saved.' }));
    return;
  }

  const newToken = await refreshToken(token);
  if (!newToken) {
    res.writeHead(400, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ ok: false, error: 'Refresh failed. Token may be invalid.' }));
    return;
  }

  const expiresAt = writeTokenCache(newToken);
  cachedToken = newToken;
  const expStr = expiresAt ? new Date(expiresAt).toISOString().slice(0, 19).replace('T', ' ') : 'unknown';
  res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
  res.end(JSON.stringify({ ok: true, expiresAt: expStr }));
}

async function ensureTokenFresh() {
  const token = getToken();
  if (!token) return;
  let expiresAt = null;
  try {
    const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
    if (payload.exp) expiresAt = payload.exp * 1000;
  } catch {}
  if (!expiresAt) return;
  // Refresh if expiring within next 6 hours
  if (Date.now() > expiresAt - 6 * 60 * 60 * 1000) {
    process.stderr.write('[qwen-proxy] token nearing expiry, refreshing...\n');
    const newToken = await refreshToken(token);
    if (newToken) {
      setToken(newToken);
      process.stderr.write('[qwen-proxy] token refreshed\n');
    } else {
      process.stderr.write('[qwen-proxy] token refresh failed\n');
    }
  }
}

const BOOKMARKLET_CODE = `javascript:(function(){var t=localStorage.getItem('token');if(!t||t.length<40){alert('No Qwen token found.\\n\\nMake sure you are logged in at chat.qwen.ai and try again.');return;}navigator.clipboard.writeText(t).then(function(){window.location.href='http://localhost:${PORT}/#/token/'+encodeURIComponent(t);}).catch(function(){var p=prompt('Token found! Press Ctrl+C to copy, then click OK to return to the proxy page.',t);if(p)window.location.href='http://localhost:${PORT}/#/token/'+encodeURIComponent(t);});})()`;

const HTML = (status, message) => `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Qwen Proxy</title>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;line-height:1.5}
.status{padding:12px 16px;border-radius:8px;margin:16px 0}
.ok{background:#d4edda;color:#155724;border:1px solid #c3e6cb}
.warn{background:#fff3cd;color:#856404;border:1px solid #ffeeba}
.err{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}
pre{background:#f4f4f4;padding:12px;border-radius:6px;overflow-x:auto;font-size:13px;word-break:break-all}
code{background:#f4f4f4;padding:2px 5px;border-radius:3px;font-size:13px}
input[type=text],input[type=password]{width:100%;padding:10px;font-size:14px;border:1px solid #ccc;border-radius:6px;margin:8px 0;font-family:monospace}
button,.btn{padding:10px 24px;background:#06f;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;display:inline-block;text-decoration:none}
button:hover,.btn:hover{background:#05e}
.btn-outline{background:#fff;color:#06f;border:1px solid #06f;margin-left:8px}
.bookmarklet{background:#28a745;color:#fff;padding:10px 24px;border-radius:6px;font-size:14px;cursor:grab;display:inline-block;text-decoration:none;font-weight:bold}
.bookmarklet:hover{background:#218838}
.step{background:#f8f9fa;border:1px solid #dee2e6;border-radius:8px;padding:16px;margin:12px 0}
.step-num{display:inline-block;background:#06f;color:#fff;width:24px;height:24px;border-radius:12px;text-align:center;font-size:14px;line-height:24px;margin-right:8px}
hr{border:none;border-top:1px solid #eee;margin:24px 0}
.hidden{display:none}
</style></head><body>
<h1>Qwen Proxy</h1>
<div class="status ${status}">${message}</div>
<div id="tokenDetected" class="hidden"></div>
<script>
(function(){
  var hash = window.location.hash;
  if (hash && hash.indexOf('/token/') > -1) {
    var token = decodeURIComponent(hash.split('/token/')[1]);
    if (token && token.length > 40) {
      var f = document.createElement('form');
      f.method = 'POST';
      f.action = '/auth';
      var i = document.createElement('input');
      i.name = 'token';
      i.value = token;
      f.appendChild(i);
      document.body.appendChild(f);
      document.getElementById('tokenDetected').innerHTML =
        '<div class="status ok">Token detected in URL. Saving...</div>';
      f.submit();
    }
  }
})();
function doRefresh() {
  var btn = document.getElementById('refreshBtn');
  var out = document.getElementById('refreshResult');
  if (!btn) return;
  btn.disabled = true; btn.textContent = 'Refreshing...';
  fetch('/refresh', { method: 'POST' })
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.ok) {
        out.innerHTML = '<div class="status ok">Refreshed! Expires: ' + d.expiresAt + '</div>';
      } else {
        out.innerHTML = '<div class="status err">' + (d.error || 'Refresh failed') + '</div>';
      }
      btn.disabled = false; btn.textContent = 'Validate & Refresh Token';
    })
    .catch(function(e){
      out.innerHTML = '<div class="status err">' + e.message + '</div>';
      btn.disabled = false; btn.textContent = 'Validate & Refresh Token';
    });
}
</script>
${status === 'ok'
  ? `<p>Proxy is ready. Point any OpenAI client to:</p>
<pre>http://localhost:${PORT}/v1/chat/completions</pre>
<p><a href="/auth">Change token</a> &middot; <a href="/forget">Clear token</a></p>
<div id="refreshResult"></div>
<p><button id="refreshBtn" class="btn" onclick="doRefresh()">Validate & Refresh Token</button></p>`
  : `<div class="step">
  <span class="step-num">1</span>
  <strong>Go to chat.qwen.ai and sign in</strong>
  <br><br>
  <a class="btn" href="https://chat.qwen.ai" target="_blank">Open chat.qwen.ai</a>
</div>
<div class="step">
  <span class="step-num">2</span>
  <strong>Drag this button to your bookmarks bar, then click it on the Qwen page</strong>
  <br><br>
  <a class="bookmarklet" href="${BOOKMARKLET_CODE}">Get Qwen Token</a>
  <br><br>
  <details><summary>Or copy the token manually</summary>
  <p>After signing in on Qwen, open the dev console (<code>F12</code> &rarr; Console) and run:</p>
  <pre>copy(localStorage.getItem('token'))</pre>
  <p>Then come back and paste:</p>
  </details>
</div>
<div class="step">
  <span class="step-num">3</span>
  <strong>Paste your token here</strong>
  <form method="post" action="/auth">
    <input type="password" name="token" placeholder="eyJ..." required>
    <button type="submit">Save Token</button>
  </form>
</div>`}
<hr>
<p><strong>Usage:</strong></p>
<pre>curl http://localhost:${PORT}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"qwen3.7-max","messages":[{"role":"user","content":"Hello"}]}'</pre>
</body></html>`;

function handleRoot(req, res) {
  const token = getToken();
  const status = token ? 'ok' : 'warn';
  const msg = token ? 'Authenticated' : 'Not authenticated';
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(HTML(status, msg));
}

async function handleAuth(req, res) {
  if (req.method === 'GET') {
    const token = getToken();
    const status = token ? 'ok' : 'warn';
    const msg = token ? 'Authenticated (token saved).' : 'Not authenticated.';
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(HTML(status, msg));
    return;
  }

  const body = await readBody(req);
  const params = new URLSearchParams(body);
  const raw = params.get('token') || '';

  if (!raw || !raw.includes('.') || raw.length < 40) {
    res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(HTML('err', 'Invalid token. Make sure you copied the full JWT from localStorage.'));
    return;
  }

  // Validate with upstream and use the returned (potentially refreshed) token
  const validated = await validateToken(raw);
  if (!validated) {
    res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(HTML('err', 'Token rejected by Qwen. Make sure you are logged in at chat.qwen.ai and the token is fresh.'));
    return;
  }

  const exp = writeTokenCache(validated);
  cachedToken = validated;
  const expStr = exp ? new Date(exp).toISOString().slice(0, 19).replace('T', ' ') : 'unknown';
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(HTML('ok', `Token saved! Expires: ${expStr}. Proxy is ready.`));
}

function handleForget(req, res) {
  try { fs.unlinkSync(TOKEN_FILE); } catch {}
  cachedToken = null;
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(HTML('warn', 'Token cleared.'));
}

async function proxyAPI(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname;
  const method = req.method;

  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, DELETE',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    });
    res.end();
    return;
  }

  let token = getToken();
  if (!token) {
    res.writeHead(401, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ error: `Not authenticated. Visit http://localhost:${PORT}/ to sign in.` }));
    return;
  }

  const targetUrl = `${TARGET}${pathname}${url.search}`;

  const body = ['POST', 'PUT', 'PATCH'].includes(method)
    ? await readBody(req).catch(() => null)
    : null;

  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': req.headers['content-type'] || 'application/json',
    'Accept': req.headers['accept'] || 'application/json',
  };

  let targetRes;
  try {
    targetRes = await fetch(targetUrl, { method, headers, body, signal: AbortSignal.timeout(120_000) });
  } catch (err) {
    res.writeHead(502, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ error: `Upstream error: ${err.message}` }));
    return;
  }

  // On 401, try refresh once before giving up
  if (targetRes.status === 401) {
    const newToken = await refreshToken(token);
    if (newToken) {
      setToken(newToken);
      headers['Authorization'] = `Bearer ${newToken}`;
      try {
        targetRes = await fetch(targetUrl, { method, headers, body, signal: AbortSignal.timeout(120_000) });
      } catch (err) {
        res.writeHead(502, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
        res.end(JSON.stringify({ error: `Upstream error: ${err.message}` }));
        return;
      }
    } else {
      cachedToken = null;
      res.writeHead(401, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify({ error: 'Token expired and refresh failed. Re-authenticate at http://localhost:' + PORT + '/' }));
      return;
    }
  }

  const ct = targetRes.headers.get('content-type') || '';
  const isStream = ct.includes('text/event-stream');

  const responseHeaders = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'Content-Type' };

  if (isStream) {
    responseHeaders['Content-Type'] = 'text/event-stream';
    responseHeaders['Cache-Control'] = 'no-cache';
    responseHeaders['Connection'] = 'keep-alive';
    responseHeaders['X-Accel-Buffering'] = 'no';
  } else {
    responseHeaders['Content-Type'] = ct || 'application/json';
  }

  res.writeHead(targetRes.status, responseHeaders);

  // Strip trailing <details> metadata block Qwen injects into content
  const META_RE = /(?:\\n|\n)?<details>[\s\S]*?<\/details>\s*/g;

  if (isStream) {
    const reader = targetRes.body.getReader();
    const decoder = new TextDecoder();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        res.write(decoder.decode(value, { stream: true }).replace(META_RE, ''));
      }
    } finally {
      reader.releaseLock();
    }
    res.end();
  } else {
    res.end((await targetRes.text()).replace(META_RE, ''));
  }
}

const routes = {
  'GET:/': handleRoot,
  'GET:/auth': handleAuth,
  'POST:/auth': handleAuth,
  'POST:/refresh': handleRefresh,
  'GET:/forget': handleForget,
  'GET:/status': handleRoot,
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const key = `${req.method}:${url.pathname}`;
  const handler = routes[key];
  if (handler) { handler(req, res); return; }
  if (url.pathname.startsWith('/v1/')) { proxyAPI(req, res); return; }
  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not found');
});

cachedToken = readTokenCache();
if (cachedToken) {
  setToken(cachedToken);
  // Proactive refresh on startup if close to expiry
  ensureTokenFresh();
}
// Periodic refresh check every 30 minutes
setInterval(ensureTokenFresh, 30 * 60 * 1000);

server.listen(PORT, () => {
  process.stderr.write(`Qwen Proxy: http://localhost:${PORT}\n`);
  if (cachedToken) {
    process.stderr.write('[qwen-proxy] token loaded from cache\n');
  } else {
    process.stderr.write('[qwen-proxy] no token. Visit http://localhost:' + PORT + '/ to set one.\n');
  }
});
