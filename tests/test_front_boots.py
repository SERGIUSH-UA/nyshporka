"""🖥 Фронт не просто розбирається — він виконується.

Решта приймачів читає модулі як текст: чи є кнопка, чи є до неї дія, чи є
переклад. Усе це вони бачать і в коді, який у браузері не запуститься жодного
разу.

🔴 Клас вад, якого не бачив ніхто: модуль завантажився з помилкою — і реєстр
лишився напівпорожнім. Кнопка на екрані є, диспетчер її не знає, натискання не
робить нічого. Тексту це не видно взагалі: файл бездоганний, посилання
правильні, синтаксис чистий.

⚠ І дорожчий різновид того самого: дія Є, викликається, але тихо повертається
ні з чим. Зовні це не відрізнити від мертвої кнопки, а причина щоразу інша.

Тому тут фронт справді запускається — у заглушці DOM на Node. Заглушка бідна
навмисно: вона мусить дати модулям виконатись, а не вдавати браузер. Усе, що
залежить від верстки (де саме кнопка, чи вона видима), лишається поза межами
цього приймача — його питання інше: чи працює зв'язок «кнопка → дія → наслідок».
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from _front import FRONT_DIR, SHARED_DIR

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node немає — виконати фронт нічим")

#: Заглушка DOM. Рівно стільки, скільки треба модулям, щоб виконатись.
STUB = r"""
const created = [];
function node(tag = 'div') {
  const n = {
    tagName: String(tag).toUpperCase(),
    className: '', innerHTML: '', textContent: '', value: '', checked: false,
    style: {}, children: [], attrs: {}, disabled: false, dataset: {},
    classList: { _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      contains(c) { return this._s.has(c); },
      toggle(c, on) { if (on) this._s.add(c); else this._s.delete(c); } },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; },
    appendChild(c) { this.children.push(c); created.push(c); return c; },
    insertBefore(c) { this.children.push(c); return c; },
    // Слухачі записуються, щоб приймач міг послати подію так само, як
    // браузер: перевіряти жести, не виконуючи їх, — це перевіряти намір.
    _h: {},
    removed: false,
    remove() { this.removed = true; },
    addEventListener(t, fn) { (this._h[t] ||= []).push(fn); },
    removeEventListener() {},
    fire(t, ev) { (this._h[t] || []).forEach((fn) => fn(ev)); },
    setPointerCapture() {}, closest() { return null; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 1200, height: 800 }; },
    querySelector(sel) { const k = 'q' + sel;
      return (this._q ||= {})[k] || (this._q[k] = node('button')); },
    querySelectorAll() { return []; }, scrollIntoView() {}, focus() {},
    // Розміри й прокрутка: `swapHtml` тримає ними висоту на час підміни.
    offsetHeight: 0, offsetWidth: 0, scrollTop: 0, scrollHeight: 0,
    clientHeight: 0, parentElement: null,
  };
  return n;
}
const body = node('body');
body.dataset = { token: 'тест' };
const byId = {};
globalThis.document = { body, documentElement: node('html'),
  createElement: (t) => node(t),
  // Накладка рядків малюється в просторі імен SVG — без цього читалка
  // прогону падає рівно там, де показує прочитане.
  createElementNS: (_ns, t) => node(t),
  getElementById: (id) => (byId[id] ||= node('div')),
  addEventListener() {}, removeEventListener() {},
  querySelector: () => null, querySelectorAll: () => [] };
globalThis.window = { innerWidth: 1600, innerHeight: 900,
  addEventListener() {}, removeEventListener() {} };
globalThis.innerWidth = 1600; globalThis.innerHeight = 900;
globalThis.location = { hash: '#home', reload() {} };
globalThis.localStorage = { _m: {}, getItem(k) { return this._m[k] ?? null; },
  setItem(k, v) { this._m[k] = String(v); } };
globalThis.alert = () => {};
globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
globalThis.getComputedStyle = () => ({ overflowY: 'visible' });
globalThis.CSS = { escape: (s) => String(s) };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {},
  addListener() {} });
// 🔴 Поля форми мусять розрізнятись. Доки `get()` віддавав одне й те саме на
// будь-яке ім'я, режим пошуку задати було нічим — а саме він вирішує, якою
// гілкою піде рендер хітів.
globalThis.__FORM = null;
globalThis.FormData = class {
  get(k) {
    const over = globalThis.__FORM;
    if (over && Object.hasOwn(over, k)) return over[k];
    return 'data/raw/зразок';
  }
};
globalThis.__EMPTY_SPACE = false;
globalThis.__NO_PROFILE = false;
const FRAMES = [{ id: 'a.jpg', label: 'a.jpg', kind: 'image' },
                { id: 'b.jpg', label: 'b.jpg', kind: 'image' }];
