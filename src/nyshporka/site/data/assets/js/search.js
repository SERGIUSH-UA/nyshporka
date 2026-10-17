// Пошук особи по assets/search.json — на головній, у дереві й на графі.
// Запис покажчика: {id, n: ім'я, a: інші форми, y: роки, s: стать, p: місце народження}.

const cache = new Map();

export function loadIndex(url) {
  if (!cache.has(url)) {
    cache.set(url, fetch(url).then((r) => (r.ok ? r.json() : [])).catch(() => []));
  }
  return cache.get(url);
}

// Без регістру й діакритики, один апостроф: «Мар’яна» = «марьяна» не буде,
// але «Мар'яна» = «мар’яна» і «Józef» = «jozef».
export function norm(s) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[’ʼ`´‘]/g, "'")
    .replace(/ё/g, 'е');
}

function prepare(index) {
  for (const e of index) {
    if (e._h) continue;
    e._n = norm(e.n);
    e._h = norm([e.n, ...(e.a || []), e.y, e.p].join(' '));
  }
  return index;
}

export function query(index, q, limit = 12) {
  const words = norm(q).split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const out = [];
  for (const e of prepare(index)) {
    if (!words.every((w) => e._h.includes(w))) continue;
    let score = 0;
    for (const w of words) {
      if (e._n.startsWith(w)) score += 3;
      else if (e._n.includes(' ' + w)) score += 2;
      else if (e._n.includes(w)) score += 1;
    }
    out.push([score, e]);
  }
  out.sort((a, b) => b[0] - a[0] || a[1].n.localeCompare(b[1].n, 'uk'));
  return out.slice(0, limit).map((x) => x[1]);
}

// Підключити поле пошуку: `root` містить .nysh-search__input і .nysh-search__list.
// `onPick(entry)` вирішує, куди вести; без нього — на сторінку особи.
export function attach(root, { url, onPick, base = '' }) {
  const input = root.querySelector('.nysh-search__input');
  const list = root.querySelector('.nysh-search__list');
  if (!input || !list) return;
  let items = [];
  let active = -1;

  const pick = (e) => {
    close();
    input.value = '';
    if (onPick) onPick(e);
    else window.location.href = `${base}persons/${e.id}.html`;
  };

  function close() {
    list.hidden = true;
    list.replaceChildren();
    active = -1;
    input.setAttribute('aria-expanded', 'false');
  }

  function render() {
    list.replaceChildren();
    if (!items.length) {
      const li = document.createElement('li');
      li.className = 'nysh-search__empty';
      li.textContent = 'Нікого не знайдено';
      list.append(li);
    }
    items.forEach((e, i) => {
      const li = document.createElement('li');
      li.className = `nysh-search__item nysh-search__item--${(e.s || 'u').toLowerCase()}`;
      li.setAttribute('role', 'option');
      if (i === active) li.classList.add('is-active');
      const name = document.createElement('span');
      name.className = 'nysh-search__name';
      name.textContent = e.n;
      const meta = document.createElement('span');
      meta.className = 'nysh-search__meta';
      meta.textContent = [e.y, e.p].filter(Boolean).join(' · ');
      li.append(name, meta);
      li.addEventListener('pointerdown', (ev) => {
        ev.preventDefault();
        pick(e);
      });
      list.append(li);
    });
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  input.addEventListener('input', async () => {
    const q = input.value.trim();
    if (q.length < 2) return close();
    const index = await loadIndex(url);
    items = query(index, q);
    active = items.length ? 0 : -1;
    render();
  });
  input.addEventListener('keydown', (ev) => {
    if (list.hidden) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      const step = ev.key === 'ArrowDown' ? 1 : -1;
      active = (active + step + items.length) % Math.max(items.length, 1);
      render();
    } else if (ev.key === 'Enter' && items[active]) {
      ev.preventDefault();
      pick(items[active]);
    } else if (ev.key === 'Escape') {
      close();
    }
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
}
