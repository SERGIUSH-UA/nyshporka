// Простий tooltip на body. Створюється раз, керується show/hide/move.

import { escapeHtml, formatLifespan } from '../utils/fmt-date.js';

let tipEl = null;

function ensureEl() {
  if (tipEl) return tipEl;
  tipEl = document.createElement('div');
  tipEl.className = 'nysh-tree-tooltip';
  tipEl.style.display = 'none';
  document.body.appendChild(tipEl);
  return tipEl;
}

export function showNodeTooltip(ev, node, rels) {
  const el = ensureEl();
  const d = node;
  const flags = [];
  if (d.has_disputed) flags.push('⚠ суперечливо');
  if (d.private) flags.push('🔒 приватна');
  const rel = rels[d.id] || {};
  const ancDesc = `${d.ancestor_count} предків · ${d.descendant_count} нащадків`;
  el.innerHTML = `
    <strong>${escapeHtml(d.name)}</strong> <code>${d.id}</code><br>
    <span>${formatLifespan(d) || '<small>без дат</small>'}</span><br>
    <small>покоління ${d.generation ?? '?'} · ${ancDesc}</small>
    ${flags.length ? `<br><small>${flags.join(' · ')}</small>` : ''}
    <div class="tip-hint">Клік — фокус / Shift+клік — деталі</div>
  `;
  el.style.display = 'block';
  moveTooltip(ev);
}

export function moveTooltip(ev) {
  if (!tipEl) return;
  tipEl.style.left = (ev.pageX + 14) + 'px';
  tipEl.style.top = (ev.pageY + 14) + 'px';
}

export function hideTooltip() {
  if (tipEl) tipEl.style.display = 'none';
}