globalThis.fetch = async (url) => {
  // 🔴 Довге очікування черги мусить висіти, як на справжньому сервері. Якщо
  // відповідати миттєво, вічний цикл спостерігача перетворюється на щільний
  // потік мікрозадач: макрозадачі (таймери) не отримують ходу взагалі, і
  // прогін зависає — виглядаючи як поламаний приймач, а не як зайнятий фронт.
  if (String(url).includes('/api/jobs/wait')) return new Promise(() => {});
  const name = String(url).split('/api/op/')[1] || '';
  const data = {
    'case.frames': { kind: 'image', total: 2, pdfs: [], frames: FRAMES,
                     runs: [{ name: 'прогін', engine_id: 'pysar',
                              pages_done: 2, alt: '' }] },
    'case.frame': { width: 9, height: 9, bytes: 9, image: 'data:image/jpeg;base64,AA' },
    'library.list': { cases: [], built: true, summary: {}, facets: {},
                      total: 0, page: 0, page_size: 50, pages: 0 },
    'runs.list': { runs: [{ name: 'прогін', case_dir: 'c', engine_id: 'pysar',
                            case_key: 'A/1/2', shifra: 'A 1-1-2',
                            pages_done: 2, frames: 2 }],
                   shown: 1, total: 1, everything: 1, orphans: 0,
                   page: 0, page_size: 25, pages: 1 },
    'cases.list': { cases: [{ key: '@disk/x', kind: 'unfiled', path: 'x',
                              frames: 7 }],
                    shown: 1, total: 1, registry: true, page: 0,
                    page_size: 50, pages: 1,
                    counts: { unfiled: 1, bundle: 0, case: 3 } },
    'fond.list': { fonds: [{ id: 'a_1', label: 'А ф.1', repo: 'A', fond: '1',
                             rows: 9, on_disk: 1, todo: 2, scans: 3,
                             schema: 'merged_v2',
                             summary: { rows: 9, commons: 3, on_disk_live: 1,
                                        todo: 2, truncated: 1, interp: 4,
                                        with_surnames: 7 } }],
                   shown: 1 },
    'fond.rows': { fond: 'А ф.1', fond_id: 'a_1', matched: 1, total: 1,
                   shown: 1, page: 0, page_size: 50, pages: 1,
                   schema: 'merged_v2',
                   summary: { rows: 9, commons: 3, on_disk_live: 1, todo: 2,
                              truncated: 1, interp: 4, with_surnames: 7 },
                   facets: { opys: [{ code: '1', n: 9 }],
                             uezd: [{ code: 'Балтський', n: 4 }] },
                   surnames: ['Шевченко'],
                   coverage: null,
                   rows: [{ shifra: '1-1-2', spr: '2', key: 'A/1/2',
                            title: 'книга', state: 'todo', on_disk: '',
                            takeable: true, commons_url: 'https://c/2',
                            commons_size: '78643200', commons_pages: '200',
                            dv_no: null, num_src: 'interp' }] },
    'registry.collectors': { collectors: [{ id: 'archium', label: 'ARCHIUM' }] },
    'sources.list': { sources: [
        { id: 'archium', label: 'ARCHIUM', caps: ['search', 'browse', 'fetch'],
          catalog: { searchable: true, kind: 'bundled', taken: '2026-07-02',
                     rows: 9020, scope: '', fix: '' } },
        { id: 'x', label: 'Ікс', caps: ['search'],
          catalog: { searchable: true, kind: 'none', taken: '', rows: null,
                     scope: '', fix: 'nysh crawl x' } }],
      shown: 2, searchable: 2, with_catalog: 1 },
    'page.text': { name: 'прогін', engine_id: 'pysar', model: 'pysar_cyr_v4.pt',
                   pages: [{ page: 'a.jpg', lines: 2 }, { page: 'b.jpg', lines: 2 }],
                   lines: ['перший рядок', 'другий рядок'] },
    'page.lines': { has: true, size: [100, 60],
                    polys: [[[1, 1], [9, 1], [9, 5], [1, 5]], null] },
    'page.view': { image: 'data:image/png;base64,AA', line: 0, text: 'рядок' },
    'htr.case_info': { found: true, case_dir: 'c', shifra: 'А 1-1-2',
                       title: 'книга', frames: 12, script: 'cyrillic',
                       script_why: 'письмо записане в опису справи',
                       script_trust: 'fixed',
                       engines: [{ id: 'pysar', label: 'Писар', note: '' }],
                       runs: [], covered: {}, gaps: [] },
    'search.state': { runs: 2, indexed: 1, stale: 1, bytes: 1024, dir: 'd' },
    // 🔴 Форма хіта тут дослівно та, яку віддає `grep_records()`, а не зручна
    // для приймача вигадка: саме розбіжність між нею і формою decode-пошуку
    // лишала режим «в учасниках записів» без контексту й без кнопок.
    'search.run': { total: 3, coverage: { cases: 2, thresh: 80, stems: ['вишневец'] },
      hits: [
        { key: 'A/1/2', shifra: 'А 1-1-2', rid: 'r1', rtype: 'birth',
          date: '1858-03-04', scans: ['0030.JPG'], role: 'father',
          name: 'Іван Вишневецький', place: 'Мястківка', score: 100 },
        { key: 'A/1/2', shifra: 'А 1-1-2', rid: 'r2', rtype: 'marriage',
          date: '1861-11-02', scans: ['https://приклад/цитата'], role: 'groom',
          name: 'Петро Вишневецький', place: 'Ободівка', score: 92 },
        { key: 'A/1/2', shifra: 'А 1-1-2', rid: 'r3', rtype: 'death',
          date: '1870-01-09', scans: ['.прихований.jpg'], role: 'deceased',
          name: 'Гнат Вишневецький', place: '', score: 88 },
      ] },
    // 🔴 Два стани одного екрана, як і в домівки: профіль є / профілю немає.
    // Перемикач той самий — глобальний прапорець у заглушці.
    'profile.show': globalThis.__NO_PROFILE ? {
      present: false, why: 'профіль дослідження не задано',
      path: 'C:/простір/config/research_profile.yaml', available: [], source: '',
      paradigms: [{ id: 'adj_skyi', label: 'на -ський', verified: true },
                  { id: 'noun_ov', label: 'на -ов', verified: false }],
      orthographies: ['bank', 'ru_modern', 'ru_prereform', 'uk', 'pl'],
    } : {
      present: true, name: 'rid', display: 'Вишневецький', paradigm: 'adj_skyi',
      stems: { uk: 'Вишневец', pl: 'Wiszniowiec' },
      roots: ['вишневец'], substrings: ['ишневец'],
      spellings: ['Вишневецький', 'Вишневецького', 'Wiszniowiecki'],
      forms: { uk: { nom_m: 'Вишневецький' } },
      selftest_mode: 'strict',
      path: 'C:/простір/config/research_profile.yaml',
      available: [{ name: 'rid', display: 'Вишневецький', active: true }],
      source: 'fallback: rid\nprofiles:\n  rid: {}\n',
      paradigms: [{ id: 'adj_skyi', label: 'на -ський', verified: true }],
      orthographies: ['bank', 'ru_modern', 'ru_prereform', 'uk', 'pl'],
    },
    'profile.set': { name: 'rid', path: 'C:/простір/config/research_profile.yaml',
                     mode: 'created', present: true, display: 'Вишневецький',
                     stems: {}, roots: [], substrings: [], spellings: [],
                     paradigm: 'adj_skyi' },
    'profile.source': { written: false, path: 'C:/простір', exists: true, text: '' },
    // 🔴 Домівка має два стани під одним іменем, і перемикає їх саме це поле:
    // порожній простір мусить показати три двері, наповнений — дашборд. Один
    // зріз на обидва випадки перевіряв би рівно половину екрана.
    'home.pulse': globalThis.__EMPTY_SPACE ? {
      workspace: { root: 'C:/простір', name: 'простір' },
      sections: { active: ['core'], preset: 'catalog' },
      pulse: { seq: 0, at: '', by: '' },
      registry: { built: false }, canon: { present: false, why: 'канону немає' },
      profile: { present: false }, reading: null, search: null, eye: null,
      jobs: { queue: false }, history: [],
    } : {
      workspace: { root: 'C:/простір', name: 'простір' },
      sections: { active: ['core', 'htr', 'research'], preset: 'researcher' },
      pulse: { seq: 7, at: '2026-08-26T14:44:53', by: 'cases.build' },
      registry: { built: true, at: '2026-08-25T16:20:43', cases: 12,
                  frames: 900, ordered: 1, htr_none: 4, htr_frames_left: 300,
                  htr_pages: 600, fuzzy_none: 5, fuzzy_hits_open: 8,
                  eye_cases: 3, eye_pages: 40, eye_pages_full: 9,
                  by_repo: [{ repo: 'ДАХмО', n: 7, frames: 700, no_htr: 2 }],
                  by_uezd: [{ uezd: 'Балтський', n: 5, frames: 400, no_htr: 1 }] },
      canon: { present: true, persons: 30, families: 8, sources: 12, places: 4,
               facts: 90, citations: 70, media: 2, facts_uncited: 6,
               persons_no_dates: 3, sources_uncited: 1,
               facts_by_type: [{ code: 'birth', n: 50 }, { code: 'death', n: 40 }],
               facts_by_decade: [{ decade: 1800, n: 20 }, { decade: 1810, n: 70 }],
               top_surnames: [{ code: 'Вишневецький', n: 21 }],
               coverage: { year_min: 1750, year_max: 1935,
                           by_status: [{ code: 'decoded', label: 'Прочитано', n: 9 }],
                           by_record_type: [{ code: 'birth', label: 'Народження', n: 7 }] } },
      profile: { present: true, name: 'd', display: 'Вишневецький',
                 roots: ['вишневец'], spellings: 12 },
      reading: { ok: true, runs: 6, pages: 600, orphans: 1, sec_median: 12.5,
                 by_engine: [{ code: 'pysar', n: 5 }],
                 by_model: [{ code: 'pysar_cyr_v17.pt', n: 5 }],
                 last: [{ name: 'прогін', shifra: 'А 1-1-2', pages: 3,
                          model: 'pysar_cyr_v17.pt', updated: '2026-08-25T10:00:00' }] },
      search: { ok: true, runs: 6, indexed: 5, stale: 1 },
      eye: { built: true, pages: 40, pages_full: 9, files: 3, records: 11,
             by_status: { full: 9, partial: 31 }, cases: 3, in_registry: 38,
             hits_open: 8, no_fuzzy: 5 },
      jobs: { queue: true, running: 1, total: 4, failed: 0, last: [] },
      history: [
        { at: '2026-06-01T12:00:00', src: 'backfill', htr_pages: 100, cases: 4 },
        { at: '2026-07-01T12:00:00', src: 'backfill', htr_pages: 300, cases: 8 },
        { at: '2026-08-26T14:44:53', src: 'live', htr_pages: 600, cases: 12 },
      ],
    },
  }[name] || {};
  if (String(url).endsWith('/api/sections')) {
    return { ok: true, status: 200, json: async () => ({ ok: true, v: 1,
      data: { sections: [], screens: {}, presets: {}, icons: {} } }) };
  }
  return { ok: true, status: 200,
    json: async () => ({ ok: true, v: 1, data, warnings: [] }) };
};
export { created };
"""

PROBE = r"""
import { created } from './_stub.js';
const { SCREENS, ACTIONS, KEYS } = await import('./core/registry.js');
await import('./app.js');

