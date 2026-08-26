"""📋 Розбір актів у поля: те, що перенос міг зламати мовчки.

Модулі приїхали з приватного дослідницького репозиторію, і небезпека тут не в
логіці — вона вже обкатана на реальній книзі, — а в переїзді: чи не лишилось
у пакеті імен парафії й родин, чи не роздвоївся перелік ролей, чи не вказує
кеш тайлів у системний temp, і чи не змиває свій профіль дослідника пакетний.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.records import CONTRACT, checksum, consensus, names, taxonomy
from nyshporka.records import profile as P


# ── контракт вичитки ─────────────────────────────────────────────────────────
def test_the_contract_ships_with_the_package() -> None:
    """Без нього агент не знає ні полів, ні правил — і вигадує їх."""
    assert CONTRACT.is_file(), f"контракту немає: {CONTRACT}"
    text = CONTRACT.read_text(encoding="utf-8")
    assert "rtype" in text and "tally" in text
    assert "[нрзб]" in text, "правило про нерозбірливе зникло"


@pytest.mark.parametrize("private", [
    # Парафія й родини конкретного дослідження. Форма контракту потрібна всім,
    # адреса дослідження — нікому: пакет роздають, і приклад із назвою села
    # прив'язав би його до чужої родини.
    "Мясков", "Ротмистров", "Ревега", "Крапотень", "Ратушняк", "Мурлика",
    "Джугастр", "Ямполь",
])
def test_the_contract_names_no_real_parish(private: str) -> None:
    assert private not in CONTRACT.read_text(encoding="utf-8")


def test_the_contract_keeps_the_orthography_it_teaches() -> None:
    """Приклади замінені, але дореформена орфографія — це і є предмет науки."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "Ѳеодоръ" in text and "крестьянинъ" in text


# ── профілі: два шари ────────────────────────────────────────────────────────
def test_packaged_profiles_cover_the_four_kinds_of_source() -> None:
    kinds = {p["name"] for p in P.available()}
    assert {"orthodox_metric_19", "catholic_metric",
            "confession_list", "revision_tale"} <= kinds


def test_the_packaged_file_binds_no_case_of_anyones_research() -> None:
    """🔴 Прив'язка справи — знання про конкретну книгу, не про тип джерела."""
    raw = P._read(P.PACKAGED)
    assert not raw.get("cases"), f"у пакеті лишились прив'язки: {raw['cases']}"


def test_a_workspace_profile_adds_without_erasing_the_packaged_ones(
        tmp_path: Path) -> None:
    """🔴 Злиття глибоке: свій профіль не має коштувати костелу й сповідки.

    Заміна файлом виглядала б як робота — доти, доки хтось не взяв би книгу
    іншого типу й не дістав нарізку метрики на сповідних розписах.
    """
    from nyshporka.core import workspace as W

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / P.WORKSPACE_CONFIG).write_text(
        "profiles:\n"
        "  my_book:\n"
        "    extends: orthodox_metric_19\n"
        "    title: моя книга\n"
        "    tiles:\n"
        "      rows: 11\n"
        "cases:\n"
        "  X/1/1: my_book\n",
        encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.reload()
    try:
        kinds = {p["name"] for p in P.available()}
        assert "my_book" in kinds
        assert "confession_list" in kinds, "пакетні профілі змило своїм файлом"

        own = P.load(case_key="X/1/1")
        assert own.name == "my_book"
        assert own.tiles["rows"] == 11, "своє перекриття не застосувалось"
        # Успадковане з пакетних defaults — саме те, чого дослідник не писав.
        assert own.book["lanes_by_sex"] == ["birth", "death"]
        assert own.tiles["overlap"] == 0.35
    finally:
        # 🔴 Простір і кеш профілів глобальні: лишити їх на tmp_path означало б
        # зелений тест, який тихо ламає наступні.
        W.reset()
        P.reload()


def test_an_unknown_profile_says_where_to_add_it() -> None:
    """Відмова без адреси — половина відмови."""
    with pytest.raises(ValueError) as exc:
        P.load("немає-такого")
    assert P.WORKSPACE_CONFIG in str(exc.value)


# ── одне джерело для переліку ролей ──────────────────────────────────────────
def test_the_skipped_roles_have_exactly_one_home() -> None:
    """🔴 Другий примірник розійшовся б із першим мовчки.

    Причт зник би зі зводу й лишився в черзі ескалації — і виглядало б це як
    різночитання між гілками, а не як розбіжність двох списків у коді.
    """
    assert {"priest"} == taxonomy.SKIP_ROLES
    assert consensus.SKIP_ROLES is taxonomy.SKIP_ROLES


# ── кеш тайлів ───────────────────────────────────────────────────────────────
def test_tiles_land_in_the_workspace_not_in_a_system_temp(
        tmp_path: Path) -> None:
    """Нарізка книги — це гігабайти; людина мусить бачити, де вони й що їх можна прибрати."""
    from nyshporka.core import workspace as W
    from nyshporka.records import tiles

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    try:
        out = tiles.default_out_dir()
        assert tmp_path in out.parents, f"тайли пішли повз простір: {out}"
    finally:
        W.reset()


# ── чексуми: приймач повноти ─────────────────────────────────────────────────
def test_the_gap_finder_names_the_missing_number() -> None:
    """Діра в нумерації — це пропущений акт із точністю до номера."""
    assert checksum.compact([]) == "—"
    assert checksum.compact([3, 4, 5, 9]) == "3–5, 9"


def test_the_row_parser_splits_the_sex_counter() -> None:
    """🔴 «м38» — не число: у метриці лічильники окремі, і зливати їх не можна."""
    assert checksum.parse_row("м38") == ("m", 38)
    assert checksum.parse_row("ж36") == ("f", 36)
    assert checksum.parse_row("9") == ("", 9)


def test_names_fold_the_prereform_letters() -> None:
    """«Ѳеодоръ» і «Феодор» — та сама людина, і звід мусить це бачити."""
    assert names.norm_given("Ѳеодоръ") == names.norm_given("Феодоръ")


# ── ціна вичитки ─────────────────────────────────────────────────────────────
def test_the_cost_is_named_before_the_work_not_after() -> None:
    """🔴 Єдиний крок конвеєра, що коштує грошей на кожному аркуші.

    Порядок величини має стояти перед тим, як людина почне книгу на дві сотні
    аркушів, — інакше вона дізнається його з рахунку.
    """
    from nyshporka.ops_records import estimate

    est = estimate(200)
    assert est["tokens"] == 200 * 84_000
    assert est["usd_rough"] > 100, "оцінка втратила порядок величини"
    assert estimate(0)["usd_rough"] == 0
