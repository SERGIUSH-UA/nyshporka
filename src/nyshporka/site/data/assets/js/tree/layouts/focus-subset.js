// Фільтр вузлів для focus-режиму: лишити особу + N поколінь предків
// + M поколінь нащадків + усіх її подружжя на тому ж рангу.

export function focusSubset(data, focusId, ancestorDepth = 5, descendantDepth = 3) {
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  if (!byId.has(focusId)) return new Set(data.nodes.map((n) => n.id));

  const kept = new Set([focusId]);

  // BFS вгору по parent_ids.
  let frontier = [focusId];
  for (let depth = 0; depth < ancestorDepth && frontier.length; depth++) {
    const next = [];
    for (const id of frontier) {
      const node = byId.get(id);
      if (!node) continue;
      for (const pid of node.parent_ids || []) {
        if (!kept.has(pid)) {
          kept.add(pid);
          next.push(pid);
        }
      }
    }
    frontier = next;
  }

  // BFS вниз по child_ids.
  frontier = [focusId];
  for (let depth = 0; depth < descendantDepth && frontier.length; depth++) {
    const next = [];
    for (const id of frontier) {
      const node = byId.get(id);
      if (!node) continue;
      for (const cid of node.child_ids || []) {
        if (!kept.has(cid)) {
          kept.add(cid);
          next.push(cid);
        }
      }
    }
    frontier = next;
  }

  // Подружжя кожного у поточному наборі — додаємо як «партнерів».
  for (const id of Array.from(kept)) {
    const node = byId.get(id);
    if (!node) continue;
    for (const sid of node.spouse_ids || []) {
      kept.add(sid);
    }
  }

  return kept;
}
