#!/usr/bin/env node
/**
 * Standalone OpenAI/Anthropic API Chat Client
 *
 * Configure via environment variables or CLI flags:
 *
 * Environment Variables:
 *   API_PROVIDER   - "openai", "anthropic", or "responses" (default: openai)
 *   API_URL        - Full endpoint URL for completions/messages
 *   API_KEY        - Your API key (required)
 *   MODEL_NAME     - Model identifier (default varies by provider)
 *   SYSTEM_MESSAGE - System prompt (default: "You are a helpful assistant.")
 *
 * CLI Flags:
 *   --provider openai|anthropic|responses  Override API_PROVIDER
 *   --url <url>                   Override API_URL
 *   --model <name>                Override MODEL_NAME
 *   --system <text>               Override SYSTEM_MESSAGE
 *   --temperature <n>             Sampling temperature (default: 0.7)
 *   --max-tokens <n>              Max response tokens (default: 4096)
 *   --no-stream                   Disable streaming
 *   --api-key <key>               Override API_KEY
 *   -h, --help                    Show help
 */

import readline from 'readline';
import { isatty } from 'tty';
import {
  chatNonStreaming,
  chatStreaming,
  detectProvider,
  DEFAULT_PROVIDER,
  DEFAULT_MODEL,
  DEFAULT_SYSTEM,
  DEFAULT_TEMPERATURE,
  DEFAULT_MAX_TOKENS,
} from './api-client.mjs';

// ── Configuration ─────────────────────────────────────────────────────────────

function parseArgs(args) {
  const opts = {
    provider: null,
    url: null,
    model: null,
    system: null,
    temperature: null,
    maxTokens: null,
    stream: true,
    apiKey: null,
    prompt: null,
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--provider' && args[i + 1]) {
      opts.provider = args[++i];
    } else if (arg === '--url' && args[i + 1]) {
      opts.url = args[++i];
    } else if (arg === '--model' && args[i + 1]) {
      opts.model = args[++i];
    } else if (arg === '--system' && args[i + 1]) {
      opts.system = args[++i];
    } else if (arg === '--temperature' && args[i + 1]) {
      opts.temperature = parseFloat(args[++i]);
    } else if (arg === '--max-tokens' && args[i + 1]) {
      opts.maxTokens = parseInt(args[++i], 10);
    } else if (arg === '--no-stream') {
      opts.stream = false;
    } else if (arg === '--api-key' && args[i + 1]) {
      opts.apiKey = args[++i];
    } else if (arg === '--prompt' && args[i + 1]) {
      opts.prompt = args[++i];
    } else if (arg === '--help' || arg === '-h') {
      showHelp();
      process.exit(0);
    }
  }

  return opts;
}

function showHelp() {
  console.log(`Usage: node cli.mjs [options]

Chat with OpenAI or Anthropic models via their REST APIs.

Environment Variables:
  API_PROVIDER     "openai", "anthropic", or "responses" (default: openai)
  API_URL          Full endpoint URL (optional, uses default if not set)
  API_KEY          Your API key (required, or set API_KEY env var)
  MODEL_NAME       Model identifier (default varies by provider)
  SYSTEM_MESSAGE   System prompt (default: "You are a helpful assistant.")

CLI Options:
  --provider <p>   API provider: "openai", "anthropic", or "responses"
  --url <url>      API endpoint URL
  --model <name>   Model name
  --system <text>  System prompt
  --temperature <n>  Sampling temperature (default: 0.7)
  --max-tokens <n>   Maximum tokens in response (default: 4096)
  --no-stream      Disable streaming (wait for complete response)
  --api-key <key>  API key (overrides API_KEY env var)
  --prompt <text>  Send a single prompt and exit
  -h, --help       Show this help

Interactive Commands:
  /quit            Exit the client
  /reset           Clear conversation history
  /model <name>    Change model
  /system <text>   Change system prompt
  /help            Show available commands
`);
}

