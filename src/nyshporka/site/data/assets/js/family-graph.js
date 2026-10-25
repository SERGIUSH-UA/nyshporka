// Граф зв'язків: увесь рід одним полотном (canvas — сотні вузлів без гальм).
// Покоління тягнуть вузли по вертикалі, тож граф читається згори вниз.
// Тап по вузлу — особа й її найближчі; повзунок року лишає тих, хто тоді жив.
import { createPanel, el } from './panel.js';
import { attach } from './search.js';
import { t } from './strings.js';
import { yearsLabel, isAnon } from './tree/render.js';

/* global d3 */

const root = document.getElementById('nysh-graph');
const PALETTE = ['#b5523b', '#3b7bb5', '#5a9a4a', '#a0782c', '#7a55a8', '#2f9a95',
  '#c0617f', '#6b7f2a', '#d08a3a', '#4a62a8', '#8a5a3a', '#3a8a6a'];

async function main() {
  const canvas = root.querySelector('canvas');
  const status = root.querySelector('.nysh-tree__status');
  let data;
  try {
    const res = await fetch(root.dataset.graphUrl);
    if (!res.ok) throw new Error(res.statusText);
    data = await res.json();
  } catch {
    status.textContent = t('graph.error');
    return;
  }
  status.hidden = true;

  const nodes = data.nodes.map((n) => ({ ...n }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = (data.links || [])
    .filter((l) => byId.has(l.source) && byId.has(l.target))
    .map((l) => ({ ...l }));

  // Колір — гілка; найбільші гілки беруть палітру першими, дрібні — сірі.
  const sizes = new Map();
  for (const n of nodes) sizes.set(n.branch_id, (sizes.get(n.branch_id) || 0) + 1);
  const ranked = [...sizes.entries()].sort((a, b) => b[1] - a[1]).map((x) => x[0]);
  const color = new Map(ranked.map((b, i) => [b, i < PALETTE.length && sizes.get(b) > 1 ? PALETTE[i] : '#9a9286']));
  const neighbours = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const l of links) {
    neighbours.get(l.source).add(l.target);
    neighbours.get(l.target).add(l.source);
  }

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id((n) => n.id).distance((l) => (l.type === 'spouse' ? 16 : 34)).strength(0.9))
    .force('charge', d3.forceManyBody().strength(-46).distanceMax(320))
    .force('y', d3.forceY((n) => (n.generation ?? 4) * 70).strength((n) => (n.generation == null ? 0.02 : 0.25)))
    .force('x', d3.forceX(0).strength(0.02))
    .force('collide', d3.forceCollide(7))
    .stop();
  for (let i = 0; i < 360; i += 1) sim.tick();

  const state = { year: null, hyp: true, selected: null, t: d3.zoomIdentity };
  const ctx = canvas.getContext('2d');
  const alive = (n) => state.year === null
    || (n.lived_from != null && n.lived_from <= state.year && (n.lived_to ?? n.lived_from + 70) >= state.year);
  const css = (name, d) => getComputedStyle(root).getPropertyValue(name).trim() || d;

  function size() {
    const r = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    return { w: r.width, h: r.height, dpr };
  }
  let dims = size();

  function draw() {
    const { w, h, dpr } = dims;
    const tf = state.t;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.translate(tf.x, tf.y);
    ctx.scale(tf.k, tf.k);
    const sel = state.selected;
    const near = sel ? neighbours.get(sel) : null;
    const ink = css('--nysh-ink-2', '#6b5d4a');
    for (const l of links) {
      if (l.hypothetical && !state.hyp) continue;
      const a = l.source;
      const b = l.target;
      const on = alive(a) && alive(b);
      const hot = sel && (a.id === sel || b.id === sel);
      ctx.globalAlpha = hot ? 0.95 : on ? (sel ? 0.18 : 0.5) : 0.06;
      ctx.strokeStyle = hot ? css('--nysh-accent', '#8b2c20') : ink;
      ctx.lineWidth = (hot ? 2 : l.type === 'spouse' ? 1.6 : 1) / Math.sqrt(tf.k);
      ctx.setLineDash(l.hypothetical ? [4 / tf.k, 3 / tf.k] : []);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    for (const n of nodes) {
      const on = alive(n);
      const hot = n.id === sel || (near && near.has(n.id));
      ctx.globalAlpha = on ? (sel && !hot ? 0.35 : 1) : 0.1;
      ctx.fillStyle = isAnon(n) ? '#b8b0a2' : color.get(n.branch_id);
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.id === sel ? 7 : 4.5, 0, Math.PI * 2);
      ctx.fill();
      if (n.id === sel) {
        ctx.lineWidth = 2 / tf.k;
        ctx.strokeStyle = css('--nysh-accent', '#8b2c20');
        ctx.stroke();
      }
    }
    // Підписи: усі — коли наблизили, інакше лише вибрана особа й її найближчі.
    ctx.globalAlpha = 1;
    ctx.font = `${12 / tf.k}px Inter, system-ui, sans-serif`;
    ctx.fillStyle = css('--nysh-ink', '#2a211a');
    ctx.strokeStyle = css('--nysh-bg', '#faf7f1');
    ctx.lineWidth = 3 / tf.k;
    for (const n of nodes) {
      const hot = n.id === sel || (near && near.has(n.id));
      if (!(hot || (tf.k > 1.6 && alive(n))) || isAnon(n)) continue;
      const label = n.name;
      ctx.strokeText(label, n.x + 8 / tf.k, n.y + 4 / tf.k);
      ctx.fillText(label, n.x + 8 / tf.k, n.y + 4 / tf.k);
    }
  }

  const zoom = d3.zoom().scaleExtent([0.1, 6]).on('zoom', (ev) => { state.t = ev.transform; draw(); });
  const sel = d3.select(canvas).call(zoom).on('dblclick.zoom', null);

  function fit(animate = true) {
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const k = Math.min(2, 0.92 * Math.min(dims.w / (x1 - x0 + 40), dims.h / (y1 - y0 + 40)));
    const tf = d3.zoomIdentity.translate(dims.w / 2 - ((x0 + x1) / 2) * k, dims.h / 2 - ((y0 + y1) / 2) * k).scale(k);
    (animate ? sel.transition().duration(400) : sel).call(zoom.transform, tf);
  }

  // ---- вибір ---------------------------------------------------------------------
  const panel = createPanel(root.querySelector('.nysh-panel'), { onClose: () => { state.selected = null; draw(); } });
  function select(id, center = false) {
    state.selected = id;
    const n = byId.get(id);
    const anon = isAnon(n);
    const rel = [...neighbours.get(id)].map((x) => byId.get(x));
    panel.show([
      el('header.nysh-panel__head', {}, el('h2', {}, anon ? t('private.title') : n.name),
        el('p.nysh-panel__years', {}, yearsLabel(n) || t('years.unknown'))),
      el('div.nysh-panel__actions', {},
        el('a.md-button.md-button--primary', { href: `family-tree.html#${id}` }, t('graph.in.tree')),
        anon ? null : el('a.md-button', { href: `persons/${id}.html` }, t('tree.page'))),
      rel.length ? el('section.nysh-panel__group', {}, el('h3', {}, t('graph.near')),
        el('div.nysh-panel__chips', {}, rel.map((r) => el('button.nysh-chip' + (isAnon(r) ? '.is-anon' : ''),
          { type: 'button', onclick: () => select(r.id, true) },
          el('span.nysh-chip__name', {}, isAnon(r) ? t('private.person') : r.name),
          el('span.nysh-chip__years', {}, yearsLabel(r)))))) : null,
    ]);
    if (center) {
      const k = Math.max(state.t.k, 1.4);
      sel.transition().duration(400).call(zoom.transform,
        d3.zoomIdentity.translate(dims.w / 2 - n.x * k, dims.h / 2 - n.y * k).scale(k));
    }
    draw();
  }
  canvas.addEventListener('click', (ev) => {
    const r = canvas.getBoundingClientRect();
    const [x, y] = state.t.invert([ev.clientX - r.left, ev.clientY - r.top]);
    let best = null;
    for (const n of nodes) {
      const d = Math.hypot(n.x - x, n.y - y);
      if (d < 14 / state.t.k && (!best || d < best[0])) best = [d, n];
    }
    if (best) select(best[1].id);
    else if (state.selected) panel.close();
  });

  // ---- керування -------------------------------------------------------------------
  attach(root.querySelector('.nysh-search'), { url: root.dataset.indexUrl, onPick: (e) => byId.has(e.id) && select(e.id, true) });
  const range = root.querySelector('input[type="range"]');
  const out = root.querySelector('[data-out="year"]');
  const yMax = Number(root.dataset.yearMax);
  range.addEventListener('input', () => {
    const v = Number(range.value);
    state.year = v > yMax ? null : v;
    out.textContent = state.year === null ? t('graph.all') : t('graph.year', { y: state.year });
    draw();
  });
  root.querySelector('[data-opt="hyp"]').addEventListener('change', (ev) => { state.hyp = ev.target.checked; draw(); });
  root.querySelector('.nysh-tree__zoom').addEventListener('click', (ev) => {
    const act = ev.target.closest('[data-act]')?.dataset.act;
    if (act === 'zoom+') sel.transition().duration(200).call(zoom.scaleBy, 1.4);
    if (act === 'zoom-') sel.transition().duration(200).call(zoom.scaleBy, 1 / 1.4);
    if (act === 'fit') fit();
  });
  window.addEventListener('resize', () => { dims = size(); draw(); });
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener?.('change', draw);
  new MutationObserver(draw).observe(document.body, { attributes: true, attributeFilter: ['data-md-color-scheme'] });

  fit(false);
  let want = '';
  try { want = decodeURIComponent(window.location.hash.slice(1)); } catch { want = ''; }
  if (byId.has(want)) select(want, true);
}

if (root) main();
