// Leaflet карта — фільтрує місця за обраною особою (selectedId).

import { escapeHtml } from '../utils/fmt-date.js';

const FACT_LABELS = {
  birth: 'народження', death: 'смерть', marriage: 'шлюб',
  residence: 'проживання', occupation: 'служба', education: 'навчання',
  baptism: 'хрещення', burial: 'поховання', emigration: 'переїзд',
  military: 'військова служба',
};

export function createMapPane({ container, geojsonUrl, store }) {
  if (typeof L === 'undefined') {
    container.innerHTML = '<div class="nysh-empty">Leaflet не завантажений</div>';
    return { render: () => {} };
  }

  const map = L.map(container, { zoomControl: true, attributionControl: false })
    .setView([47.5, 28.5], 5);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 16,
    attribution: '&copy; OSM',
  }).addTo(map);

  let layer = null;
  let allFeatures = [];

  fetch(geojsonUrl)
    .then((r) => r.json())
    .then((geo) => {
      allFeatures = geo.features || [];
      drawLayer(null);
    });

  function drawLayer(personId) {
    if (layer) map.removeLayer(layer);
    const filtered = personId
      ? filterByPerson(allFeatures, personId)
      : allFeatures;

    layer = L.geoJSON({ type: 'FeatureCollection', features: filtered }, {
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: personId ? 9 : 6,
        fillColor: personId ? '#e44' : '#3949ab',
        color: '#fff',
        weight: 2,
        opacity: 1,
        fillOpacity: 0.85,
      }),
      onEachFeature: (feature, lyr) => {
        const p = feature.properties || {};
        const persons = (p.persons || [])
          .filter((pp) => !personId || pp.id === personId);
        const events = persons.map((pp) => {
          const label = FACT_LABELS[pp.fact_type] || pp.fact_type;
          const yr = pp.fact_year != null ? ` ${pp.fact_year}` : '';
          return `${escapeHtml(pp.name)} — ${label}${yr}`;
        }).join('<br>');
        lyr.bindPopup(`
          <strong>${escapeHtml(p.name)}</strong>
          ${events ? `<div class="popup-events">${events}</div>` : ''}
          <div><a href="places/${p.id}.html">${p.id} →</a></div>
        `);
      },
    }).addTo(map);

    if (filtered.length && personId) {
      try {
        map.fitBounds(layer.getBounds(), { padding: [30, 30], maxZoom: 9 });
      } catch (_) { /* single point */ }
    }
  }

  function filterByPerson(features, personId) {
    return features.filter((f) => {
      const persons = (f.properties && f.properties.persons) || [];
      return persons.some((p) => p.id === personId);
    });
  }

  function render(state) {
    drawLayer(state.selectedId);
  }

  return { render };
}
