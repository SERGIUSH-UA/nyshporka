"""🗂 Композиція екранів (перекрій консолі, R2) у Node.

Огляд Майстерні — продовження роботи, а не моніторинг; діагностика — на «Стані
Майстерні»; Бібліотека — одна підписана дія в рядку; Читання — кроки й рядок
наслідку. Майстерня з вигаданими проєктами, справи `TEST/…`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from _front import FRONT_DIR, SHARED_DIR
from test_front_boots import STUB

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node немає — виконати фронт нічим")

PROBE = r"""
import './_stub.js';
globalThis.location.pathname = '/';
globalThis.location.search = '__SEARCH__';
document.body.dataset.token = 'tok';
const stubFetch = globalThis.fetch;
const MINE = '__PID__';
const PROJECTS = { projects: [
  { id: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', color: '#aa3300', glyph: 'С' },
  { id: 'kovalchuk', name: 'Рід Ковальчуків', kind: 'family', color: '#0055aa', glyph: 'К' }],
  current: MINE || null, default: null, hub_only: true, hub_id: '_hub' };
const row = (key, stage, by) => ({ key, shifra: key, title: 'Сповідка', htr_stage: stage,
  searched_by: by, verdict: '', on_disk: true, frames: 9, path: 'data/raw/' + key, fond: '1' });
const DATA = {
  'home.pulse': { workspace: { root: 'X' }, registry: { built: true, cases: 3, frames: 9, unfiled: 2, bundles: 1 },
    reading: { ok: true, runs: 1, pages: 5, by_engine: [], by_model: [],
      last: [{ shifra: 'ТЕСТ 1-1-1', pages: 5, frames: 9, state: 'done', model: 'm', updated: '2026-10-20T10:00:00' }] },
    search: {}, eye: {}, history: [], pulse: {}, machine: { ok: true, ready: true }, agent: { connected: true } },
  'home.machine': { ok: true, ready: true },
  'project.list': { projects: [
    { id: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', persons: 1, hypotheses: { open: 1 } },
    { id: 'kovalchuk', name: 'Рід Ковальчуків', kind: 'family', persons: 0, hypotheses: {} },
    { id: 'old', name: 'Старе замовлення', kind: 'order', archived: true }] },
  'library.list': { built: true, cases: [
      row('TEST/1/1/1', 'none', {}),
      row('TEST/1/1/2', 'pysar', {}),
      row('TEST/1/1/3', 'pysar', { sydoruk: '2026-10-20T10:00' })],
    shown: 3, total: 3, page: 0, pages: 1, library_total: 3, facets: {},
    summary: { all: 3, has_layers: true }, kinds: {} },
  'htr.case_info': { shifra: 'ТЕСТ 1-1-1', title: 'Сповідка', frames: 9, script: 'cyrillic',
    script_trust: 'fixed', models: {}, engines: [], done: {}, gaps: [] },
  'queue.status': { items: [], runner: null, counts: {} },
  'read.plan': { plan: { frames: 9, script: 'cyrillic', model: 'models/pysar_cyr_v19.pt',
    voices: [], out_dir: 'reports/htr/t1' } },
};
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/jobs/wait')) return new Promise(() => {});
  if (u.endsWith('/api/projects')) return { ok: true, status: 200, json: async () => PROJECTS };
  const name = u.split('/api/op/')[1] || '';
  if (name && Object.hasOwn(DATA, name)) {
    return { ok: true, status: 200, json: async () => ({ ok: true, v: 1, warnings: [], data: DATA[name] }) };
  }
  return stubFetch(url, opts);
};
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));
const view = () => document.getElementById('view').innerHTML || '';
const { SCREENS, ACTIONS } = await import('./core/registry.js');
await import('./app.js');
await tick(200);
const nav = await import('./core/nav.js');
nav.setSections({ hub_only: !MINE });
const { ST } = await import('./core/state.js');
const out = {};
if (!MINE) {
  await SCREENS.home(); await tick(120); out.home = view();
  out.cards = document.getElementById('hub-cards').innerHTML || '';
  await SCREENS.status(); await tick(80); out.status = view();
  await SCREENS.projects(); await tick(80); out.projects = view();
  await SCREENS.status(); await tick(80);
  const beforeCheck = view();
  DATA['setup.check'] = { level: 'warn', ready: false, checks: [], sample_case: true, sample_available: false };
  await ACTIONS['home.demo'](); await tick(80);
  out.statusKept = view() === beforeCheck;
  out.checkBox = document.getElementById('dlg-body').innerHTML || '';
}
await SCREENS.library(); await tick(80); out.library = view();
if (MINE) {
  ST.read = { case_dir: 'data/raw/TEST/1/1/1' };
  await SCREENS.read(); await tick(120);
  out.readCard = view();
  await ACTIONS['read.plan']({ preventDefault() {}, target: { querySelector: () => null } });
  await tick(120);
  out.plan = document.getElementById('hits').innerHTML || '';
  await SCREENS.library(); await tick(80);
  await ACTIONS['lib.verdict'](null, { dataset: { arg: 'TEST/1/1/2' } });
  out.verdict = view();
  await SCREENS.queue(); await tick(80);
  out.queue = view();
  const EV = await import('./screens/evidence.js');
  EV.openEvidence({ case: 'TEST/1/1/2', page: '4', line: 3, card: 'I9001' });
  out.evidence = document.getElementById('dlg-body').innerHTML || '';
}
const V = await import('./core/view.js');
const td = { dataset: {} };
const own = { dataset: { l: 'своє' } };
const table = { querySelectorAll: (q) => (q === 'thead th'
  ? [{ textContent: ' Шифра ' }, { textContent: 'Стан' }] : [{ children: [td, own] }]) };
