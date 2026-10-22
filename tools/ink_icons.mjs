// 🖋 Запекти тремтіння пера в значки: `ui/data/icons.src.svg` → `ui/data/icons.svg`.
//
//   npm i --prefix <тимчасова тека> roughjs@4.6.6
//   node tools/ink_icons.mjs <тимчасова тека>/node_modules/roughjs/bundled/rough.cjs.js
//
// Чому запікання, а не rough.js у браузері: застосунок працює офлайн і без
// збірки фронту, а спрайт вставляється в кожну сторінку готовим. Бібліотека
// потрібна лише тому, хто перемальовує значки, тому вона не лежить у пакеті.
//
// 🔴 Правити треба ДЖЕРЕЛО. Готовий спрайт несе в шапці хеш джерела, і
// `tests/test_ui_shared.py` падає, якщо джерело змінили, а спрайт не перезапекли.
//
// Тремтіння детерміноване: зерно кожної лінії береться з імені символу й номера
// елемента. Перемальований значок не зсуває штрихи всіх інших, тож різниця в
// git показує рівно те, що змінилось.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROUGHNESS = 0.35;
const BOWING = 0.5;

const here = dirname(fileURLToPath(import.meta.url));
const DATA = join(here, '..', 'src', 'nyshporka', 'ui', 'data');
const roughPath = process.argv[2];
if (!roughPath) {
  console.error('вкажіть шлях до roughjs/bundled/rough.cjs.js (див. шапку файла)');
  process.exit(2);
}
const rough = createRequire(import.meta.url)(roughPath);
const gen = rough.generator();

const src = readFileSync(join(DATA, 'icons.src.svg'), 'utf8').replace(/\r\n/g, '\n');
const digest = createHash('sha256').update(src).digest('hex');

const seedOf = (s) => parseInt(createHash('sha1').update(s).digest('hex').slice(0, 7), 16) || 1;
const num = (n) => String(Math.round(n * 100) / 100);
const attrs = (tag) => Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map((m) => [m[1], m[2]]));

function rr(x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  if (!r) return `M${x} ${y}h${w}v${h}h${-w}Z`;
  return `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}`
    + `A${r} ${r} 0 0 1 ${x + w - r} ${y + h}H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}`
    + `V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z`;
}

function ink(id, i, tag) {
  const name = tag.match(/^<(\w+)/)[1];
  const a = attrs(tag);
  const f = (k) => parseFloat(a[k] || '0');
  const o = { roughness: ROUGHNESS, bowing: BOWING, disableMultiStroke: true, seed: seedOf(`${id}#${i}`) };
  let d;
  if (name === 'path') d = gen.path(a.d, o);
  else if (name === 'circle') d = gen.ellipse(f('cx'), f('cy'), f('r') * 2, f('r') * 2, o);
  else if (name === 'ellipse') d = gen.ellipse(f('cx'), f('cy'), f('rx') * 2, f('ry') * 2, o);
  else if (name === 'rect') d = gen.path(rr(f('x'), f('y'), f('width'), f('height'), f('rx')), o);
  else if (name === 'line') d = gen.line(f('x1'), f('y1'), f('x2'), f('y2'), o);
  else throw new Error(`${id}: невідомий елемент <${name}>`);
  const fill = a.fill ? ` fill="${a.fill}"` : '';
  return gen.toPaths(d).map((p) => `<path d="${p.d.replace(/-?\d*\.?\d+(?:e-?\d+)?/g, (m) => num(+m))}"${fill}/>`).join('');
}

const out = [];
for (const m of src.matchAll(/<symbol ([^>]*)>([\s\S]*?)<\/symbol>/g)) {
  const head = attrs(`<s ${m[1]}>`);
  if ('data-plain' in head) {
    out.push(`  <symbol id="${head.id}" viewBox="${head.viewBox}">${m[2]}</symbol>`);
    continue;
  }
  const kids = m[2].match(/<\w+\b[^>]*\/>/g) || [];
  out.push(`  <symbol id="${head.id}" viewBox="${head.viewBox}">${kids.map((k, i) => ink(head.id, i, k)).join('')}</symbol>`);
}

const sprite = '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>\n'
  + `  <!-- 🖋 ЗГЕНЕРОВАНО з icons.src.svg (tools/ink_icons.mjs) — не правити руками. source-sha256: ${digest} -->\n`
  + out.join('\n') + '\n</defs></svg>\n';
writeFileSync(join(DATA, 'icons.svg'), sprite);
console.log(`icons.svg: ${out.length} символів, ${sprite.length} байт`);
