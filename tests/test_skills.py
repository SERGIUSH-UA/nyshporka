"""Постачання скілів: із пакета в теку, яку читає агент.

🔴 Головне, що тут перевіряється, — НЕ «файл скопіювався», а що інструмент не
затирає роботу дослідника. Скіл заводять саме для того, щоб дописувати в нього
свої заміри й свої пастки; установлення, яке мовчки їх зносить, коштувало б
рівно тієї роботи, заради якої скіли й потрібні.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka import skills as S

CARD = """---
name: probe
description: Зразок для перевірки постачання.
---

# Проба
"""


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Підкладений «пакет» із двома скілами, один — з довідником."""
    root = tmp_path / "pack"
    (root / "probe").mkdir(parents=True)
    (root / "probe" / "SKILL.md").write_text(CARD, encoding="utf-8")
    (root / "other" / "references").mkdir(parents=True)
    (root / "other" / "SKILL.md").write_text(
        CARD.replace("probe", "other"), encoding="utf-8")
    (root / "other" / "references" / "TABLE.md").write_text("довідник\n",
                                                            encoding="utf-8")
    monkeypatch.setattr(S, "_roots", lambda: [root])
    return root


def test_available_finds_skills_and_their_references(pack: Path) -> None:
    got = {s.name: s for s in S.available()}
    assert set(got) == {"other", "probe"}
    assert got["probe"].title == "Зразок для перевірки постачання."
    assert len(got["other"].files()) == 2, "довідник поруч теж належить скілу"


def test_a_directory_without_a_card_is_not_a_skill(pack: Path) -> None:
    """Тека без `SKILL.md` — не скіл, і мовчки напівскілом не стає."""
    (pack / "junk").mkdir()
    (pack / "junk" / "notes.md").write_text("щось", encoding="utf-8")
    assert "junk" not in {s.name for s in S.available()}


