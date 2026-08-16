"""🗺🏛 Довідники дійшли до продуктового застосунку — і не за рахунок агента.

Три речі, які тут закріплені, бо кожну легко зламати непомітно:

1. **Вкладки дійсно є** — операція, до якої не дійти жодним обличчям, це код,
   який ніхто не викличе (це стереже й `test_no_dead_ends`, тут — конкретніше).
2. **Стеля агентських tool'ів не зрушила.** Вона не технічна: далі модель
   перестає дочитувати описи й починає вгадувати. П'ять нових операцій підняли
   б перелік із 18 до 23, тож вони свідомо `agent=False`.
3. **Кожна відповідь довідника несе покриття.** Без нього «нічого не знайдено»
   не відрізнити від «ніде не шукали» — а це різниця між «перевірено» і
   «напрям закрито наосліп».
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

OPS: Any = None

_PLACES = [("c1", "church", "православна церква", "М'ястківка", "Мястковка",
            "Брацлавського пов.", "Ольгопольського пов.", "Городківка",
            "Благовіщення")]
_CASES = [("224", "1", "864", 1752, 1777, "метрична книга", "Благовіщення", "c1")]


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір + каталог із одним паком газетира."""
    global OPS
    from nyshporka.core import workspace as W

    ws = tmp_path / "ws"
    (ws / "data" / "derived").mkdir(parents=True)
    W.use(W.Workspace(root=ws, name="тест", origin="test"))

    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))

    src = tmp_path / "src"
    src.mkdir()
    p_tsv, c_tsv = src / "p.tsv", src / "c.tsv"
    with p_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["card", "section", "institution", "village_uk", "village_ru",
                    "hist_place", "uezd_gub", "modern_place", "church",
                    "eparchy", "parishes", "note"])
        for r in _PLACES:
            w.writerow([*r, "", "", ""])
    with c_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["fond", "opys", "spr", "year_from", "year_to", "doc_type",
                    "case_church", "card"])
        for r in _CASES:
            w.writerow(list(r))

    from nyshporka import ops as _O
    from nyshporka.catalog import build as B
    from nyshporka.catalog import store as S

    B.build_geog(p_tsv, c_tsv, cat / "geog-test-2026.08.sqlite",
                 pack_id="geog-test-2026.08", taken="2026-08-16")
    S.invalidate()
    OPS = _O
    yield tmp_path
    W.reset()
    S.invalidate()


# ── стеля агентського переліку ───────────────────────────────────────────────

def test_reference_ops_do_not_eat_the_agent_budget():
    """🔴 Довідники додано в браузер, НЕ забравши місця в агента.

    Стеля 18 — рішення, а не технічна межа. Якщо колись ці операції захочуть
    зробити агентськими, доведеться свідомо посунути щось інше, і цей тест
    змусить це помітити.
    """
    from nyshporka import ops as _O

    names = {o.name for o in _O.REGISTRY.all()}
    reference = {"geog.find", "geog.card", "fond.list", "fond.rows",
                 "catalog.packs"}
    assert reference <= names, "операції довідників зникли з реєстру"

    agent = {o.name for o in _O.REGISTRY.for_agent()}
    assert not (reference & agent), (
        "довідники потрапили в агентський перелік — перевірте стелю TOOL_LIMIT "
        "і те, кого при цьому посунули"
    )


def test_reference_ops_are_visible_in_the_gui():
    """Вони мусять бути в переліку екранів — інакше вкладок просто немає.

    Довідники живуть у секції «Матеріали», тож перевіряємо їх саме в наборі
    ввімкнених секцій: у профілі, де матеріали вимкнено, вкладок і не має бути.
    """
    from nyshporka import ops as _O
    from nyshporka.core import sections as S

    gui = {o.name for o in _O.for_sections(S.preset_sections("researcher"))}
    for name in ("geog.find", "geog.card", "fond.list", "fond.rows",
                 "catalog.packs"):
        assert name in gui, name
    off = {o.name for o in _O.for_sections(S.resolve(explicit=["core"]))}
    assert "geog.find" not in off, (
        "довідник лишився доступним із вимкненою секцією «Матеріали»")


