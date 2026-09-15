/** 🔑 Допуск мережевого пристрою: код сполучення або ключ → cookie допуску. */
import { t } from './core/strings.js';

const $ = (id) => document.getElementById(id);

/** Позначка, що сторінка вже раз перекидала на консоль — щоб не крутитись. */
const BOUNCE_KEY = 'nysh.access.bounce';

async function ask(body) {
  const init = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) }
    : { method: 'GET' };
  const res = await fetch('/api/access', init);
  return res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
}

function say(text, bad) {
  const box = $('access-msg');
  box.textContent = text;
  box.classList.toggle('err', !!bad);
}

async function enter(body) {
  say(t('access.checking'));
  const env = await ask(body);
  if (env.ok) {
    location.replace('/');
    return;
  }
  say(env.error || t('access.refused'), true);
}

function bouncedRecently() {
  try {
    const at = Number(sessionStorage.getItem(BOUNCE_KEY) || 0);
    sessionStorage.setItem(BOUNCE_KEY, String(Date.now()));
    return Date.now() - at < 5000;
  } catch {
    return false;
  }
}

async function start() {
  for (const node of document.querySelectorAll('[data-i18n]')) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of document.querySelectorAll('[data-i18n-placeholder]')) {
    node.setAttribute('placeholder', t(node.dataset.i18nPlaceholder));
  }
  // Код сполучення їде у фрагменті: на сервер фрагмент не йде, а з адресного
  // рядка й поточного запису історії його прибираємо одразу.
  const code = new URLSearchParams(location.hash.slice(1)).get('pair');
  if (location.hash) history.replaceState(null, '', location.pathname);

  $('access-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const key = $('access-key').value.trim();
    if (key) enter({ key });
  });

  // 🔴 Cookie допуску — SameSite=Strict, тож відкриття з месенджера чи ярлика
  // її не несе, і ворота показують цю сторінку навіть сполученому пристрою.
  // Запит звідси вже свій — cookie в ньому є; дійсна — переходимо на консоль.
  const probe = await ask(null);
  if (probe.ok && probe.data && probe.data.valid && !bouncedRecently()) {
    location.replace('/');
    return;
  }
  if (code) await enter({ code });
}

start();
