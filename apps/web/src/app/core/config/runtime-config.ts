import { InjectionToken } from '@angular/core';

export interface RuntimeConfig {
  apiBaseUrl: string;
  discoveryUrl: string;
  chatTransport: 'ws' | 'sse';
  mode: 'replay' | 'live' | 'auto';
  environment: 'development' | 'production';
  release: string;
}

export const RUNTIME_CONFIG = new InjectionToken<RuntimeConfig>('RUNTIME_CONFIG');

const DEFAULTS: RuntimeConfig = {
  apiBaseUrl: '',
  discoveryUrl: '',
  chatTransport: 'ws',
  mode: 'replay',
  environment: 'production',
  release: '0.0.0',
};

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function httpUrlOrEmpty(value: unknown): string {
  if (typeof value !== 'string' || value === '') return '';
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? value.replace(/\/+$/, '') : '';
  } catch {
    return '';
  }
}

export function normalizeRuntimeConfig(raw: unknown): RuntimeConfig {
  const input = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  return {
    apiBaseUrl: httpUrlOrEmpty(input['apiBaseUrl']),
    discoveryUrl: httpUrlOrEmpty(input['discoveryUrl']),
    chatTransport: pick(input['chatTransport'], ['ws', 'sse'], DEFAULTS.chatTransport),
    mode: pick(input['mode'], ['replay', 'live', 'auto'], DEFAULTS.mode),
    environment: pick(input['environment'], ['development', 'production'], DEFAULTS.environment),
    release:
      typeof input['release'] === 'string' && /^[0-9A-Za-z.+-]{1,32}$/.test(input['release'])
        ? input['release']
        : DEFAULTS.release,
  };
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch('/config.json', {
      cache: 'no-cache',
      signal: controller.signal,
      headers: { accept: 'application/json' },
    });
    if (!response.ok) return DEFAULTS;
    return normalizeRuntimeConfig(await response.json());
  } catch {
    return DEFAULTS;
  } finally {
    clearTimeout(timer);
  }
}
