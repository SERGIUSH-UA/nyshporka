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
    'case.frames': { kind: 'image', total: 2, pdfs: [], frames: FRAMES },
    'case.frame': { width: 9, height: 9, bytes: 9, image: 'data:image/jpeg;base64,AA' },
    'library.list': { cases: [], built: true, summary: {}, facets: {} },
    'runs.list': { runs: [{ name: 'прогін', case_dir: 'c', engine_id: 'pysar',
                            pages_done: 2, frames: 2 }] },
    'page.text': { name: 'прогін', engine_id: 'pysar', model: 'pysar_cyr_v4.pt',
                   pages: [{ page: 'a.jpg', lines: 2 }, { page: 'b.jpg', lines: 2 }],
                   lines: ['перший рядок', 'другий рядок'] },
    'page.lines': { has: true, size: [100, 60],
                    polys: [[[1, 1], [9, 1], [9, 5], [1, 5]], null] },
    'page.view': { image: 'data:image/png;base64,AA', line: 0, text: 'рядок' },
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
