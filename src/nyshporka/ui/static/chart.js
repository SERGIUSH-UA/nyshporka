// Нишпорка — крихітні діаграми інлайновим SVG. Спільний шар: ними користуються
// обидві морди.
//
// 🔴 Своє, а не бібліотека. Застосунок мусить працювати в архіві без інтернету,
// тож CDN відпадає за побудовою, а вендорити сорок кілобайт заради чотирьох
// фігур означало б завести другий набір стилів поруч із `tokens.css` — той не
// знає ні про теми, ні про наші кольори, і кожна тема довелося б наздоганяти
// руками. Тут же все малюється `currentColor` і змінними теми, тобто світла й
// темна виходять безкоштовно.
//
// 🔴 Кольори — ТІЛЬКИ наявні токени. `tokens.css` згенеровано з `brand.yaml`,
// і колір, вписаний сюди руками, розійдеться з ним мовчки (а в CI впаде
// перевірка токенів). Треба нового відтінку — заводити його в бренді.
//
// 🔴 Кожна фігура несе `<title>` із самими числами. Діаграма, чиї значення
// можна дізнатись лише навівши мишу, для читача з екранним диктором не існує
// зовсім, а для читача з тачскрином — майже.

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Число, як його читає людина: 287 376 → «287 376». */
export function num(n) {
  if (n === null || n === undefined || n === '') return '—';
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n);
  return v.toLocaleString('uk-UA').replace(/ /g, ' ');
}

/**
 * Мікротренд у плитці — лінія без осей і підписів.
 *
 * ⚠ Свідомо БЕЗ нуля на осі Y: спарклайн відповідає на «куди воно йде», а не
 * «скільки його». Притиснувши шкалу до нуля, ми б перетворили будь-який
 * реальний приріст на пряму, бо в цьому застосунку числа різняться на порядки
 * (сотні справ — сотні тисяч кадрів).
 *
 * @param {number[]} values
 * @param {{w?: number, h?: number, title?: string}} [opts]
 */
