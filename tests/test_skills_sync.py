"""🔄 Скіли після оновлення: перекладаються самі, але не всюди й не мовчки.

🔴 Вада, яку це закриває: пакет оновлювався, а скіли лишались від попередньої
версії — і людина працювала за старою карткою, не маючи як це помітити.
Застарілий скіл виглядає точно так само, як свіжий.

🔴 Три межі лишаються від правила «пакет не пише в конфіг агента мовчки», і всі
три тут стережуться: тільки наявні теки · правлене руками не чіпається ·
є вимикач.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka import skills as S

VER = "9.9.9"


@pytest.fixture
def dest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Тека агента в проєкті, куди скіли вже клали давньою версією."""
    monkeypatch.delenv(S.ENV_NO_SYNC, raising=False)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    d = tmp_path / ".claude" / "skills"
    S.install(d, version="0.0.1")
    return d


def _card(dest: Path) -> Path:
    return next(dest.glob("*/SKILL.md"))


def test_an_older_ledger_is_brought_up_to_date(dest) -> None:
    """🔴 Заради чого все: наступний запуск перекладає, і людина це бачить."""
    got = S.sync(VER)
    assert [str(d) for d, _ in got] == [str(dest)]
    assert json.loads((dest / S.LEDGER).read_text(encoding="utf-8"))["version"] == VER


def test_a_current_ledger_is_left_alone(dest) -> None:
    """Однакова версія — робити нема чого, і файлів не торкаємось."""
    S.sync(VER)
    before = _card(dest).stat().st_mtime_ns
    assert S.sync(VER) == []
    assert _card(dest).stat().st_mtime_ns == before


def test_a_hand_edited_skill_survives(dest) -> None:
    """🔴 Скіл — це текст, який дослідник дописує під свій матеріал.

    Сліпе оновлення знищувало б рівно ту роботу, заради якої скіли й заводять.
    """
    card = _card(dest)
    card.write_text("мій власний замір\n", encoding="utf-8")
    got = S.sync(VER)
    assert card.read_text(encoding="utf-8") == "мій власний замір\n"
    assert got[0][1].get("kept", 0) >= 1, "правлений файл мусить бути порахований"


def test_a_folder_nobody_chose_is_never_created(tmp_path, monkeypatch) -> None:
    """🔴 Тека, куди скіли не клали, нам не належить — нових не заводимо."""
    monkeypatch.delenv(S.ENV_NO_SYNC, raising=False)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    assert S.sync(VER) == []
    assert not (tmp_path / ".claude").exists()


def test_the_switch_turns_it_off(dest, monkeypatch) -> None:
    """Вимикач потрібен і людині, і тестам: інакше прогін пише в чужу домівку."""
    monkeypatch.setenv(S.ENV_NO_SYNC, "1")
    assert S.sync(VER) == []


def test_the_tally_says_what_happened(dest) -> None:
    """Мовчки не буває: викликач мусить мати що надрукувати."""
    tally = S.sync(VER)[0][1]
    assert sum(tally.values()) > 0
    assert set(tally) <= {"new", "updated", "same", "kept"}
