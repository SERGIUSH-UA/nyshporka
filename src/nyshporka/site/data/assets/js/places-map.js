// Мапа місць: Leaflet створюється один раз, фільтри лише ховають і показують
// маркери. Перелік місць — праворуч на широкому екрані, шторкою на телефоні.
// `places-map.html#PL9001` відкриває мапу на цьому місці.
import { createPanel, el } from './panel.js';

/* global L */

const root = document.getElementById('nysh-map');

const parse = (s, d) => { try { return JSON.parse(s || ''); } catch { return d; } };

function yearsOf(p) {
  const a = p.fact_year ?? p.lived_from;
  const b = p.fact_year_end ?? p.fact_year ?? p.lived_to ?? a;
  return a == null ? null : [a, b ?? a];
}

async function main() {
  const canvas = root.querySelector('.nysh-map__canvas');
  let gj;
  try {
    const res = await fetch(root.dataset.geojsonUrl);
    if (!res.ok) throw new Error(res.statusText);
    gj = await res.json();
  } catch {
    canvas.append(el('p.nysh-tree__status', {}, 'Не вдалося завантажити мапу. Якщо сторінку відкрито як файл, запустіть nysh site serve.'));
    return;
  }

  // Група без власного кольору (сірий за замовчуванням) бере барву з палітри.
  const PALETTE = ['#3f6c9f', '#b5523b', '#5a9a4a', '#a0782c', '#7a55a8', '#2f9a95'];
  const groups = parse(root.dataset.groups, []).map((g, i) => (
    !g.color || g.color.toLowerCase() === '#7f7f7f' ? { ...g, color: PALETTE[i % PALETTE.length] } : g));
  // Без груп у site.yml усі місця однієї барви — акцентної, а не «сірого іншого».
  const other = { id: 'other', label: 'Інше', color: groups.length ? '#8a8a8a' : '#a8443a', match: [] };
  const groupOf = (props) => {
    const byId = groups.find((g) => g.id === props.region);
    if (byId) return byId;
    const admin = (props.admin || []).join(' ').toLowerCase();
    return groups.find((g) => (g.match || []).some((m) => m && admin.includes(m.toLowerCase()))) || other;
  };
  const eras = [{ id: 'all', label: 'Усі роки' },
    ...parse(root.dataset.eras, []).map((e, i) => ({ id: `e${i}`, label: e.label, from: e.from ?? -1e9, to: e.to ?? 1e9 }))];

  const places = (gj.features || [])
    .filter((f) => f.geometry && f.geometry.type === 'Point')
    .map((f) => {
      const p = f.properties || {};
      const [lon, lat] = f.geometry.coordinates;
      return { id: p.id, name: p.name, admin: p.admin || [], persons: p.persons || [], lat, lon, group: groupOf(p) };
    });
  const usedGroups = [...new Map(places.map((p) => [p.group.id, p.group])).values()];

  const state = { groups: new Set(usedGroups.map((g) => g.id)), era: 'all', active: null };

  const map = L.map(canvas, { zoomControl: true, scrollWheelZoom: true, tap: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17, attribution: '&copy; OpenStreetMap',
  }).addTo(map);
  map.setView([48.5, 30.5], 6);

  const inEra = (person) => {
    if (state.era === 'all') return true;
    const era = eras.find((e) => e.id === state.era);
    const y = yearsOf(person);
    return !!y && y[1] >= era.from && y[0] <= era.to;
  };
  const visiblePersons = (pl) => pl.persons.filter(inEra);

  // Маркер: коло, площа — за кількістю згаданих осіб.
  for (const pl of places) {
    const n = pl.persons.length;
    pl.marker = L.circleMarker([pl.lat, pl.lon], {
      radius: 6 + Math.min(14, Math.sqrt(n) * 2.4),
      color: '#fff', weight: 1.5, fillColor: pl.group.color, fillOpacity: 0.88,
    });
    pl.marker.bindPopup(() => popup(pl), { maxWidth: 300, autoPanPadding: [24, 24] });
    pl.marker.on('click', () => { state.active = pl.id; highlight(); });
  }

  function popup(pl) {
    const ps = visiblePersons(pl);
    const kind = { birth: 'нар.', death: 'пом.', marriage: 'шлюб', baptism: 'хрещ.', burial: 'похов.', residence: 'жив' };
    const list = el('ul.nysh-popup__persons', {}, ps.slice(0, 14).map((p) => el('li', {},
      p.private && !p.name ? 'приватна особа' : el('a', { href: `persons/${p.id}.html` }, p.name),
      el('span', {}, ` ${kind[p.fact_type] || ''} ${p.fact_year ?? ''}`.trimEnd()))));
    return el('div.nysh-popup', {},
      el('a.nysh-popup__title', { href: `places/${pl.id}.html` }, pl.name),
      el('div.nysh-popup__admin', {}, pl.admin.slice(1, -1).join(' · ')),
      ps.length ? list : el('p', {}, 'Згадок у вибраний період немає.'),
      ps.length > 14 ? el('p.nysh-meta', {}, `і ще ${ps.length - 14} — на сторінці місця`) : null);
  }

  // ---- фільтри ---------------------------------------------------------------
  const chipsG = root.querySelector('[data-role="groups"]');
  const chipsE = root.querySelector('[data-role="eras"]');
  if (usedGroups.length > 1) {
    for (const g of usedGroups) {
      chipsG.append(el('button.nysh-chip.is-on', { type: 'button', 'data-id': g.id, style: `--chip:${g.color}`,
        onclick: (ev) => {
          const on = !state.groups.has(g.id);
          if (on) state.groups.add(g.id); else state.groups.delete(g.id);
          ev.currentTarget.classList.toggle('is-on', on);
          apply(true);
        } }, el('i.nysh-chip__dot'), g.label));
    }
  }
  if (eras.length > 1) {
    for (const e of eras) {
      chipsE.append(el('button.nysh-chip' + (e.id === 'all' ? '.is-on' : ''), { type: 'button', 'data-id': e.id,
        onclick: () => {
          state.era = e.id;
          chipsE.querySelectorAll('.nysh-chip').forEach((c) => c.classList.toggle('is-on', c.dataset.id === e.id));
          apply(true);
        } }, e.label));
    }
  }

  // ---- перелік ---------------------------------------------------------------
  const panel = createPanel(root.querySelector('.nysh-panel'));
  function list(visible) {
    const sorted = [...visible].sort((a, b) => visiblePersons(b).length - visiblePersons(a).length || a.name.localeCompare(b.name, 'uk'));
    panel.show([
      el('header.nysh-panel__head', {}, el('h2', {}, `Місця: ${visible.length}`)),
      el('ul.nysh-placelist', {}, sorted.map((pl) => el('li', {},
        el('button' + (pl.id === state.active ? '.is-active' : ''), { type: 'button', 'data-id': pl.id, onclick: () => go(pl) },
          el('i.nysh-chip__dot', { style: `--chip:${pl.group.color}` }),
          el('span.nysh-placelist__name', {}, pl.name),
          el('span.nysh-placelist__n', {}, String(visiblePersons(pl).length)))))),
    ]);
  }
  function highlight() {
    root.querySelectorAll('.nysh-placelist button').forEach((b) => b.classList.toggle('is-active', b.dataset.id === state.active));
  }
  function go(pl) {
    state.active = pl.id;
    highlight();
    map.flyTo([pl.lat, pl.lon], Math.max(map.getZoom(), 9), { duration: 0.6 });
    pl.marker.openPopup();
    if (window.matchMedia('(max-width: 899px)').matches) panel.setState('peek');
    history.replaceState(null, '', `#${pl.id}`);
  }

  // Кадр — на місцях, де 90 % згадок: одне далеке місце (заслання, еміграція)
  // не має віддаляти мапу до цілого континенту. Решта лишається на мапі.
  function core(visible) {
    const sorted = [...visible].sort((a, b) => visiblePersons(b).length - visiblePersons(a).length);
    const total = sorted.reduce((s, pl) => s + visiblePersons(pl).length, 0);
    const out = [];
    let acc = 0;
    for (const pl of sorted) {
      out.push(pl);
      acc += visiblePersons(pl).length;
      if (out.length >= 3 && acc >= total * 0.9) break;
    }
    return out;
  }

  function apply(fit) {
    const visible = places.filter((pl) => state.groups.has(pl.group.id) && (state.era === 'all' || visiblePersons(pl).length));
    for (const pl of places) {
      const on = visible.includes(pl);
      if (on && !map.hasLayer(pl.marker)) pl.marker.addTo(map);
      if (!on && map.hasLayer(pl.marker)) map.removeLayer(pl.marker);
    }
    list(visible);
    if (fit && visible.length) {
      map.fitBounds(L.latLngBounds(core(visible).map((pl) => [pl.lat, pl.lon])), { padding: [32, 32], maxZoom: 9 });
    }
  }

  apply(true);
  const want = places.find((pl) => pl.id === decodeURIComponent(window.location.hash.slice(1)));
  if (want) setTimeout(() => go(want), 300);
  window.addEventListener('resize', () => map.invalidateSize());
}

if (root) main();
