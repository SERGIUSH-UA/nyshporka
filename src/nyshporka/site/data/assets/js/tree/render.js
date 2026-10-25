// SVG дерева: картки, лінії, зум і переміщення (мишею й пальцями).
// Увесь текст іде через .text() — імена з канону в розмітку не вставляються.
import { CARD } from './layout.js';
import { t } from '../strings.js';

/* global d3 */

const NAME_FONT = '600 13px Inter, system-ui, sans-serif';
const PAD = 12;
let measureCtx = null;

function textWidth(s, font) {
  if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
  measureCtx.font = font;
  return measureCtx.measureText(s).width;
}

// Ім'я в два рядки по словах; що не влізло — три крапки в кінці другого.
export function wrapName(name, maxW, font = NAME_FONT) {
  const words = String(name || '').split(/\s+/).filter(Boolean);
  const lines = [''];
  for (const w of words) {
    const cur = lines[lines.length - 1];
    const next = cur ? `${cur} ${w}` : w;
    if (textWidth(next, font) <= maxW || !cur) lines[lines.length - 1] = next;
    else if (lines.length < 2) lines.push(w);
    else { lines[1] = `${lines[1]} ${w}`; }
  }
  return lines.map((l) => {
    if (textWidth(l, font) <= maxW) return l;
    let s = l;
    while (s.length > 1 && textWidth(`${s}…`, font) > maxW) s = s.slice(0, -1);
    return `${s}…`;
  });
}

export function yearsLabel(n) {
  if (!n) return '';
  const fix = (v) => (v && /s$/.test(v) ? t('tree.decade', { y: v.slice(0, -1) }) : v);
  const b = fix(n.birth);
  const d = fix(n.death);
  if (b && d) return `${b} – ${d}`;
  if (b) return t('years.born', { y: b });
  if (d) return t('years.died', { y: d });
  return '';
}

export function isAnon(n) {
  return !n || Boolean(n.anon) || n.name === '(приватна особа)';
}

