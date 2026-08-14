"""🏛 Пак архівів мусить відтворювати чинні константи ДОСЛІВНО.

Ці словники керують тим, як справа отримує ключ, шифру й географію. Помилка тут
не падає: вона тихо злипає дві різні книги в одну (якщо загубити `opys_in_key`),
або вимиває половину фондів зі зрізу по губернії, або робить теку описів
«справою». Тому нижче — дослівні копії того, що було в коді, і звірка з паком.
"""
from __future__ import annotations

import pytest

from nyshporka.archives import pack as P

# ── еталони: копії констант із дослідницького репо ───────────────────────────
LEGACY_REPO_LABEL = {
    "DAHMO": "ДАХмО", "CDIAK": "ЦДІАК", "DAVO": "ДАВО", "DAVIO": "ДАВіО",
    "ANRM": "ANRM", "BNRM": "BNRM", "DACHVO": "ДАЧвО", "DAOO": "ДАОО",
}
LEGACY_DEFAULT_OPYS = {
    ("DAHMO", "315"): "1", ("CDIAK", "224"): "1", ("CDIAK", "127"): "1076",
}
LEGACY_OPYS_IN_KEY = {("ANRM", "211")}
LEGACY_SKIP_SLUGS = {
    "davo_opysy", "dahmo_319_f65_opisy", "bev_pdh", "kev_pdh",
    "khev_pdh", "eev_pdh", "_console_pages",
}
LEGACY_FOND_GUBERNIYA = {
    ("DAHMO", "315"): "Подільська",
    ("DAHMO", "226"): "Подільська",
    ("DAHMO", "196"): "Подільська",
    ("DAHMO", "230"): "Подільська",
    ("DAVO", "904"): "Подільська",
    ("DAVO", "792"): "Подільська",
}
LEGACY_RTYPE_LABEL = {
    "birth": "народження", "marriage": "шлюби", "death": "смерті",
    "confession": "сповідні", "revision": "ревізькі", "gazette": "єпарх. відомості",
    "clergy_list": "клірові", "finding_aid": "опис фонду", "other": "інше",
}


@pytest.fixture(scope="module")
def pk() -> P.ArchivesPack:
    return P.load()


# ── дослівні тотожності ──────────────────────────────────────────────────────
def test_repo_labels_match_legacy(pk):
    assert {c: pk.repo_label(c) for c in LEGACY_REPO_LABEL} == LEGACY_REPO_LABEL


def test_default_opys_matches_legacy(pk):
    got = {k: pk.default_opys(*k) for k in LEGACY_DEFAULT_OPYS}
    assert got == LEGACY_DEFAULT_OPYS
    # і ЛИШЕ для них — зайвий дефолт приписав би справі чужий опис
    extra = [f.key for f in pk.fonds.values()
             if f.default_opys is not None and f.key not in LEGACY_DEFAULT_OPYS]
    assert not extra, f"нові дефолтні описи без підстави: {extra}"


def test_opys_in_key_matches_legacy(pk):
    """🔴 Найдорожча помилка паку: втратити цей прапорець.

    Без нього «ANRM 211-1-140» (метрики с. Парково) і «ANRM 211-3-140»
    (Кишинівський кафедральний собор) дають один ключ — і аркуші однієї книги
    мовчки дописуються в іншу.
    """
    got = {f.key for f in pk.fonds.values() if f.opys_in_key}
    assert got == LEGACY_OPYS_IN_KEY
    assert pk.opys_in_key("ANRM", "211")
    assert not pk.opys_in_key("DAHMO", "315")


def test_skip_slugs_match_legacy(pk):
    assert set(pk.skip_slugs) == LEGACY_SKIP_SLUGS


def test_fond_guberniya_matches_legacy(pk):
    got = {f.key: f.guberniya for f in pk.fonds.values() if f.guberniya}
    assert got == LEGACY_FOND_GUBERNIYA


def test_record_type_labels_match_legacy(pk):
    assert pk.record_type_labels == LEGACY_RTYPE_LABEL


# ── поведінка на невідомому ──────────────────────────────────────────────────
def test_unknown_repo_returns_its_own_code(pk):
    """У шифрі краще побачити «XYZ 315-1-8433», ніж « 315-1-8433»."""
    assert pk.repo_label("XYZ") == "XYZ"
    assert pk.repo_label(None) == ""


def test_unknown_fond_is_silent_not_wrong(pk):
    assert pk.default_opys("XYZ", "1") is None
    assert not pk.opys_in_key("XYZ", "1")
    assert pk.guberniya("XYZ", "1") == ""


def test_repo_code_is_case_insensitive(pk):
    assert pk.repo_label("dahmo") == pk.repo_label("DAHMO") == "ДАХмО"
    assert pk.opys_in_key("anrm", "211")


# ── розширення користувачем ──────────────────────────────────────────────────
def test_user_overlay_adds_without_erasing_builtin(tmp_path):
    """🔴 Накладка перебиває ПО КЛЮЧУ, а не заміщає секцію.

    Інакше дослідник, який дописав один свій архів, мовчки втратив би всі
    вбудовані — і це виглядало б як «програма забула половину фондів».
    """
    over = tmp_path / "archives.yaml"
    over.write_text(
        "repositories:\n"
        "  DAZHO: {label: ДАЖО, name: Держархів Житомирської області}\n"
        "fonds:\n"
        "  - {repo: DAZHO, fond: '178', guberniya: Волинська}\n"
        "skip_slugs: [my_scratch]\n",
        encoding="utf-8")
    pk = P.load(extra=over)
    # нове з'явилось
    assert pk.repo_label("DAZHO") == "ДАЖО"
    assert pk.guberniya("DAZHO", "178") == "Волинська"
    assert "my_scratch" in pk.skip_slugs
    # і жодне вбудоване не зникло
    assert pk.repo_label("DAHMO") == "ДАХмО"
    assert pk.opys_in_key("ANRM", "211")
    assert "bev_pdh" in pk.skip_slugs


def test_user_overlay_can_correct_a_builtin_entry(tmp_path):
    over = tmp_path / "archives.yaml"
    over.write_text(
        "fonds:\n  - {repo: CDIAK, fond: '224', default_opys: '2'}\n",
        encoding="utf-8")
    pk = P.load(extra=over)
    assert pk.default_opys("CDIAK", "224") == "2"
    assert pk.default_opys("CDIAK", "127") == "1076", "сусідній запис не мав зникнути"


def test_broken_overlay_does_not_take_down_the_pack(tmp_path):
    """Криву накладку краще проігнорувати, ніж лишити користувача без каталогу."""
    over = tmp_path / "archives.yaml"
    over.write_text("це: [не закритий список\n", encoding="utf-8")
    pk = P.load(extra=over)
    assert pk.repo_label("DAHMO") == "ДАХмО"


# ── повнота ──────────────────────────────────────────────────────────────────
def test_every_fond_belongs_to_a_known_repository(pk):
    unknown = sorted({f.repo for f in pk.fonds.values()} - set(pk.repositories))
    assert not unknown, f"фонди посилаються на невідомі архіви: {unknown}"


def test_opys_in_key_fonds_explain_themselves(pk):
    """Прапорець, що змінює ключ справи, мусить нести підставу.

    Через півроку «чому саме цей фонд» уже не відновити, а зняти прапорець
    легко — наслідки будуть тихі.
    """
    for f in pk.fonds.values():
        if f.opys_in_key:
            assert f.note.strip(), f"{f.key}: opys_in_key без пояснення"
