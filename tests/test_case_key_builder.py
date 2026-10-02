"""Ключ справи збирає тільки будівник (`core.casekey.make`, `library._mk_key`).

Підстава — інцидент 2026-08-25: збірка реєстру відв'язала від справи канон, і
картка показала «фактів 0» там, де канон цитує аркуш дослівно. Причина —
`cases/collect.py` у трьох місцях складав ключ як `f"{repo}/{fond}/{spr}"`,
тобто без опису, хоч ключ справи його несе.

Помилка мовчазна за побудовою: рядок збирається успішно, просто не влучає в
жоден запис реєстру. Тому приймач тут не на поведінку, а на форму коду.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# 🔴 `nyshporka.library` НЕ імпортується в шапці, і це не стиль. Модуль бере
# `ROOT = workspace().root` на рівні модуля, тобто заморожує простір у мить
# першого імпорту, — а pytest імпортує ВСІ тестові модулі на збиранні, коли
# ізолювальна фікстура ще не діяла. Одна імпортна стрічка тут прив'язує
# бібліотеку до простору розробника, і сусідній тест, який підставив тимчасову
# теку, мовчки бачить справжні справи. Спіймано 2026-08-26: `test_case_roots`
# окремо проходив, у повному прогоні падав.
#
# ⚠ Перенести імпорт усередину тесту НЕ досить: простір тоді знаходять і без
# змінної середовища — через файл «останній використаний», що лежить у профілі
# ОС, — тож бібліотека все одно замерзає на чужому. Тому фікстура спершу
# ОГОЛОШУЄ тимчасовий простір і лише потім імпортує; той самий порядок, що в
# `test_register_and_notes.space`.


@pytest.fixture
def lib(tmp_path: Path):
    """Бібліотека, заморожена на ТИМЧАСОВОМУ просторі.

    Констант простору цей файл не читає — лише таблиці фондів і збирачі
    ключів, — але імпортувати модуль інакше не можна, не лишивши слід сусідам.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L

    return L

PKG = Path(__file__).resolve().parents[1] / "src" / "nyshporka"

#: `f"{repo}/{fond}/{spr}"` і подібне: три поля через слеш усередині f-рядка.
HAND_BUILT = re.compile(r'f"\{[a-z_]+(?:\[\d\])?\}/\{[a-z_]+(?:\[\d\])?\}/\{[a-z_]+(?:\[\d\])?\}"')


