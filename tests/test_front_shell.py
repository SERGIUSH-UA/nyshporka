"""🧭 Каркас консолі в Node: бічне меню, заголовок сторінки, зміна контексту.

Майстерня з двома вигаданими проєктами — `sydoruk` (вкладка) і `kovalchuk`.

🔴 Три питання людини (правила інтерфейсу, 22.10.2026): де я, що тут головне,
що станеться після дії. Каркас відповідає на перше — назвою роду в меню й
заголовку, міткою шару і тим, що зміна роду не викидає з екрана.
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
globalThis.location.search = '?p=sydoruk';
document.body.dataset.token = 'tok';
const stubFetch = globalThis.fetch;
const PROJECTS = { projects: [
  { id: 'sydoruk', name: 'Рід Сидоруків', kind: 'family', color: '#aa3300', glyph: 'С' },
  { id: 'kovalchuk', name: 'Рід Ковальчуків', kind: 'family', color: '#0055aa', glyph: 'К' }],
  current: 'sydoruk', default: null, hub_only: true, hub_id: '_hub' };
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/jobs/wait')) return new Promise(() => {});
  // Перелік проєктів приходить ПІСЛЯ першого показу екрана, як на великому
  // просторі: заголовок мусить дописати назву роду, коли він доїде.
  if (u.endsWith('/api/projects')) {
    await new Promise((r) => setTimeout(r, 1500));
    return { ok: true, status: 200, json: async () => PROJECTS };
  }
  return stubFetch(url, opts);
};
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const { ACTIONS } = await import('./core/registry.js');
await import('./app.js');
await tick(150);
const nav = await import('./core/nav.js');
nav.setSections({ nav: [
    { id: 'project', label: 'Рід', block: 'own', fold: false, screens: ['home', 'canon'] },
    { id: 'hub', label: 'Майстерня', block: 'hub', fold: false, screens: ['home'] },
    { id: 'material', label: 'Матеріали', block: 'shared', fold: true, screens: ['library', 'cases'] },
    { id: 'reading', label: 'Читання', block: 'shared', fold: true, screens: ['read', 'queue'] }],
  blocks: ['own', 'hub', 'shared', 'service'],
  layers: { library: 'mixed', canon: 'own', read: 'shared', home: 'context' },
  project_screens: ['canon'], screen_action: { library: 'newcase' }, hub_only: false });
const out = {};

// Бібліотека сама чекає переліку проєктів: заголовок знімаємо, не чекаючи екрана.
const shown = nav.show('library');
await tick(20);
out.headEarly = document.getElementById('phead').innerHTML;
await shown;
await tick(100);
out.side = document.getElementById('side').innerHTML;
out.head = document.getElementById('phead').innerHTML;

// Зміна роду на тому самому екрані: адреса веде в той самий екран.
const before = location.href;
ACTIONS['project.go'](null, { dataset: { arg: 'sydoruk' } });
out.sameKept = location.href === before;
ACTIONS['project.go'](null, { dataset: { arg: 'kovalchuk' } });
out.toOther = String(location.href);
// Екран роду → сама Майстерня: на її Огляд, а не на вибір проєкту.
await nav.show('canon');
ACTIONS['project.go'](null, { dataset: { arg: '_hub' } });
out.toHubFromCanon = String(location.href);
await nav.show('read');
ACTIONS['project.go'](null, { dataset: { arg: '_hub' } });
out.toHubFromRead = String(location.href);

// Телефон: ☰ висуває меню, перехід його ховає.
ACTIONS['side.toggle']();
out.openAfterToggle = document.body.classList.contains('side-open');
await nav.show('queue');
out.openAfterNav = document.body.classList.contains('side-open');
// Група: підпис веде на перший екран, стрілка розкриває без переходу.
ACTIONS['side.fold'](null, { dataset: { arg: 'material' } });
out.sideFolded = document.getElementById('side').innerHTML;
// Невідомий екран в адресі — Огляд, а не заголовок із сирим хешем.
await nav.show('nosuchscreen');
out.unknownHead = document.getElementById('phead').innerHTML;
// Екран роду в Майстерні — вибір проєкту без мітки «належить «Рід»».
nav.setSections({ hub_only: true });
await nav.show('canon');
out.hubCanonHead = document.getElementById('phead').innerHTML;
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("front-shell")
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
    (root / "_probe.mjs").write_text(PROBE, encoding="utf-8")
    res = subprocess.run(["node", "--input-type=module", "-e",
                          f"await import({json.dumps((root / '_probe.mjs').as_uri())})"],
                         capture_output=True, cwd=root, encoding="utf-8", errors="replace",
                         timeout=120)
    line = next((x for x in res.stdout.splitlines() if x.startswith("@@")), "")
    assert line, "фронт не виконався:\n" + (res.stderr or res.stdout)[:3000]
    return json.loads(line[2:])


def test_project_block_and_head_name_the_family(probe) -> None:
    """Блок меню й заголовок називають рід словами, а не лише кольором."""
    assert '<h4>Рід Сидоруків</h4>' in probe["side"]
    head = probe["head"]
    assert 'data-arg="home">Рід Сидоруків</button>' in head, "крихти починаються з роду"
    assert "<h1>Бібліотека справ</h1>" in head
    assert "зріз для «Рід Сидоруків»" in head
    # Перелік доїхав після першого показу — заголовок дописав назву.
    assert "Рід Сидоруків" not in probe["headEarly"]


def test_switching_family_keeps_the_screen(probe) -> None:
    """Бібліотека в роді X → Бібліотека в роді Y; той самий рід — нікуди."""
    assert probe["sameKept"]
    assert probe["toOther"].endswith("?p=kovalchuk#library")


def test_family_screen_to_the_hub_lands_on_the_hub_overview(probe) -> None:
    assert probe["toHubFromCanon"].endswith("?p=_hub#home")
    assert probe["toHubFromRead"].endswith("?p=_hub#read"), "спільний екран лишається"


def test_phone_menu_slides_out_and_hides_on_navigation(probe) -> None:
    assert probe["openAfterToggle"] is True
    assert probe["openAfterNav"] is False


def test_group_label_leads_to_its_first_screen_and_arrow_only_unfolds(probe) -> None:
    side = probe["sideFolded"]
    assert '<div class="sg-h"><button data-act="nav" data-arg="library">Матеріали</button>' in side
    assert 'data-act="side.fold" data-arg="material" aria-expanded="true"' in side


def test_unknown_screen_falls_back_to_the_overview(probe) -> None:
    head = probe["unknownHead"]
    assert "nosuchscreen" not in head and "<h1>Рід Сидоруків</h1>" in head


def test_family_screen_in_the_hub_has_no_owner_tag(probe) -> None:
    head = probe["hubCanonHead"]
    assert "<h1>Канон</h1>" in head and "layer-own" not in head
