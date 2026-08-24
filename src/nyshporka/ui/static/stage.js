// Нишпорка — спільне ядро canvas-редакторів (усуває дубль zoom/fit/xy 4 редакторів tp/bk/ad/sy).
// Zoom тримається як module-local `let` у кожному редакторі (reassign → owner), тож ці хелпери
// приймають zoom як параметр і повертають нове значення, а не володіють ним.

// Виставити CSS-розмір img+canvas = natural*zoom (буфер canvas лишається нативним) + оновити %.
export function stApplyZoom(img, cv, zoom, zoomLabelId) {
  if (!img.naturalWidth) return;
  const w = Math.round(img.naturalWidth * zoom), h = Math.round(img.naturalHeight * zoom);
  img.style.width = w + 'px'; img.style.height = h + 'px';
  cv.style.width = w + 'px'; cv.style.height = h + 'px';
  // Підпис зуму не обов'язковий: редактор без нього — законний випадок, а
  // незловлений TypeError тут зупинив би саме масштабування.
  const label = document.getElementById(zoomLabelId);
  if (label) label.textContent = Math.round(zoom * 100) + '%';
}

// Кламп зуму [0.05, 4] (спільний для −/+ кнопок і клавіш).
export function stClampZoom(zoom, f) {
  return Math.max(0.05, Math.min(4, zoom * f));
}

// «Вмістити сторінку»: зум під тіло модалки з відступами. padX різний: bk=250 (збоку список
// боксів), решта=20. Повертає null, якщо img ще не завантажене або тіла модалки нема (тоді
// редактор НЕ змінює zoom — як у оригіналі).
export function stFitZoom(img, mbodySel, padX = 20, padY = 20) {
  const mb = document.querySelector(mbodySel);
  if (!img.naturalWidth || !mb) return null;
  return Math.min((mb.clientWidth - padX) / img.naturalWidth, (mb.clientHeight - padY) / img.naturalHeight);
}

// Екран → source-px напряму (зум враховано через співвідношення cv.width/rect.width).
// Працює для mouse/pointer/touch: touch-подія не має clientX на самому event → беремо перший дотик.
export function stCanvasXY(cv, e) {
  const r = cv.getBoundingClientRect();
  const src = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
  return [(src.clientX - r.left) * cv.width / r.width, (src.clientY - r.top) * cv.height / r.height];
}

// Універсальний біндер малювання боксів на canvas: Pointer Events (mouse+touch+pen) з
// pointer-capture (move/up доходять і поза межами), touch-action:none (палець малює бокс, а не
// скролить сторінку) і preventDefault (без синтетичних mouse-подій / зуму-жестом). Колбеки
// down/move/up отримують [x,y] у source-px і сам event. Один жест = одне активне перо
// (мульти-тач ігнорується — для малювання рамки достатньо одного пальця).
//
// opts.enabled: опційний предикат. Коли повертає false — «режим ✋ рука»: біндер НЕ малює, НЕ
// перехоплює подію і скидає touch-action у auto, тож палець нативно скролить/панорамить фото у
// батьківському overflow-контейнері (на мобільному по великому скану не посунутись інакше).
// Повертає {refresh}: клич після зміни режиму, щоб перевиставити touch-action.
export function stBindDraw(cv, { down, move, up, enabled }) {
  const on = () => (enabled ? enabled() : true);
  const refresh = () => { cv.style.touchAction = on() ? 'none' : 'auto'; };
  refresh();
  let pid = null;
  cv.addEventListener('pointerdown', e => {
    if (!on()) return;                              // ✋ рука → лишаємо браузеру скрол/зум
    if (pid !== null) return;                       // вже малюємо іншим пером/пальцем
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    pid = e.pointerId;
    try { cv.setPointerCapture(pid); } catch (_) {}
    e.preventDefault();
    if (down) down(stCanvasXY(cv, e), e);
  });
  cv.addEventListener('pointermove', e => {
    if (e.pointerId !== pid) return;
    e.preventDefault();
    if (move) move(stCanvasXY(cv, e), e);
  });
  const end = e => {
    if (e.pointerId !== pid) return;
    const p = stCanvasXY(cv, e); pid = null;
    e.preventDefault();
    if (up) up(p, e);
  };
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', end);
  return { refresh };
}
