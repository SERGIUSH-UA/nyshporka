/** Транспорт: один шлях до операцій і одна форма відмови. */
import { t } from './strings.js';

// ── транспорт ────────────────────────────────────────────────────────────────
const TOKEN = document.body.dataset.token || '';
/**
 * Проєкт вкладки — з адреси (`?p=<id>`). 🔴 Демон один на Майстерню, і без
 * цього заголовка кожен запит ішов би в проєкт запуску демона: вкладка з
 * іншим родом записувала б нотатки й розділи туди. Адреса, а не cookie: дві
 * вкладки можуть бути відкриті на двох різних проєктах.
 */
const ASKED = new URLSearchParams(location.search).get('p') || '';
/**
 * `?p=_hub` (`HUB_ID` у `daemon/app.py`) — сама Майстерня: заголовок іде як є,
 * бо демон міг стартувати з теки проєкту, а для екранів це «без проєкту».
 * Доти Огляд з перемикача «Майстерня» вважав `_hub` проєктом і кликав
 * проєктні операції — чотири відмови на кожне відкриття (22.10.2026).
 */
const PROJECT = ASKED === '_hub' ? '' : ASKED;

/** `fetch` до демона з проєктом вкладки. Усі запити консолі йдуть через нього. */
function apiFetch(url, init = {}) {
  if (!ASKED) return fetch(url, init);
  const headers = new Headers(init.headers || {});
  headers.set('X-Nysh-Project', ASKED);
  return fetch(url, { ...init, headers });
}
/** Фінальні стани завдання — дзеркало `JobState.final` у `core/jobs.py`. */
const FINAL_STATES = ['done', 'error', 'cancelled'];

async function callOp(name, args) {
  const res = await apiFetch(`/api/op/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Nysh-Token': TOKEN },
    body: JSON.stringify(args || {}),
  });
  const env = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  return normErr(env, res.status);
}

/**
 * Дві форми відмови зводяться до однієї.
 *
 * 🔴 Помилка операції приходить конвертом `{ok:false, error}`, а `HTTPException`
 * (403 на токені, 404 на вимкненій секції) — фастапішним `{detail}`. Це валідний
 * JSON, тож `catch` вище не спрацьовує, і на екран іде об'єкт без `ok` і без
 * `error`: `failure()` друкує «Не вийшло: ?», `alert(env.error)` — «undefined»,
 * а червона плашка виходить порожньою. Найдорожче тут те, що серверне
 * пояснення вимкненої секції («Увімкнути: nysh sections enable …») написане, але
 * не доходило до екрана ніколи.
 */
function normErr(env, status) {
  // 401 дають лише ворота мережевого режиму: допуск пристрою протух (ротація
  // ключа, строк cookie). Підказка «демон перезапустився» тут збрехала б.
  if (status === 401) return { ok: false, error: t('err.access') };
  if (env && env.ok !== undefined) return env;
  const detail = (env && (env.detail || env.error)) || '';
  // Токен вшитий у сторінку при завантаженні, а демон генерує новий на кожному
  // старті. Після перезапуску читання ще працює (воно без токена), а кожна
  // мутація віддає 403 — без цієї підказки людина не здогадається перезавантажити.
  if (status === 403) return { ok: false, error: t('err.token') };
  return { ok: false, error: detail || `HTTP ${status}` };
}

/**
 * Лічильники «виграє остання відправлена, а не остання прийнята».
 *
 * 🔴 `libLoad` таке має, а три інші пошуки — ні, хоч гонка в них та сама:
 * виправив описку, натиснув ще раз, перший запит (він обходить усі прогони
 * простору) прийшов пізніше — і на екрані лишилась видача старого запиту.
 * Гірше за косметику: `SIFT` при цьому вже перезаписаний свіжим, тож таблиця
 * показує одне, а «Розбір знахідок» відкриває інше.
 */
const SEQ = { search: 0, geog: 0, fond: 0, casecheck: 0 };

/**
 * ⚡ «Спершу відоме, потім свіже» для повільних переліків.
 *
 * `paint(env, stale)` кличеться до двох разів: одразу — з останньою відповіддю
 * цієї ж операції з тими самими аргументами (якщо вона є в цій вкладці), і
 * вдруге — зі свіжою, лише якщо та відрізняється. Поки на екрані старе, біля
 * заголовка стоїть «Оновлюю…». Доти «Віддати» щоразу показувало 6 с скелетона,
 * Набори — 2 с, хоча між двома відкриттями там зазвичай не змінюється нічого
 * (замір 23.10.2026).
 *
 * ⚠ Пам'ять — на вкладку й до перезавантаження, ключ — проєкт + операція +
 * аргументи. Відмова не запам'ятовується. Для того, що МУСИТЬ бути свіжим у
 * момент рішення (план читання, кошторис хмари), не вживати.
 */
const MEMO = new Map();
const MEMO_MAX = 40;
function staleBadge(on) {
  const head = document.getElementById('phead');
  const old = document.getElementById('stale-badge');
  if (!on) { if (old) old.remove(); return; }
  if (old || !head) return;
  head.insertAdjacentHTML('beforeend',
    `<span id="stale-badge" class="tag stale-badge" role="status">${t('load.refreshing')}</span>`);
}
async function staleThenFresh(name, args, paint) {
  const key = `${ASKED}|${name}|${JSON.stringify(args || {})}`;
  const old = MEMO.get(key);
  if (old) { paint(old, true); staleBadge(true); }
  const env = await callOp(name, args);
  staleBadge(false);
  if (env.ok) {
    MEMO.delete(key);
    MEMO.set(key, env);
    if (MEMO.size > MEMO_MAX) MEMO.delete(MEMO.keys().next().value);
  }
  const same = old && env.ok && JSON.stringify(old.data) === JSON.stringify(env.data)
    && JSON.stringify(old.warnings || []) === JSON.stringify(env.warnings || []);
  if (!same) paint(env, false);
  return env;
}

export { TOKEN, PROJECT, FINAL_STATES, apiFetch, callOp, normErr, SEQ, staleThenFresh };
