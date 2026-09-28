// Основна панель: рендерить sugiyama-DAG як SVG.
// При зміні state.mode/focusId/yearCursor/showHypothesis — перебудовується.

import { layoutSugiyama } from '../layouts/sugiyama.js';
import { focusSubset } from '../layouts/focus-subset.js';
import { renderPersonNode } from '../ui/node-renderer.js';
import { renderEdge } from '../ui/edge-renderer.js';
import { buildRelationships } from '../utils/relationships.js';
import { showNodeTooltip, moveTooltip, hideTooltip } from '../ui/tooltip.js';
import { isAliveAt } from '../utils/fmt-date.js';

export function createTreePane({ svg, data, store }) {
  const palette = d3.scaleOrdinal()
    .domain(Array.from(new Set(data.nodes.map((n) => n.branch_id))).sort())
    .range(d3.schemeTableau10.concat(d3.schemeSet3));

  const rels = buildRelationships(data);

  const root = d3.select(svg);
  root.selectAll('*').remove();

  // Defs (clipPath для аватарів).
  const defsEl = root.append('defs');
  const defsCollector = {
    contents: new Set(),
    add(html) { this.contents.add(html); },
  };

  const viewport = root.append('g').attr('class', 'nysh-tree-viewport');
  const edgesLayer = viewport.append('g').attr('class', 'nysh-tree-edges');
  const nodesLayer = viewport.append('g').attr('class', 'nysh-tree-nodes');

  const zoom = d3.zoom()
    .scaleExtent([0.15, 3])
    .on('zoom', (ev) => viewport.attr('transform', ev.transform));
  root.call(zoom);

  // Mobile: тап по фону / поза будь-яким вузлом — ховаємо тултіп.
  // (Тільки touch — desktop hover-state працює як було.)
  svg.addEventListener('touchstart', (ev) => {
    if (!ev.target.closest('.nysh-tree-node')) {
      hideTooltip();
      store.update({ hoverId: null });
    }
  }, { passive: true });

  // Reset zoom (кнопка зовні).
  const resetBtn = document.getElementById('nysh-reset-zoom');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      root.transition().duration(450).call(zoom.transform, d3.zoomIdentity);
    });
  }

  let lastSnapshot = null;
  function rebuild(state) {
    const includeHypothesis = state.showHypothesis;
    const onlyIds = state.mode === 'focus' && state.focusId
      ? focusSubset(data, state.focusId, state.ancestorDepth, state.descendantDepth)
      : null;

    // Кеш: якщо ключові параметри не змінились — не перерендеримо геометрію,
    // тільки оновимо фільтри/підсвітку.
    const sig = JSON.stringify({
      mode: state.mode,
      focusId: state.focusId,
      includeHypothesis,
      showPrivate: state.showPrivate,
    });
    if (sig !== lastSnapshot) {
      lastSnapshot = sig;
      doFullLayout({ includeHypothesis, onlyIds, state });
    }
    applyOverlays(state);
  }

  function doFullLayout({ includeHypothesis, onlyIds, state }) {
    const filteredData = filterByPrivacy(data, state.showPrivate);
    let result;
    try {
      result = layoutSugiyama(filteredData, { includeHypothesis, onlyIds });
    } catch (e) {
      console.error('[nysh-tree] sugiyama layout fail:', e);
      throw e;
    }
    console.log('[nysh-tree] layout:', result.nodes.length, 'nodes,',
                result.edges.length, 'edges,',
                Math.round(result.width), 'x', Math.round(result.height));

    // viewBox робить SVG надійно «вписаним» у контейнер, навіть коли
    // grid-item ще не дав фактичної висоти. d3.zoom доповнює — користувач
    // може збільшити для деталей колесом миші.
    root.attr('viewBox', `0 0 ${result.width} ${result.height}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    edgesLayer.selectAll('*').remove();
    for (const edge of result.edges) {
      renderEdge(edgesLayer, edge);
    }

    nodesLayer.selectAll('*').remove();
    for (const node of result.nodes) {
      if (node.kind !== 'person') continue;
      const sel = renderPersonNode(nodesLayer, node, defsCollector, { palette });
      sel
        .style('cursor', 'pointer')
        .on('mouseover', (ev) => {
          store.update({ hoverId: node.data.id });
          showNodeTooltip(ev, node.data, rels);
        })
        .on('mousemove', moveTooltip)
        .on('mouseout', () => {
          store.update({ hoverId: null });
          hideTooltip();
        })
        .on('click', (ev) => {
          ev.preventDefault();
          // Mobile: mouseout не приходить після tap-у, тому тултіп лишався
          // висіти. Будь-який клік — закриваємо тултіп і скидаємо hover.
          hideTooltip();
          store.update({ hoverId: null });
          if (ev.shiftKey) {
            store.update({ selectedId: node.data.id });
          } else {
            store.update({
              mode: 'focus',
              focusId: node.data.id,
              selectedId: node.data.id,
            });
          }
        });
    }

    // Перенесемо акумульовані clipPath у defs.
    defsEl.html(Array.from(defsCollector.contents).join('\n'));

    // Скинути zoom-трансформ до identity — viewBox уже вписує контент.
    root.call(zoom.transform, d3.zoomIdentity);
  }

  function applyOverlays(state) {
    const year = state.yearCursor;
    const hoverId = state.hoverId;
    const selectedId = state.selectedId;

    nodesLayer.selectAll('.nysh-tree-node')
      .each(function() {
        const id = this.getAttribute('data-id');
        const node = data.nodes.find((n) => n.id === id);
        if (!node) return;
        const sel = d3.select(this);
        // Year filter.
        const dim = year != null && !isAliveAt(node, year);
        sel.classed('year-dimmed', dim);
        // Selected.
        sel.classed('selected', id === selectedId);
        // Hover: підсвітка родичів.
        if (hoverId) {
          const rel = rels[hoverId];
          const inFocus = id === hoverId
            || (rel && (rel.parents.has(id) || rel.children.has(id)
                        || rel.spouses.has(id) || rel.siblings.has(id)));
          sel.classed('rel-dim', !inFocus);
          sel.classed('rel-parent', rel && rel.parents.has(id));
          sel.classed('rel-child', rel && rel.children.has(id));
          sel.classed('rel-spouse', rel && rel.spouses.has(id));
          sel.classed('rel-sibling', rel && rel.siblings.has(id));
        } else {
          sel.classed('rel-dim', false)
             .classed('rel-parent', false)
             .classed('rel-child', false)
             .classed('rel-spouse', false)
             .classed('rel-sibling', false);
        }
      });

    edgesLayer.selectAll('.nysh-tree-edge')
      .each(function() {
        const sid = this.getAttribute('data-source');
        const tid = this.getAttribute('data-target');
        const sel = d3.select(this);
        if (hoverId) {
          const incident = sid === hoverId || tid === hoverId
            || sid.startsWith('__fam_') || tid.startsWith('__fam_');
          // Простіше: підсвічуємо edge тільки якщо одна з кінцівок — hoverId
          // АБО family-node, де один із батьків — hoverId. Дрібний хак: ми не
          // зберігаємо родин-членів на edge, тому family-edges залишаємо без диммингу.
          const isFam = sid.startsWith('__fam_') || tid.startsWith('__fam_');
          sel.classed('rel-dim', !(sid === hoverId || tid === hoverId || isFam));
        } else {
          sel.classed('rel-dim', false);
        }
      });
  }

  return { rebuild };
}

function filterByPrivacy(data, showPrivate) {
  if (showPrivate) return data;
  const allowedIds = new Set(data.nodes.filter((n) => !n.private).map((n) => n.id));
  return {
    ...data,
    nodes: data.nodes.filter((n) => !n.private),
    links: data.links.filter((l) => allowedIds.has(l.source) && allowedIds.has(l.target)),
    families: (data.families || []).map((f) => ({
      ...f,
      husband_id: allowedIds.has(f.husband_id) ? f.husband_id : null,
      wife_id: allowedIds.has(f.wife_id) ? f.wife_id : null,
      children_ids: (f.children_ids || []).filter((c) => allowedIds.has(c)),
      hypothetical_children_ids: (f.hypothetical_children_ids || []).filter((c) => allowedIds.has(c)),
    })),
  };
}
