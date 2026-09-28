// Індекс родинних зв'язків з tree.json. Дублює серверні parent_ids/
// child_ids/spouse_ids у Set для швидкого has(), плюс обчислює siblings
// через family_id (діти однієї родини).

export function buildRelationships(data) {
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

  for (const n of data.nodes) {
    const r = ensure(n.id);
    (n.parent_ids || []).forEach((id) => r.parents.add(id));
    (n.child_ids || []).forEach((id) => r.children.add(id));
    (n.spouse_ids || []).forEach((id) => r.spouses.add(id));
  }

  // Сіблінги: діти однієї родини.
  for (const fam of data.families || []) {
    const kids = [
      ...(fam.children_ids || []),
      ...(fam.hypothetical_children_ids || []),
    ];
    for (const a of kids) {
      for (const b of kids) {
        if (a !== b) ensure(a).siblings.add(b);
      }
    }
  }

  return rels;
}
