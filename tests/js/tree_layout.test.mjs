// node --test tests/js — інваріанти розкладки дерева на вигаданих родинах (I9…, F9…).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CARD, indexData, layout, rootOf } from '../../src/nyshporka/site/data/assets/js/tree/layout.js';

const n = (id, birth, extra = {}) => ({ id, name: `Тест ${id}`, sex: 'M', birth, child_ids: [], ...extra });

// Дід I9001 × баба I9002 → батько I9003 (+ брат I9010, сестра I9011).
// Батько I9003 × мати I9004 → фокус I9005 (+ гіпотетичний батько I9012 у тій самій родині).
// Фокус I9005 у двох шлюбах: з I9006 (діти I9007, I9008) і з I9009 (дитина I9013).
// I9008 одружений з I9014, донькою I9010 (шлюб двоюрідних): I9010 — спільний предок.
function fixture() {
  const nodes = [
    n('I9001', '1800', { child_ids: ['I9003', 'I9010', 'I9011'] }),
    n('I9002', '1802', { sex: 'F', child_ids: ['I9003', 'I9010', 'I9011'] }),
    n('I9003', '1830', { child_ids: ['I9005'] }),
    n('I9004', '1832', { sex: 'F', child_ids: ['I9005'] }),
    n('I9005', '1860', { child_ids: ['I9007', 'I9008', 'I9013'] }),
    n('I9006', '1862', { sex: 'F', child_ids: ['I9007', 'I9008'] }),
    n('I9007', '1885'),
    n('I9008', '1887', { child_ids: [] }),
    n('I9009', '1870', { sex: 'F', child_ids: ['I9013'] }),
    n('I9010', '1828', { child_ids: ['I9014'] }),
    n('I9011', '1835', { sex: 'F' }),
    n('I9012', '1829'),
    n('I9013', '1895'),
    n('I9014', '1888', { sex: 'F' }),
  ];
  const families = [
    { id: 'F9001', husband_id: 'I9001', wife_id: 'I9002', children_ids: ['I9003', 'I9010', 'I9011'] },
    { id: 'F9002', husband_id: 'I9003', wife_id: 'I9004', hypothetical_husband_id: 'I9012',
      children_ids: ['I9005'] },
    { id: 'F9003', husband_id: 'I9005', wife_id: 'I9006', children_ids: ['I9007', 'I9008'] },
    { id: 'F9004', husband_id: 'I9005', wife_id: 'I9009', children_ids: ['I9013'] },
    { id: 'F9005', husband_id: 'I9010', children_ids: ['I9014'] },
    { id: 'F9006', husband_id: 'I9008', wife_id: 'I9014', children_ids: [] },
  ];
  return indexData({ nodes, families });
}

const overlap = (a, b) => a.y === b.y && Math.abs(a.x - b.x) < CARD.w;

test('картки не перетинаються', () => {
  for (const focus of ['I9005', 'I9003', 'I9001', 'I9008']) {
    const { cards } = layout(fixture(), focus, { up: 3, down: 3 });
    for (let i = 0; i < cards.length; i += 1) {
      for (let j = i + 1; j < cards.length; j += 1) {
        assert.ok(!overlap(cards[i], cards[j]), `${focus}: ${cards[i].key} × ${cards[j].key}`);
      }
    }
  }
});

test('подружжя в одному ряду з фокусом, обабіч', () => {
  const { cards, focus } = layout(fixture(), 'I9005', { up: 2, down: 2 });
  const spouses = cards.filter((c) => c.role === 'spouse' && c.y === 0);
  assert.deepEqual(spouses.map((c) => c.id).sort(), ['I9006', 'I9009']);
  assert.ok(spouses.some((c) => c.x < focus.x) && spouses.some((c) => c.x > focus.x));
});

test('гіпотетичний батько не займає місце підтвердженого', () => {
  const { cards } = layout(fixture(), 'I9005', { up: 1, down: 0 });
  const parents = cards.filter((c) => c.role === 'anc').map((c) => c.id).sort();
  assert.deepEqual(parents, ['I9003', 'I9004']);
});

test('діти під своїм рядом, на одне покоління нижче', () => {
  const { cards } = layout(fixture(), 'I9005', { up: 0, down: 1 });
  const kids = cards.filter((c) => c.role === 'desc');
  assert.deepEqual(kids.map((c) => c.id).sort(), ['I9007', 'I9008', 'I9013']);
  assert.ok(kids.every((c) => c.y > 0));
});

test('брати й сестри — у ряду фокуса, старші ліворуч', () => {
  const { cards, focus } = layout(fixture(), 'I9003', { up: 1, down: 0 });
  const sib = Object.fromEntries(cards.filter((c) => c.role === 'sib').map((c) => [c.id, c]));
  assert.ok(sib.I9010.x < focus.x && sib.I9011.x > focus.x);
  assert.ok(sib.I9010.y === 0 && sib.I9011.y === 0);
});

test('повтор особи — посилання, не копія піддерева', () => {
  // Від діда вниз: I9014 — онука через I9010 і невістка I9008-го.
  // Хто з пари I9008 × I9014 стане посиланням — залежить від порядку обходу;
  // інваріант інший: кожна особа справжньою карткою лише раз, і повтор є.
  const { cards } = layout(fixture(), 'I9001', { up: 0, down: 4 });
  const real = cards.filter((c) => !c.ref).map((c) => c.id);
  assert.equal(new Set(real).size, real.length);
  assert.ok(cards.some((c) => c.ref && ['I9008', 'I9014'].includes(c.id)));
});

test('позначки «є ще»: предки й нащадки за краєм', () => {
  const { cards } = layout(fixture(), 'I9005', { up: 1, down: 0 });
  const father = cards.find((c) => c.id === 'I9003');
  const focus = cards.find((c) => c.id === 'I9005');
  assert.equal(father.moreUp, true);
  assert.equal(focus.moreDown, 3);
});

test('корінь — по батьківській лінії', () => {
  assert.equal(rootOf(fixture(), 'I9007'), 'I9001');
});
