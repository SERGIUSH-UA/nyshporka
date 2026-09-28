// Force-directed граф родини з канону.
// Підвантажує docs/assets/graph.json, рендерить через D3 v7 з фільтрами по
// гіпотетичних, приватних і кандидатах + часовий слайдер.

(function () {
  const svgEl = document.getElementById('nysh-family-graph');
  if (!svgEl || typeof d3 === 'undefined') return;

  const publicUrl = svgEl.dataset.graphUrl || 'assets/graph.json';
  // На localhost спершу пробуємо повну версію (приватні особи з повними іменами
  // і точними роками); fallback на публічну редаговану.
  const isLocal =
    location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  const localUrl = publicUrl.replace(/graph\.json$/, 'graph.full.json');

  const yearSlider = document.getElementById('nysh-year-slider');
  const yearDisplay = document.getElementById('nysh-year-display');
  const toggleHypothesis = document.getElementById('nysh-toggle-hypothesis');
  const togglePrivate = document.getElementById('nysh-toggle-private');
  const toggleCandidates = document.getElementById('nysh-toggle-candidates');
  const resetBtn = document.getElementById('nysh-reset-zoom');
  const eventTrack = document.getElementById('nysh-event-track');
  const tooltip = document.getElementById('nysh-tooltip');

  const CONFIDENCE_WIDTH = {
    direct: 2.5,
    indirect: 2,
    circumstantial: 1.5,
    speculative: 1,
    negative: 1,
  };
  const CONFIDENCE_OPACITY = {
    direct: 1.0,
    indirect: 0.9,
    circumstantial: 0.7,
    speculative: 0.45,
    negative: 0.3,
  };

  fetchGraph()
    .then((data) => render(data))
    .catch((e) => {
      svgEl.outerHTML = `<p style="padding:1rem;color:#c62828">Помилка завантаження graph.json: ${e}</p>`;
    });

  async function fetchGraph() {
    // Cache-bust: на localhost mkdocs livereload оновлює HTML, але JSON-дані
    // браузер кешує — без querystring побачимо стару версію після reindex.
    const bust = isLocal ? `?t=${Date.now()}` : '';
    const fetchOpts = isLocal ? { cache: 'no-store' } : {};
    if (isLocal) {
      try {
        const r = await fetch(localUrl + bust, fetchOpts);
        if (r.ok) {
          document.body.dataset.nyshGraphMode = 'full';
          return await r.json();
        }
      } catch (_) {
        // ignore — впадемо на публічну версію
      }
    }
    document.body.dataset.nyshGraphMode = 'public';
    const r = await fetch(publicUrl + bust, fetchOpts);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  }

  function render(data) {
    const nodes = data.nodes.map((d) => ({ ...d }));
    const links = data.links.map((d) => ({ ...d }));
    const events = data.events || [];

    const branchIds = Array.from(new Set(nodes.map((n) => n.branch_id))).sort();
    const palette = d3
      .scaleOrdinal()
      .domain(branchIds)
      .range(d3.schemeTableau10.concat(d3.schemeSet3));

    const width = svgEl.clientWidth || 900;
    const height = 700;

    const svg = d3
      .select(svgEl)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    svg.selectAll('*').remove();

    const g = svg.append('g');

    const zoom = d3
      .zoom()
      .scaleExtent([0.2, 4])
      .on('zoom', (ev) => g.attr('transform', ev.transform));
    svg.call(zoom);

    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity);
      });
    }

    // Індекс родинних зв'язків: для кожного id — батьки, діти, подружжя, брати/сестри.
    const rels = buildRelationships(nodes, links);

    const linkLayer = g.append('g').attr('class', 'nysh-links');
    const nodeLayer = g.append('g').attr('class', 'nysh-nodes');

    const linkSel = linkLayer
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('class', linkClass)
      .attr('stroke', (d) => (d.type === 'spouse' ? '#c44' : '#888'))
      .attr('stroke-width', (d) => CONFIDENCE_WIDTH[d.confidence] || 1.5)
      .attr('stroke-opacity', (d) => CONFIDENCE_OPACITY[d.confidence] || 0.7)
      .attr('stroke-dasharray', (d) =>
        d.status === 'hypothesis' || d.type === 'candidate' ? '4 3' : null
      );

    const nodeSel = nodeLayer
      .selectAll('circle')
      .data(nodes)
      .join('circle')
      .attr('class', nodeClass)
      .attr('r', (d) => 6 + Math.min(6, (d.fact_count || 0) * 0.5))
      .attr('fill', (d) => palette(d.branch_id))
      .attr('stroke', strokeFor)
      .attr('stroke-width', (d) => (d.has_disputed ? 3 : 1.5))
      .attr('stroke-dasharray', (d) =>
        d.lived_certainty === 'inferred' ? '3 2' :
        d.lived_certainty === 'approximate' && d.lived_method !== 'dates' ? '5 2' :
        null
      )
      .attr('fill-opacity', (d) => {
        const base = d.private ? 0.35 : (CONFIDENCE_OPACITY[d.min_confidence] || 0.85);
        if (d.lived_certainty === 'inferred') return base * 0.6;
        if (d.lived_certainty === 'unknown') return base * 0.5;
        return base;
      })
      .style('cursor', 'pointer')
      .call(drag())
      .on('mouseover', (ev, d) => {
        highlightRelations(d.id);
        showTooltip(ev, d);
      })
      .on('mousemove', moveTooltip)
      .on('mouseout', () => {
        clearHighlight();
        hideTooltip();
      })
      .on('click', (ev, d) => {
        if (d.type === 'candidate') return;
        window.location.href = `persons/${d.id}.html`;
      });

    function highlightRelations(focusId) {
      const rel = rels[focusId] || { parents: new Set(), children: new Set(),
                                     spouses: new Set(), siblings: new Set() };
      const inFocus = (id) =>
        id === focusId || rel.parents.has(id) || rel.children.has(id)
        || rel.spouses.has(id) || rel.siblings.has(id);

      nodeSel
        .classed('dimmed', (n) => !inFocus(n.id))
        .classed('focus', (n) => n.id === focusId)
        .classed('rel-parent', (n) => rel.parents.has(n.id))
        .classed('rel-child', (n) => rel.children.has(n.id))
        .classed('rel-spouse', (n) => rel.spouses.has(n.id))
        .classed('rel-sibling', (n) => rel.siblings.has(n.id));

      linkSel.classed('dimmed', (l) => {
        const sid = typeof l.source === 'object' ? l.source.id : l.source;
        const tid = typeof l.target === 'object' ? l.target.id : l.target;
        return !(sid === focusId || tid === focusId);
      });
    }

    function clearHighlight() {
      nodeSel
        .classed('dimmed', false)
        .classed('focus', false)
        .classed('rel-parent', false)
        .classed('rel-child', false)
        .classed('rel-spouse', false)
        .classed('rel-sibling', false);
      linkSel.classed('dimmed', false);
    }

    const sim = d3
      .forceSimulation(nodes)
      .force(
        'link',
        d3
          .forceLink(links)
          .id((d) => d.id)
          .distance((l) => (l.type === 'spouse' ? 50 : 80))
          .strength((l) => (l.status === 'hypothesis' ? 0.3 : 0.7))
      )
      .force('charge', d3.forceManyBody().strength(-220))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(18))
      .on('tick', () => {
        linkSel
          .attr('x1', (d) => d.source.x)
          .attr('y1', (d) => d.source.y)
          .attr('x2', (d) => d.target.x)
          .attr('y2', (d) => d.target.y);
        nodeSel.attr('cx', (d) => d.x).attr('cy', (d) => d.y);
      });

    // Слайдер року.
    if (yearSlider) {
      yearSlider.addEventListener('input', () => {
        const year = +yearSlider.value;
        if (yearDisplay) yearDisplay.textContent = year;
        applyYearFilter(year);
      });
    }

    // Чекбокси.
    if (toggleHypothesis) {
      toggleHypothesis.addEventListener('change', applyVisibility);
    }
    if (togglePrivate) {
      togglePrivate.addEventListener('change', applyVisibility);
    }
    if (toggleCandidates) {
      toggleCandidates.addEventListener('change', applyVisibility);
    }

    function applyYearFilter(year) {
      nodeSel.attr('display', (d) => isAliveAt(d, year) ? null : 'none');
      linkSel.attr('display', (d) => {
        const s = typeof d.source === 'object' ? d.source : nodes.find((n) => n.id === d.source);
        const t = typeof d.target === 'object' ? d.target : nodes.find((n) => n.id === d.target);
        return isAliveAt(s, year) && isAliveAt(t, year) ? null : 'none';
      });
    }

    function applyVisibility() {
      const showHyp = !toggleHypothesis || toggleHypothesis.checked;
      const showPriv = !togglePrivate || togglePrivate.checked;
      const showCand = !toggleCandidates || toggleCandidates.checked;
      nodeSel.style('display', (d) => {
        if (!showPriv && d.private) return 'none';
        if (!showCand && d.type === 'candidate') return 'none';
        return null;
      });
      linkSel.style('display', (d) => {
        if (!showHyp && d.status === 'hypothesis') return 'none';
        if (!showCand && d.type === 'candidate') return 'none';
        return null;
      });
    }
    applyVisibility();

    renderEvents(events);

    function renderEvents(evts) {
      if (!eventTrack || !evts.length) return;
      const minY = d3.min(evts, (e) => e.year);
      const maxY = d3.max(evts, (e) => e.year);
      const w = eventTrack.clientWidth || 800;
      const margin = 20;
      const x = d3.scaleLinear().domain([minY, maxY]).range([margin, w - margin]);

      const trackSvg = d3
        .select(eventTrack)
        .selectAll('svg')
        .data([null])
        .join('svg')
        .attr('width', '100%')
        .attr('height', 60)
        .attr('viewBox', `0 0 ${w} 60`);

      trackSvg.selectAll('*').remove();

      trackSvg
        .append('line')
        .attr('x1', margin)
        .attr('x2', w - margin)
        .attr('y1', 30)
        .attr('y2', 30)
        .attr('stroke', '#888')
        .attr('stroke-width', 1);

      const decades = d3.range(Math.ceil(minY / 10) * 10, maxY + 1, 20);
      trackSvg
        .selectAll('text.year')
        .data(decades)
        .join('text')
        .attr('class', 'year')
        .attr('x', (d) => x(d))
        .attr('y', 50)
        .attr('text-anchor', 'middle')
        .attr('font-size', 10)
        .attr('fill', 'currentColor')
        .text((d) => d);

      trackSvg
        .selectAll('circle.event')
        .data(evts)
        .join('circle')
        .attr('class', (e) => `event event-${e.fact_type}`)
        .attr('cx', (e) => x(e.year))
        .attr('cy', 30)
        .attr('r', 5)
        .attr('fill', (e) => eventColor(e.fact_type))
        .attr('stroke', (e) => (e.status === 'disputed' ? 'red' : '#fff'))
        .attr('stroke-width', 1.5)
        .style('cursor', 'pointer')
        .on('mouseover', (ev, e) => showTooltip(ev, { _event: true, ...e }))
        .on('mousemove', moveTooltip)
        .on('mouseout', hideTooltip)
        .on('click', (ev, e) => {
          if (e.person_id) window.location.href = `persons/${e.person_id}.html`;
        });
    }

    function showTooltip(ev, d) {
      if (!tooltip) return;
      let html;
      if (d._event) {
        html = `<strong>${d.year}</strong><br>${escapeHtml(d.label)}`;
      } else {
        const certaintyLabel = {
          exact: 'точні дати',
          approximate: 'приблизно',
          inferred: 'виведено',
          unknown: 'без дат',
        }[d.lived_certainty] || '';
        let years;
        if (d.lived_certainty === 'exact') {
          years = `${d.birth || '?'} – ${d.death || ''}`.trim();
        } else if (d.lived_from != null || d.lived_to != null) {
          const f = d.lived_from != null ? d.lived_from : '?';
          const t = d.lived_to != null ? d.lived_to : '?';
          years = `~${f}–${t} <small>(${certaintyLabel})</small>`;
        } else {
          years = `<small>(${certaintyLabel})</small>`;
        }
        const flags = [];
        if (d.has_disputed) flags.push('⚠ суперечливо');
        if (d.private) flags.push('🔒 приватна');
        if (d.type === 'candidate') flags.push('? кандидат');
        const rel = rels[d.id] || {};
        const relRows = [
          formatRel('Батьки', rel.parents, '#48c'),
          formatRel('Подружжя', rel.spouses, '#e88'),
          formatRel('Діти', rel.children, '#0a8'),
          formatRel('Брати/сестри', rel.siblings, '#fa3'),
        ].filter(Boolean).join('');
        html =
          `<strong>${escapeHtml(d.name)}</strong> <code>${d.id}</code><br>` +
          `<span>${years}</span><br>` +
          `<small>гілка: ${d.branch_id} · фактів: ${d.fact_count || 0} · ${d.min_confidence || '—'}</small>` +
          (flags.length ? `<br><small>${flags.join(' · ')}</small>` : '') +
          (relRows ? `<div class="rel-list">${relRows}</div>` : '');
      }
      tooltip.innerHTML = html;
      tooltip.style.display = 'block';
      moveTooltip(ev);
    }

    function formatRel(label, ids, color) {
      if (!ids || !ids.size) return '';
      const names = Array.from(ids)
        .map((id) => {
          const n = nodes.find((x) => x.id === id);
          return n ? `${escapeHtml(n.name)} <code>${id}</code>` : id;
        })
        .join(', ');
      return `<div><span class="rel-dot" style="background:${color}"></span><b>${label}:</b> ${names}</div>`;
    }
    function moveTooltip(ev) {
      if (!tooltip) return;
      tooltip.style.left = ev.pageX + 12 + 'px';
      tooltip.style.top = ev.pageY + 12 + 'px';
    }
    function hideTooltip() {
      if (tooltip) tooltip.style.display = 'none';
    }

    function drag() {
      return d3
        .drag()
        .on('start', (ev, d) => {
          if (!ev.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (ev, d) => {
          d.fx = ev.x;
          d.fy = ev.y;
        })
        .on('end', (ev, d) => {
          if (!ev.active) sim.alphaTarget(0);
        });
    }
  }

  function buildRelationships(nodes, links) {
    const rels = {};
    const ensure = (id) => {
      if (!rels[id]) {
        rels[id] = {
          parents: new Set(),
          children: new Set(),
          spouses: new Set(),
          siblings: new Set(),
        };
      }
      return rels[id];
    };
    nodes.forEach((n) => ensure(n.id));
    // Групуємо parent-links по family_id, щоб обчислити сіблінгів і батьків.
    const families = {};
    links.forEach((l) => {
      const sid = typeof l.source === 'object' ? l.source.id : l.source;
      const tid = typeof l.target === 'object' ? l.target.id : l.target;
      if (l.type === 'parent') {
        ensure(sid).children.add(tid);
        ensure(tid).parents.add(sid);
        const fid = l.family_id || 'F?';
        if (!families[fid]) families[fid] = { parents: new Set(), children: new Set() };
        families[fid].parents.add(sid);
        families[fid].children.add(tid);
      } else if (l.type === 'spouse') {
        ensure(sid).spouses.add(tid);
        ensure(tid).spouses.add(sid);
      }
    });
    // Сіблінги: усі діти однієї родини (крім самих себе).
    Object.values(families).forEach((fam) => {
      fam.children.forEach((c1) => {
        fam.children.forEach((c2) => {
          if (c1 !== c2) ensure(c1).siblings.add(c2);
        });
      });
    });
    return rels;
  }

  function isAliveAt(node, year) {
    if (!node) return false;
    const from = node.lived_from;
    const to = node.lived_to;
    // Особи без жодної дати і без датованих родичів — не показуємо у часовому фільтрі.
    if (from == null && to == null) return false;
    if (from != null && year < from) return false;
    if (to != null && year > to) return false;
    return true;
  }

  function linkClass(d) {
    const cls = ['nysh-link', `link-${d.type}`];
    if (d.status === 'hypothesis') cls.push('hypothesis-link');
    if (d.confidence === 'speculative') cls.push('speculative-link');
    return cls.join(' ');
  }

  function nodeClass(d) {
    const cls = ['nysh-node'];
    if (d.private) cls.push('private-node');
    if (d.has_disputed) cls.push('disputed-node');
    if (d.type === 'candidate') cls.push('candidate-node');
    return cls.join(' ');
  }

  function strokeFor(d) {
    if (d.has_disputed) return '#e44';
    if (d.type === 'candidate') return '#999';
    if (d.sex === 'F') return '#c97';
    if (d.sex === 'M') return '#36c';
    return '#777';
  }

  function eventColor(factType) {
    return {
      emigration: '#0a8',
      military: '#c44',
      education: '#48c',
      occupation: '#a6c',
      baptism: '#fa3',
      death: '#666',
      marriage: '#e88',
    }[factType] || '#888';
  }

  function escapeHtml(s) {
    if (!s) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
