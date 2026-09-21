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
def uvimknena(monkeypatch: Any) -> None:
    """Ворота фічі зняті — інакше обидва хвости мовчать за побудовою."""
    from nyshporka.share.cli import DEV_FLAG

    monkeypatch.setenv(DEV_FLAG, "1")


def test_lookup_movchyt_bez_vorit(space: Path, monkeypatch: Any, capsys: Any) -> None:
    """🔴 Поки пул не запущено, прогін про нього не знає.

    Це та сама межа, що ховає команду `share`: роздане один раз живе в
    чужих теках, і формат ще може змінитись.
    """
    from nyshporka.cli import _supriaha_lookup
    from nyshporka.share.cli import DEV_FLAG

    monkeypatch.delenv(DEV_FLAG, raising=False)

    def _ne_klykaty(*_: Any, **__: Any) -> None:
        raise AssertionError("без воріт фічі в пул не ходимо")

    monkeypatch.setattr("nyshporka.share.catalog.lookup", _ne_klykaty)
    _supriaha_lookup("DAHMO/315/8433", 3772)
    assert capsys.readouterr().out == ""


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
