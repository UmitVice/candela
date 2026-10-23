import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
const env = process.env;

const fail = (message) => {
  console.error(`render-dist: ${message}`);
  process.exit(1);
};

const oneOf = (name, value, allowed) => {
  if (!allowed.includes(value))
    fail(`${name} must be one of ${allowed.join(', ')} (got "${value}")`);
  return value;
};

const httpsUrl = (name, value) => {
  if (!value) return '';
  let url;
  try {
    url = new URL(value);
  } catch {
    fail(`${name} is not a valid URL`);
  }
  if (url.protocol !== 'https:' && url.hostname !== 'localhost' && url.hostname !== '127.0.0.1') {
    fail(`${name} must use https`);
  }
  return value.replace(/\/+$/, '');
};

const config = {
  apiBaseUrl: httpsUrl('WEB_API_BASE_URL', env.WEB_API_BASE_URL ?? ''),
  discoveryUrl: httpsUrl('WEB_DISCOVERY_URL', env.WEB_DISCOVERY_URL ?? ''),
  chatTransport: oneOf('WEB_CHAT_TRANSPORT', env.WEB_CHAT_TRANSPORT ?? 'ws', ['ws', 'sse']),
  mode: oneOf('WEB_MODE', env.WEB_MODE ?? 'replay', ['replay', 'live', 'auto']),
  environment: oneOf('WEB_ENVIRONMENT', env.WEB_ENVIRONMENT ?? 'production', [
    'development',
    'production',
  ]),
  release: env.WEB_RELEASE ?? pkg.version,
};
if (!/^[0-9A-Za-z.+-]{1,32}$/.test(config.release)) fail('WEB_RELEASE has invalid characters');

const sources = new Set(["'self'"]);
const addOrigin = (value) => {
  if (!value) return;
  const url = new URL(value);
  sources.add(url.origin);
  sources.add(`${url.protocol === 'https:' ? 'wss:' : 'ws:'}//${url.host}`);
};
if (config.mode !== 'replay') {
  addOrigin(config.apiBaseUrl);
  if (config.discoveryUrl) {
    sources.add(new URL(config.discoveryUrl).origin);
    // Quick-tunnel hostnames change on every start, so discovery can point anywhere under this domain.
    sources.add('https://*.trycloudflare.com');
    sources.add('wss://*.trycloudflare.com');
  }
}
for (const extra of (env.WEB_CONNECT_SRC_EXTRA ?? '').split(/\s+/).filter(Boolean)) {
  if (!/^(https|wss):\/\/[A-Za-z0-9.*-]+(:\d+)?$/.test(extra))
    fail(`invalid WEB_CONNECT_SRC_EXTRA entry "${extra}"`);
  sources.add(extra);
}
const connectSrc = [...sources].join(' ');

const headersPath = join(dist, '_headers');
const headers = await readFile(headersPath, 'utf8');
if (!headers.includes('__CONNECT_SRC__'))
  fail('dist/_headers has no __CONNECT_SRC__ placeholder (already rendered?)');
await writeFile(headersPath, headers.replaceAll('__CONNECT_SRC__', connectSrc));
await writeFile(join(dist, 'config.json'), `${JSON.stringify(config, null, 2)}\n`);

console.log(
  `render-dist: mode=${config.mode} transport=${config.chatTransport} release=${config.release}`,
);
console.log(`render-dist: connect-src ${connectSrc}`);
