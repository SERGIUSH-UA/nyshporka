"""Посилання на джерело сканів беруться й з реєстру опису, не лише з сайдкара.

Навіщо це є: ворота попереджають `no_refs` — «звірити знахідку з зображенням
отримувачу буде нікуди піти». На десятьох засіяних справах сайдкари джерела не
мали (`spr-6940` прямо каже «DGS не зафіксовано на момент завантаження»), а
реєстр опису його знає — просто пакувальник туди не заглядав.

🔴 Головне, що стережуть ці тести, — що реєстрове посилання лягає в `links`, а
НЕ в `refs`. На боці пулу `refs` означає «та сама ЗЙОМКА» і склеює зйомки між
собою; реєстр знає лише, що СПРАВА десь є. Потрапивши в `refs`, він склеїв би
дві різні зйомки однієї справи в одну.
"""
from typing import Any

import pytest

from nyshporka.share import publish

#: Рядок реєстру опису в тому вигляді, в якому його віддає `registry_row`.
RYADOK: dict[str, Any] = {
    "fs_dgs": "118463212",
    "fs_frames": "209",
    "commons_title": "ДАХмО 315-1-84а. 1808. Журнал",
    "commons_url": "https://upload.wikimedia.org/…/dahmo-315-1-84a.pdf",
    "archium_url": "",
}


@pytest.fixture
def reiestr(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Підмінений реєстр опису. Віддає, ЯКИХ саме ключів у нього питали."""
    pytannia: list[tuple[str, ...]] = []

    def _row(repo: str, fond: str, opys: str, spr: str,
             letter: str = "") -> tuple[dict[str, Any] | None, Any]:
        pytannia.append((repo, fond, opys, spr, letter))
        # Реєстр тримає літеру так, як стоїть в опису, — КИРИЛИЦЕЮ.
        return (dict(RYADOK) if letter == "а" or (spr == "6940" and not letter)
                else None), "шлях"

    monkeypatch.setattr("nyshporka.fonds.registry.registry_row", _row)
    return pytannia


def test_dgs_z_reiestru_staie_posylanniam(reiestr: list[tuple[str, ...]]) -> None:
    """Справа без сайдкара все одно дістає адресу, куди піти по скани."""
    got = publish._links_from_registry("ДАХмО 315-1-84а")

    assert got[0]["label"].startswith("FamilySearch, DGS 118463212")
    assert "imageGroupNumbers=118463212" in got[0]["url"]
    assert any("Commons" in x["label"] for x in got)


def test_litera_shukaietsia_oboma_pysmamy(reiestr: list[tuple[str, ...]]) -> None:
    """`84a` латинкою мусить знайти рядок, який лежить під `84а` кирилицею.

    🔴 Це не теоретичний випадок: `resolve_case` зводить літерний індекс до
    латиниці (канон сховища сторінок), а реєстр опису зберігає його так, як
    надруковано в опису. Без другої спроби ДАХмО 315-1-84а виглядає як справа
    без джерела, хоч DGS у реєстрі є — виміряно на живій базі 23.09.2026.
    """
    got = publish._links_from_registry("ДАХмО 315-1-84a")  # латинська «a»

    assert got, "латинське написання літери лишилось без джерела"
    litery = [q[4] for q in reiestr]
    assert "a" in litery and "а" in litery, f"пробували лише {litery}"


def test_reiestrove_posylannia_ne_ide_v_refs(reiestr: list[tuple[str, ...]]) -> None:
    """Найважливіше: реєстр не має права склеювати зйомки.

    `books.ziomka` на сервері вважає спільний `refs` доказом «та сама плівка».
    Реєстр такого не доводить — він каже лише, що справа є на FamilySearch.
    """
    assert not hasattr(publish._links_from_registry("ДАХмО 315-1-84а")[0], "source")
    for link in publish._links_from_registry("ДАХмО 315-1-84а"):
        assert set(link) <= {"label", "url"}, "формат links, не refs"


def test_svoie_posylannia_ne_vytisniaietsia(reiestr: list[tuple[str, ...]]) -> None:
    """Назване людиною стоїть першим: вона знає, звідки качала саме цю зйомку."""
    svoie = [{"label": "звідки скани", "url": "https://arhiv.example/case/84a"}]

    got = publish._with_registry(svoie, "ДАХмО 315-1-84а")

    assert got[0] == svoie[0]
    assert len(got) > 1, "реєстрові посилання мусили додатись після свого"


def test_povtor_ne_dubliuietsia(reiestr: list[tuple[str, ...]]) -> None:
    """Та сама адреса, названа руками й знайдена в реєстрі, лишається одна."""
    svoie = [{"label": "моє", "url": RYADOK["commons_url"] + "/"}]

    got = publish._with_registry(svoie, "ДАХмО 315-1-84а")

    adresy = [x["url"].rstrip("/") for x in got]
    assert len(adresy) == len(set(adresy)), f"повтор: {adresy}"


def test_bez_reiestru_pakuvannia_ne_padaie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Реєстру фонду немає — пакет однаково збирається.

    Мовчазна відмова тут правильна: посилання це зручність, а не умова, і
    завалити пакування чужої роботи через незібраний реєстр не можна.
    """
    def _vybukh(*_: Any, **__: Any) -> None:
        raise RuntimeError("реєстру цього фонду немає")

    monkeypatch.setattr("nyshporka.fonds.registry.registry_row", _vybukh)

    assert publish._links_from_registry("ДАХмО 315-1-84а") == []
    assert publish._with_registry([], "ДАХмО 315-1-84а") == []


def test_porozhnia_shyfra_ne_pytaie_reiestr(reiestr: list[tuple[str, ...]]) -> None:
    """Без шифри питати нічого — і реєстр не турбуємо."""
    assert publish._links_from_registry("") == []
    assert reiestr == []