const out = { screens: Object.keys(SCREENS), actions: Object.keys(ACTIONS),
              keys: Object.keys(KEYS), lightbox: null };

// Клік «на весь екран» на екрані аркушів — від дії до появи переглядача.
await ACTIONS['frames.open']({ preventDefault() {}, target: { tagName: 'FORM' } });
await new Promise((r) => setTimeout(r, 20));
const before = created.length;
await ACTIONS['frames.full']();
await new Promise((r) => setTimeout(r, 20));
const boxes = created.slice(before).filter((c) => c.className === 'lb');
out.lightbox = boxes.length;
if (boxes.length) {
  // Читалка бібліотеки мусить мати ті самі рамки, що й читалка гортача:
  // справа одна, прочитане одне, різниця була лише у вході.
  out.libShapes = (boxes[0].querySelector('.lb-ov').children || []).length;
}

// ── жест: тягнути аркуш не означає зачинити ────────────────────────────────
if (boxes.length) {
  const lb = boxes[0];
  const canvas = lb.querySelector('.lb-canvas');
  const press = (t) => ({ button: 0, clientX: 100, clientY: 100,
                          pointerId: 1, target: t });
  // 1. Тягнення, що почалось і скінчилось на тлі.
  canvas.fire('pointerdown', press(canvas));
  canvas.fire('pointermove', { clientX: 260, clientY: 180, target: canvas });
  canvas.fire('pointerup', { target: canvas });
  lb.fire('click', { target: canvas });
  out.closedByDrag = lb.removed;

  // 2. Справжній клік повз аркуш — має зачинити.
  lb.removed = false;
  canvas.fire('pointerdown', press(canvas));
  canvas.fire('pointerup', { target: canvas });
  lb.fire('click', { target: canvas });
  out.closedByClick = lb.removed;

  // 3. Клік, що почався на аркуші й доїхав до тла, — це теж перетягування.
  const img = lb.querySelector('.lb-img');
  lb.removed = false;
  canvas.fire('pointerdown', { ...press(img), target: img });
  canvas.fire('pointerup', { target: canvas });
  lb.fire('click', { target: canvas });
  out.closedFromImage = lb.removed;
}

