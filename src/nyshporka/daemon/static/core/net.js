/** Транспорт: один шлях до операцій і одна форма відмови. */
import { t } from './strings.js';

// ── транспорт ────────────────────────────────────────────────────────────────
const TOKEN = document.body.dataset.token || '';
/** Фінальні стани завдання — дзеркало `JobState.final` у `core/jobs.py`. */
const FINAL_STATES = ['done', 'error', 'cancelled'];

async function callOp(name, args) {
  const res = await fetch(`/api/op/${encodeURIComponent(name)}`, {
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
 * JSON, тож `catch` вище не спрацьовує, і на екран іде об'єкт БЕЗ `ok` і БЕЗ
 * `error`: `failure()` друкує «Не вийшло: ?», `alert(env.error)` — «undefined»,
 * а червона плашка виходить порожньою. Найдорожче тут те, що серверне
 * пояснення вимкненої секції («Увімкнути: nysh sections enable …») написане, але
 * не доходило до екрана ніколи.
 */
function normErr(env, status) {
  if (env && env.ok !== undefined) return env;
  const detail = (env && (env.detail || env.error)) || '';
  // Токен вшитий у сторінку при завантаженні, а демон генерує новий на кожному
  // старті. Після перезапуску читання ще працює (воно без токена), а КОЖНА
  // мутація віддає 403 — без цієї підказки людина не здогадається перезавантажити.
  if (status === 403) return { ok: false, error: t('err.token') };
  return { ok: false, error: detail || `HTTP ${status}` };
}

/**
 * Лічильники «виграє остання ВІДПРАВЛЕНА, а не остання ПРИЙНЯТА».
 *
 * 🔴 `libLoad` таке має, а три інші пошуки — ні, хоч гонка в них та сама:
 * виправив описку, натиснув ще раз, перший запит (він обходить усі прогони
 * простору) прийшов пізніше — і на екрані лишилась видача СТАРОГО запиту.
 * Гірше за косметику: `SIFT` при цьому вже перезаписаний свіжим, тож таблиця
 * показує одне, а «Розбір знахідок» відкриває інше.
 */
const SEQ = { search: 0, geog: 0, fond: 0 };

export { TOKEN, FINAL_STATES, callOp, normErr, SEQ };
