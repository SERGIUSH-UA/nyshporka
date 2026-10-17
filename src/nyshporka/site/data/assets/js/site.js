// Дрібниці для всіх сторінок: фільтр покажчиків і перегляд доказів на весь екран.
(function () {
  'use strict';

  function norm(s) {
    return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[’ʼ`]/g, "'");
  }

  // Фільтр покажчика: ховає картки, що не підходять, і заголовки порожніх груп.
  function initFilters() {
    document.querySelectorAll('.nysh-filter').forEach((box) => {
      const input = box.querySelector('.nysh-filter__input');
      const count = box.querySelector('.nysh-filter__count');
      if (!input || input.dataset.ready) return;
      input.dataset.ready = '1';
      const lists = Array.from(document.querySelectorAll(box.dataset.filterTarget || '.nysh-plist'));
      const cards = lists.flatMap((l) => Array.from(l.querySelectorAll('.nysh-pc')));
      cards.forEach((c) => { c.dataset.q = norm(c.textContent); });
      const total = count ? count.textContent : '';
      input.addEventListener('input', () => {
        const words = norm(input.value).split(/\s+/).filter(Boolean);
        let shown = 0;
        cards.forEach((c) => {
          const ok = words.every((w) => c.dataset.q.includes(w));
          c.hidden = !ok;
          if (ok) shown += 1;
        });
        lists.forEach((l) => {
          const any = Array.from(l.querySelectorAll('.nysh-pc')).some((c) => !c.hidden);
          l.hidden = !any;
          const h = l.previousElementSibling;
          if (h && /^H[23]$/.test(h.tagName)) h.hidden = !any;
        });
        document.querySelectorAll('.nysh-jumpbar').forEach((j) => { j.hidden = words.length > 0; });
        if (count) count.textContent = words.length ? `${shown} з ${total}` : total;
      });
    });
  }

  // Доказ-вирізка на весь екран; закривається тапом, Esc або кнопкою «назад».
  function initLightbox() {
    document.querySelectorAll('.nysh-gallery__item').forEach((a) => {
      if (a.dataset.ready) return;
      a.dataset.ready = '1';
      a.addEventListener('click', (ev) => {
        if (ev.metaKey || ev.ctrlKey) return;
        ev.preventDefault();
        const box = document.createElement('div');
        box.className = 'nysh-lightbox';
        box.setAttribute('role', 'dialog');
        const img = document.createElement('img');
        img.src = a.getAttribute('href');
        img.alt = a.getAttribute('title') || '';
        const cap = document.createElement('div');
        cap.className = 'nysh-lightbox__cap';
        const open = document.createElement('a');
        open.href = a.getAttribute('href');
        open.target = '_blank';
        open.rel = 'noopener';
        open.textContent = 'Відкрити файл';
        cap.append(document.createTextNode(img.alt + ' · '), open);
        box.append(img, cap);
        const close = () => { box.remove(); document.removeEventListener('keydown', onKey); };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        box.addEventListener('click', (e) => { if (e.target !== open) close(); });
        document.addEventListener('keydown', onKey);
        document.body.append(box);
      });
    });
  }

  function init() {
    initFilters();
    initLightbox();
  }

  if (window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(init);
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
