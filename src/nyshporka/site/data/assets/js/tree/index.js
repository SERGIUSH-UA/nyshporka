// Entry point нової multi-pane візуалізації дерева.
// Підвантажується через mkdocs.yml як <script type="module">.

import { createStore, initialState } from './state.js';
import { loadTree } from './data-loader.js';
import { createTreePane } from './panes/tree-pane.js';
import { createDetailsPane } from './panes/details-pane.js';
import { createMapPane } from './panes/map-pane.js';
import { createTimelinePane } from './panes/timeline-pane.js';
import { createBreadcrumbs } from './ui/breadcrumbs.js';

async function bootstrap() {
  console.log('[nysh-tree] bootstrap start');
  const app = document.getElementById('nysh-tree-app');
  if (!app) { console.warn('[nysh-tree] #nysh-tree-app не знайдено'); return; }

  console.log('[nysh-tree] d3:', typeof d3, 'dagre:', typeof dagre, 'L:', typeof L);
  if (typeof d3 === 'undefined' || typeof dagre === 'undefined') {
    app.innerHTML = '<div class="nysh-error">D3 або dagre не завантажений (перевір mkdocs.yml).</div>';
    return;
  }

  const treeUrl = app.dataset.treeUrl || 'assets/tree.json';
  const geojsonUrl = app.dataset.geojsonUrl || 'assets/places.geojson';

  let data;
  try {
    data = await loadTree(treeUrl);
    console.log('[nysh-tree] завантажено', data.nodes.length, 'osob,', data.links.length, 'links');
  } catch (e) {
    console.error('[nysh-tree] loadTree fail:', e);
    app.innerHTML = `<div class="nysh-error">Не вдалось завантажити дерево: ${e}</div>`;
    return;
  }

  const store = createStore(initialState);

  // Tree pane (центральний SVG).
  const svgEl = document.getElementById('nysh-tree-svg');
  if (!svgEl) {
    console.error('[nysh-tree] #nysh-tree-svg не знайдено');
    app.innerHTML = '<div class="nysh-error">SVG-вузол відсутній у HTML.</div>';
    return;
  }
  let treePane;
  try {
    treePane = createTreePane({ svg: svgEl, data, store });
  } catch (e) {
    console.error('[nysh-tree] createTreePane fail:', e);
    app.innerHTML = `<div class="nysh-error">Tree pane error: ${e.message || e}</div>`;
    return;
  }

  // Details right pane.
  const detailsEl = document.getElementById('nysh-details-pane');
  const detailsPane = createDetailsPane({ container: detailsEl, data, store });

  // Map pane (Leaflet).
  const mapEl = document.getElementById('nysh-tree-map');
  const mapPane = mapEl
    ? createMapPane({ container: mapEl, geojsonUrl, store })
    : { render: () => {} };

  // Timeline.
  const timelineEl = document.getElementById('nysh-tree-timeline');
  const timelinePane = timelineEl
    ? createTimelinePane({ container: timelineEl, data, store })
    : { render: () => {} };

  // Breadcrumbs.
  const breadcrumbsEl = document.getElementById('nysh-breadcrumbs');
  const breadcrumbs = breadcrumbsEl
    ? createBreadcrumbs({ container: breadcrumbsEl, data, store })
    : { render: () => {} };

  // Mode switch buttons.
  document.querySelectorAll('.nysh-tree-modeswitch [data-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      if (mode === 'overview') {
        store.update({ mode: 'overview', focusId: null });
      } else if (mode === 'focus' && !btn.disabled) {
        // активне тільки якщо є selectedId.
        const s = store.get();
        if (s.selectedId) {
          store.update({ mode: 'focus', focusId: s.selectedId });
        }
      }
    });
  });

  // Загальний subscribe — кожна панель сама вирішує, що змінилось.
  store.subscribe((state) => {
    treePane.rebuild(state);
    detailsPane.render(state);
    mapPane.render(state);
    timelinePane.render(state);
    breadcrumbs.render(state);
    syncModeButtons(state);
  });

  // Прибрати «Завантаження…» після першого render.
  const loader = document.querySelector('.nysh-tree-loading');
  if (loader) loader.remove();
}

function syncModeButtons(state) {
  document.querySelectorAll('.nysh-tree-modeswitch [data-mode]').forEach((btn) => {
    const isActive = btn.dataset.mode === state.mode;
    btn.classList.toggle('active', isActive);
    if (btn.dataset.mode === 'focus') {
      btn.disabled = !state.selectedId;
    }
  });
}

// Стартуємо, коли DOM готовий (script type=module за замовчуванням defer).
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap);
} else {
  bootstrap();
}