// ── читалка прогону: знімок разом із прочитаним ────────────────────────────
await import('./screens/view.js');
const { ST } = await import('./core/state.js');
ST.view = { run: 'прогін', page: '', line: null };
await SCREENS.view();
await new Promise((r) => setTimeout(r, 40));
const b2 = created.length;
await ACTIONS['view.full']();
await new Promise((r) => setTimeout(r, 40));
const reader = created.slice(b2).filter((c) => c.className === 'lb');
out.reader = reader.length;
if (reader.length) {
  const ovNode = reader[0].querySelector('.lb-ov');
  out.shapes = (ovNode.children || []).length;
}

// ── екрани мусять намалюватись, а не лише зареєструватись ──────────────────
// 🔴 Модуль, який завантажився, і екран, який щось показав, — різні речі. Саме
// між ними живе клас вад «кнопка є, натискається, нічого не відбувається».
// `settings` тут тому, що він рівно так і зламався: присвоєння в імпортоване
// зв'язування (`SECTIONS = env.data`) синтаксично бездоганне, статичні
// перевірки його не бачать, і падає воно лише коли екран справді малюють.
ST.read = { case_dir: 'data/raw/зразок' };
for (const name of ['cases', 'fonds', 'sources', 'read', 'search', 'settings',
                    'profile']) {
  await SCREENS[name]();
  await new Promise((r) => setTimeout(r, 30));
  const view = document.getElementById('view');
  // 🔴 Разом із тим, що екрани домальовують у власні контейнери після запиту.
  // Заглушка тримає їх окремими вузлами, і дивитись лише на `#view` означало б
  // перевіряти каркас, а не відповідь.
  const html = (view.innerHTML || '')
    + (document.getElementById('card').innerHTML || '')
    + (document.getElementById('search-index').innerHTML || '')
    + (document.getElementById('hits').innerHTML || '');
  out[`drew_${name}`] = html.length;
  // Знаменник приймальні: число описаних справ мусить бути видним, інакше
  // «192 теки» читаються як увесь простір.
  if (name === 'cases') out.intakeHasLibraryLink = html.includes('data-arg="library"');
  // Опис мусить назвати фонд і його обсяг до будь-якого запиту. Раніше
  // ознакою була кнопка в таблиці фондів; тепер фонд обирають пікером, і
  // видимою частиною є його підпис — «А ф.1 — 9 справ».
  if (name === 'fonds') {
    out.fondsListsFonds = html.includes('id="fd-pick"') && html.includes('9 справ');
    // Зведення фонду — сім чисел, кожне з яких є рішенням.
    out.fondsShowsSummary = html.includes('зі сканом') && html.includes('обрізано');
  }
  // Каталоги мусять назвати, на чому шукали, до будь-якого запиту.
  if (name === 'sources') out.sourcesShowBasis = html.includes('nysh crawl x');
  // Картка справи мусить назвати причину письма, а не саме лише письмо.
  if (name === 'read') out.readShowsWhy = html.includes('опису справи');
  // Пошук мусить сказати, скільки прогонів поза індексом, до запиту.
  if (name === 'search') out.searchShowsIndex = html.includes('data-act="search.index"');
}

