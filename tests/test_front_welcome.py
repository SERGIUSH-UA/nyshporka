"""👋 Знайомство в Node: коли з'являється, що кличе кожен крок і куди веде «Готово».

Порожня Майстерня (ні проєктів, ні справ) без позначки в браузері відкриває
знайомство замість Огляду; з позначкою — Огляд з головною дією «Створити
перший проєкт». Мова перезавантажує на крок вигляду, проєкт кличе
`project.new` і переходить у нього, рід кличе `profile.where`. Рід вигаданий
(«Сидорук»).
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
globalThis.location.href = '';
globalThis.history = { replaceState(_s, _t, url) {
  const u = String(url); globalThis.location.search = u.slice(u.indexOf('?'), u.indexOf('#')); } };
document.body.dataset.token = 'tok';
const PROJECTS = { projects: __PROJ_ROWS__, current: '__PID__' || null, default: null,
  hub_only: !'__PID__', hub_id: '_hub' };
const DATA = {
  'home.pulse': { workspace: { root: 'X' }, registry: { built: true, cases: 0, unfiled: 0 },
    reading: {}, search: {}, eye: {}, history: [], pulse: {}, machine: { ok: true, ready: true },
    agent: { connected: false } },
  'home.machine': { ok: true, ready: true },
  'project.list': { projects: __PROJ_ROWS__ },
  'project.new': { root: 'projects/rid-sydorukiv', files: [], profile: { paradigm: 'noun_bare' } },
  'profile.where': { places: [], archives: [], years: null },
  'archives.list': { archives: [{ code: 'DAHMO', label: 'ДАХмО' }] },
  'profile.show': { present: true, places: [{ name: 'Стара Сидорівка' }], archives: [], years: { from: 1800, to: 1850 } },
};
const asked = [];
const stubFetch = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/jobs/wait')) return new Promise(() => {});
  if (u.endsWith('/api/projects')) return { ok: true, status: 200, json: async () => PROJECTS };
  const name = u.split('/api/op/')[1] || '';
  if (name && Object.hasOwn(DATA, name)) {
    asked.push([name, JSON.parse((opts || {}).body || '{}')]);
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
nav.setSections({ hub_only: !'__PID__' });
const out = {};
const val = (id, v) => { document.getElementById(id).value = v; };
if ('__MODE__' === 'hub') {
  location.hash = '#home';
  await SCREENS.home(); await tick(120);
  out.firstHash = location.hash;
  localStorage.setItem('nysh.welcome.done', '1');
  location.hash = '#home';
  await SCREENS.home(); await tick(120);
  out.doneHash = location.hash; out.doneHome = view();
  localStorage.setItem('nysh.welcome.done', '');
  await SCREENS.welcome(); await tick(40);
  out.lang = view();
  out.welcomeOn = document.body.classList.contains('welcome-on');
  ACTIONS['wc.lang'](null, { dataset: { arg: 'en' } });
  out.langHref = location.href; out.langSaved = localStorage.getItem('nysh.lang');
  localStorage.setItem('nysh.lang', 'uk');
  location.search = '?step=project';
  await SCREENS.welcome(); await tick(40);
  out.project = view();
  await ACTIONS['wc.next'](); await tick(40);
  out.needBox = document.getElementById('wc-box').innerHTML || '';
  out.askedBefore = asked.filter((a) => a[0] === 'project.new').length;
  val('wc-title', 'Рід Сидоруків'); val('wc-surname', 'Сидорук'); val('wc-variants', 'Сидорукъ, Sydoruk');
  await ACTIONS['wc.next'](); await tick(40);
  out.projectNew = (asked.find((a) => a[0] === 'project.new') || [])[1] || null;
  out.projectHref = location.href;
} else {
  out.step = location.search;
  location.search = '?p=rid-sydorukiv&step=project';
  await SCREENS.welcome(); await tick(40);
  out.made = view();
  await ACTIONS['wc.next'](); await tick(40);
  out.madeNew = asked.filter((a) => a[0] === 'project.new').length;
  out.madeStep = location.search;
  out.family = view();
  out.prefill = document.getElementById('wc-where').innerHTML || '';
  val('wh-y1', '1900'); val('wh-y2', '1800');
  await ACTIONS['wc.next'](); await tick(40);
  out.badYears = document.getElementById('wc-box').innerHTML || '';
  out.badAsked = asked.filter((a) => a[0] === 'profile.where').length;
  const inp = (k, v) => ({ dataset: { k }, value: v });
  const rowOf = (...inputs) => ({ querySelectorAll: () => inputs });
  document.getElementById('wh-places').querySelectorAll = () => [
    rowOf(inp('name', 'Сидорівка'), inp('also', 'Сидоровка, Sydorówka'), inp('uezd', 'Летичівський')),
    rowOf(inp('name', ''), inp('also', ''), inp('uezd', ''))];
  document.getElementById('wh-archives').querySelectorAll = () => [rowOf(inp('repo', 'дахмо'), inp('fond', '315'))];
  val('wh-y1', '1790'); val('wh-y2', '1920');
  await ACTIONS['wc.next'](); await tick(40);
  out.where = (asked.find((a) => a[0] === 'profile.where') || [])[1] || null;
  out.afterWhere = location.search;
  out.cases = view();
  await ACTIONS['wc.door'](null, { dataset: { arg: 'later' } }); await tick(20);
  out.doneHref = location.href; out.done = localStorage.getItem('nysh.welcome.done');
  out.welcomeOff = !document.body.classList.contains('welcome-on');
}
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


def _run(tmp_path_factory, mode: str, search: str, pid: str, rows: list) -> dict:
    root = tmp_path_factory.mktemp("front-welcome")
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
    probe = (PROBE.replace("__SEARCH__", search).replace("__PID__", pid)
             .replace("__MODE__", mode).replace("__PROJ_ROWS__", json.dumps(rows, ensure_ascii=False)))
    (root / "_probe.mjs").write_text(probe, encoding="utf-8")
    res = subprocess.run(["node", "--input-type=module", "-e",
                          f"await import({json.dumps((root / '_probe.mjs').as_uri())})"],
                         capture_output=True, cwd=root, encoding="utf-8", errors="replace",
                         timeout=120)
    line = next((x for x in res.stdout.splitlines() if x.startswith("@@")), "")
    assert line, "фронт не виконався:\n" + (res.stderr or res.stdout)[:3000]
    return json.loads(line[2:])


@pytest.fixture(scope="module")
def hub(tmp_path_factory) -> dict:
    return _run(tmp_path_factory, "hub", "", "", [])


@pytest.fixture(scope="module")
def fam(tmp_path_factory) -> dict:
    rows = [{"id": "rid-sydorukiv", "name": "Рід Сидоруків", "kind": "family"}]
    return _run(tmp_path_factory, "family", "?p=rid-sydorukiv&step=family", "rid-sydorukiv", rows)


def test_an_empty_workshop_opens_the_introduction_once(hub) -> None:
    assert hub["firstHash"] == "welcome", "порожня Майстерня без позначки — знайомство"
    assert hub["doneHash"] == "#home", "позначка є — Огляд, а не знайомство вдруге"


def test_without_projects_the_overview_offers_the_first_project(hub) -> None:
    home = hub["doneHome"]
    assert "first-pj" in home and 'data-arg="newproject"' in home
    assert "/?step=lang#welcome" in home, "знайомство можна пройти й звідси"
    assert 'data-act="home.scans"' not in home, "двері справ без проєкту — не головне"


def test_language_step_reloads_on_the_theme_step(hub) -> None:
    assert hub["welcomeOn"], "шапка й меню на час знайомства сховані"
    assert 'data-act="wc.lang"' in hub["lang"]
    assert hub["langSaved"] == "en"
    assert "step=theme" in hub["langHref"] and hub["langHref"].endswith("#welcome")


def test_project_step_asks_for_a_name_then_creates_and_enters_the_project(hub) -> None:
    assert 'id="wc-title"' in hub["project"] and 'id="wc-surname"' in hub["project"]
    assert hub["askedBefore"] == 0 and hub["needBox"], "без назви й прізвища — не створює"
    pn = hub["projectNew"]
    assert pn and pn["title"] == "Рід Сидоруків" and pn["surname"] == "Сидорук"
    assert pn["variants"] == ["Сидорукъ", "Sydoruk"] and pn["kind"] == "family"
    assert re.fullmatch(r"[a-z0-9-]+", pn["name"]), pn["name"]
    assert f"p={pn['name']}" in hub["projectHref"] and "step=family" in hub["projectHref"]


def test_back_to_a_created_project_goes_on_instead_of_creating_again(fam) -> None:
    assert "уже заведено" in fam["made"] and "Рід Сидоруків" in fam["made"]
    assert 'id="wc-title"' not in fam["made"]
    assert fam["madeNew"] == 0 and "step=family" in fam["madeStep"]


def test_family_step_shows_what_is_already_written(fam) -> None:
    assert "Стара Сидорівка" in fam["prefill"] and 'value="1800"' in fam["prefill"]


def test_bad_years_are_said_in_the_window_language_and_not_sent(fam) -> None:
    assert fam["badAsked"] == 0
    assert "«від» не пізніше «до»" in fam["badYears"]


def test_family_step_writes_villages_years_archives(fam) -> None:
    assert 'id="wh-places"' in fam["family"] and 'id="wh-y1"' in fam["family"]
    w = fam["where"]
    assert w == {"places": [{"name": "Сидорівка", "also": "Сидоровка, Sydorówka", "uezd": "Летичівський"}],
                 "archives": [{"repo": "DAHMO", "fond": "315"}],
                 "years_from": 1790, "years_to": 1920}, w
    assert "step=cases" in fam["afterWhere"]
    assert 'data-act="wc.door"' in fam["cases"]


def test_finish_marks_the_introduction_and_opens_the_project(fam) -> None:
    assert fam["done"] == "1"
    assert "p=rid-sydorukiv" in fam["doneHref"] and fam["doneHref"].endswith("#home")
    assert "step=" not in fam["doneHref"]
    assert fam["welcomeOff"]
