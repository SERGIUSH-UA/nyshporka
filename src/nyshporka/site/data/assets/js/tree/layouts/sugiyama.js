// Sugiyama (layered) layout через dagre. Вхід — tree.json (nodes+links+families),
// вихід — об'єкти з координатами вузлів і polyline-точками ребер.
//
// Стратегія для генеалогії: між парою батьків і їхніми дітьми вставляємо
// invisible "family-node" — це дає компактнішу укладку без перетину ребер.
// Spouse-зв'язок між парою — окремо, як ребро того ж рангу.

const NODE_W = 130;
const NODE_H = 64;
const FAMILY_W = 8;
const FAMILY_H = 8;

export function layoutSugiyama(data, opts = {}) {
  if (typeof dagre === 'undefined') {
    throw new Error('dagre не завантажений (перевір mkdocs.yml extra_javascript)');
  }
  const includeHypothesis = opts.includeHypothesis !== false;
  const onlyIds = opts.onlyIds || null;  // Set<string> для focus-mode

  const g = new dagre.graphlib.Graph({ multigraph: false, compound: false });
  // LR (зліва направо) для 100+ вузлів — компактніше у середньому стовпчику
  // гриду, ніж TB (де 7 поколінь розтягуються на ~5000px горизонталі).
  g.setGraph({
    rankdir: opts.rankdir || 'LR',
    nodesep: 18,
    edgesep: 10,
    ranksep: 100,
    marginx: 30,
    marginy: 30,
  });
  g.setDefaultEdgeLabel(() => ({}));

  // 1. Вузли-особи.
  const personIds = new Set();
  for (const n of data.nodes) {
    if (onlyIds && !onlyIds.has(n.id)) continue;
    personIds.add(n.id);
    g.setNode(n.id, {
      width: NODE_W,
      height: NODE_H,
      data: n,
      kind: 'person',
    });
  }

  // 2. Family-nodes між парами з дітьми. Це invisible вузол що отримує
  //    parent-edges від обох батьків і дочірні-edges до кожної дитини.
  //    Sugiyama тоді природно вирівнює дітей під парою без перехресть.
  const familyNodes = [];
  for (const fam of data.families || []) {
    const parents = [];
    if (fam.husband_id && personIds.has(fam.husband_id)) parents.push(fam.husband_id);
    if (fam.wife_id && personIds.has(fam.wife_id)) parents.push(fam.wife_id);
    if (includeHypothesis) {
      if (fam.hypothetical_husband_id && personIds.has(fam.hypothetical_husband_id))
        parents.push(fam.hypothetical_husband_id);
      if (fam.hypothetical_wife_id && personIds.has(fam.hypothetical_wife_id))
        parents.push(fam.hypothetical_wife_id);
    }
    const children = (fam.children_ids || []).filter((c) => personIds.has(c));
    if (includeHypothesis) {
      for (const c of fam.hypothetical_children_ids || []) {
        if (personIds.has(c) && !children.includes(c)) children.push(c);
      }
    }
    if (!parents.length || !children.length) continue;

    const fid = `__fam_${fam.id}`;
    g.setNode(fid, {
      width: FAMILY_W,
      height: FAMILY_H,
      kind: 'family',
      family: fam,
    });
    familyNodes.push(fid);
    for (const par of parents) {
      g.setEdge(par, fid, { kind: 'parent-to-fam', family_id: fam.id });
    }
    for (const child of children) {
      g.setEdge(fid, child, {
        kind: 'fam-to-child',
        family_id: fam.id,
        hypothetical: (fam.hypothetical_children_ids || []).includes(child),
      });
    }
  }

  // 3. Парні зв'язки (для пар без дітей — щоб все одно з'явилось ребро).
  const seenSpouses = new Set();
  for (const link of data.links) {
    if (link.type !== 'spouse') continue;
    if (!personIds.has(link.source) || !personIds.has(link.target)) continue;
    if (!includeHypothesis && link.status === 'hypothesis') continue;
    const k = [link.source, link.target].sort().join('|');
    if (seenSpouses.has(k)) continue;
    seenSpouses.add(k);
    g.setEdge(link.source, link.target, {
      kind: 'spouse',
      status: link.status,
      confidence: link.confidence,
      family_id: link.family_id,
    });
  }

  dagre.layout(g);

  // 4. Era-based post-processing: dagre кидає сиріт у rank=0 разом з предками
  //    XIX ст. Виправляємо так — для кожного rank-стовпця обчислюємо
  //    «характеристичну епоху» (з осіб у яких є батьки — їхній rank довірливий),
  //    потім для кожного orphan з era_index знаходимо стовпець-ціль і
  //    зсуваємо його piддерево по X.
  applyEraShifts(g, data, onlyIds);

  // 5. Витягаємо координати.
  const nodes = [];
  for (const nid of g.nodes()) {
    const item = g.node(nid);
    if (!item) continue;
    nodes.push({
      id: nid,
      kind: item.kind,
      x: item.x,
      y: item.y,
      width: item.width,
      height: item.height,
      data: item.data,
      family: item.family,
    });
  }

  const edges = [];
  for (const e of g.edges()) {
    const item = g.edge(e);
    edges.push({
      source: e.v,
      target: e.w,
      points: item.points || [],
      kind: item.kind,
      status: item.status,
      confidence: item.confidence,
      hypothetical: item.hypothetical,
      family_id: item.family_id,
    });
  }

  // Графік міг розрости після era-shift — перерахуємо bounds замість того,
  // щоб довірятись graph().width/height, які dagre обчислила ДО shift.
  const graph = g.graph();
  let bbox = null;
  for (const n of nodes) {
    if (n.x == null || n.y == null) continue;
    const left = n.x - (n.width || 0) / 2;
    const right = n.x + (n.width || 0) / 2;
    const top = n.y - (n.height || 0) / 2;
    const bottom = n.y + (n.height || 0) / 2;
    if (!bbox) { bbox = { l: left, r: right, t: top, b: bottom }; }
    else {
      bbox.l = Math.min(bbox.l, left);
      bbox.r = Math.max(bbox.r, right);
      bbox.t = Math.min(bbox.t, top);
      bbox.b = Math.max(bbox.b, bottom);
    }
  }
  const marg = 30;
  const width = bbox ? Math.round(bbox.r - bbox.l + marg * 2) : graph.width;
  const height = bbox ? Math.round(bbox.b - bbox.t + marg * 2) : graph.height;
  // Якщо bbox починається не з 0 — зсунемо все так, щоб лівий-верх був (marg, marg).
  if (bbox && (bbox.l < marg || bbox.t < marg)) {
    const sx = marg - bbox.l;
    const sy = marg - bbox.t;
    for (const n of nodes) { if (n.x != null) { n.x += sx; n.y += sy; } }
    for (const e of edges) {
      for (const p of e.points) { p.x += sx; p.y += sy; }
    }
  }

  return {
    nodes,
    edges,
    width,
    height,
  };
}

