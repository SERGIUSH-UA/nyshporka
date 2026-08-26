"""🏛 Одна дія замість вибору джерела: `registry.build`.

🔴 Файл існує через розрив, який дослідник знайшов руками. Збирання й зведення
були двома кроками: обхід клав свій файл у `registry/<фонд>/`, а екран описів
читає інший файл — зведений. Тобто «Зібрати опис» закінчувалось так: робота
«готово», 229 справ у файлі — і екран, який каже «реєстру опису ще не збирали».
Людина зробила все правильно й дістала порожнечу.

Друга половина того самого: збирача доводилось обирати зі списку, не маючи чим
відповісти на питання «а котрий із них знає мій фонд». Відповідь знає план.
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.core import workspace as W


class _Збирач:
    """Збирач, який каже про себе рівно те, що йому наказали."""

    caps = frozenset({"plan", "collect"})

    def __init__(self, cid: str, *, ready: bool, rows: int = 0,
                 why: str = "") -> None:
        self.id = cid
        self.label = cid.upper()
        self.filename = f"{cid}.tsv"
        self.source_id = cid
        self._ready, self._rows, self._why = ready, rows, why
        self.collected = 0

    def plan(self, _target: Any) -> Any:
        ready, why = self._ready, self._why

        class _P:
            # `ready`/`why` полями, а не лише в `as_dict()`: `registry.collect`
            # читає їх напряму (`ops_catalog.py:491`), а `registry.plan` —
            # через словник. Заглушка мусить витримати обидва звертання.
            def __init__(self) -> None:
                self.ready, self.why = ready, why

            def as_dict(self) -> dict[str, Any]:
                return {"collector": "x", "ready": ready, "why": why,
                        "opys": [], "requests": 1, "eta_sec": 1, "needs": {}}
        return _P()

    def collect(self, _target: Any, *, dest: Any, **_kw: Any) -> Any:
        self.collected += 1
        rows, out = self._rows, dest / self.filename

        class _R:
            blind: tuple[Any, ...] = ()
            kept = 0

            def as_dict(self) -> dict[str, Any]:
                return {"collector": "x", "out": str(out), "rows": rows,
                        "kept": 0, "opys_seen": [], "opys_collected": [],
                        "quality": {}, "blind": [], "notes": []}
        return _R()


@pytest.fixture
def space(tmp_path, monkeypatch):
    root = tmp_path / "простір"
    (root / "data" / "raw").mkdir(parents=True)
    (root / W.MARKER).write_text('[workspace]\nschema = 1\nname = "тест"\n',
                                 encoding="utf-8")
    monkeypatch.setenv(W.ENV_WORKSPACE, str(root))
    W.reset()
    yield root
    W.reset()


def _stub(monkeypatch, *collectors: _Збирач, merged: int = 0) -> dict[str, Any]:
    """Підмінити реєстр збирачів і зведення. Повертає лічильник злиттів."""
    from nyshporka import ops_catalog as OC
    from nyshporka.core.envelope import ok
    from nyshporka.fonds import collect as C

    class _Reg:
        broken: tuple[Any, ...] = ()

        def all(self) -> list[_Збирач]:
            return list(collectors)

        def get(self, cid: str) -> _Збирач | None:
            return next((c for c in collectors if c.id == cid), None)

    monkeypatch.setattr(C, "load", lambda *_a, **_k: _Reg())
    seen = {"merges": 0}

    def _merge(_a: Any) -> Any:
        seen["merges"] += 1
        return ok({"rows": merged, "sources": [], "conflicts": 0})

    monkeypatch.setattr(OC, "registry_merge", _merge)
    return seen


def test_it_does_not_ask_which_site_knows_this_fond(space, monkeypatch) -> None:
    """🔴 Збирач — наша механіка, а не рішення дослідника.

    Обидва готові джерела мусять бути обійдені без жодного вибору з боку
    людини: питання «котрий із них знає цей фонд» має відповідь у плані.
    """
    a = _Збирач("альфа", ready=True, rows=100)
    b = _Збирач("бета", ready=True, rows=29)
    _stub(monkeypatch, a, b, merged=129)

    env = O.call("registry.build", {"repo": "ДАХмО", "fond": "230"})

    assert env.ok, env.error
    assert (a.collected, b.collected) == (1, 1), "обійдено не всі джерела"
    assert {x["collector"] for x in env.data["took"]} == {"альфа", "бета"}


def test_a_source_that_cannot_does_not_sink_the_rest(space, monkeypatch) -> None:
    """🔴 Неготове джерело пропускається з поясненням, а не валить дію.

    Причини нормальні й різні: archium адресує фонд власним внутрішнім
    номером, Commons знає лише те, що хтось виклав. Але мовчати про пропуск
    не можна — інакше реєстр виглядав би повнішим, ніж він є.
    """
    good = _Збирач("добрий", ready=True, rows=42)
    bad = _Збирач("кривий", ready=False,
                  why="сайт адресує фонд власним номером")
    _stub(monkeypatch, good, bad, merged=42)

    env = O.call("registry.build", {"repo": "ДАХмО", "fond": "230"})

    assert env.ok, env.error
    assert good.collected == 1 and bad.collected == 0
    assert [x["collector"] for x in env.data["skipped"]] == ["кривий"]
    said = " ".join(w.text for w in env.warnings)
    assert "кривий" in said and "власним номером" in said, (
        f"пропуск не пояснено: {said}")


def test_the_registry_is_merged_once_not_per_source(space, monkeypatch) -> None:
    """⚠ Зведення — один раз, після всіх обходів.

    Інакше той самий реєстр перезводився б стільки разів, скільки джерел, і
    кожне зведення читало б неповний набір файлів.
    """
    seen = _stub(monkeypatch,
                 _Збирач("а", ready=True, rows=1),
                 _Збирач("б", ready=True, rows=2),
                 _Збирач("в", ready=True, rows=3), merged=6)

    env = O.call("registry.build", {"repo": "ДАХмО", "fond": "230"})

    assert env.ok, env.error
    assert seen["merges"] == 1, f"зведень: {seen['merges']}"


def test_nothing_collected_is_said_out_loud(space, monkeypatch) -> None:
    """🔴 Коли не змогло жодне джерело — реєстр лишився таким, як був.

    Це не помилка виклику, але й не успіх: мовчазне «готово» тут читалось би
    як «опис зібрано».
    """
    seen = _stub(monkeypatch,
                 _Збирач("а", ready=False, why="немає fond_id"),
                 _Збирач("б", ready=False, why="фонду там немає"))

    env = O.call("registry.build", {"repo": "ДАХмО", "fond": "230"})

    assert env.ok, env.error
    assert env.data["took"] == []
    assert seen["merges"] == 0, "зводити нічого, а зведення відбулось"
    codes = {w.code for w in env.warnings}
    assert "nothing_collected" in codes, codes
