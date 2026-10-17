// Головна: пошук особи веде на її сторінку; `[data-stat]` бере живі лічильники
// з assets/stats.json — так рукописна головна не бреше застарілими числами.
import { attach } from './search.js';

document.querySelectorAll('.nysh-home .nysh-search').forEach((root) => {
  attach(root, { url: root.dataset.indexUrl, base: root.dataset.base || '' });
});

const slots = document.querySelectorAll('[data-stat]');
if (slots.length) {
  const base = document.querySelector('.nysh-home')?.dataset.base || '';
  fetch(`${base}assets/stats.json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((stats) => {
      if (!stats) return;
      slots.forEach((s) => {
        const v = stats[s.dataset.stat];
        if (v === undefined || v === null) return;
        s.textContent = Number.isFinite(v) && !s.dataset.stat.startsWith('year') ? v.toLocaleString('uk-UA') : String(v);
      });
    })
    .catch(() => {});
}