def test_tabs_are_wired_in_the_page_and_the_script():
    """Кнопка, екран і дія — три місця, і зникнути може будь-яке.

    🔴 Кнопки більше не зашиті в розмітку: шапку будує `renderNav` із
    `/api/sections`. Тому перевіряємо не HTML, а те, що екран оголошений у
    порядку навігації, має підпис і має секцію — розрив у будь-якій із трьох
    ланок так само лишає людину без входу.
    """
    static = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "daemon" / "static"
    js = (static / "app.js").read_text(encoding="utf-8")

    from nyshporka.core import sections as S

    for arg in ("geog", "fonds"):
        assert f"'{arg}'" in js.split("const NAV_ORDER")[1].split("]")[0], (
            f"екран «{arg}» не потрапив у NAV_ORDER — кнопки не буде")
        assert f"{arg}:" in js.split("const NAV_LABEL")[1].split("};")[0], (
            f"екран «{arg}» без підпису в NAV_LABEL")
        assert arg in S.SCREENS, f"екран «{arg}» не належить жодній секції"
        assert f"SCREENS.{arg} " in js or f"SCREENS.{arg}=" in js, (
            f"немає екрана «{arg}»")
    for act in ("'geog.find'", "'geog.card'", "'fond.rows'"):
        assert act in js, f"немає дії {act}"
    assert "renderCoverage" in js, "покриття нема чим намалювати"


# ── покриття у відповідях ────────────────────────────────────────────────────

def test_find_carries_coverage_even_when_it_found_nothing(space):
    """🔴 Головне: порожня відповідь приходить РАЗОМ зі знаменником."""
    env = OPS.call("geog.find", {"q": "Такогоселанемає"})
    assert env.ok and env.data["shown"] == 0
    assert env.coverage, "нуль без покриття читається як «ніде не шукали»"
    assert env.coverage[0].taken == "2026-08-16"
    # і те саме — текстом, бо саме текст читає агент
    assert "шукали в" in env.as_agent_text()


def test_find_refuses_when_there_is_nowhere_to_search(tmp_path, monkeypatch):
    """Каталогу немає → відмова з підказкою, а не порожній список."""
    from nyshporka import ops as _O
    from nyshporka.catalog import store as S

    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path / "порожньо"))
    S.invalidate()
    env = _O.call("geog.find", {"q": "М'ястківка"})
    assert not env.ok
    assert "catalog install" in env.error
    S.invalidate()


def test_card_shows_cases_and_confusers(space):
    env = OPS.call("geog.card", {"card": "М'ястківка"})
    assert env.ok
    place = env.data["place"]
    assert place["village_uk"] == "М'ястківка"
    assert [c["shifra"] for c in place["cases"]] == ["224-1-864"]
    assert "confusers" in place
    assert env.coverage


def test_fond_rows_keep_the_denominator(space, monkeypatch):
    """«5 справ» без «із 2944» — інша відповідь, а не коротша."""
    from nyshporka.fonds import registry as R

    rows = [{"opys": "1", "spr_int": str(i), "spr_letter": "", "spr": str(i),
             "shifra": f"999-1-{i}", "title": "Метрична книга Ольгопольского уезда",
             "on_disk": "", "commons_url": None, "mirror_url": None,
             "truncated_mirror": None, "num_src": "read", "page_quality": "ok",
             "title_alt": None, "surnames": "", "spr_letter_x": "",
             "year_from": "1800", "year_to": "1800", "schema": "merged_v2"}
            for i in range(1, 21)]
    fond = {"id": "test_999", "repo": "TEST", "repo_label": "Тест", "fond": "999",
            "label": "Тест ф.999", "path": "", "mtime": 1.0,
            "has_coverage": False, "has_conflicts": False, "has_alfavitka": False}
    monkeypatch.setattr(R, "discover_fonds", lambda: [fond])
    monkeypatch.setattr(R, "load_rows", lambda fid: rows)
    monkeypatch.setattr(R, "conflicts_index", lambda fid: {})
    monkeypatch.setattr(R, "live_on_disk", lambda repo, f: {})

    env = OPS.call("fond.rows", {"fond": "test_999", "limit": 5})
    assert env.ok
    assert env.data["shown"] == 5
    assert env.data["matched"] == 20
    assert env.data["summary"]["rows"] == 20, (
        "знаменник мусить рахуватись по ВСЬОМУ фонду, а не по сторінці"
    )


def test_unknown_fond_lists_the_known_ones(space):
    env = OPS.call("fond.rows", {"fond": "немає_такого"})
    assert not env.ok and "немає серед реєстрів опису" in env.error