def test_install_then_reinstall_changes_nothing(pack: Path, tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    first = S.install(dest, version="1.0")
    assert {o.verdict for o in first} == {"new"}
    assert (dest / "other" / "references" / "TABLE.md").is_file()

    again = S.install(dest, version="1.0")
    assert {o.verdict for o in again} == {"same"}


def test_hand_edited_file_survives(pack: Path, tmp_path: Path) -> None:
    """Дописане дослідником лишається — і про це сказано вголос.

    🔴 Мовчазне збереження було б не краще за мовчазне затирання: людина мала б
    вважати, що поставила свіжу версію, а насправді читає стару.
    """
    dest = tmp_path / "dest"
    S.install(dest, version="1.0")
    card = dest / "probe" / "SKILL.md"
    card.write_text(card.read_text(encoding="utf-8") + "\nмій розділ\n",
                    encoding="utf-8")

    out = {o.rel: o.verdict for o in S.install(dest, version="1.1")}
    assert out["probe/SKILL.md"] == "kept"
    assert "мій розділ" in card.read_text(encoding="utf-8")

    forced = {o.rel: o.verdict for o in S.install(dest, version="1.1", force=True)}
    assert forced["probe/SKILL.md"] == "updated"
    assert "мій розділ" not in card.read_text(encoding="utf-8")


def test_stale_copy_is_updated_but_edited_one_is_not(pack: Path,
                                                     tmp_path: Path) -> None:
    """Дві причини розбіжності розрізняються, і саме в цьому сенс обліку.

    Файл, який змінився В ПАКЕТІ, оновлюється; файл, який змінив КОРИСТУВАЧ,
    лишається. Без sha256 в обліку обидва виглядали б однаково.
    """
    dest = tmp_path / "dest"
    S.install(dest, version="1.0")

    (pack / "probe" / "SKILL.md").write_text(CARD + "\nнове в пакеті\n",
                                             encoding="utf-8")
    out = {o.rel: o.verdict for o in S.install(dest, version="1.1")}
    assert out["probe/SKILL.md"] == "updated"
    assert "нове в пакеті" in (dest / "probe" / "SKILL.md").read_text(encoding="utf-8")


def test_ledger_does_not_claim_what_it_did_not_write(pack: Path,
                                                     tmp_path: Path) -> None:
    """Облік не записує чуже своїм — інакше наступний прогін його затер би."""
    dest = tmp_path / "dest"
    S.install(dest, version="1.0")
    card = dest / "probe" / "SKILL.md"
    card.write_text("цілком своє\n", encoding="utf-8")
    S.install(dest, version="1.1")

    files = json.loads((dest / S.LEDGER).read_text(encoding="utf-8"))["files"]
    assert "probe/SKILL.md" not in files
    assert "other/SKILL.md" in files

    # і наступний прогін теж його не чіпає
    out = {o.rel: o.verdict for o in S.install(dest, version="1.2")}
    assert out["probe/SKILL.md"] == "kept"


def test_only_installs_the_named_skill(pack: Path, tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    S.install(dest, version="1.0", names=("probe",))
    assert (dest / "probe").is_dir()
    assert not (dest / "other").exists()


def test_package_ships_its_skills(tmp_path: Path) -> None:
    """Скіли, які пакет НЕСЕ насправді, а не в підкладеній фікстурі.

    ⚠ Ворота проти розкладки: `.claude/skills/` у репо і `nyshporka/skills/` у
    колесі — одна тека під двома іменами, і саме тут вона мовчки зникає, коли
    правлять `force-include`.
    """
    got = S.available()
    assert got, "пакет не бачить жодного власного скіла"
    for sk in got:
        assert sk.card.is_file()
        text = sk.card.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{sk.name}: немає frontmatter"
        assert f"name: {sk.name}" in text, f"{sk.name}: ім'я не збігається з текою"


def test_shipped_references_match_their_source() -> None:
    """Довідник, який скіл везе з собою, дорівнює доці ПОБАЙТОВО.

    🔴 Скіл ставиться користувачеві, а `docs/` у колесо не їде — тож посилання
    з картки на доку в репозиторії у встановленого користувача веде в нікуди.
    Тому довідник їде копією. Копія без воріт розходиться з оригіналом мовчки:
    правлять доку, а користувач далі читає торішній текст і не має жодної
    ознаки, що вони різні.
    """
    root = Path(__file__).resolve().parents[1]
    pairs = [(p, root / "docs" / "agents" / p.name)
             for p in (root / ".claude" / "skills").rglob("references/*.md")]
    assert pairs, "жоден скіл не везе довідника — перевірка нічого не доводить"
    for copy, source in pairs:
        assert source.is_file(), f"{copy}: немає джерела {source}"
        assert copy.read_bytes() == source.read_bytes(), (
            f"{copy.name} розійшовся з docs/agents/ — оновіть копію")


def test_frontmatter_is_valid_yaml() -> None:
    """Шапка скіла мусить розбиратись як YAML — без здогадів про парсер.

    🔴 Двокрапка з пробілом усередині нелапкованого скаляра робить шапку
    невалідною: «Знайти рід у декоді так: канал…» YAML читає як вкладений
    мапінг і падає. Наявні скіли жили з цим, бо читалка виявилась
    поблажливою, — але покладатись на поблажливість чужого парсера означає
    дізнатись про межу тоді, коли скіл мовчки перестане спрацьовувати.
    Лікує одне: опис у лапках.
    """
    import yaml

    for sk in S.available():
        text = sk.card.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{sk.name}: немає шапки"
        head = text.split("---", 2)[1]
        try:
            data = yaml.safe_load(head)
        except yaml.YAMLError as exc:  # pragma: no cover - тіло діагностики
            raise AssertionError(f"{sk.name}: шапка не є YAML — {exc}") from None
        assert isinstance(data, dict), f"{sk.name}: шапка не мапінг"
        assert data.get("name") == sk.name
        assert data.get("description"), f"{sk.name}: порожній опис"


def test_description_stays_readable() -> None:
    """Опис лишається тригером, а не процедурою.

    ⚠ Поріг тут не про технічну межу читалки (вона невідома), а про жанр: опис,
    який не влазить у 1000 символів, майже завжди означає, що в нього поклали
    інструкцію замість переліку випадків, коли скіл кликати.
    """
    for sk in S.available():
        text = sk.card.read_text(encoding="utf-8")
        desc = str(__import__("yaml").safe_load(text.split("---", 2)[1])["description"])
        assert len(desc) <= 1000, f"{sk.name}: опис {len(desc)} символів"
