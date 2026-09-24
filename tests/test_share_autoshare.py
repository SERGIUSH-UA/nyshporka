"""Lookup перед прогоном і автовіддача після нього.

Два хвости команди `read`, і обидва мусять мовчати, коли їх не просили, і
ніколи не псувати результат прогону.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.share import profile as P


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


@pytest.fixture
def uvimknena(space: Path, monkeypatch: Any) -> None:
    """Людина ввімкнула питання пулу й під'єднала Нишпорку."""
    from nyshporka.share.upload import ENV_NAME

    prof = P.load()
    prof.lookup = True
    P.save(prof)
    monkeypatch.setenv(ENV_NAME, "kliuch")


def test_lookup_typovo_vymknenyi(space: Path, monkeypatch: Any, capsys: Any) -> None:
    """🔴 Типово пул перед прогоном НЕ питається.

    Запит несе шифру справи й ключ — сервер бачив би, що читає людина.
    `PRIVACY.md` обіцяє, що фонових запитів немає, доки їх не ввімкнули.
    """
    from nyshporka.cli import _supriaha_lookup
    from nyshporka.share.upload import ENV_NAME

    monkeypatch.setenv(ENV_NAME, "kliuch")
    assert P.load().lookup is False

    def _ne_klykaty(*_: Any, **__: Any) -> None:
        raise AssertionError("типово в пул не ходимо")

    monkeypatch.setattr("nyshporka.share.catalog.lookup", _ne_klykaty)
    _supriaha_lookup("DAHMO/315/8433", 3772)
    assert capsys.readouterr().out == ""


def test_lookup_bez_kliucha_ne_pytaie(space: Path, monkeypatch: Any, capsys: Any) -> None:
    """Без ключа пул відповів би 401 — запит без відповіді лише витік.

    Замість нього — підказка, як під'єднатись.
    """
    from nyshporka.cli import _supriaha_lookup
    from nyshporka.share.upload import ENV_NAME

    prof = P.load()
    prof.lookup = True
    P.save(prof)
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.setattr("nyshporka.share.upload.token", lambda: "")

    def _ne_klykaty(*_: Any, **__: Any) -> None:
        raise AssertionError("без ключа в пул не ходимо")

    monkeypatch.setattr("nyshporka.share.catalog.lookup", _ne_klykaty)
    _supriaha_lookup("DAHMO/315/8433", 3772)
    assert "share login" in capsys.readouterr().out


def test_lookup_movchyt_koly_vymknuto_v_profili(
    space: Path, uvimknena: None, monkeypatch: Any, capsys: Any
) -> None:
    """Хто вимкнув питання в профілі, того не питають."""
    from nyshporka.cli import _supriaha_lookup

    prof = P.load()
    prof.lookup = False
    P.save(prof)

    def _ne_klykaty(*_: Any, **__: Any) -> None:
        raise AssertionError("профіль сказав не питати")

    monkeypatch.setattr("nyshporka.share.catalog.lookup", _ne_klykaty)
    _supriaha_lookup("DAHMO/315/8433", 3772)
    assert capsys.readouterr().out == ""


def test_lookup_ne_valyt_prohin_koly_pul_lezhyt(
    space: Path, uvimknena: None, monkeypatch: Any, capsys: Any
) -> None:
    """🔴 Прогін на ніч не має зриватись через чужий сервер.

    Тихий фолбек тут не зручність, а умова: людина читає сама, як читала
    досі.
    """
    from nyshporka.cli import _supriaha_lookup

    def _vybukh(*_: Any, **__: Any) -> None:
        raise RuntimeError("пул недосяжний")

    monkeypatch.setattr("nyshporka.share.catalog.lookup", _vybukh)
    _supriaha_lookup("DAHMO/315/8433", 3772)     # не кидає
    assert capsys.readouterr().out == ""


