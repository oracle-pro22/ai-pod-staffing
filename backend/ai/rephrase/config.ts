import 'server-only';

import { homedir } from 'node:os';
import { isAbsolute, join, resolve } from 'node:path';

export type AiRephraseConfig = {
  endpoint: string;
  compartmentId: string;
  modelId: string;
  configFile: string;
  configProfile: string;
  timeoutMs: number;
};

const DEFAULT_TIMEOUT_MS = 15_000;
const MIN_TIMEOUT_MS = 1_000;
const MAX_TIMEOUT_MS = 60_000;

function enabled(name: string): boolean {
  return ['1', 'true', 'yes', 'on'].includes((process.env[name] ?? '').trim().toLowerCase());
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required server environment variable ${name}.`);
  return value;
}

function timeout(): number {
  const raw = process.env.AI_REPHRASE_TIMEOUT_MS?.trim();
  if (!raw) return DEFAULT_TIMEOUT_MS;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < MIN_TIMEOUT_MS || value > MAX_TIMEOUT_MS) {
    throw new Error(`AI_REPHRASE_TIMEOUT_MS must be between ${MIN_TIMEOUT_MS} and ${MAX_TIMEOUT_MS}.`);
  }
  return value;
}

function endpoint(): string {
  const raw = required('OCI_GENAI_ENDPOINT').replace(/\/+$/, '');
  const parsed = new URL(raw);
  if (parsed.protocol !== 'https:') throw new Error('OCI_GENAI_ENDPOINT must use HTTPS.');
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('OCI_GENAI_ENDPOINT must be an HTTPS service origin without credentials, query, or fragment.');
  }
  if (parsed.pathname !== '/' && parsed.pathname !== '') {
    throw new Error('OCI_GENAI_ENDPOINT must not include an API path.');
  }
  return parsed.origin;
}

function expandHome(path: string): string {
  if (path === '~') return homedir();
  if (path.startsWith('~/') || path.startsWith('~\\')) return join(homedir(), path.slice(2));
  return isAbsolute(path) ? path : resolve(path);
}

export function readAiRephraseConfig(): AiRephraseConfig {
  if (!enabled('AI_REPHRASE_ENABLED')) {
    throw new Error('AI rephrasing is disabled by configuration.');
  }

  return {
    endpoint: endpoint(),
    compartmentId: required('OCI_GENAI_COMPARTMENT_ID'),
    modelId: required('OCI_GENAI_MODEL_ID'),
    configFile: expandHome(process.env.OCI_CONFIG_FILE?.trim() || '~/.oci/config'),
    configProfile: process.env.OCI_CONFIG_PROFILE?.trim() || 'DEFAULT',
    timeoutMs: timeout(),
  };
}
