// Leaflet-мапа місць канону роду.
// Підвантажує places.geojson, рендерить точки на OSM-tile.
// Групи місць (колір і легенда) та епохи беруться з data-атрибутів контейнера,
// які пише генератор сайту з `data/site/site.yml`: мапа не знає нічого про
// конкретний рід.

(function () {
  const containerId = 'nysh-places-map';
  const container = document.getElementById(containerId);
  if (!container) return;

  const map = L.map(containerId).setView([47.5, 30.0], 5);

  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const geojsonUrl = container.dataset.geojsonUrl || 'assets/places.geojson';

  // Групи: [{id, label, color, match: ["підрядок", ...]}]. Місце потрапляє в
  // першу групу, чий підрядок є в його адмінподілі; решта — «Інше».
  const GROUPS = parseJson(container.dataset.groups, []);
  const OTHER = { id: 'other', label: 'Інше', color: '#7f7f7f', match: [] };
  const REGION_COLORS = {};
  const REGION_LABELS = {};
  for (const g of [...GROUPS, OTHER]) {
    REGION_COLORS[g.id] = g.color || OTHER.color;
    REGION_LABELS[g.id] = g.label || g.id;
  }

  function classify(admin) {
    const text = (Array.isArray(admin) ? admin.join(' ') : '').toLowerCase();
    for (const g of GROUPS) {
      if ((g.match || []).some((m) => m && text.includes(String(m).toLowerCase()))) return g.id;
    }
    return 'other';
  }

  function parseJson(raw, fallback) {
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (e) { return fallback; }
  }

  const FACT_LABELS = {
    birth: 'народження',
    death: 'смерть',
    marriage: 'шлюб',
    divorce: 'розлучення',
    residence: 'проживання',
    occupation: 'служба',
    education: 'навчання',
    baptism: 'хрещення',
    burial: 'поховання',
    emigration: 'переїзд',
    military: 'військова служба',
    religion: 'віросповідання',
    nationality: 'громадянство',
    other: 'подія',
  };

  // Ери — кожне місце фільтрується за роками подій: потрапляє в еру, якщо
  // діапазон [min_year, max_year] перетинається з нею. Без конфігу — лише «Усе».
  const ERAS = [
    { id: 'all', label: 'Усе', from: -Infinity, to: Infinity },
    ...parseJson(container.dataset.eras, []).map((e, i) => ({
      id: `e${i + 1}`,
      label: e.label,
      from: e.from == null ? -Infinity : e.from,
      to: e.to == null ? Infinity : e.to,
    })),
  ];
  let currentEra = 'all';

  // Зберігаємо посилання на маркери для тогглу.
  const markerEntries = []; // [{ marker, yearRange: [min, max] }]
  let markerGroup = null;

  fetch(geojsonUrl)
    .then((r) => r.json())
    .then((data) => {
      markerGroup = L.featureGroup();

      L.geoJSON(data, {
        pointToLayer: (feature, latlng) => {
          const region = classify((feature.properties || {}).admin);
          return L.circleMarker(latlng, {
            radius: 7,
            fillColor: REGION_COLORS[region] || REGION_COLORS.other,
            color: '#fff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.85,
          });
        },
        onEachFeature: (feature, lyr) => {
          const p = feature.properties || {};
          const adminText = Array.isArray(p.admin)
            ? p.admin.filter(Boolean).join(', ')
            : '';
          const personsHtml = renderPersons(p.persons || []);
          const html = [
            `<strong>${escapeHtml(p.name || p.id)}</strong>`,
            adminText ? `<div class="popup-admin">${escapeHtml(adminText)}</div>` : '',
            personsHtml,
            p.id
              ? `<div class="popup-id"><a href="places/${p.id}.html">${p.id}</a></div>`
              : '',
          ]
            .filter(Boolean)
            .join('');
          lyr.bindPopup(html, { maxWidth: 360 });
          lyr.bindTooltip(escapeHtml(p.name || p.id), {
            direction: 'top',
            offset: [0, -8],
            opacity: 0.95,
            className: 'nysh-marker-tooltip',
          });
          // Обчислюємо діапазон років для era-фільтрації.
          const yearRange = computeYearRange(p.persons || []);
          markerEntries.push({ marker: lyr, yearRange, region: classify(p.admin) });
        },
      });

      // Початково — усі.
      applyEra(currentEra);
      markerGroup.addTo(map);

      // Region legend (як раніше).
      const legend = L.control({ position: 'bottomright' });
      legend.onAdd = () => {
        const div = L.DomUtil.create('div', 'nysh-map-legend');
        const used = new Set(markerEntries.map((e) => e.region));
        div.innerHTML = Object.keys(REGION_COLORS)
          .filter((k) => used.has(k))
          .map(
            (k) =>
              `<div><span class="dot" style="background:${REGION_COLORS[k]}"></span>${REGION_LABELS[k]}</div>`,
          )
          .join('');
        return div;
      };
      legend.addTo(map);

      // Era-control (наш кастом).
      const eraControl = L.control({ position: 'topright' });
      eraControl.onAdd = () => {
        const div = L.DomUtil.create('div', 'nysh-era-control');
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);
        div.innerHTML =
          '<div class="nysh-era-title">Епоха</div>' +
          ERAS.map(
            (e) =>
              `<label class="nysh-era-option${
                e.id === currentEra ? ' nysh-era-option--active' : ''
              }">` +
              `<input type="radio" name="nysh-era" value="${e.id}"${
                e.id === currentEra ? ' checked' : ''
              }>` +
              `<span>${escapeHtml(e.label)}</span>` +
              '</label>',
          ).join('');
        div.querySelectorAll('input[name="nysh-era"]').forEach((input) => {
          input.addEventListener('change', (ev) => {
            const newEra = ev.target.value;
            if (newEra !== currentEra) {
              currentEra = newEra;
              applyEra(newEra);
              // Active class toggle.
              div.querySelectorAll('.nysh-era-option').forEach((label) => {
                label.classList.toggle(
                  'nysh-era-option--active',
                  label.querySelector('input').value === newEra,
                );
              });
            }
          });
        });
        return div;
      };
      if (ERAS.length > 1) eraControl.addTo(map);

      if (markerEntries.length > 0) {
        map.fitBounds(markerGroup.getBounds(), { padding: [40, 40] });
      }
    })
    .catch((e) => {
      container.innerHTML =
        '<p style="padding: 1rem; color: #c62828;">Помилка завантаження мапи: ' +
        e +
        '</p>';
    });

  function applyEra(eraId) {
    if (!markerGroup) return;
    const era = ERAS.find((e) => e.id === eraId) || ERAS[0];
    markerGroup.clearLayers();
    let visible = 0;
    for (const { marker, yearRange } of markerEntries) {
      if (overlapsEra(yearRange, era)) {
        markerGroup.addLayer(marker);
        visible += 1;
      }
    }
    // Якщо нічого не показується — fallback на all без зміни currentEra,
    // щоб не залишати порожню мапу мовчки.
    if (visible === 0 && eraId !== 'all') {
      // не змінюємо markerGroup, але користувач побачить що це порожньо.
    }
  }

  function computeYearRange(persons) {
    let min = Infinity;
    let max = -Infinity;
    for (const ev of persons) {
      const candidates = [ev.fact_year, ev.fact_year_end, ev.lived_from, ev.lived_to];
      for (const y of candidates) {
        if (typeof y === 'number' && isFinite(y)) {
          if (y < min) min = y;
          if (y > max) max = y;
        }
      }
    }
    if (min === Infinity) return null;
    return [min, max];
  }

  function overlapsEra(range, era) {
    if (era.id === 'all') return true;
    if (!range) return false; // без років — лише в «Усе»
    const [mn, mx] = range;
    return mx >= era.from && mn <= era.to;
  }

  function renderPersons(persons) {
    if (!persons.length) return '';
    // Згрупувати факти по person.id — щоб одна людина не виводилась двічі.
    const byPerson = new Map();
    for (const item of persons) {
      if (!byPerson.has(item.id)) {
        byPerson.set(item.id, {
          id: item.id,
          name: item.name,
          private: item.private,
          lived_from: item.lived_from,
          lived_to: item.lived_to,
          lived_certainty: item.lived_certainty,
          events: [],
        });
      }
      byPerson.get(item.id).events.push({
        type: item.fact_type,
        year: item.fact_year,
        year_end: item.fact_year_end,
      });
    }
    const items = Array.from(byPerson.values()).map((p) => {
      const lifespan = formatLifespan(p);
      const events = p.events.map(formatEvent).filter(Boolean).join(', ');
      const nameHtml = p.private
        ? `<span>${escapeHtml(p.name)}</span>`
        : `<a href="persons/${p.id}.html">${escapeHtml(p.name)}</a>`;
      const lifeSpan = lifespan ? ` <small>(${lifespan})</small>` : '';
      const evSpan = events ? ` — ${events}` : '';
      return `<li>${nameHtml}${lifeSpan}${evSpan}</li>`;
    });
    return `<div class="popup-persons"><strong>Хто тут згаданий</strong><ul>${items.join('')}</ul></div>`;
  }

  function formatLifespan(p) {
    if (p.lived_from == null && p.lived_to == null) return '';
    const cert = p.lived_certainty;
    const dash = '–';
    if (cert === 'exact') {
      return `${p.lived_from ?? '?'}${dash}${p.lived_to ?? ''}`.replace(/–$/, '');
    }
    const f = p.lived_from ?? '?';
    const t = p.lived_to ?? '?';
    if (cert === 'inferred') return `бл. ${f}${dash}${t}`;
    return `~${f}${dash}${t}`;
  }

  function formatEvent(ev) {
    const label = FACT_LABELS[ev.type] || ev.type;
    if (ev.year == null) return label;
    if (ev.year_end != null && ev.year_end !== ev.year) {
      return `${label} ${ev.year}${'–'}${ev.year_end}`;
    }
    return `${label} ${ev.year}`;
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
