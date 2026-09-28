// Рендер ребер: parent-edges як ламані лінії через family-node,
// spouse-edges — товсте кольорове ребро між парою.

export function renderEdge(g, edge) {
  const d3line = d3.line()
    .x((p) => p.x)
    .y((p) => p.y)
    .curve(d3.curveBasis);

  const cls = edgeClass(edge);
  const path = g.append('path')
    .attr('class', cls)
    .attr('d', d3line(edge.points))
    .attr('fill', 'none')
    .attr('data-source', edge.source)
    .attr('data-target', edge.target);

  const stroke = edge.kind === 'spouse' ? '#c44' : '#999';
  const width = edge.kind === 'spouse' ? 2.2 : 1.6;
  path.attr('stroke', stroke)
    .attr('stroke-width', width)
    .attr('stroke-opacity', opacityFor(edge));

  const dashes = dashFor(edge);
  if (dashes) path.attr('stroke-dasharray', dashes);

  return path;
}

function edgeClass(edge) {
  const cls = ['nysh-tree-edge', `edge-${edge.kind}`];
  if (edge.status === 'hypothesis' || edge.hypothetical) cls.push('hypothesis');
  if (edge.status === 'disputed') cls.push('disputed');
  return cls.join(' ');
}

function dashFor(edge) {
  if (edge.hypothetical || edge.status === 'hypothesis') return '5 4';
  if (edge.confidence === 'speculative') return '2 3';
  if (edge.confidence === 'circumstantial') return '6 2';
  return null;
}

function opacityFor(edge) {
  if (edge.status === 'hypothesis' || edge.hypothetical) return 0.55;
  const op = {
    direct: 0.95,
    indirect: 0.85,
    circumstantial: 0.7,
    speculative: 0.45,
  };
  return op[edge.confidence] || 0.85;
}
