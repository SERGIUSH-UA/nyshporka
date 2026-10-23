"""🖼 Значки проєктів: мальований кружок замість літери в перемикачі.

Перелік значків живе в трьох місцях — `core/projects.py::ICONS`, консоль
(`core/projects.js`) і самі картинки `ui/static/img/pj-*.webp`, — плюс назва
кожного значка сімома мовами. Тест стереже, щоб вони не розійшлись: значок,
якого немає на диску, дав би в перемикачі порожній кружок, а без назви вибір
показував би ключ `pj.icon.mlyn`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _front import FRONT_DIR, SHARED_DIR
from test_front_boots import STUB
from test_projects import _hub, _project

from nyshporka import ops as O
from nyshporka.core import projects as P
from nyshporka.core import workspace as W

LANGS = ("uk", "en", "pl", "ro", "fr", "de", "ru")


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def test_icons_agree_across_python_console_files_and_languages() -> None:
    js = (FRONT_DIR / "core" / "projects.js").read_text(encoding="utf-8")
    body = re.search(r"export const ICONS = \[(.*?)\];", js, re.S)
    assert body, "перелік ICONS у core/projects.js не знайдено"
    assert tuple(re.findall(r"'([a-z]+)'", body.group(1))) == P.ICONS
    files = {p.stem.removeprefix("pj-") for p in (SHARED_DIR / "img").glob("pj-*.webp")}
    assert files == set(P.ICONS)
    for lang in LANGS:
        text = (FRONT_DIR / "core" / "strings" / f"{lang}.js").read_text(encoding="utf-8")
        missing = [k for k in P.ICONS if f"'pj.icon.{k}':" not in text]
        assert not missing, f"{lang}: без назви {missing}"


def test_icon_is_set_listed_cleared_and_checked(tmp_path: Path) -> None:
    hub = _hub(tmp_path, hub_only=True)
    W.use(W._build(hub, "test"))
    env = O.call("project.new", {"name": "rid-s", "color": "#8a5a2b", "icon": "mlyn"})
    assert env.ok, env.error
    rows = {r["id"]: r for r in O.call("project.list").data["projects"]}
    assert (rows["rid-s"]["icon"], rows["rid-s"]["color"]) == ("mlyn", "#8a5a2b")
    W.use(W._build(hub / "projects/rid-s", "test"))
    assert O.call("project.status").data["icon"] == "mlyn"
    W.use(W._build(hub, "test"))
    # Невідомий значок — відмова з переліком, а не порожній кружок у консолі.
    got = O.call("project.new", {"name": "rid-x", "icon": "dub"})
    assert not got.ok and "derevo" in got.error and not (hub / "projects/rid-x").exists()
    assert not O.call("project.style", {"name": "rid-s", "icon": "dub"}).ok
    # Зміна знака не чіпає значка; порожній значок — знімає.
    st = O.call("project.style", {"name": "rid-s", "glyph": "С"})
    assert st.ok and st.data["icon"] == "mlyn"
    st = O.call("project.style", {"name": "rid-s", "icon": ""})
    assert st.ok and st.data["icon"] == ""
    assert "icon" not in (hub / "projects/rid-s/nyshporka.toml").read_text(encoding="utf-8")


def test_a_hand_broken_icon_in_the_marker_is_ignored(tmp_path: Path) -> None:
    hub = _hub(tmp_path, hub_only=True)
    _project(hub, "rid-a", 'icon = "../../etc"\n')
    assert P.list_projects(hub)[0].icon == ""


PROBE = r"""
import './_stub.js';
const P = await import('./core/projects.js');
const out = {};
out.icon = P.projectBadge({ id: 'a', name: 'Рід А', color: '#aa3300', icon: 'mlyn' });
out.iconNoColor = P.projectBadge({ id: 'a', name: 'Рід А', icon: 'mlyn' });
out.letter = P.projectBadge({ id: 'b', name: 'Рід Б', color: '#0055aa', icon: 'nema' });
out.picker = P.iconPicker('zamok');
console.log('@@' + JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node немає — виконати фронт нічим")
    root = tmp_path_factory.mktemp("front-icons")
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


def test_badge_shows_the_icon_with_the_colour_as_a_rim(probe) -> None:
    assert '<img src="/ui/img/pj-mlyn.webp"' in probe["icon"]
    assert "pj-ring" in probe["icon"] and "--pj:#aa3300" in probe["icon"]
    assert "pj-ring" not in probe["iconNoColor"]
    # Невідомий значок — літера, а не порожня картинка.
    assert "<img" not in probe["letter"] and ">Р<" in probe["letter"]


def test_picker_offers_the_letter_and_every_icon(probe) -> None:
    pk = probe["picker"]
    assert pk.count('type="radio" name="icon"') == len(P.ICONS) + 1
    assert 'value="zamok" checked' in pk and 'value="" checked' not in pk
    assert 'title="Замок"' in pk