function resolveConfig(opts) {
  const provider = opts.provider || process.env.API_PROVIDER || DEFAULT_PROVIDER;

  if (provider !== 'openai' && provider !== 'anthropic' && provider !== 'responses') {
    console.error(`Error: provider must be "openai", "anthropic", or "responses", got "${provider}"`);
    process.exit(1);
  }

  const apiKey = opts.apiKey || process.env.API_KEY;
  if (!apiKey) {
    console.error('Error: API_KEY not set. Set API_KEY environment variable or --api-key flag.');
    process.exit(1);
  }

  let url = opts.url || process.env.API_URL;
  if (!url) {
    if (provider === 'openai') url = 'https://api.openai.com/v1/chat/completions';
    else if (provider === 'responses') url = 'https://api.openai.com/v1/responses';
    else url = 'https://api.anthropic.com/v1/messages';
  }

  const model = opts.model || process.env.MODEL_NAME || DEFAULT_MODEL[provider];
  const system = opts.system || process.env.SYSTEM_MESSAGE || DEFAULT_SYSTEM;
  const temperature = opts.temperature ?? parseFloat(process.env.TEMPERATURE || DEFAULT_TEMPERATURE);
  const maxTokens = opts.maxTokens ?? parseInt(process.env.MAX_TOKENS || DEFAULT_MAX_TOKENS, 10);

  return {
    provider,
    url,
    apiKey,
    model,
    system,
    temperature,
    maxTokens,
    stream: opts.stream,
    prompt: opts.prompt,
  };
}

// ── CLI Interface ─────────────────────────────────────────────────────────────

const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

function createReadline() {
  return readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false,
  });
}

async function sendMessage(config, messages) {
  process.stderr.write('\x1b[?25l');

  let spinnerInterval;
  if (process.stderr.isTTY) {
    let frame = 0;
    spinnerInterval = setInterval(() => {
      process.stderr.write(`\r\x1b[K${SPINNER[frame % SPINNER.length]} waiting...`);
      frame++;
    }, 120);
  }

  try {
    if (config.stream) {
      let fullResponse = '';
      for await (const chunk of chatStreaming(config, messages)) {
        if (spinnerInterval) {
          clearInterval(spinnerInterval);
          process.stderr.write('\r\x1b[K');
          spinnerInterval = null;
        }
        process.stdout.write(chunk);
        fullResponse += chunk;
      }
      process.stdout.write('\n');
      return fullResponse;
    } else {
      const { text } = await chatNonStreaming(config, messages);
      if (spinnerInterval) {
        clearInterval(spinnerInterval);
        process.stderr.write('\r\x1b[K');
      }
      process.stdout.write(text + '\n');
      return text;
    }
  } finally {
    if (spinnerInterval) clearInterval(spinnerInterval);
    process.stderr.write('\x1b[?25h');
  }
}

async function interactiveMode(config) {
  const rl = createReadline();
  const messages = [];

  console.log(`Connected to ${config.provider} API`);
  const endpointLabel = config.provider === 'responses' ? 'Responses' : config.provider;
  console.log(`Model: ${config.model}`);
  console.log(`URL: ${config.url}`);
  console.log('Type /help for commands, or enter a message to chat.\n');

  const handleInput = async (input) => {
    input = input.trim();
    if (!input) { promptUser(); return; }

    if (input.startsWith('/')) {
      const [cmd, ...args] = input.slice(1).split(/\s+/);
      await handleCommand(cmd.toLowerCase(), args, config, messages, rl);
      promptUser();
      return;
    }

    if (input === 'exit' || input === 'quit') {
      console.log('Goodbye!');
      rl.close();
      process.exit(0);
    }

    messages.push({ role: 'user', content: input });

    try {
      process.stderr.write('\x1b[?25l');
      const response = await sendMessage(config, messages);
      messages.push({ role: 'assistant', content: response });
      process.stderr.write('\n');
    } catch (e) {
      process.stderr.write(`\nError: ${e.message}\n`);
    }

    promptUser();
  };

  function promptUser() {
    process.stdout.write('> ');
  }

  rl.on('line', handleInput);
  promptUser();
}

