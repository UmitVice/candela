import { createReadStream } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const port = Number(process.env.WEB_PREVIEW_PORT ?? 4210);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.txt': 'text/plain; charset=utf-8',
};

function parseHeaders(text) {
  const rules = [];
  let current = null;
  for (const line of text.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue;
    if (!/^\s/.test(line)) {
      const pattern = new RegExp(
        `^${line
          .trim()
          .replace(/[.+?^${}()|[\]\\]/g, '\\$&')
          .replace(/\*/g, '.*')}$`,
      );
      current = { pattern, headers: [] };
      rules.push(current);
    } else if (current) {
      const index = line.indexOf(':');
      current.headers.push([line.slice(0, index).trim(), line.slice(index + 1).trim()]);
    }
  }
  return rules;
}

const rawHeaders = await readFile(join(dist, '_headers'), 'utf8');
if (rawHeaders.includes('__CONNECT_SRC__')) {
  console.error('preview: dist/_headers is not rendered; run `make web-preview`');
  process.exit(1);
}
const rules = parseHeaders(rawHeaders);

// Plain-http loopback cannot honour HSTS or upgrade-insecure-requests; everything else is served as on Netlify.
const localize = (name, value) =>
  name.toLowerCase() === 'content-security-policy'
    ? value.replace(/\s*upgrade-insecure-requests;?/, '')
    : value;

function headersFor(path) {
  const out = {};
  for (const rule of rules) {
    if (!rule.pattern.test(path)) continue;
    for (const [name, value] of rule.headers) {
      if (name.toLowerCase() === 'strict-transport-security') continue;
      out[name] = localize(name, value);
    }
  }
  return out;
}

async function resolveFile(path) {
  const safe = normalize(decodeURIComponent(path)).replace(/^(\.\.[/\\])+/, '');
  const candidate = join(dist, safe);
  if (!candidate.startsWith(dist)) return null;
  try {
    const info = await stat(candidate);
    if (info.isFile()) return candidate;
    if (info.isDirectory()) {
      const index = join(candidate, 'index.html');
      if ((await stat(index)).isFile()) return index;
    }
  } catch {
    return null;
  }
  return null;
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://localhost:${port}`);
  const hidden = /^\/(_headers|_redirects)$/.test(url.pathname);
  let file = hidden ? null : await resolveFile(url.pathname);
  let status = 200;
  if (!file) {
    if (extname(url.pathname)) status = 404;
    else file = join(dist, 'index.html');
  }
  const headers = headersFor(url.pathname);
  if (status === 404 || !file) {
    res
      .writeHead(404, { ...headers, 'content-type': 'text/plain; charset=utf-8' })
      .end('Not found');
    return;
  }
  res.writeHead(status, {
    ...headers,
    'content-type': MIME[extname(file)] ?? 'application/octet-stream',
  });
  createReadStream(file).pipe(res);
}).listen(port, '127.0.0.1', () => {
  console.log(`preview: serving dist with rendered headers on http://localhost:${port}`);
});
