"""🖥 Фронт не просто розбирається — він ВИКОНУЄТЬСЯ.

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
globalThis.FormData = class { get() { return 'data/raw/зразок'; } };
const FRAMES = [{ id: 'a.jpg', label: 'a.jpg', kind: 'image' },
                { id: 'b.jpg', label: 'b.jpg', kind: 'image' }];
globalThis.fetch = async (url) => {
  // 🔴 Довге очікування черги мусить ВИСІТИ, як на справжньому сервері. Якщо
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
                             rows: 9, on_disk: 1, todo: 2, scans: 3 }],
                   shown: 1 },
    'fond.rows': { fond: 'А ф.1', fond_id: 'a_1', matched: 1, total: 1,
                   shown: 1, page: 0, page_size: 50, pages: 1,
                   summary: { rows: 9 },
                   rows: [{ shifra: '1-1-2', spr: '2', key: 'A/1/2',
                            title: 'книга', state: 'todo', on_disk: '',
                            takeable: true }] },
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

// ── жест: тягнути аркуш НЕ означає зачинити ────────────────────────────────
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

  // 3. Клік, що почався НА аркуші й доїхав до тла, — це теж перетягування.
  const img = lb.querySelector('.lb-img');
  lb.removed = false;
  canvas.fire('pointerdown', { ...press(img), target: img });
  canvas.fire('pointerup', { target: canvas });
  lb.fire('click', { target: canvas });
  out.closedFromImage = lb.removed;
}

// ── читалка прогону: знімок РАЗОМ із прочитаним ────────────────────────────
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

// ── три перероблені екрани мусять НАМАЛЮВАТИСЬ, а не лише зареєструватись ──
// 🔴 Модуль, який завантажився, і екран, який щось показав, — різні речі. Саме
// між ними живе клас вад «кнопка є, натискається, нічого не відбувається».
ST.read = { case_dir: 'data/raw/зразок' };
for (const name of ['cases', 'fonds', 'sources', 'read', 'search']) {
  await SCREENS[name]();
  await new Promise((r) => setTimeout(r, 30));
  const view = document.getElementById('view');
  // 🔴 Разом із тим, що екрани домальовують у власні контейнери ПІСЛЯ запиту.
  // Заглушка тримає їх окремими вузлами, і дивитись лише на `#view` означало б
  // перевіряти каркас, а не відповідь.
  const html = (view.innerHTML || '')
    + (document.getElementById('card').innerHTML || '')
    + (document.getElementById('search-index').innerHTML || '')
    + (document.getElementById('hits').innerHTML || '');
  out[`drew_${name}`] = html.length;
  // Знаменник приймальні: число описаних справ мусить бути ВИДНИМ, інакше
  // «192 теки» читаються як увесь простір.
  if (name === 'cases') out.intakeHasLibraryLink = html.includes('data-arg="library"');
  // Опис мусить показати ПЕРЕЛІК фондів, а не саму лише форму пошуку.
  if (name === 'fonds') out.fondsListsFonds = html.includes('data-act="fond.open"');
  // Каталоги мусять назвати, на чому шукали, ДО будь-якого запиту.
  if (name === 'sources') out.sourcesShowBasis = html.includes('nysh crawl x');
  // Картка справи мусить назвати ПРИЧИНУ письма, а не саме лише письмо.
  if (name === 'read') out.readShowsWhy = html.includes('опису справи');
  // Пошук мусить сказати, скільки прогонів поза індексом, ДО запиту.
  if (name === 'search') out.searchShowsIndex = html.includes('data-act="search.index"');
}

console.log('@@' + JSON.stringify(out));
// 🔴 Вихід ЯВНИЙ. Застосунок навмисно тримає вічний цикл спостереження за
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
    бути. Тому перевіряється не наявність обробника, а НАСЛІДОК: після виклику
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
    """🔴 Полотно переглядача займає ВЕСЬ екран, тож натискання «щоб потягнути»
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

    ⚠ Саме тому запам'ятовується, де натискання ПОЧАЛОСЬ, а не де скінчилось:
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
    """🔴 Головне, заради чого читалка робилась: текст НА СВОЄМУ МІСЦІ.

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
    """
    assert probe.get("fondsListsFonds"), (
        "екран описів не показав жодного фонду до запиту")


def test_catalogues_name_what_they_searched_before_the_query(probe) -> None:
    """🔴 «Нічого не знайшлось» без переліку оглянутого не є відповіддю.

    Джерело, яке вміє шукати й не має каталогу, мусить бути назване поіменно —
    разом із командою, якою це лікується, — ДО пошуку, а не після одинадцяти
    секунд очікування.
    """
    assert probe.get("sourcesShowBasis"), (
        "екран каталогів не назвав джерело без обходу й спосіб це полагодити")


def test_the_read_card_names_why_it_thinks_so(probe) -> None:
    """🔴 Письмо без ПРИЧИНИ — половина відповіді, і саме дорога половина.

    Здогад із назви теки й запис у паспорті справи розрізняються надійністю на
    порядок, а на екрані виглядали б однаково. Помилка тут не дає збою: вона
    дає осмислене на вигляд сміття через годину роботи.
    """
    assert probe.get("readShowsWhy"), (
        "картка справи показала письмо, не сказавши, звідки воно відоме")


def test_search_shows_what_is_outside_the_index(probe) -> None:
    """🔴 Знаменник пошуку — ДО запиту, а не застереженням після нього.

    Пошук чеше лише зібране. Побачивши це вже у видачі, людина встигла
    зачекати й повірити нулю.
    """
    assert probe.get("searchShowsIndex"), (
        "екран пошуку не сказав, що частина прогонів поза індексом")
