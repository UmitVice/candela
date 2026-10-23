import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const LIMIT_KB = 250;
const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const html = await readFile(join(dist, 'index.html'), 'utf8');
const scripts = new Set();
for (const match of html.matchAll(/<script[^>]+src="([^"]+\.js)"/g)) scripts.add(match[1]);
for (const match of html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+\.js)"/g))
  scripts.add(match[1]);

const queue = [...scripts];
while (queue.length) {
  const file = queue.shift();
  const code = await readFile(join(dist, file), 'utf8');
  for (const match of code.matchAll(/(?:from|import)\s*"\.\/(chunk-[A-Za-z0-9]+\.js)"/g)) {
    if (!scripts.has(match[1])) {
      scripts.add(match[1]);
      queue.push(match[1]);
    }
  }
}

let total = 0;
for (const file of scripts) {
  const size = gzipSync(await readFile(join(dist, file)), { level: 9 }).length;
  total += size;
  console.log(`  ${file.padEnd(28)} ${(size / 1024).toFixed(1).padStart(7)} kB gzip`);
}
const totalKb = total / 1024;
console.log(
  `  initial JS total            ${totalKb.toFixed(1).padStart(7)} kB gzip (limit ${LIMIT_KB} kB)`,
);
if (totalKb > LIMIT_KB) {
  console.error(`initial JS exceeds ${LIMIT_KB} kB gzip`);
  process.exit(1);
}
