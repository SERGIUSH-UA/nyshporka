// Дерево роду: фокус в адресі (`family-tree.html#I9001`), «назад» повертає
// попередню особу. Тап по картці — деталі, ще тап (або подвійний клік) — центр.
import { indexData, layout, parentsOf, siblingsOf, familiesOf, rootOf } from './layout.js';
import { createView, yearsLabel, isAnon } from './render.js';
import { createPanel, el } from '../panel.js';
import { attach, loadIndex } from '../search.js';

const app = document.getElementById('nysh-tree');

const store = {
  get(k, d) { try { const v = localStorage.getItem(`nysh-tree-${k}`); return v === null ? d : Number(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`nysh-tree-${k}`, String(v)); } catch { /* приватне вікно */ } },
};

async function main() {
  const status = app.querySelector('.nysh-tree__status');
  let data;
  try {
    const res = await fetch(app.dataset.treeUrl);
    if (!res.ok) throw new Error(res.statusText);
    data = await res.json();
  } catch (e) {
    status.textContent = 'Не вдалося завантажити дерево. Якщо сторінку відкрито як файл, запустіть nysh site serve.';
    return;
  }
  const search = await loadIndex(app.dataset.indexUrl);
  const entries = new Map(search.map((e) => [e.id, e]));
  const ix = indexData(data);
  const nodes = ix.nodes;
  if (!nodes.size) {
    status.textContent = 'У дереві поки нікого немає.';
    return;
  }
  status.hidden = true;

  const state = { focus: null, selected: null, up: store.get('up', 3), down: store.get('down', 2), result: null };
  const panel = createPanel(app.querySelector('.nysh-panel'), { onClose: () => { state.selected = null; view.setSelected(null); } });
  const view = createView(app.querySelector('.nysh-tree__svg'), {
    onTap: (c) => {
      if (c.ref || (state.selected === c.id && c.id !== state.focus)) focusOn(c.id);
      else select(c.id);
    },
    onActivate: (c) => focusOn(c.id),
  });

  // Початкова особа: з адреси, інакше — та, чий родовід сягає найглибше.
  const defaultFocus = () => {
    let best = null;
    for (const n of nodes.values()) {
      if (isAnon(n)) continue;
      const score = (n.ancestor_count || 0) * 2 + Math.min(n.descendant_count || 0, 10);
      if (!best || score > best[0]) best = [score, n.id];
    }
    return best ? best[1] : nodes.keys().next().value;
  };
  const fromHash = () => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    return nodes.has(id) ? id : null;
  };

  function render(animate) {
    state.result = layout(ix, state.focus, { up: state.up, down: state.down });
    view.draw(state.result, nodes, { selectedId: state.selected, animate });
    app.querySelector('[data-out="up"]').textContent = state.up;
    app.querySelector('[data-out="down"]').textContent = state.down;
  }

  function focusOn(id, { push = true, animate = true } = {}) {
    if (!nodes.has(id)) return;
    state.focus = id;
    state.selected = id;
    if (push && window.location.hash.slice(1) !== id) history.pushState({ id }, '', `#${id}`);
    const n = nodes.get(id);
    document.title = `${isAnon(n) ? 'Дерево' : n.name} — дерево`;
    render(animate);
    showDetails(id, false);
  }

  function select(id) {
    state.selected = id;
    view.setSelected(id);
    showDetails(id, true);
  }

  // ---- панель деталей --------------------------------------------------------
  function personChip(p) {
    const n = nodes.get(p.id);
    const anon = isAnon(n);
    return el('button.nysh-chip' + (p.hyp ? '.is-hyp' : '') + (anon ? '.is-anon' : ''),
      { type: 'button', title: p.hyp ? 'гіпотеза' : null, onclick: () => focusOn(p.id) },
      el('span.nysh-chip__name', {}, anon ? 'приватна особа' : n.name),
      el('span.nysh-chip__years', {}, yearsLabel(n)));
  }
  function group(title, people) {
    if (!people.length) return null;
    return el('section.nysh-panel__group', {}, el('h3', {}, title),
      el('div.nysh-panel__chips', {}, people.map(personChip)));
  }

  function showDetails(id, expand) {
    const n = nodes.get(id);
    const anon = isAnon(n);
    const entry = entries.get(id);
    const par = parentsOf(ix, id);
    const fams = familiesOf(ix, id);
    const card = state.result?.cards.find((c) => c.id === id && !c.ref);
    const kids = fams.flatMap((f) => f.children);
    const sex = { M: 'чоловік', F: 'жінка' }[n.sex];
    const head = el('header.nysh-panel__head', {},
      el('h2', {}, anon ? 'Приватна особа' : n.name),
      el('p.nysh-panel__years', {}, [yearsLabel(n), entry?.p].filter(Boolean).join(' · ') || 'роки невідомі'));
    const tags = el('p.nysh-panel__tags', {},
      sex ? el('span.nysh-badge', {}, sex) : null,
      card?.hyp ? el('span.nysh-badge.nysh-badge--hyp', {}, "зв'язок — гіпотеза") : null,
      n.has_disputed ? el('span.nysh-badge.nysh-badge--disputed', {}, 'є суперечливі факти') : null,
      anon ? el('span.nysh-badge.nysh-badge--private', {}, 'дані приховано') : null);
    const actions = el('div.nysh-panel__actions', {},
      id !== state.focus ? el('button.md-button.md-button--primary', { type: 'button', onclick: () => focusOn(id) }, 'Зробити центром') : null,
      entry ? el('a.md-button' + (id === state.focus ? '.md-button--primary' : ''), { href: `persons/${id}.html` }, 'Сторінка особи') : null);
    const parents = par ? [par.father, par.mother].filter(Boolean) : [];
    const spouses = fams.map((f) => f.partner).filter(Boolean);
    panel.show([
      head, actions, tags,
      group('Батьки', parents),
      group(spouses.length > 1 ? 'Подружжя' : 'Чоловік / дружина', spouses),
      group('Діти', kids),
      group('Брати й сестри', siblingsOf(ix, id)),
      el('p.nysh-meta', {}, `Відомих предків: ${n.ancestor_count || 0} · нащадків: ${n.descendant_count || 0}`),
    ], { expand });
  }

  // ---- керування ---------------------------------------------------------------
  attach(app.querySelector('.nysh-search'), { url: app.dataset.indexUrl, onPick: (e) => focusOn(e.id) });
  app.querySelector('.nysh-tree__bar').addEventListener('click', onAct);
  app.querySelector('.nysh-tree__zoom').addEventListener('click', onAct);
  function onAct(ev) {
    const b = ev.target.closest('[data-act]');
    if (!b) return;
    const act = b.dataset.act;
    if (act === 'up+' || act === 'up-') {
      state.up = Math.max(0, Math.min(8, state.up + (act === 'up+' ? 1 : -1)));
      store.set('up', state.up);
      render(true);
    } else if (act === 'down+' || act === 'down-') {
      state.down = Math.max(0, Math.min(8, state.down + (act === 'down+' ? 1 : -1)));
      store.set('down', state.down);
      render(true);
    } else if (act === 'root') {
      focusOn(rootOf(ix, state.focus));
    } else if (act === 'fit') {
      view.fit();
    } else if (act === 'zoom+') {
      view.zoomBy(1.3);
    } else if (act === 'zoom-') {
      view.zoomBy(1 / 1.3);
    }
  }
  window.addEventListener('popstate', () => {
    const id = fromHash();
    if (id && id !== state.focus) focusOn(id, { push: false });
  });
  window.addEventListener('hashchange', () => {
    const id = fromHash();
    if (id && id !== state.focus) focusOn(id, { push: false });
  });
  let resizeT = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => view.recenter(), 200);
  });

  const first = fromHash() || defaultFocus();
  history.replaceState({ id: first }, '', `#${first}`);
  focusOn(first, { push: false, animate: false });
}

if (app) main();