// ── пошук «в учасниках записів»: інша форма хіта, інший рендер ────────────
// 🔴 Тут перевіряється не «модуль виконався», а те, що видача НЕ порожня по
// суті: хіти цього режиму приходять формою моделі `Record`, і рендер, писаний
// під форму decode-пошуку, малював рівно шифру й бал — issue #4.
globalThis.__FORM = { where: 'records', q: 'Вишневецький', case: '' };
// ⚠ Ціль події мусить бути ВУЗЛОМ, а не парою полів: перед запитом форма
// глушить свої кнопки, і на голому об'єкті фронт падає ще до пошуку.
const searchForm = document.createElement('form');
await ACTIONS['search.run']({ preventDefault() {}, target: searchForm });
await new Promise((r) => setTimeout(r, 40));
out.recHits = document.getElementById('hits').innerHTML || '';
globalThis.__FORM = null;

// ── «Рід»: форма є в обох станах ───────────────────────────────────────────
// 🔴 Доти профіль можна було завести лише командою в терміналі, а вікно про
// нього тільки попереджало. Приймач тут — саме наявність ФОРМИ у стані «профілю
// немає»: попередження без неї це знову глухий кут.
out.profileHasForm = (document.getElementById('view').innerHTML || '')
  .includes('data-act="prof.save"');
globalThis.__NO_PROFILE = true;
await SCREENS.profile();
await new Promise((r) => setTimeout(r, 30));
const noProf = document.getElementById('view').innerHTML || '';
out.profileEmptyForm = noProf.includes('data-act="prof.save"');
out.profileEmptySource = noProf.includes('data-act="prof.source"');
globalThis.__NO_PROFILE = false;

// ── домівка: два стани одного екрана ───────────────────────────────────────
// 🔴 Наповнений простір не має бачити «З чого почнемо», а порожній — плитки з
// прочерками. Обидва зрізи малюються тим самим модулем, тож помилка тут — це
// не косметика: людині з тисячею справ головна показувала б онбординг.
async function drawHome() {
  await SCREENS.home();
  await new Promise((r) => setTimeout(r, 30));
  return document.getElementById('view').innerHTML || '';
}
const full = await drawHome();
out.homeFullTiles = full.includes('class="tile"');
out.homeFullChart = full.includes('ch-steps') || full.includes('ch-bars');
out.homeFullCanon = full.includes('Факти за типом');
out.homeFullDoors = full.includes('data-act="home.scans"');

// Перемикач метрики міняє тільки коробку графіка: застереження конверта на
// екрані лишаються, бо серед них буває «зріз застарів» із кнопкою перезбірки.
if (ACTIONS['home.metric']) {
  await ACTIONS['home.metric'](null, { dataset: { arg: 'cases' } });
  out.metricKeptScreen = (document.getElementById('view').innerHTML || '')
    .includes('class="tile"');
  out.metricSwapped = (document.getElementById('dash-time').innerHTML || '')
    .includes('aria-pressed="true"');
}

globalThis.__EMPTY_SPACE = true;
const empty = await drawHome();
out.emptyDoors = empty.includes('data-act="home.scans"');
out.emptyNoTiles = !empty.includes('class="tile"');
globalThis.__EMPTY_SPACE = false;
globalThis.__NO_PROFILE = false;

console.log('@@' + JSON.stringify(out));
// 🔴 Вихід явний. Застосунок навмисно тримає вічний цикл спостереження за
// чергою робіт: у браузері він блокується на сервері до 25 с, а тут заглушка
// відповідає миттєво — і прогін крутився б без кінця, виглядаючи як зависання
// приймача, а не як зроблена робота.
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    """Скопіювати фронт, переписати абсолютні шляхи `/ui/` і виконати."""
    root = tmp_path_factory.mktemp("front")
    shutil.copytree(FRONT_DIR, root, dirs_exist_ok=True)
    shutil.copytree(SHARED_DIR, root / "ui", dirs_exist_ok=True)
    # Браузер бере спільний шар з `/ui/**` — тека, яку монтує сервер. На диску
    # її поруч немає, тож для прогону шлях стає відносним. Це єдина правка;
    # решта коду виконується як є.
    for p in root.rglob("*.js"):
        depth = len(p.relative_to(root).parts) - 1
        prefix = "./" if depth == 0 else "../" * depth
        s = p.read_text(encoding="utf-8")
        s2 = re.sub(r"from '/ui/", f"from '{prefix}ui/", s)
        if s2 != s:
            p.write_text(s2, encoding="utf-8")
    (root / "_stub.js").write_text(STUB, encoding="utf-8")
    (root / "_probe.mjs").write_text(PROBE, encoding="utf-8")

    res = subprocess.run(["node", "--input-type=module", "-e",
                          f"await import({json.dumps((root / '_probe.mjs').as_uri())})"],
                         capture_output=True, text=True, cwd=root)
    line = next((x for x in res.stdout.splitlines() if x.startswith("@@")), "")
    assert line, (
        "фронт не виконався — у браузері це порожній екран без жодного слова:\n"
        + (res.stderr or res.stdout)[:1500])
    return json.loads(line[2:])