export function spark(values, opts = {}) {
  const vals = (values || []).filter((v) => Number.isFinite(Number(v))).map(Number);
  if (vals.length < 2) return '';
  const w = opts.w || 96;
  const h = opts.h || 24;
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const step = w / (vals.length - 1);
  const pts = vals.map((v, i) =>
    `${(i * step).toFixed(1)},${(h - 1 - ((v - lo) / span) * (h - 2)).toFixed(1)}`);
  const title = opts.title || `від ${num(vals[0])} до ${num(vals[vals.length - 1])}`;
  return `<svg class="ch-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"
    preserveAspectRatio="none" role="img" aria-label="${esc(title)}">
    <title>${esc(title)}</title>
    <polyline points="${pts.join(' ')}" fill="none" stroke="currentColor"
      stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

/**
 * Горизонтальні смуги з підписами — розріз за архівом, повітом, типом факту.
 *
 * Смуга масштабується до найбільшого рядка, а не до суми: питання тут «хто
 * більший за кого», і частка від цілого на нього не відповідає — при
 * двадцяти категоріях усі стають однаково тонкими.
 *
 * 🔴 Довгий хвіст згортається В ОДИН рядок «ще N», а не обрізається мовчки.
 * Вісімнадцять моделей у стовпчику розрізу — це вже не діаграма, а список, і
 * він з'їдає екран; але зникнути безслідно вони теж не мають права: мовчазне
 * обрізання це той самий тихий знаменник, від якого відмовляється решта
 * застосунку. Скільки саме показувати — вирішує ТУТ, бо це питання
 * читабельності графіка, а не властивість даних.
 *
 * @param {{code?: string, label?: string, n: number, rest?: number}[]} items
 * @param {{max?: number, unit?: string, of?: number, rows?: number,
 *          restLabel?: string}} [opts]
 */
export function bars(items, opts = {}) {
  let rows = (items || []).filter((r) => r && Number.isFinite(Number(r.n)));
  if (!rows.length) return '';
  const cap = opts.rows || 12;
  if (rows.length > cap && !rows.some((r) => r.rest)) {
    const tail = rows.slice(cap - 1);
    rows = [...rows.slice(0, cap - 1),
      { n: tail.reduce((a, r) => a + Number(r.n), 0), rest: tail.length }];
  }
  const top = opts.max || Math.max(...rows.map((r) => Number(r.n)), 1);
  const unit = opts.unit ? ` ${opts.unit}` : '';
  const body = rows.map((r) => {
    // Рядок хвоста (`rest`) — це «ще N категорій», а не категорія. Підпис
    // мусить казати саме це: мовчазне обрізання списку — той самий тихий
    // знаменник, від якого відмовляється решта застосунку.
    //
    // ⚠ Підпис приходить ЗВЕРХУ шаблоном із `{n}` (`opts.restLabel`). Цей
    // модуль на спільному шарі, а словник — у кожної морди свій, тож зашите
    // тут «ще» лишалось би українським і в англійському інтерфейсі. Саме
    // ШАБЛОН, а не слово: українською число йде після («ще 61»), англійською —
    // перед («61 more»), і склейкою двох рядків цього не покрити.
    const label = r.rest
      ? (opts.restLabel || '+{n}').replace('{n}', num(r.rest))
      : (r.label || r.code || '—');
    const pct = (Number(r.n) / top) * 100;
    const share = opts.of ? ` · ${Math.round((Number(r.n) / opts.of) * 100)}%` : '';
    return `<div class="ch-bar${r.rest ? ' rest' : ''}"
        title="${esc(label)}: ${num(r.n)}${unit}${share}">
      <span class="ch-bar-l">${esc(label)}</span>
      <span class="ch-bar-t"><i style="width:${pct.toFixed(1)}%"></i></span>
      <span class="ch-bar-n">${num(r.n)}</span>
    </div>`;
  }).join('');
  return `<div class="ch-bars">${body}</div>`;
}

/**
 * Стекова смуга поступу: скільки зроблено, скільки лишилось.
 *
 * 🔴 Частка рахується від СУМИ переданих часток, а не від окремо заданого
 * цілого. Ціле, яке не дорівнює сумі, дає смугу, що не сходиться, — і читач
 * бачить порожній хвіст, не знаючи, це «ще не зроблено» чи «не порахували».
 *
 * @param {{label: string, n: number, tone?: string}[]} parts
 */
export function meter(parts) {
  const rows = (parts || []).filter((p) => p && Number(p.n) > 0);
  const total = rows.reduce((s, p) => s + Number(p.n), 0);
  if (!total) return '';
  const seg = rows.map((p) => {
    const pct = (Number(p.n) / total) * 100;
    return `<i class="t-${esc(p.tone || 'mut')}" style="width:${pct.toFixed(2)}%"
      title="${esc(p.label)}: ${num(p.n)} (${Math.round(pct)}%)"></i>`;
  }).join('');
  const legend = rows.map((p) =>
    `<span class="ch-key"><i class="t-${esc(p.tone || 'mut')}"></i>
      ${esc(p.label)} <b>${num(p.n)}</b></span>`).join('');
  return `<div class="ch-meter" role="img"
      aria-label="${esc(rows.map((p) => `${p.label}: ${p.n}`).join(', '))}">${seg}</div>
    <div class="ch-legend">${legend}</div>`;
}

/**
 * Сходинки в часі — головний графік журналу спостережень.
 *
 * 🔴 Саме СХОДИНКИ, а не плавна лінія. Журнал записує спостереження, а не
 * кожну зміну: між двома точками ми не знаємо, коли саме зросло число, і
 * пряма між ними намалювала б рівномірний приріст, якого ніхто не міряв.
 * Сходинка каже чесно: «стільки було, поки не побачили більше».
 *
 * 🔴 Реконструйований відрізок (`src: "backfill"`) іде ПУНКТИРОМ. Ці точки
 * зібрані з міток на диску заднім числом, і видавати їх за спостережені
 * означало б збрехати рівно тим графіком, який заводили заради довіри.
 *
 * @param {{at: string, v: number, src?: string}[]} series
 * @param {{w?: number, h?: number, unit?: string}} [opts]
 */
export function steps(series, opts = {}) {
  const pts = (series || []).filter((p) => Number.isFinite(Number(p.v)));
  if (pts.length < 2) return '';
  const w = opts.w || 720;
  const h = opts.h || 160;
  const padL = 4;
  const padB = 18;
  const t0 = Date.parse(pts[0].at);
  const t1 = Date.parse(pts[pts.length - 1].at);
  const tSpan = (t1 - t0) || 1;
  const hi = Math.max(...pts.map((p) => Number(p.v)));
  // Нуль на осі Y тут, на відміну від спарклайна, ОБОВ'ЯЗКОВИЙ: це графік
  // накопиченого, і зрізана шкала перетворила б приріст на 2% у злет удвічі.
  const y = (v) => h - padB - (Number(v) / (hi || 1)) * (h - padB - 6);
  const x = (at) => padL + ((Date.parse(at) - t0) / tSpan) * (w - padL * 2);

  // Одна ламана на суцільне, друга на пунктирне: розрив між ними не «дірка»,
  // а межа між реконструйованим і спостереженим.
  const solid = [];
  const dashed = [];
  let prev = null;
  for (const p of pts) {
    const px = x(p.at);
    const py = y(p.v);
    const bucket = p.src === 'backfill' ? dashed : solid;
    if (prev) {
      // Сходинка: спершу вбік по старому рівню, тоді вгору.
      bucket.push(`${prev.x.toFixed(1)},${prev.y.toFixed(1)}`);
      bucket.push(`${px.toFixed(1)},${prev.y.toFixed(1)}`);
    }
    bucket.push(`${px.toFixed(1)},${py.toFixed(1)}`);
    // ⚠ `prev` спільний на обидві ламані навмисно: перша спостережена точка
    // тягне сходинку від ОСТАННЬОЇ реконструйованої, тож на межі не виникає
    // розриву. Розрив там читався б як «дані загубились», хоча насправді
    // просто змінилось походження точок — а про це каже пунктир.
    prev = { x: px, y: py };
  }
  // 🔴 `vector-effect="non-scaling-stroke"` обов'язковий: полотно тягнеться
  // `preserveAspectRatio="none"`, тож без нього товщина лінії розтягується
  // разом із координатами — горизонтальні відрізки стають волосинами, а
  // вертикальні смугами, і графік читається як дефект рендеру.
  const line = (points, dash) => points.length < 2 ? '' :
    `<polyline points="${points.join(' ')}" fill="none" stroke="currentColor"
      stroke-width="1.75" stroke-linejoin="round" vector-effect="non-scaling-stroke"
      ${dash ? 'stroke-dasharray="4 3" opacity=".65"' : ''}/>`;

  const first = pts[0];
  const last = pts[pts.length - 1];
  const unit = opts.unit ? ` ${opts.unit}` : '';
  const label = `${first.at.slice(0, 10)}: ${num(first.v)}${unit} → `
    + `${last.at.slice(0, 10)}: ${num(last.v)}${unit}`;
  // 🔴 Стеля підписана числом. Рівна лінія під самим верхом без нього
  // читається як «графік не намалювався»: за нею не видно ні того, що шкала
  // йде від нуля, ні того, на якому саме значенні вона стоїть.
  return `<svg class="ch-steps" viewBox="0 0 ${w} ${h}" role="img"
      preserveAspectRatio="none" aria-label="${esc(label)}">
    <title>${esc(label)}</title>
    <line class="ch-ax" x1="${padL}" y1="${h - padB}" x2="${w - padL}" y2="${h - padB}"
      vector-effect="non-scaling-stroke"/>
    ${line(dashed, true)}${line(solid, false)}
  </svg>
  <div class="ch-axis"><span>${esc(first.at.slice(0, 10))}</span>
    <span class="ch-top">${num(hi)}${esc(unit)}</span>
    <span>${esc(last.at.slice(0, 10))}</span></div>`;
}

/**
 * Стовпчики за роками/десятиліттями — історична вісь ДОКУМЕНТА.
 *
 * ⚠ Не плутати зі `steps`: там дні, коли ми про щось дізнались, тут — роки
 * самих подій. Обидва графіки бувають на одному екрані, і різна форма це
 * єдине, що не дає їх переплутати з відстані.
 *
 * @param {{decade: number, n: number}[]} items
 */
export function histogram(items, opts = {}) {
  const rows = (items || []).filter((r) => Number.isFinite(Number(r.n)));
  if (!rows.length) return '';
  const hi = Math.max(...rows.map((r) => Number(r.n)), 1);
  const unit = opts.unit ? ` ${opts.unit}` : '';
  // 🔴 Підпис — ПОВНИЙ рік, і тільки на кожному п'ятому стовпчику. Дві останні
  // цифри («00», «20») на ряду, що йде через два століття, повторюються — і
  // 1800-ті від 1900-х не відрізнити взагалі. Решта стовпчиків лишається без
  // підпису: вони й так читаються за сусідами, а суцільний ряд чотиризначних
  // чисел перетворюється на сіру смугу.
  const body = rows.map((r, i) => {
    const pct = (Number(r.n) / hi) * 100;
    // ⚠ Діапазон цифрами, а не «1800-ті»: суфікс був би українським і в
    // англійському інтерфейсі, а «1800–1809» читається в обох і точніше.
    const key = r.decade !== undefined
      ? `${r.decade}–${Number(r.decade) + 9}` : (r.label || r.code || '');
    const show = r.decade === undefined
      ? key
      : (i % 5 === 0 || i === rows.length - 1 ? String(r.decade) : '');
    return `<span class="ch-col" title="${esc(key)}: ${num(r.n)}${unit}">
      <i style="height:${Math.max(pct, 2).toFixed(1)}%"></i>
      <b>${esc(show)}</b>
    </span>`;
  }).join('');
  const label = rows.map((r) => `${r.decade ?? r.code}: ${r.n}`).join(', ');
  return `<div class="ch-cols" role="img" aria-label="${esc(label)}">${body}</div>`;
}