V.labelCells({ querySelectorAll: (q) => (q === 'table.tbl-cards' ? [table] : []) });
out.labels = [td.dataset.l, own.dataset.l];
const BT = await import('./core/bits.js');
const refs = { I9001: 'Іван Сидорук', PL9001: 'Городківка' };
out.named = BT.named('Чоловік I9001, [[PL9001]], [[I9002|Петро]], **важливо**, I9999', refs);
out.namedTwice = BT.named('[[I9001]] — це I9001', refs);
out.day = [BT.fmtDay('2026-07-23T00:00:00Z'), BT.fmtDay('1993-08-28'), BT.fmtDay('1850')];
out.forms = BT.fieldValue('name_variants', [{ form: 'Городківка' }, { form: 'Городковка' }]);
out.md = BT.mdLite(['Вступ', '', '| Справа | Сторінок |', '|---|---|', '| [[I9001]] | 12 |', '',
  'Кінець'].join(String.fromCharCode(10)), refs);
const SH = await import('./screens/share.js');
out.card = SH.cardRows({ title: 'Сповідка', years: [1801, 1803], places: ['Городківка', 'Липівка'],
  doc_type: 'confession', scans: { label: 'Зйомка М. Сидорука', url: 'https://example.org/x' } },
  { total: 120, source: 'бібліотека' });
out.cardNone = SH.cardRows({ frames_unknown: 'опису немає', scans: { label: '', url: 'javascript:alert(1)' } }, {});
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


def _run(tmp_path_factory, search: str, pid: str) -> dict:
    root = tmp_path_factory.mktemp("front-compose")
    shutil.copytree(FRONT_DIR, root, dirs_exist_ok=True)
    shutil.copytree(SHARED_DIR, root / "ui", dirs_exist_ok=True)
    for p in root.rglob("*.js"):
        depth = len(p.relative_to(root).parts) - 1
        prefix = "./" if depth == 0 else "../" * depth
        s = p.read_text(encoding="utf-8")
        s2 = re.sub(r"from '/ui/", f"from '{prefix}ui/", s)
        if s2 != s:
            p.write_text(s2, encoding="utf-8")
    (root / "_stub.js").write_text(STUB, encoding="utf-8")
    (root / "_probe.mjs").write_text(
        PROBE.replace("__SEARCH__", search).replace("__PID__", pid), encoding="utf-8")
    res = subprocess.run(["node", "--input-type=module", "-e",
                          f"await import({json.dumps((root / '_probe.mjs').as_uri())})"],
                         capture_output=True, cwd=root, encoding="utf-8", errors="replace",
                         timeout=120)
    line = next((x for x in res.stdout.splitlines() if x.startswith("@@")), "")
    assert line, "фронт не виконався:\n" + (res.stderr or res.stdout)[:3000]
    return json.loads(line[2:])


@pytest.fixture(scope="module")
def hub(tmp_path_factory) -> dict:
    return _run(tmp_path_factory, "", "")


@pytest.fixture(scope="module")
def proj(tmp_path_factory) -> dict:
    return _run(tmp_path_factory, "?p=sydoruk", "sydoruk")


def test_hub_overview_is_about_continuing_work(hub) -> None:
    """Проєкти → головні інструменти → числа → останні прогони; діагностики немає."""
    home = hub["home"]
    assert home.index('id="hub-cards"') < home.index('class="tools"'), "спершу проєкти"
    assert "Продовжити дослідження" in hub["cards"] and "Рід Сидоруків" in hub["cards"]
    assert 'class="tools"' in home and 'data-arg="read"' in home and 'data-arg="newcase"' in home
    assert 'data-arg="status"' in home, "діагностика — посиланням на «Стан Майстерні»"
    assert "ТЕСТ 1-1-1" in home, "останні прогони видно"
    assert "dash.reading.engines" not in home and "Рушії" not in home
    # Реєстр рахує ще нові теки й збірки — під плиткою «справ» видно, звідки різниця.
    assert "+ нових тек: 2 · збірок: 1" in home


def test_status_screen_carries_the_diagnostics(hub) -> None:
    assert "ТЕСТ 1-1-1" in hub["status"] and 'class="tools"' not in hub["status"]


def test_projects_screen_lists_all_and_archived_apart(hub) -> None:
    pj = hub["projects"]
    assert "Рід Ковальчуків" in pj and 'class="pj-arch"' in pj and "Старе замовлення" in pj


