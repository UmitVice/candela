import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import sharp from 'sharp';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, 'public', 'icons');
const mark = await readFile(join(root, 'public', 'brand', 'candela-mark.svg'), 'utf8');
const inner = mark.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');

const tile = (markScale, radius) => {
  const offset = (64 - 64 * markScale) / 2;
  return Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
      `<rect width="64" height="64" rx="${radius}" fill="#07090c"/>` +
      `<g transform="translate(${offset} ${offset}) scale(${markScale})">${inner}</g></svg>`,
  );
};

const targets = [
  { file: 'icon-32.png', size: 32, svg: tile(0.84, 12) },
  { file: 'icon-192.png', size: 192, svg: tile(0.8, 14) },
  { file: 'icon-512.png', size: 512, svg: tile(0.8, 14) },
  // Maskable icons must keep the mark inside the 80% safe zone and fill the whole canvas.
  { file: 'maskable-512.png', size: 512, svg: tile(0.6, 0) },
  // iOS applies its own corner mask and renders transparency as black, so the tile is full-bleed.
  { file: 'apple-touch-icon-180.png', size: 180, svg: tile(0.72, 0) },
];

await mkdir(outDir, { recursive: true });
for (const { file, size, svg } of targets) {
  await sharp(svg, { density: 72 * (size / 64) * 2 })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toFile(join(outDir, file));
  console.log(`icons/${file} ${size}x${size}`);
}