def test_no_hand_built_case_keys() -> None:
    """У пакеті `cases` ключ не збирається f-рядком із трьох полів."""
    findings: list[str] = []
    for path in sorted((PKG / "cases").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HAND_BUILT.search(line):
                findings.append(f"{path.name}:{n}: {line.strip()}")
    assert not findings, (
        "ключ справи зібрано f-рядком повз `_mk_key` — такий ключ не несе "
        "опису й не влучає в реєстр:\n" + "\n".join(findings))


def test_every_key_carries_the_opys(lib) -> None:
    """Опис — у ключі будь-якого фонду; невідомий — `_`, а не пропуск."""
    _mk_key = lib._mk_key

    for repo, fond in [("ANRM", "211"), ("DAHMO", "315"), ("CDIAK", "2"), ("DAOO", "37")]:
        assert _mk_key(repo, fond, "13", "3") == f"{repo}/{fond}/3/13"
        assert _mk_key(repo, fond, "13") == f"{repo}/{fond}/_/13"


def test_a_case_without_opys_is_found_by_the_fond_default(lib) -> None:
    """Справа, названа без опису, знаходиться за описом за замовчуванням фонду.

    ID джерела канону (`S_<архів>_F<фонд>_D<справа>`) опису здебільшого не
    несе — і без цього канон відв'язався б від справи («канон: фактів 0»).
    """
    from nyshporka.archives import active

    pk = active()
    fonds = [(f.repo, f.fond, f.default_opys) for f in pk.fonds.values() if f.default_opys]
    assert fonds, "у паку немає жодного опису за замовчуванням — тест сліпий"
    for repo, fond, default in fonds:
        entry = {"key": lib._mk_key(repo, fond, "13", default), "repo": repo,
                 "fond": fond, "opys": default, "spr": "13"}
        other = {**entry, "key": lib._mk_key(repo, fond, "13", "999"), "opys": "999"}
        lk = lib.LibraryLookup.build([other, entry])
        assert lk.find(repo, fond, None, "13") is entry, f"{repo} ф.{fond}"


# ── радянські фонди: літера в номері фонду ───────────────────────────────────
def test_a_soviet_fond_is_one_fond_in_both_scripts() -> None:
    """🔴 «Р-6129» кирилицею і «R-6129» латинкою — це ОДИН фонд, а не два.

    Літерний префікс несуть фонди радянського періоду, і нумерація в них
    власна: ф.Р-6129 не має нічого спільного з ф.6129, якби той з'явився. Але
    набирають його обома письмами — шифра пише кирилицею, `source_id` латинкою
    й без дефіса, — і без зведення до одного канону та сама справа заходила б у
    бібліотеку двома ключами. Розходження було б тихим: половина сторінок під
    одним ключем, половина під іншим.
    """
    from nyshporka.library import _norm_fond

    assert _norm_fond("Р-6129") == "R-6129", "кирилична «Р» мусить стати латинською"
    assert _norm_fond("р-06129") == "R-6129", "провідні нулі й регістр не рахуються"
    assert _norm_fond("R6129") == "R-6129", "у source_id дефіс не вживається"
    assert _norm_fond("R-6129") == "R-6129"
    # А звичайний фонд лишається звичайним — правило не сміє чіпати решту.
    assert _norm_fond("0315") == "315"
    assert _norm_fond("315") == "315"


def test_the_letter_prefix_does_not_fall_off_the_shifra() -> None:
    """🔴 Без групи під літери регекс брав із «ДАВіО Р-6129-24-5» саме
    «6129-24-5» — тобто мовчки зливав фонд Р-6129 з фондом 6129.

    ⚠ Дефіс одразу після літер обов'язковий саме для того, щоб хвіст назви
    архіву («ДАВіО ») у номер фонду не потрапляв.
    """
    from nyshporka.library import _SHIFRA_RE

    m = _SHIFRA_RE.search("ДАВіО Р-6129-24-5")
    assert m and m.groups() == ("Р-6129", "24", "5")
    # Звичайна шифра розбирається як і раніше.
    m2 = _SHIFRA_RE.search("ДАХмО 315-1-8433")
    assert m2 and m2.groups() == ("315", "1", "8433")


def test_a_soviet_source_id_parses_at_all() -> None:
    """Доти ID радянського фонду не розбирався ЗОВСІМ, і картка справи казала
    «канон: фактів 0» там, де канон цитує аркуш дослівно."""
    from nyshporka.library import parse_source_id

    # 🔴 Код зводиться до КАНОНІЧНОГО, як і в решти входів бібліотеки. Доти ця
    # гілка віддавала його дослівно з імені файла — і канонічне джерело
    # («S_DAVO_…») лягало під один код, а тека на диску під інший: та сама
    # книга ставала двома записами з різним числом кадрів. Заміряно на живому
    # просторі: 336 ключів змінили б ім'я, 13 книг роздвоїлись би.
    assert parse_source_id("S_DAVO_FR6129_OP24_D5") == ("DAVIO", "R-6129", "24", "5")
    # Не за рахунок звичайних: сусідня форма мусить лишитись цілою.
    # ⚠ Архів і номери тут вигадані навмисно — справжній ID канону в тесті
    # спіймали б ворота проти приватних даних, і вони мали б рацію.
    assert parse_source_id("S_XYZ_F1_D2") == ("XYZ", "1", None, "2")


# ── адреса справи: те, що набирає людина ─────────────────────────────────────
def test_the_natural_order_of_a_shifra_is_accepted(lib) -> None:
    """🔴 Три числа через скісну — перше, що набере будь-хто.

    Шифра в усьому світі пишеться «фонд-опис-справа» в один ряд, тож
    «CDIAK/127/781/534» природніше за «CDIAK/127-781/534». Доти перша форма
    відмовлялась, і правило («опис приєднується до фонду ДЕФІСОМ») треба було
    вивести з двох прикладів у тексті відмови.
    """
    def parts(v):
        a = lib.parse_address(v)
        # `repo_word` навмисно зберігає написання людини, тож рівність самих
        # адрес тут не про те: звірятись мусить РОЗІБРАНЕ.
        return a and (a.repo, a.fond, a.opys, a.spr)

    want = ("CDIAK", "127", "781", "534")
    assert parts("CDIAK/127/781/534") == want
    assert parts("CDIAK/127-781/534") == want
    assert parts("ЦДІАК 127-781-534") == want


def test_the_form_the_app_prints_can_be_typed_back(lib) -> None:
    """🔴 Замкнена петля: адресу, яку показав застосунок, мусить приймати вхід.

    Пошук друкує в рядку хіта «ДАВіО-172-4-112» саме як адресу справи. Ця
    форма — назва архіву, приліплена дефісом — не розбиралась ні реєстрацією,
    ні сховищем сторінок, тобто набрати назад показане було не можна. Клас
    вади той самий, що стереже `test_no_dead_ends`: обіцянка без входу.
    """
    a = lib.parse_address("ДАВіО-172-4-112")
    assert a and (a.fond, a.opys, a.spr) == ("172", "4", "112")
    assert a.repo, "архів, приліплений дефісом, не впізнано"


def test_a_soviet_fond_is_not_mistaken_for_an_archive(lib) -> None:
    """🔴 Однолітерне слово — префікс фонду, а не назва архіву.

    «Р-6129-24-5» і «ДАВіО Р-6129-24-5» мають однакову форму. Дозволивши групі
    архіву одну літеру, ми читали б ф.Р-6129 як архів «Р» і фонд 6129 — рівно
    та вада, від якої написаний `_norm_fond`.
    """
    bare = lib.parse_address("Р-6129-24-5")
    assert bare and bare.fond == "R-6129" and bare.repo_word == ""
    named = lib.parse_address("ДАВіО Р-6129-24-5")
    assert named and named.fond == "R-6129" and named.repo


def test_a_three_part_key_still_means_fond_and_case(lib) -> None:
    """Нова форма строго довша за наявну й нічого в неї не забирає."""
    assert lib.parse_address("DAHMO/315/8433") is None
    assert lib.parse_address("CDIAK/127/781") is None


def test_a_path_and_a_sentence_are_not_addresses(lib) -> None:
    """Адреса — це коли рядок ЦІЛКОМ є адресою, інакше пошук перестав би бути
    повнотекстовим."""
    assert lib.parse_address("data/raw/dahmo_315/spr-8433") is None
    assert lib.parse_address("Метрична книга 127-1078-1662") is None
