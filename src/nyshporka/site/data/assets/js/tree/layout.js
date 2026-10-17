// Розкладка дерева навколо особи у фокусі: предки вгору, нащадки вниз,
// подружжя поруч у тому ж ряду, брати й сестри — обабіч.
//
// Чиста функція без DOM: (index, focusId, {up, down}) → {cards, links, bounds}.
// Картки не перетинаються за побудовою: кожне піддерево отримує смугу завширшки
// на свою найширшу частину, і сусідні смуги не накладаються. Особа, яка
// трапляється вдруге (шлюб родичів, спільний предок), малюється посиланням
// `ref` — інакше дерево розросталося б копіями й петлями.

export const CARD = { w: 168, h: 64 };
const GAP = 20;      // між сусідніми картками й піддеревами
const COUPLE = 16;   // між подружжям
const FAMGAP = 36;   // між гуртами дітей від різних шлюбів
const ROW = CARD.h + 88;

const yearOf = (n) => {
  const m = n && /\d{4}/.exec(String(n.birth ?? ''));
  return m ? Number(m[0]) : null;
};

const byBirth = (ix) => (a, b) => {
  const ya = yearOf(ix.nodes.get(a.id));
  const yb = yearOf(ix.nodes.get(b.id));
  if (ya === null && yb === null) return 0;
  if (ya === null) return 1;
  if (yb === null) return -1;
  return ya - yb;
};

// Індекси з tree.json: хто чия дитина, хто в яких шлюбах.
export function indexData(data) {
  const nodes = new Map(data.nodes.map((n) => [n.id, n]));
  const fams = new Map();
  const childFam = new Map();
  const spouseFams = new Map();
  for (const f of data.families || []) {
    fams.set(f.id, f);
    for (const c of f.children_ids || []) {
      if (!childFam.has(c) || childFam.get(c).hyp) childFam.set(c, { fam: f, hyp: false });
    }
    for (const c of f.hypothetical_children_ids || []) {
      if (!childFam.has(c)) childFam.set(c, { fam: f, hyp: true });
    }
    for (const pid of [f.husband_id, f.wife_id, f.hypothetical_husband_id, f.hypothetical_wife_id]) {
      if (!pid) continue;
      if (!spouseFams.has(pid)) spouseFams.set(pid, []);
      const list = spouseFams.get(pid);
      if (!list.includes(f)) list.push(f);
    }
  }
  return { nodes, fams, childFam, spouseFams };
}

// Батьки особи: підтверджений слот важить більше за гіпотетичний.
export function parentsOf(ix, pid) {
  const cf = ix.childFam.get(pid);
  if (!cf) return null;
  const f = cf.fam;
  const slot = (main, hyp) => {
    if (main && ix.nodes.has(main)) return { id: main, hyp: cf.hyp };
    if (hyp && ix.nodes.has(hyp)) return { id: hyp, hyp: true };
    return null;
  };
  const father = slot(f.husband_id, f.hypothetical_husband_id);
  const mother = slot(f.wife_id, f.hypothetical_wife_id);
  if (!father && !mother) return null;
  return { fam: f, father, mother, hyp: cf.hyp };
}

export function siblingsOf(ix, pid) {
  const cf = ix.childFam.get(pid);
  if (!cf) return [];
  const f = cf.fam;
  const out = [];
  for (const c of f.children_ids || []) if (c !== pid && ix.nodes.has(c)) out.push({ id: c, hyp: cf.hyp });
  for (const c of f.hypothetical_children_ids || []) {
    if (c !== pid && ix.nodes.has(c) && !out.some((x) => x.id === c)) out.push({ id: c, hyp: true });
  }
  return out.sort(byBirth(ix));
}