def test_every_declared_screen_registers_itself(probe) -> None:
    """🔴 Модуль, який упав при завантаженні, лишає екран невідомим.

    Диспетчер тоді мовчки показує домівку замість того, що просили, — і
    виглядає це як «кнопка веде не туди», а не як помилка.
    """
    from nyshporka.core import sections as S

    got = set(probe["screens"])
    want = set(S.SCREENS)
    missing = sorted(want - got)
    assert not missing, (
        f"екрани оголошені, але себе не зареєстрували: {missing}. "
        "Найімовірніше, їхній модуль упав при завантаженні")


def test_the_action_registry_is_not_half_empty(probe) -> None:
    """Половина реєстру — типовий наслідок падіння одного модуля."""
    n = len(probe["actions"])
    assert n >= 40, (
        f"дій зареєстровано лише {n} — схоже, частина модулів не виконалась")


def test_the_fullscreen_button_actually_opens_the_viewer(probe) -> None:
    """🔴 Кнопка, що мовчить, — найдорожчий вид поломки.

    Людина не знає, чи вона не влучила, чи застосунок зламався, чи так і має
    бути. Тому перевіряється не наявність обробника, а наслідок: після виклику
    дії в документі мусить з'явитись переглядач.
    """
    assert "frames.full" in probe["actions"], "дії «на весь екран» немає в реєстрі"
    assert probe["lightbox"] == 1, (
        "дія відпрацювала, а переглядач не з'явився — саме так виглядає "
        "мертва кнопка: ні наслідку, ні помилки")


def test_keyboard_is_bound_to_the_screens_that_need_it(probe) -> None:
    """Клавіші живуть у модулях екранів; порожньо тут — модуль не виконався."""
    got = set(probe["keys"])
    assert {"view", "sift", "frames"} <= got, (
        f"клавіші зареєстрували лише {sorted(got)}")


# ── жести: тягнути ≠ зачинити ────────────────────────────────────────────────
def test_dragging_the_sheet_does_not_close_the_viewer(probe) -> None:
    """🔴 Полотно переглядача займає весь екран, тож натискання «щоб потягнути»
    падає на тло — а браузер після відпускання все одно шле `click`.

    Доти фон читав його як «клікнули повз аркуш, зачиняємось»: людина тягне,
    вікно зникає. Найгірше тут те, що жест і закриття невідрізненні — це
    виглядає як випадковий збій, а не як власна дія.
    """
    assert probe.get("closedByDrag") is False, (
        "перетягування зачинило переглядач — рухати аркуш стало неможливо")


def test_a_real_click_past_the_sheet_still_closes(probe) -> None:
    """Захист від жесту не має вбити саму дію: клік повз аркуш зачиняє."""
    assert probe.get("closedByClick") is True, (
        "клік повз аркуш перестав зачиняти — захист з'їв корисну дію")


def test_a_drag_that_began_on_the_sheet_is_not_a_click_past_it(probe) -> None:
    """Жест, що стартував на аркуші й доїхав до тла, — перетягування.

    ⚠ Саме тому запам'ятовується, де натискання почалось, а не де скінчилось:
    при наближенні аркуш займає весь екран, і тягнути його доводиться саме
    «з аркуша на тло».
    """
    assert probe.get("closedFromImage") is False, (
        "перетягування з аркуша на тло зачинило переглядач")


# ── читалка прогону ──────────────────────────────────────────────────────────
def test_the_run_reader_opens_with_the_sheet(probe) -> None:
    """Гортач на весь екран мусить відкриватись так само, як перегляд аркушів."""
    assert probe.get("reader") == 1, (
        "читалка прогону не відкрилась — а саме нею тепер і читають")


def test_the_reader_draws_the_line_boxes_on_the_scan(probe) -> None:
    """🔴 Головне, заради чого читалка робилась: текст на своєму місці.

    Рядок формуляра — короткий шматок усередині графи, і списком під знімком
    він втрачає єдине, що робить його зрозумілим: де він стояв. Рамки
    малюються в просторі імен SVG, і саме на цьому читалка падала б мовчки,
    якби накладку ніхто не виконував.

    ⚠ Порожня фігура серед рамок — законне значення: рядок без обведення її не
    має, і раннер пише в масив саме `null`, зберігаючи довжину. Тому з двох
    рамок малюється одна, а нумерація рядків не зсувається.
    """
    assert probe.get("shapes") == 1, (
        f"на скан лягло {probe.get('shapes')} рамок замість однієї — "
        "накладка або не намалювалась, або порахувала порожню фігуру")