// ----- era-shift post-processing -----

function applyEraShifts(g, data, onlyIds) {
  const nodeData = new Map(data.nodes.map((n) => [n.id, n]));
  // 1. Стовпці: округлимо X до 25px-bins, групуємо ноди.
  const binSize = 25;
  const columns = new Map();  // bin → { x: centerX, persons: [ids] }
  for (const nid of g.nodes()) {
    if (nid.startsWith('__fam_')) continue;
    const item = g.node(nid);
    if (!item || item.kind !== 'person') continue;
    const bin = Math.round(item.x / binSize) * binSize;
    if (!columns.has(bin)) columns.set(bin, { x: item.x, persons: [] });
    columns.get(bin).persons.push(nid);
  }
  // 2. Era for column: median era_index серед НЕ-сиріт у стовпці.
  const columnEra = new Map();
  for (const [bin, col] of columns) {
    const eras = [];
    for (const pid of col.persons) {
      const d = nodeData.get(pid);
      if (!d || typeof d.era_index !== 'number') continue;
      if (!d.parent_ids || !d.parent_ids.length) continue;  // тільки з батьками
      eras.push(d.era_index);
    }
    if (eras.length) {
      eras.sort((a, b) => a - b);
      columnEra.set(bin, eras[Math.floor(eras.length / 2)]);
    }
  }
  // 3. era → target_x (avg X стовпців з тією епохою).
  const eraTargetX = new Map();
  const eraXAccum = new Map();
  for (const [bin, era] of columnEra) {
    if (!eraXAccum.has(era)) eraXAccum.set(era, []);
    eraXAccum.get(era).push(columns.get(bin).x);
  }
  for (const [era, xs] of eraXAccum) {
    eraTargetX.set(era, xs.reduce((a, b) => a + b, 0) / xs.length);
  }

  // 4. Для кожного orphan з era_index — shift його піддерево.
  const childrenOfNode = computeChildrenIndex(g);
  for (const nid of g.nodes()) {
    if (nid.startsWith('__fam_')) continue;
    const d = nodeData.get(nid);
    if (!d) continue;
    if (onlyIds && !onlyIds.has(nid)) continue;
    if (d.parent_ids && d.parent_ids.length) continue;  // не orphan
    if (typeof d.era_index !== 'number') continue;
    const targetX = eraTargetX.get(d.era_index);
    if (targetX == null) continue;
    const item = g.node(nid);
    const currentX = item.x;
    const delta = targetX - currentX;
    if (Math.abs(delta) < 60) continue;  // вже близько — не чіпаємо
    shiftSubtree(g, nid, delta, childrenOfNode);
  }
}

function computeChildrenIndex(g) {
  // node → set of "downstream" nodes (children for persons, descendants for fams).
  const idx = new Map();
  for (const e of g.edges()) {
    const item = g.edge(e);
    if (item.kind === 'spouse') continue;  // spouse — не downstream
    if (!idx.has(e.v)) idx.set(e.v, new Set());
    idx.get(e.v).add(e.w);
  }
  return idx;
}

function shiftSubtree(g, rootId, deltaX, childrenIdx) {
  // BFS усе піддерево через downstream-edges (parent→family→child).
  const subtree = new Set();
  const queue = [rootId];
  while (queue.length) {
    const cur = queue.shift();
    if (subtree.has(cur)) continue;
    subtree.add(cur);
    const ch = childrenIdx.get(cur);
    if (ch) for (const c of ch) if (!subtree.has(c)) queue.push(c);
  }
  // Sift nodes.
  for (const nid of subtree) {
    const item = g.node(nid);
    if (item && item.x != null) item.x += deltaX;
  }
  // Shift edge points: тільки якщо обидва кінці у piддереві (інакше edge стане кривим).
  for (const e of g.edges()) {
    if (!subtree.has(e.v) || !subtree.has(e.w)) continue;
    const item = g.edge(e);
    if (item.points) {
      for (const p of item.points) p.x += deltaX;
    }
  }
}

export { NODE_W, NODE_H };
