// Панель деталей: праворуч на широкому екрані, шторка знизу на телефоні.
// Стани шторки: closed → peek (ім'я й кнопки) → half → full. Тягнеться за ручку.

const STATES = ['closed', 'peek', 'half', 'full'];

export function createPanel(aside, { onClose } = {}) {
  const body = aside.querySelector('.nysh-panel__body');
  const grip = aside.querySelector('.nysh-panel__grip');
  const narrow = () => window.matchMedia('(max-width: 899px)').matches;

  const set = (s) => {
    aside.dataset.state = s;
    if (s === 'closed' && onClose) onClose();
  };

  // Тап по ручці: peek ↔ half; перетягування: вгору — більше, вниз — менше.
  let startY = null;
  let moved = false;
  grip.addEventListener('pointerdown', (ev) => {
    startY = ev.clientY;
    moved = false;
    grip.setPointerCapture(ev.pointerId);
  });
  grip.addEventListener('pointermove', (ev) => {
    if (startY !== null && Math.abs(ev.clientY - startY) > 8) moved = true;
  });
  grip.addEventListener('pointerup', (ev) => {
    if (startY === null) return;
    const dy = ev.clientY - startY;
    startY = null;
    const i = STATES.indexOf(aside.dataset.state);
    if (!narrow()) {
      set(aside.dataset.state === 'closed' ? 'half' : 'closed');
      return;
    }
    if (!moved) set(aside.dataset.state === 'half' ? 'peek' : 'half');
    else if (dy < 0) set(STATES[Math.min(i + 1 + (dy < -200 ? 1 : 0), 3)]);
    else set(STATES[Math.max(i - 1 - (dy > 200 ? 1 : 0), 0)]);
  });

  return {
    body,
    show(nodes, { expand = false } = {}) {
      body.replaceChildren(...nodes);
      body.scrollTop = 0;
      const cur = aside.dataset.state;
      if (narrow()) set(expand ? 'half' : (cur === 'closed' ? 'peek' : cur));
      else set('half');
    },
    close() { set('closed'); },
    setState(s) { set(s); },
    state: () => aside.dataset.state,
  };
}

// Невеликий будівельник DOM: el('a.cls', {href}, 'текст', child…).
export function el(spec, attrs = {}, ...kids) {
  const [tag, ...cls] = spec.split('.');
  const node = document.createElement(tag || 'div');
  if (cls.length) node.className = cls.join(' ');
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue;
    node.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return node;
}
