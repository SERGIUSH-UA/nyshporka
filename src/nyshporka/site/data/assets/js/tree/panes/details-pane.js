// Картка обраної особи: фото, факти, перехресні посилання.

import { escapeHtml, formatLifespan } from '../utils/fmt-date.js';

export function createDetailsPane({ container, data, store }) {
  const byId = new Map(data.nodes.map((n) => [n.id, n]));

  function render(state) {
    const id = state.selectedId;
    if (!id) {
      container.innerHTML = '<div class="nysh-empty">Виберіть особу у дереві</div>';
      return;
    }
    const node = byId.get(id);
    if (!node) {
      container.innerHTML = `<div class="nysh-empty">Особу ${id} не знайдено</div>`;
      return;
    }

    const parents = node.parent_ids
      .map((pid) => byId.get(pid))
      .filter(Boolean);
    const spouses = node.spouse_ids
      .map((sid) => byId.get(sid))
      .filter(Boolean);
    const children = node.child_ids
      .map((cid) => byId.get(cid))
      .filter(Boolean);

    const photoHtml = node.has_photo && node.photo_url
      ? `<img class="details-photo" src="${escapeHtml(node.photo_url)}" alt="${escapeHtml(node.name)}" onerror="this.style.display='none'">`
      : `<div class="details-photo-placeholder">${escapeHtml(node.initials)}</div>`;

    const flags = [];
    if (node.private) flags.push('<span class="flag flag-private">🔒 приватна</span>');
    if (node.has_disputed) flags.push('<span class="flag flag-disputed">⚠ суперечливо</span>');
    if (node.is_root) flags.push('<span class="flag flag-root">🌱 корінь гілки</span>');

    const setFocus = (pid) => () => store.update({ mode: 'focus', focusId: pid, selectedId: pid });
    const setSelected = (pid) => () => store.update({ selectedId: pid });

    container.innerHTML = `
      <div class="details-header">
        ${photoHtml}
        <div class="details-name">
          <h3>${escapeHtml(node.name)}</h3>
          <div class="details-meta">
            <code>${node.id}</code>
            <span>${escapeHtml(formatLifespan(node) || 'без дат')}</span>
          </div>
          ${flags.length ? `<div class="details-flags">${flags.join(' ')}</div>` : ''}
        </div>
      </div>

      <div class="details-stats">
        <div><b>${node.fact_count}</b><span>фактів</span></div>
        <div><b>${node.ancestor_count}</b><span>предків</span></div>
        <div><b>${node.descendant_count}</b><span>нащадків</span></div>
        <div><b>${node.generation ?? '?'}</b><span>покоління</span></div>
      </div>

      ${renderRel('Батьки', parents)}
      ${renderRel('Подружжя', spouses)}
      ${renderRel('Діти', children)}

      <div class="details-actions">
        <button type="button" class="action-focus">Зробити фокусом</button>
        <a class="action-page" href="persons/${node.id}.html">Сторінка особи →</a>
      </div>
    `;

    // Підв'язати клік-обробники для родинних посилань.
    container.querySelectorAll('[data-pid]').forEach((el) => {
      el.addEventListener('click', (ev) => {
        ev.preventDefault();
        const pid = el.dataset.pid;
        if (ev.shiftKey) setSelected(pid)();
        else setFocus(pid)();
      });
    });
    const focusBtn = container.querySelector('.action-focus');
    if (focusBtn) focusBtn.addEventListener('click', setFocus(node.id));
  }

  function renderRel(label, items) {
    if (!items.length) return '';
    const html = items.map((p) => {
      const cls = p.private ? 'rel-private' : '';
      return `<a class="rel-link ${cls}" data-pid="${p.id}" href="persons/${p.id}.html">
        ${escapeHtml(p.name)} <small>${escapeHtml(formatLifespan(p) || p.id)}</small>
      </a>`;
    }).join('');
    return `<div class="details-rel"><h4>${label}</h4><div class="rel-list">${html}</div></div>`;
  }

  return { render };
}
