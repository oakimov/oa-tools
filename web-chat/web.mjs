#!/usr/bin/env node
/**
 * Web UI Server for the API Chat Client.
 * Serves a ChatGPT-like interface with streaming support, theme switcher,
 * and model auto-discovery via models.dev/api.json.
 */

import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import {
  chatStreaming,
  chatNonStreaming,
  detectProvider,
  fetchModelCatalog,
} from './api-client.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(__dirname, 'public');
const PORT = parseInt(process.env.PORT || process.argv[2] || '3000', 10);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

const MAX_BODY_BYTES = 1 * 1024 * 1024;

// ── Helper: parse JSON body ───────────────────────────────────────────────────

function parseBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    let settled = false;

    req.on('data', c => {
      if (settled) return;
      total += c.length;
      if (total > MAX_BODY_BYTES) {
        settled = true;
        const err = new Error('Request body too large');
        err.statusCode = 413;
        reject(err);
        return;
      }
      chunks.push(c);
    });

    req.on('end', () => {
      if (settled) return;
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString()));
      } catch {
        settled = true;
        const err = new Error('Invalid JSON');
        err.statusCode = 400;
        reject(err);
      }
    });

    req.on('error', (err) => {
      if (settled) return;
      settled = true;
      reject(err);
    });
  });
}

// ── Helper: SSE write ─────────────────────────────────────────────────────────

function sseWrite(res, event, data) {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

// ── Route: POST /api/chat (streaming SSE) ─────────────────────────────────────

async function handleChat(req, res) {
  let body;
  try {
    body = await parseBody(req);
  } catch (err) {
    const status = err?.statusCode || 400;
    const error = status === 413 ? 'Request body too large (max 1MB)' : 'Invalid JSON body';
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error }));
    return;
  }

  const { messages, model, temperature, topK, maxTokens, url, apiKey, provider, system, stream } = body;
  if (!apiKey || !url) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'apiKey and url are required' }));
    return;
  }

  // Resolve $ENV_VAR references in apiKey
  const resolvedKey = apiKey.startsWith('$') ? (process.env[apiKey.slice(1)] || '') : apiKey;
  if (!resolvedKey) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: `API key resolved to empty. Check env var ${apiKey.slice(1)}` }));
    return;
  }

  const config = {
    provider: provider || detectProvider(url),
    url,
    apiKey: resolvedKey,
    model: model || 'gpt-4o',
    system: system || '',
    temperature: temperature ?? 0.7,
    topK: topK ?? null,
    maxTokens: maxTokens ?? 4096,
    timeout: 120_000,
    stream: stream !== false,
  };

  const useStream = config.stream !== false;

  if (useStream) {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });

    try {
      sseWrite(res, 'start', {});
      let fullText = '';
      for await (const chunk of chatStreaming(config, messages)) {
        fullText += chunk;
        sseWrite(res, 'delta', { text: chunk });
      }
      sseWrite(res, 'done', {});
    } catch (err) {
      sseWrite(res, 'error', { message: err.message });
    }
    res.end();
  } else {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    try {
      const { text } = await chatNonStreaming(config, messages);
      res.end(JSON.stringify({ text }));
    } catch (err) {
      res.end(JSON.stringify({ error: err.message }));
    }
  }
}

// ── Route: GET /api/providers ────────────────────────────────────────────────

async function handleProviders(req, res) {
  res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
  try {
    const catalog = await fetchModelCatalog();
    res.end(JSON.stringify(catalog));
  } catch {
    res.end(JSON.stringify({
      providers: [
        { id: 'openai', name: 'OpenAI', base_url: 'https://api.openai.com/v1', models: [] },
        { id: 'anthropic', name: 'Anthropic', base_url: 'https://api.anthropic.com', models: [] },
      ],
    }));
  }
}

// ── Route: GET /api/env ──────────────────────────────────────────────────────

function handleEnv(req, res) {
  res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
  const vars = Object.keys(process.env).filter(k => /api.?key/i.test(k) || /token/i.test(k));
  res.end(JSON.stringify({ envKeys: vars }));
}

// ── Route: static files ──────────────────────────────────────────────────────

function serveStatic(req, res) {
  let filePath = path.join(PUBLIC, req.url === '/' ? 'index.html' : req.url);

  if (!filePath.startsWith(PUBLIC)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      fs.readFile(path.join(PUBLIC, 'index.html'), (err2, data2) => {
        if (err2) {
          res.writeHead(404);
          res.end('Not Found');
          return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(data2);
      });
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  });
}

// ── Router ────────────────────────────────────────────────────────────────────

const routes = {
  'POST:/api/chat': handleChat,
  'GET:/api/providers': handleProviders,
  'GET:/api/env': handleEnv,
};

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const routeKey = `${req.method}:${req.url.split('?')[0]}`;
  const handler = routes[routeKey];

  if (handler) {
    handler(req, res);
  } else {
    serveStatic(req, res);
  }
});

server.listen(PORT, () => {
  console.log(`Web UI: http://localhost:${PORT}`);
});
