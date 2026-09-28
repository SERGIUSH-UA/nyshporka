// Timeline: горизонтальна вісь з подіями (events з tree.json) +
// scrub-курсор, що оновлює state.yearCursor для year-фільтру у дереві.

import { escapeHtml } from '../utils/fmt-date.js';

const EVENT_COLORS = {
  emigration: '#0a8',
  military: '#c44',
  education: '#48c',
  occupation: '#a6c',
  baptism: '#fa3',
  birth: '#666',
  death: '#666',
  marriage: '#e88',
};

export function createTimelinePane({ container, data, store }) {
  const events = data.events || [];
  if (!events.length) {
    container.innerHTML = '<div class="nysh-empty">Нема подій</div>';
    return { render: () => {} };
  }

  const minY = Math.min(...events.map((e) => e.year));
  const maxY = Math.max(...events.map((e) => e.year));

  const margin = 32;
  const h = 80;
  const svg = d3.select(container).append('svg')
    .attr('class', 'nysh-tl-svg')
    .attr('width', '100%')
    .attr('height', h);

  const x = d3.scaleLinear().domain([minY, maxY]);

  function resize() {
    const w = container.clientWidth || 800;
    svg.attr('viewBox', `0 0 ${w} ${h}`);
    x.range([margin, w - margin]);
    draw(w);
  }

  let cursorLine, cursorLabel;
  function draw(w) {
    svg.selectAll('*').remove();

    // Базова вісь.
    svg.append('line')
      .attr('class', 'tl-axis')
      .attr('x1', margin).attr('x2', w - margin)
      .attr('y1', 38).attr('y2', 38)
      .attr('stroke', '#888').attr('stroke-width', 1);

    // Підписи десятиліть.
    const decadeStart = Math.ceil(minY / 10) * 10;
    const decades = d3.range(decadeStart, maxY + 1, 20);
    svg.selectAll('text.tl-decade')
      .data(decades).join('text')
      .attr('class', 'tl-decade')
      .attr('x', (d) => x(d)).attr('y', 58)
      .attr('text-anchor', 'middle')
      .attr('font-size', 10).attr('fill', 'currentColor')
      .text((d) => d);

    // Події.
    svg.selectAll('circle.tl-event')
      .data(events).join('circle')
      .attr('class', (e) => `tl-event tl-event-${e.fact_type}`)
      .attr('cx', (e) => x(e.year)).attr('cy', 38).attr('r', 5)
      .attr('fill', (e) => EVENT_COLORS[e.fact_type] || '#888')
      .attr('stroke', (e) => e.status === 'disputed' ? '#e44' : '#fff')
      .attr('stroke-width', 1.5)
      .style('cursor', 'pointer')
      .append('title')
      .text((e) => `${e.year}: ${e.label}`);

    svg.selectAll('circle.tl-event')
      .on('click', (ev, e) => {
        if (e.person_id) store.update({ selectedId: e.person_id });
      });

    // Cursor (scrub).
    cursorLine = svg.append('line')
      .attr('class', 'tl-cursor')
      .attr('y1', 8).attr('y2', 70)
      .attr('stroke', '#e44').attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '3 2')
      .style('display', 'none');
    cursorLabel = svg.append('text')
      .attr('class', 'tl-cursor-label')
      .attr('y', 14).attr('text-anchor', 'middle')
      .attr('font-size', 11).attr('fill', '#e44')
      .style('display', 'none');

    // Overlay для mouse-tracking.
    const overlay = svg.append('rect')
      .attr('class', 'tl-overlay')
      .attr('x', margin).attr('y', 0)
      .attr('width', w - 2 * margin).attr('height', h)
      .attr('fill', 'transparent')
      .style('cursor', 'col-resize');

    overlay
      .on('mousemove', (ev) => {
        const px = d3.pointer(ev, svg.node())[0];
        const year = Math.round(x.invert(px));
        cursorLine.attr('x1', px).attr('x2', px).style('display', null);
        cursorLabel.attr('x', px).text(year).style('display', null);
        store.update({ yearCursor: year });
      })
      .on('mouseleave', () => {
        cursorLine.style('display', 'none');
        cursorLabel.style('display', 'none');
        store.update({ yearCursor: null });
      });
  }

  resize();
  window.addEventListener('resize', resize);

  function render(_state) { /* statelessly drawn — nothing to update on state change */ }
  return { render };
}