def test_lookup_drukuie_znaydene(
    space: Path, uvimknena: None, monkeypatch: Any, capsys: Any
) -> None:
    """Знайшлось — один рядок і підказка, а не питання.

    Рішення лишається за людиною: питання посеред довгої команди — це те
    саме, від чого відмовились у режимах згоди.
    """
    from nyshporka.cli import _supriaha_lookup

    monkeypatch.setattr(
        "nyshporka.share.catalog.lookup",
        lambda *a, **k: {"found": True, "pages": 412, "models": ["pysar-v3"],
                         "license": "CC0-1.0", "status": "nove"})
    _supriaha_lookup("DAHMO/315/8433", 3772)
    out = capsys.readouterr().out
    assert "412" in out
    assert "pysar-v3" in out
    assert "не перевірено" in out
    assert "share pull" in out
    porada = next(ln for ln in out.splitlines() if "share pull" in ln)
    assert "«" not in porada, "порада без лапок-ялинок: shell передав би їх у запит"


def test_lookup_movchyt_na_promakhu(
    space: Path, uvimknena: None, monkeypatch: Any, capsys: Any
) -> None:
    """Не знайшлось — жодного рядка: людина й так зараз читатиме."""
    from nyshporka.cli import _supriaha_lookup

    monkeypatch.setattr("nyshporka.share.catalog.lookup",
                        lambda *a, **k: {"found": False})
    _supriaha_lookup("DAHMO/315/8433", 3772)
    assert capsys.readouterr().out == ""


def test_autoshare_movchyt_u_rezhymi_pytaty(space: Path, uvimknena: None) -> None:
    """🔴 Типовий режим нічого не віддає сам."""
    from nyshporka import ops as O

    env = O.call("share.autoshare", {"case": "DAHMO/315/8433", "complete": True})
    assert (env.data or {}).get("skipped")
    assert (env.data or {}).get("consent") == P.PYTATY


def test_autoshare_ne_pakuie_chastkovyi(space: Path, uvimknena: None) -> None:
    """Частковий прогін ворота відкинули б за знаменником.

    Успішне читання закінчилось би помилкою пакування — тобто ціна
    автоматизму лягла б на того, хто нічого не просив.
    """
    from nyshporka import ops as O

    prof = P.load()
    prof.consent = P.ZAVZHDY
    P.save(prof)

    env = O.call("share.autoshare", {"case": "DAHMO/315/8433", "complete": False})
    assert "руками" in str((env.data or {}).get("skipped"))


def test_autoshare_bez_shyfry_movchyt(space: Path, uvimknena: None) -> None:
    from nyshporka import ops as O

    prof = P.load()
    prof.consent = P.ZAVZHDY
    P.save(prof)

    env = O.call("share.autoshare", {"case": "", "complete": True})
    assert (env.data or {}).get("skipped")


def test_demon_klyche_tu_samu_operatsiiu(space: Path, uvimknena: None) -> None:
    """🔴 Демон і термінал — одна операція, а не дві гілки з тими ж умовами.

    Режим «завжди» без цього мовчки не працював би саме в тих, хто
    користується застосунком, а не терміналом, тобто в більшості. Помітити
    таку відмову нічим: прогони йдуть, пакети не їдуть, помилки немає.
    """
    import asyncio

    from nyshporka.daemon import workers as W

    prof = P.load()
    prof.consent = P.ZAVZHDY
    P.save(prof)

    got = asyncio.run(W._autoshare("DAHMO/315/8433"))
    # Пакування впаде — прогону з такою шифрою немає, — і це мусить лишитись
    # записом у результаті завдання, а не винятком із воркера.
    assert got is not None
    assert got["packed"] is False
    assert [w["code"] for w in got["warnings"]] == ["pack_failed"], (
        "невдача мусить доїхати до того, хто дивиться на завдання"
    )
    assert "error" not in got, "це відповідь операції, а не перехоплений виняток"


def test_demon_movchyt_u_rezhymi_pytaty(space: Path, uvimknena: None) -> None:
    """Типовий режим нічого не віддає й у демоні теж."""
    import asyncio

    from nyshporka.daemon import workers as W

    assert asyncio.run(W._autoshare("DAHMO/315/8433")) is None


def test_autoshare_ne_valyt_prohin(space: Path, uvimknena: None, capsys: Any) -> None:
    """🔴 Хвіст успішного прогону не робить із нього невдалий.

    Пакування впаде — бо прогону з такою шифрою немає, — і це має лишитись
    попередженням, а не винятком назовні.
    """
    from nyshporka.cli import _supriaha_autoshare

    prof = P.load()
    prof.consent = P.ZAVZHDY
    P.save(prof)

    _supriaha_autoshare("DAHMO/315/8433")      # не кидає
    assert "⚠" in capsys.readouterr().out