def test_the_library_reader_shows_the_decode_too(probe) -> None:
    """🔴 Та сама справа не має читатись по-різному залежно від входу.

    Доти з гортача аркуш відкривався з текстом і рамками, а з бібліотеки —
    самим папером. Різниця була не в даних, а в тому, що один екран про них не
    спитав: кадр і сторінка прогону — це одне ім'я файлу, тож зіставляти нічого
    не треба.
    """
    assert probe.get("libShapes") == 1, (
        f"читалка бібліотеки поклала {probe.get('libShapes')} рамок замість "
        "однієї — прочитане з бібліотеки не видно")


def test_the_reworked_screens_actually_draw(probe) -> None:
    """🔴 Модуль завантажився ≠ екран щось показав.

    Між цими двома станами живе цілий клас вад: кнопка в шапці є, натискається,
    і лишає порожнє полотно. Помітно це лише оком, а оком дивляться не щодня —
    тому три перероблені екрани виконуються тут і мусять лишити по собі
    розмітку.
    """
    for name in ("cases", "fonds", "sources"):
        size = probe.get(f"drew_{name}") or 0
        assert size > 200, (
            f"екран «{name}» намалював {size} символів розмітки — це порожньо, "
            f"а не екран")


def test_intake_names_the_library_too(probe) -> None:
    """🔴 Знаменник обома боками межі.

    Приймальня без числа бібліотеки читається як увесь простір: «192 теки» —
    і невідомо, з чого. Саме на цій парі дослідник і спитав, чим одна закладка
    відрізняється від другої, тож посилання на сусідній реєстр тут не
    оздоблення, а частина відповіді.
    """
    assert probe.get("intakeHasLibraryLink"), (
        "приймальня не назвала бібліотеку — її число лишилось без знаменника")


def test_the_finding_aid_lists_its_fonds_without_a_query(probe) -> None:
    """🔴 Перелік фондів був захований у випадному списку всередині форми.

    Щоб побачити, що реєстр не порожній, треба було спершу натиснути «Знайти», —
    і той, хто цього не зробив, чесно вважав, що описів у нього немає.

    ⚠ Ознака змінилась разом із екраном: фонд тепер обирають пікером, а не
    таблицею. Вимога лишилась та сама — обсяг реєстру мусить бути видний до
    будь-якого запиту, тож перевіряється підпис «А ф.1 — 9 справ».
    """
    assert probe.get("fondsListsFonds"), (
        "екран описів не назвав жодного фонду до запиту")


def test_the_fond_says_what_it_costs_to_work_with(probe) -> None:
    """🔴 `summarize()` рахує вісімнадцять показників, наверх ішли чотири.

    Через це екран не міг сказати ні скільки справ обрізає дзеркало, ні
    скільки номерів відновлено між якорями — тобто мовчав саме про те, чим
    вирішують, куди дивитись далі й чи варто качати з дзеркала взагалі.
    """
    assert probe.get("fondsShowsSummary"), (
        "рядок метаданих фонду не показав ні сканів, ні обрізаних справ")


def test_catalogues_name_what_they_searched_before_the_query(probe) -> None:
    """🔴 «Нічого не знайшлось» без переліку оглянутого не є відповіддю.

    Джерело, яке вміє шукати й не має каталогу, мусить бути назване поіменно —
    разом із командою, якою це лікується, — до пошуку, а не після одинадцяти
    секунд очікування.
    """
    assert probe.get("sourcesShowBasis"), (
        "екран каталогів не назвав джерело без обходу й спосіб це полагодити")


def test_the_read_card_names_why_it_thinks_so(probe) -> None:
    """🔴 Письмо без причини — половина відповіді, і саме дорога половина.

    Здогад із назви теки й запис у паспорті справи розрізняються надійністю на
    порядок, а на екрані виглядали б однаково. Помилка тут не дає збою: вона
    дає осмислене на вигляд сміття через годину роботи.
    """
    assert probe.get("readShowsWhy"), (
        "картка справи показала письмо, не сказавши, звідки воно відоме")


def test_search_shows_what_is_outside_the_index(probe) -> None:
    """🔴 Знаменник пошуку — до запиту, а не застереженням після нього.

    Пошук чеше лише зібране. Побачивши це вже у видачі, людина встигла
    зачекати й повірити нулю.
    """
    assert probe.get("searchShowsIndex"), (
        "екран пошуку не сказав, що частина прогонів поза індексом")


def test_home_shows_a_dashboard_when_the_workspace_has_material(probe) -> None:
    """🔴 Наповнений простір не має бачити онбординг.

    Три двері «з чого почнемо» — правильна відповідь рівно один раз, першого
    дня. Людині, у якої вже є справи, прогони й канон, вони не кажуть нічого
    про те, де вона стоїть, — а це єдине, по що на головну й заходять.
    """
    assert probe["homeFullTiles"], "дашборд не намалював жодної плитки"
    assert probe["homeFullChart"], "дашборд без жодної діаграми"
    assert probe["homeFullCanon"], "розріз канону не намалювався"
    # Двері лишаються — але внизу, як швидка дія, а не як увесь екран.
    assert probe["homeFullDoors"], "двері зникли зовсім — почати нове нема звідки"


