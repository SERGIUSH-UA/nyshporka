// Хлібні крихти: показує шлях від кореня гілки до focus-особи.

import { escapeHtml } from '../utils/fmt-date.js';

export function createBreadcrumbs({ container, data, store }) {
  const byId = new Map(data.nodes.map((n) => [n.id, n]));

  function render(state) {
    container.innerHTML = '';
    if (state.mode === 'overview' || !state.focusId) {
      const span = document.createElement('span');
      span.className = 'bc-item bc-current';
      span.textContent = 'Усе дерево';
      container.appendChild(span);
      return;
    }

    // Знайти ланцюг від кореня гілки до focus-особи (через parent_ids,
    // обираючи батька з найменшою generation на кожному кроці).
    const chain = [];
    let cur = byId.get(state.focusId);
    const seen = new Set();
    while (cur && !seen.has(cur.id)) {
      chain.unshift(cur);
      seen.add(cur.id);
      const parents = (cur.parent_ids || [])
        .map((id) => byId.get(id))
        .filter(Boolean);
      if (!parents.length) break;
      parents.sort((a, b) => (a.generation ?? 99) - (b.generation ?? 99));
      cur = parents[0];
    }

    // Кнопка «Усе дерево».
    const home = document.createElement('button');
    home.className = 'bc-item bc-home';
    home.type = 'button';
    home.textContent = 'Усе дерево';
    home.addEventListener('click', () => store.update({
      mode: 'overview', focusId: null,
    }));
    container.appendChild(home);

    chain.forEach((node, i) => {
      const sep = document.createElement('span');
      sep.className = 'bc-sep';
      sep.textContent = '›';
      container.appendChild(sep);

      const item = document.createElement(i === chain.length - 1 ? 'span' : 'button');
      item.className = 'bc-item ' + (i === chain.length - 1 ? 'bc-current' : '');
      if (item.tagName === 'BUTTON') {
        item.type = 'button';
        item.addEventListener('click', () => store.update({
          mode: 'focus', focusId: node.id, selectedId: node.id,
        }));
      }
      item.textContent = node.name;
      container.appendChild(item);
    });
  }

  return { render };
}