def test_library_row_has_one_labelled_action_and_more(hub, proj) -> None:
    lib = hub["library"]
    def row(html: str, key: str) -> str:
        return html[html.index(f'data-arg="{key}"'):].split("</tr>")[0]

    one, two = row(lib, "TEST/1/1/1"), row(lib, "TEST/1/1/2")
    assert 'data-act="lib.read"' in one and 'data-act="lib.find"' not in one, "непрочитану — читати"
    assert 'data-act="lib.find"' in two, "прочитану — шукати"
    assert 'data-act="lib.more"' in one and "⋯" in one
    # Вердикти проєктні: у Майстерні колонки немає.
    assert ">вердикт<" not in lib.split("</thead>")[0]
    assert ">вердикт<" in proj["library"].split("</thead>")[0]
    plib = proj["library"]
    three = row(plib, "TEST/1/1/3")
    assert 'data-act="lib.find"' not in three, "уже прошукане для роду — не «шукати»"
    assert 'id="lib-scope"' in plib and 'aria-pressed="true"' in plib


def test_reading_shows_steps_and_where_the_result_lands(proj) -> None:
    assert 'class="rd-step"' in proj["readCard"]
    plan = proj["plan"]
    assert plan.count('class="rd-step"') == 2, "кроки 3 і 4 — у плані"
    assert 'class="consequence"' in plan and "спільний матеріал" in plan and "Рід Сидоруків" in plan
    assert "<details" in plan.split("reports/htr/t1")[0], "тека результату — у подробицях плану"
    assert 'data-act="read.cloud"' in plan, "хмара — поруч із запуском, як вибір де читати"


def test_writing_actions_say_where_the_result_lands(proj) -> None:
    """Вердикт — для роду; доказ — у канон роду; черга — у спільне з підписом."""
    assert 'class="consequence"' in proj["verdict"] and "для «Рід Сидоруків»" in proj["verdict"]
    assert 'class="consequence"' in proj["evidence"] and "канон «Рід Сидоруків»" in proj["evidence"]
    assert 'class="consequence"' in proj["queue"] and "Замовник: Рід Сидоруків" in proj["queue"]


def test_cases_tile_leads_to_the_library(hub) -> None:
    """Плитка «справ» вела в «Нові теки» — там «нових тек немає» проти числа 3."""
    assert 'data-arg="library"' in hub["status"]
    assert 'data-arg="cases"' not in hub["status"].split('class="tiles"')[1].split("</div></div>")[0]


def test_machine_check_opens_over_the_status_screen(hub) -> None:
    assert hub["statusKept"], "перевірка машини замінила «Стан Майстерні»"
    assert "Читання поки не запуститься" in hub["checkBox"]


def test_verdict_form_without_a_verdict_does_not_offer_to_clear(proj) -> None:
    f = proj["verdict"]
    assert "оберіть рішення" in f and "зняти вердикт" not in f
    assert 'class="fld-l"' in f, "поля форми підписані"


def test_phone_cards_take_field_labels_from_the_table_head(hub) -> None:
    """Таблиця-картка на телефоні: підпис поля — з заголовка колонки, своє лишається."""
    assert hub["labels"] == ["Шифра", "своє"]


def test_canon_text_names_ids_and_renders_marks(hub) -> None:
    """ID → ім'я з `refs` (ID у підказці), вікі-посилання, жирне; невідомий ID лишається."""
    html = hub["named"]
    assert 'title="I9001">Іван Сидорук</span>' in html and "Городківка" in html and "Петро" in html
    assert "<b>важливо</b>" in html and "I9999" in html and "[[" not in html
    # 🔴 Той самий id у `[[…]]` і голим: друга заміна не сміє лізти в атрибут
    # першої (у назвах гіпотез проступав сирий HTML, QA 23.10.2026).
    twice = hub["namedTwice"]
    assert twice.count("<span") == 2 and "&gt;" not in twice and 'title="<' not in twice
    assert hub["day"] == ["23.07.2026", "28.08.1993", "1850"]
    assert hub["forms"] == "Городківка, Городковка", "варіанти назв, а не «записів: 2»"


def test_report_tables_are_tables(hub) -> None:
    md = hub["md"]
    assert '<table class="md-table">' in md and "<th>Справа</th>" in md and "Іван Сидорук" in md
    assert "---" not in md and "<p>Кінець</p>" in md


def test_supriaha_card_shows_labelled_fields(hub) -> None:
    """Картка Супряги у вікні — підписи полів, не сирі ключі й JSON (провтик 22.10.2026)."""
    c = hub["card"]
    assert "<dt>Назва</dt>" in c and "<dt>Жанр</dt>" in c and "сповідний розпис" in c
    assert "1801–1803" in c and "Городківка, Липівка" in c and "120" in c
    assert 'href="https://example.org/x"' in c and "Зйомка М. Сидорука" in c
    assert "doc_type" not in c and "{" not in c and "scans" not in c
    none = hub["cardNone"]
    assert "невідомо" in none and "опису немає" in none and "javascript" not in none