async function handleCommand(cmd, args, config, messages, rl) {
  switch (cmd) {
    case 'help':
      console.log(`
Commands:
  /help             Show this help
  /quit, /exit      Exit the client
  /reset            Clear conversation history
  /model <name>     Change model (e.g., /model gpt-4o)
  /system <text>    Change system prompt (e.g., /system You are...)
  /status           Show current configuration
  /provider <name>  Switch provider: openai, anthropic, responses
  /url <url>        Change API endpoint URL
  /api-key <key>    Change API key
  /temperature <n>  Set temperature (0.0-2.0)
  /max-tokens <n>   Set max tokens
  /stream on|off    Toggle streaming mode
`);
      break;

    case 'quit':
    case 'exit':
      console.log('Goodbye!');
      rl.close();
      process.exit(0);

    case 'reset':
      messages.length = 0;
      console.log('Conversation history cleared.');
      break;

    case 'model':
      if (args[0]) { config.model = args.join(' '); console.log(`Model changed to: ${config.model}`); }
      else console.log(`Current model: ${config.model}`);
      break;

    case 'system':
      if (args.length > 0) { config.system = args.join(' '); console.log(`System prompt changed.`); }
      else console.log(`Current system: ${config.system}`);
      break;

    case 'status':
      console.log(`
Provider:    ${config.provider}
Model:      ${config.model}
URL:        ${config.url}
Temperature: ${config.temperature}
Max Tokens:  ${config.maxTokens}
Streaming:   ${config.stream}
Messages:    ${messages.length} in history
`);
      break;

    case 'provider':
      if (args[0] && ['openai', 'anthropic', 'responses'].includes(args[0])) {
        config.provider = args[0];
        if (!process.env.API_URL && !process.argv.includes('--url')) {
          if (args[0] === 'openai') config.url = 'https://api.openai.com/v1/chat/completions';
          else if (args[0] === 'responses') config.url = 'https://api.openai.com/v1/responses';
          else config.url = 'https://api.anthropic.com/v1/messages';
        }
        console.log(`Provider changed to: ${config.provider}`);
      } else console.log(`Current provider: ${config.provider}\nUsage: /provider openai|anthropic|responses`);
      break;

    case 'url':
      if (args[0]) { config.url = args[0]; console.log(`URL changed to: ${config.url}`); }
      else console.log(`Current URL: ${config.url}`);
      break;

    case 'api-key':
      if (args[0]) { config.apiKey = args[0]; console.log('API key updated.'); }
      break;

    case 'temperature':
      if (args[0]) {
        const t = parseFloat(args[0]);
        if (!isNaN(t) && t >= 0 && t <= 2) { config.temperature = t; console.log(`Temperature set to: ${config.temperature}`); }
        else console.log('Temperature must be between 0.0 and 2.0');
      } else console.log(`Current temperature: ${config.temperature}`);
      break;

    case 'max-tokens':
      if (args[0]) {
        const m = parseInt(args[0], 10);
        if (!isNaN(m) && m > 0) { config.maxTokens = m; console.log(`Max tokens set to: ${config.maxTokens}`); }
        else console.log('Max tokens must be a positive integer');
      } else console.log(`Current max tokens: ${config.maxTokens}`);
      break;

    case 'stream':
      if (args[0] === 'on') { config.stream = true; console.log('Streaming enabled.'); }
      else if (args[0] === 'off') { config.stream = false; console.log('Streaming disabled.'); }
      else console.log(`Streaming: ${config.stream ? 'on' : 'off'}\nUsage: /stream on|off`);
      break;

    default:
      console.log(`Unknown command: /${cmd}. Type /help for available commands.`);
  }
}

async function singlePromptMode(config) {
  const messages = [{ role: 'user', content: config.prompt }];
  try {
    await sendMessage(config, messages);
    process.stdout.write('\n');
  } catch (e) {
    process.stderr.write(`Error: ${e.message}\n`);
    process.exit(1);
  }
}

async function pipeMode(config) {
  let input = '';
  process.stdin.setEncoding('utf-8');
  for await (const chunk of process.stdin) {
    input += chunk;
  }
  input = input.trim();
  if (input) {
    const messages = [{ role: 'user', content: input }];
    try {
      await sendMessage(config, messages);
      process.stdout.write('\n');
    } catch (e) {
      process.stderr.write(`Error: ${e.message}\n`);
      process.exit(1);
    }
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const config = resolveConfig(opts);

  if (opts.prompt) {
    config.prompt = opts.prompt;
    await singlePromptMode(config);
  } else if (!isatty(0)) {
    await pipeMode(config);
  } else {
    await interactiveMode(config);
  }
}

main().catch((e) => {
  console.error('Fatal:', e.message);
  process.exit(1);
});

export { resolveConfig, detectProvider, DEFAULT_MODEL };