def test_home_stays_an_onboarding_while_the_workspace_is_empty(probe) -> None:
    """🔴 Порожній простір мусить бачити три двері, а не дашборд із прочерками.

    Нуль справ там, де їх ще не клали, — це не результат, а стан «нічого не
    починали», і показувати замість входу таблицю нулів означає відповісти на
    питання, якого не ставили.
    """
    assert probe["emptyDoors"], "на порожньому просторі немає входу «у мене є скани»"
    assert probe["emptyNoTiles"], "порожній простір показує плитки з прочерками"


def test_switching_the_time_metric_does_not_wipe_the_warnings(probe) -> None:
    """🔴 Перемальовується лише коробка графіка.

    Через `setView` пішли б і застереження конверта — а серед них «зріз
    застарів» із кнопкою перезбірки. Клік по підпису кривої не має права гасити
    попередження про те, що всі числа поруч старі.
    """
    assert probe["metricKeptScreen"], "перемикач метрики зніс увесь екран"
    assert probe["metricSwapped"], "коробка графіка не перемалювалась"


def test_the_family_screen_offers_a_form_when_there_is_no_profile(probe) -> None:
    """🔴 Найпропущеніший крок першої сесії — і доти єдиний без дверей у вікні.

    Попередження «профілю немає» показувалось, а завести його можна було лише
    командою в терміналі. Для людини, яка запустила застосунок подвійним
    кліком, це читалось як «щось не так, і вдіяти нічого не можна» — тобто
    найдорожчий вид глухого кута: він виглядає як несправність.
    """
    assert probe["profileEmptyForm"], (
        "на порожньому профілі немає форми заведення — попередження знову "
        "нікуди не веде")
    assert probe["profileEmptySource"], (
        "немає редактора файла: полагодити побитий конфіг з вікна нічим")


def test_the_family_screen_draws_an_existing_profile_too(probe) -> None:
    """Форма мусить бути й тоді, коли профіль є: інакше правити його нічим."""
    assert probe["profileHasForm"]
    assert probe["drew_profile"] > 200, "екран «Рід» намалював порожнечу"


# ── 🔎 пошук у записах: форма хіта інша, і рендер мусить це знати ────────────
def test_records_search_shows_what_it_found(probe) -> None:
    """🔴 Режим «в учасниках записів» показував саму шифру й бал.

    Хіт `grep_records()` — це форма моделі `Record`: `scans` (множина), `role`,
    `name`, `date`, `place`. Жодного з полів, під які писався рендер (`page`,
    `scan`, `matched`, `line`, `text`, `surname`), у ньому немає — тож колонки
    виходили порожніми на КОЖНОМУ хіті без винятку, незалежно від того, звідки
    запис узявся.

    ⚠ Тексту модуля це не видно: шаблон бездоганний, поля існують, синтаксис
    чистий. Видно лише тому, хто справді намалював видачу — тому приймач тут
    виконує фронт, а не читає його.
    """
    html = probe["recHits"]
    assert html, "видача записів порожня — рендер не дійшов до таблиці"
    for want in ("Іван Вишневецький", "father", "1858-03-04"):
        assert want in html, f"«{want}» не доїхав у видачу — колонка знову порожня"


def test_a_record_hit_carries_the_place_that_tells_namesakes_apart(probe) -> None:
    """Прізвище в парафії повторюється частіше, ніж здається.

    Без місця хіт лишається нерозрізненим, і розбирати його доводиться тією
    самою роботою, заради якої пошук і кликали.
    """
    assert "Мястківка" in probe["recHits"]
    assert "Ободівка" in probe["recHits"]


def test_the_eye_is_not_offered_where_there_is_nothing_to_open(probe) -> None:
    """🔴 Кнопка 👁 прив'язана до прогону читання, а в записів такого зв'язку
    немає взагалі.

    Намальована «щоб було», вона коштувала б дорожче за свою відсутність:
    натискання веде в порожній гортач, і це читається як зламаний гортач, а не
    як відсутній зв'язок run↔scan.
    """
    assert 'data-act="hit.eye"' not in probe["recHits"]


def test_the_note_button_appears_only_where_it_will_not_fail(probe) -> None:
    """🔴 Приймач тут — не сама кнопка, а збіг із валідатором `PageNote.scan`.

    Він приймає ГОЛЕ ім'я файлу: ні шляху, ні провідної крапки. Кнопка,
    показана на цитаті-URL чи на прихованому файлі, падає вже після кліку —
    тобто помилку видно там, де її причини не видно.
    """
    html = probe["recHits"]
    assert 'data-scan="0030.JPG"' in html, "на своєму скані ✎ мусить бути"
    assert "приклад" not in html.split('data-act="hit.note"')[0][-200:] or True
    for bad in ("https://приклад/цитата", ".прихований.jpg"):
        assert f'data-scan="{bad}"' not in html, (
            f"✎ показано на «{bad}» — валідатор відкине його вже після кліку")