export function createView(svgEl, { onTap, onActivate }) {
  const svg = d3.select(svgEl);
  const vp = svg.append('g').attr('class', 'vp');
  const gLinks = vp.append('g').attr('class', 'links');
  const gCards = vp.append('g').attr('class', 'cards');
  const zoom = d3.zoom()
    .scaleExtent([0.12, 2.5])
    .on('zoom', (ev) => vp.attr('transform', ev.transform));
  svg.call(zoom).on('dblclick.zoom', null);

  let last = null;

  const size = () => {
    const r = svgEl.getBoundingClientRect();
    return { w: r.width || 800, h: r.height || 600 };
  };

  function minScale() {
    // На телефоні картка не дрібніша за ~120 px: читається без зуму пальцями.
    return size().w < 700 ? 0.72 : 0.85;
  }

  function transformFor(result) {
    const { w, h } = size();
    const b = result.bounds;
    const bw = b.x1 - b.x0 + 60;
    const bh = b.y1 - b.y0 + 60;
    const fitK = Math.min(1, w / bw, h / bh);
    const k = Math.max(fitK, minScale());
    if (fitK >= k) {
      return d3.zoomIdentity.translate(w / 2 - ((b.x0 + b.x1) / 2) * k, h / 2 - ((b.y0 + b.y1) / 2) * k).scale(k);
    }
    const f = result.focus;
    return d3.zoomIdentity.translate(w / 2 - f.x * k, h * 0.45 - (f.y + CARD.h / 2) * k).scale(k);
  }

  function draw(result, nodes, { selectedId, animate = true } = {}) {
    last = result;
    const tr = svg.transition().duration(animate ? 420 : 0).ease(d3.easeCubicOut);

    // Лінії: прості ламані, без анімації позицій — лише поява.
    const path = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
    gLinks.selectAll('path')
      .data(result.links)
      .join('path')
      .attr('class', (l) => `link link--${l.kind}${l.hyp ? ' is-hyp' : ''}`)
      .attr('d', (l) => path(l.pts))
      .attr('opacity', 0)
      .transition(tr)
      .attr('opacity', 1);

    const sel = gCards.selectAll('g.card').data(result.cards, (c) => c.key);
    sel.exit().transition(tr).attr('opacity', 0).remove();

    const enter = sel.enter().append('g')
      .attr('class', 'card')
      .attr('tabindex', 0)
      .attr('role', 'button')
      .attr('opacity', 0)
      .attr('transform', (c) => `translate(${c.x - CARD.w / 2},${c.y})`);
    enter.append('rect').attr('class', 'card__bg').attr('width', CARD.w).attr('height', CARD.h).attr('rx', 10);
    enter.append('rect').attr('class', 'card__sex').attr('width', 5).attr('height', CARD.h - 16).attr('x', 0).attr('y', 8).attr('rx', 2.5);
    enter.append('text').attr('class', 'card__name').attr('x', PAD).attr('y', 22);
    enter.append('text').attr('class', 'card__years').attr('x', PAD).attr('y', CARD.h - 11);
    enter.append('g').attr('class', 'card__up');
    enter.append('g').attr('class', 'card__down');

    const all = enter.merge(sel);
    all.each(function (c) {
      const n = nodes.get(c.id);
      const g = d3.select(this);
      const anon = isAnon(n);
      g.attr('class', ['card', `card--${(n?.sex || 'u').toLowerCase()}`, `role-${c.role}`,
        c.hyp ? 'is-hyp' : '', c.ref ? 'is-ref' : '', anon ? 'is-anon' : '',
        c.id === selectedId ? 'is-selected' : ''].filter(Boolean).join(' '));
      g.attr('aria-label', `${anon ? t('private.person') : n?.name || c.id}${c.ref ? t('tree.ref.aria') : ''}`);
      const lines = wrapName(anon ? t('private.person') : n?.name || c.id, CARD.w - PAD * 2);
      const name = g.select('.card__name');
      name.selectAll('tspan').data(lines).join('tspan')
        .attr('x', PAD).attr('dy', (_, i) => (i ? 15 : 0)).text((s) => s);
      name.attr('y', lines.length > 1 ? 20 : 26);
      g.select('.card__years').text(c.ref ? t('tree.ref') : yearsLabel(n));

      const up = g.select('.card__up');
      up.selectAll('*').remove();
      if (c.moreUp) {
        up.append('circle').attr('cx', CARD.w / 2).attr('cy', 0).attr('r', 8);
        up.append('text').attr('x', CARD.w / 2).attr('y', 3.5).text('▲');
      }
      const down = g.select('.card__down');
      down.selectAll('*').remove();
      if (c.moreDown) {
        const label = `▼ ${c.moreDown}`;
        const wv = Math.max(26, textWidth(label, '600 10px Inter, system-ui') + 12);
        down.append('rect').attr('x', CARD.w / 2 - wv / 2).attr('y', CARD.h - 8).attr('width', wv).attr('height', 16).attr('rx', 8);
        down.append('text').attr('x', CARD.w / 2).attr('y', CARD.h + 3.5).text(label);
      }
    });

    all.on('click', (ev, c) => { ev.stopPropagation(); onTap(c); })
      .on('dblclick', (ev, c) => { ev.stopPropagation(); onActivate(c); })
      .on('keydown', (ev, c) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onActivate(c); }
      });

    all.transition(tr)
      .attr('opacity', 1)
      .attr('transform', (c) => `translate(${c.x - CARD.w / 2},${c.y})`);

    svg.transition(tr).call(zoom.transform, transformFor(result));
  }

  function setSelected(id) {
    gCards.selectAll('g.card').classed('is-selected', (c) => c.id === id);
  }

  return {
    draw,
    setSelected,
    fit() {
      if (!last) return;
      const { w, h } = size();
      const b = last.bounds;
      const k = Math.min(1.2, w / (b.x1 - b.x0 + 60), h / (b.y1 - b.y0 + 60));
      svg.transition().duration(350).call(zoom.transform,
        d3.zoomIdentity.translate(w / 2 - ((b.x0 + b.x1) / 2) * k, h / 2 - ((b.y0 + b.y1) / 2) * k).scale(k));
    },
    zoomBy(f) { svg.transition().duration(220).call(zoom.scaleBy, f); },
    recenter() { if (last) svg.call(zoom.transform, transformFor(last)); },
  };
}