// Шлюби особи з партнером (якщо відомий) і дітьми за роком народження.
export function familiesOf(ix, pid) {
  const out = [];
  for (const f of ix.spouseFams.get(pid) || []) {
    const isHusband = pid === f.husband_id || pid === f.hypothetical_husband_id;
    const selfHyp = pid === f.hypothetical_husband_id || pid === f.hypothetical_wife_id;
    const main = isHusband ? f.wife_id : f.husband_id;
    const alt = isHusband ? f.hypothetical_wife_id : f.hypothetical_husband_id;
    let partner = null;
    if (main && main !== pid && ix.nodes.has(main)) partner = { id: main, hyp: selfHyp };
    else if (alt && alt !== pid && ix.nodes.has(alt)) partner = { id: alt, hyp: true };
    const children = [];
    for (const c of f.children_ids || []) if (ix.nodes.has(c)) children.push({ id: c, hyp: selfHyp });
    for (const c of f.hypothetical_children_ids || []) {
      if (ix.nodes.has(c) && !children.some((x) => x.id === c)) children.push({ id: c, hyp: true });
    }
    out.push({ fam: f, partner, children: children.sort(byBirth(ix)) });
  }
  return out;
}

export function layout(ix, focusId, { up = 3, down = 2 } = {}) {
  const cards = [];
  const links = [];
  const seen = new Set([focusId]);
  const addCard = (c) => { cards.push(c); return c; };

  // ---- предки: дерево пар над дитиною --------------------------------------
  function buildAnc(id, depth) {
    const node = { id, parents: [] };
    if (depth <= 0) return node;
    const par = parentsOf(ix, id);
    if (!par) return node;
    node.par = par;
    for (const p of [par.father, par.mother]) {
      if (!p) continue;
      if (seen.has(p.id)) {
        node.parents.push({ id: p.id, hyp: p.hyp, ref: true, parents: [] });
      } else {
        seen.add(p.id);
        node.parents.push({ ...buildAnc(p.id, depth - 1), hyp: p.hyp });
      }
    }
    return node;
  }
  function ancWidth(node) {
    const kids = node.parents.map(ancWidth);
    node.w = Math.max(CARD.w, kids.reduce((s, w) => s + w, 0) + GAP * Math.max(kids.length - 1, 0));
    return node.w;
  }

  // ---- нащадки: особа з подружжям, під кожним шлюбом — діти -----------------
  function buildDesc(id, depth) {
    const unit = { id, fams: [] };
    for (const f of familiesOf(ix, id)) {
      let partner = null;
      if (f.partner) {
        partner = { ...f.partner, ref: seen.has(f.partner.id) };
        seen.add(f.partner.id);
      }
      const kids = [];
      if (depth > 0) {
        for (const c of f.children) {
          if (seen.has(c.id)) {
            kids.push({ id: c.id, hyp: c.hyp, ref: true, fams: [] });
          } else {
            seen.add(c.id);
            kids.push({ ...buildDesc(c.id, depth - 1), hyp: c.hyp });
          }
        }
      }
      unit.fams.push({ fam: f.fam, partner, kids });
    }
    return unit;
  }
  function descWidth(unit) {
    const partners = unit.fams.filter((f) => f.partner).length;
    unit.rowW = CARD.w * (partners + 1) + COUPLE * partners;
    let kidsW = 0;
    let blocks = 0;
    for (const f of unit.fams) {
      const ws = f.kids.map(descWidth);
      f.w = ws.reduce((s, w) => s + w, 0) + GAP * Math.max(ws.length - 1, 0);
      if (ws.length) {
        kidsW += f.w;
        blocks += 1;
      }
    }
    unit.kidsW = kidsW + FAMGAP * Math.max(blocks - 1, 0);
    unit.w = Math.max(unit.rowW, unit.kidsW, CARD.w);
    return unit.w;
  }

  // Подружжя чергуються: перший праворуч, другий ліворуч, третій знову праворуч.
  function placeDesc(unit, left, y, role, hyp) {
    const withPartner = unit.fams.filter((f) => f.partner);
    const rightSide = withPartner.filter((_, i) => i % 2 === 0);
    const leftSide = withPartner.filter((_, i) => i % 2 === 1).reverse();
    const order = [...leftSide, null, ...rightSide];
    let x = left + (unit.w - unit.rowW) / 2 + CARD.w / 2;
    const self = { key: unit.id, id: unit.id, x: 0, y, role, hyp: !!hyp };
    for (const slot of order) {
      if (slot === null) {
        self.x = x;
        addCard(self);
      } else {
        slot.card = addCard({
          key: slot.partner.ref ? `ref:${slot.partner.id}:${unit.id}` : slot.partner.id,
          id: slot.partner.id, x, y, role: 'spouse', hyp: slot.partner.hyp, ref: slot.partner.ref,
        });
      }
      x += CARD.w + COUPLE;
    }
    // Шлюбні лінії й вузли-«стики», від яких ідуть діти.
    for (const f of unit.fams) {
      if (f.partner) {
        const p = f.card;
        const adjacent = Math.abs(p.x - self.x) <= CARD.w + COUPLE + 1;
        const a = Math.min(p.x, self.x);
        const b = Math.max(p.x, self.x);
        if (adjacent) {
          f.jx = (a + b) / 2;
          f.jy = y + CARD.h / 2;
          links.push({ kind: 'marriage', hyp: f.partner.hyp,
            pts: [[a + CARD.w / 2, f.jy], [b - CARD.w / 2, f.jy]] });
        } else {
          // Не сусіди (третій шлюб і далі): дужка під картками, а не крізь чужу.
          const by = y + CARD.h + 10;
          f.jx = (a + b) / 2;
          f.jy = by;
          links.push({ kind: 'marriage', hyp: f.partner.hyp,
            pts: [[self.x, y + CARD.h], [self.x, by], [p.x, by], [p.x, y + CARD.h]] });
        }
      } else {
        f.jx = self.x;
        f.jy = y + CARD.h;
      }
    }
    // Гурти дітей — у порядку партнерів зліва направо, щоб лінії не схрещувались.
    const blocks = unit.fams.filter((f) => f.kids.length).sort((a, b) => a.jx - b.jx);
    let kl = left + (unit.w - unit.kidsW) / 2;
    const childY = y + ROW;
    blocks.forEach((f, i) => {
      const busY = y + CARD.h + (ROW - CARD.h) / 2 + (i - (blocks.length - 1) / 2) * 10;
      const xs = [];
      for (const k of f.kids) {
        if (k.ref) {
          const c = addCard({ key: `ref:${k.id}:${unit.id}`, id: k.id, x: kl + CARD.w / 2, y: childY,
            role: 'desc', hyp: k.hyp, ref: true });
          xs.push([c.x, k.hyp]);
          kl += CARD.w + GAP;
        } else {
          placeDesc(k, kl, childY, 'desc', k.hyp);
          xs.push([k.x, k.hyp]);
          kl += k.w + GAP;
        }
      }
      kl += FAMGAP - GAP;
      bus(f.jx, f.jy, busY, xs, childY);
    });
    unit.x = self.x;
    return self;
  }

  // Від стику пари вниз до шини, по шині — до кожної дитини.
  function bus(jx, jy, busY, xs, childY) {
    const lo = Math.min(jx, ...xs.map((x) => x[0]));
    const hi = Math.max(jx, ...xs.map((x) => x[0]));
    links.push({ kind: 'stem', hyp: false, pts: [[jx, jy], [jx, busY]] });
    if (hi > lo) links.push({ kind: 'bus', hyp: false, pts: [[lo, busY], [hi, busY]] });
    for (const [x, hyp] of xs) links.push({ kind: 'child', hyp, pts: [[x, busY], [x, childY]] });
  }

  function placeAnc(node, cx, y) {
    if (!node.parents.length) return;
    const total = node.parents.reduce((s, p) => s + p.w, 0) + GAP * (node.parents.length - 1);
    let left = cx - total / 2;
    const py = y - ROW;
    const placed = [];
    for (const p of node.parents) {
      const px = left + p.w / 2;
      addCard({ key: p.ref ? `ref:${p.id}:${node.id}` : p.id, id: p.id, x: px, y: py,
        role: 'anc', hyp: p.hyp, ref: !!p.ref });
      placed.push([px, p.hyp]);
      if (!p.ref) placeAnc(p, px, py);
      left += p.w + GAP;
    }
    let jx = placed[0][0];
    let jy = py + CARD.h;
    if (placed.length === 2) {
      const [[fx, fh], [mx, mh]] = placed;
      jx = (fx + mx) / 2;
      jy = py + CARD.h / 2;
      links.push({ kind: 'marriage', hyp: fh || mh, pts: [[fx + CARD.w / 2, jy], [mx - CARD.w / 2, jy]] });
    }
    node.junction = [jx, jy];
    if (node.id !== focusId) {
      bus(jx, jy, py + CARD.h + (ROW - CARD.h) / 2, [[cx, !!node.par?.hyp]], y);
    }
  }

  // ---- збірка ---------------------------------------------------------------
  const anc = buildAnc(focusId, up);
  const sibs = parentsOf(ix, focusId) && up > 0 ? siblingsOf(ix, focusId) : [];
  for (const s of sibs) seen.add(s.id);
  const desc = buildDesc(focusId, down);
  ancWidth(anc);
  descWidth(desc);
  placeDesc(desc, 0, 0, 'focus', false);
  const focusX = desc.x;
  placeAnc(anc, focusX, 0);

  // Брати й сестри: старші ліворуч від ряду фокуса, молодші праворуч.
  const row0 = cards.filter((c) => c.y === 0);
  const minX = Math.min(...row0.map((c) => c.x)) - CARD.w / 2;
  const maxX = Math.max(...row0.map((c) => c.x)) + CARD.w / 2;
  const fy = yearOf(ix.nodes.get(focusId));
  const older = [];
  const younger = [];
  for (const s of sibs) {
    const sy = yearOf(ix.nodes.get(s.id));
    if (fy !== null && sy !== null && sy < fy) older.push(s);
    else younger.push(s);
  }
  const sibXs = [[focusX, !!anc.par?.hyp]];
  older.reverse().forEach((s, i) => {
    const x = minX - GAP * 1.5 - CARD.w / 2 - i * (CARD.w + GAP);
    addCard({ key: s.id, id: s.id, x, y: 0, role: 'sib', hyp: s.hyp });
    sibXs.push([x, s.hyp]);
  });
  younger.forEach((s, i) => {
    const x = maxX + GAP * 1.5 + CARD.w / 2 + i * (CARD.w + GAP);
    addCard({ key: s.id, id: s.id, x, y: 0, role: 'sib', hyp: s.hyp });
    sibXs.push([x, s.hyp]);
  });
  if (anc.junction) {
    const [jx, jy] = anc.junction;
    bus(jx, jy, -(ROW - CARD.h) / 2, sibXs, 0);
  }

  // Що лишилось за краєм: є батьки, яких не видно; скільки дітей не показано.
  const shown = new Set(cards.filter((c) => !c.ref).map((c) => c.id));
  for (const c of cards) {
    if (c.ref) continue;
    const par = parentsOf(ix, c.id);
    c.moreUp = !!par && [par.father, par.mother].some((p) => p && !shown.has(p.id));
    const kids = (ix.nodes.get(c.id)?.child_ids || []).filter((k) => ix.nodes.has(k));
    c.moreDown = kids.filter((k) => !shown.has(k)).length;
  }

  const xs = cards.map((c) => c.x);
  const ys = cards.map((c) => c.y);
  const bounds = {
    x0: Math.min(...xs) - CARD.w / 2, x1: Math.max(...xs) + CARD.w / 2,
    y0: Math.min(...ys), y1: Math.max(...ys) + CARD.h,
  };
  return { cards, links, bounds, focus: cards.find((c) => c.role === 'focus') };
}

// Найдавніший предок по прямій лінії: спершу батько, нема — мати.
export function rootOf(ix, id) {
  const seen = new Set([id]);
  let cur = id;
  for (;;) {
    const par = parentsOf(ix, cur);
    const next = par && (par.father || par.mother);
    if (!next || seen.has(next.id)) return cur;
    seen.add(next.id);
    cur = next.id;
  }
}
