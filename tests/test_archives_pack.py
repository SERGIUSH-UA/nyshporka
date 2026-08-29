"""🏛 Пак архівів мусить відтворювати чинні константи дослівно.

Ці словники керують тим, як справа отримує ключ, шифру й географію. Помилка тут
не падає: вона тихо злипає дві різні книги в одну (якщо загубити `opys_in_key`),
або вимиває половину фондів зі зрізу по губернії, або робить теку описів
«справою». Тому нижче — дослівні копії того, що було в коді, і звірка з паком.
"""
from __future__ import annotations

import pytest

from nyshporka.archives import pack as P

# ── еталони: копії констант із дослідницького репо ───────────────────────────
# ⚠ Один запис свідомо РОЗХОДИТЬСЯ з тим, що було в коді, і саме тому він тут
# із поясненням, а не мовчки: `DAVO` мав підпис «ДАВО», а такого скорочення
# серед архівів України немає зовсім — Вінницька це ДАВіО, Волинська ДАВоО.
# «ДАВО» лишається нашим КОДОМ (під ним ключі сховища сторінок), але підписом
# бути перестало: показаний людині, він вчить писати шифру, яка не зійдеться
# ні з архівом, ні з чужим дослідником. Давнє написання приймається
# псевдонімом — див. `test_no_archive_is_shown_under_a_spelling_that_does_not_exist`.
LEGACY_REPO_LABEL = {
    "DAHMO": "ДАХмО", "CDIAK": "ЦДІАК", "DAVO": "ДАВіО", "DAVIO": "ДАВіО",
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
    ("DAVIO", "904"): "Подільська",
    ("DAVIO", "792"): "Подільська",
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
    # і лише для них — зайвий дефолт приписав би справі чужий опис
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
    """🔴 Накладка перебиває по ключу, а не заміщає секцію.

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


def test_pack_file_is_tracked_by_git():
    """🔴 Дані пакета мусять бути В репозиторії, а не лише на диску.

    Спіймано на коміті, який вийшов на три файли замість чотирьох: правило
    `data/` у `.gitignore`, задумане для робочого простору дослідника, git
    застосовує на будь-якій глибині — і з'їло `archives/data/archives.yaml`.

    Локально й у тестах усе працювало б: файл лежить на диску. Зламалось би
    рівно в користувача, який поставив пакет із релізу, і рівно на першому
    запуску. Тому перевіряється саме `git ls-files`, а не `Path.exists()`.
    """
    import subprocess

    root = P.BUILTIN.resolve().parents[4]
    rel = P.BUILTIN.resolve().relative_to(root).as_posix()
    res = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                         cwd=root, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"{rel} не відстежується git — пакет поїде в реліз без свого ж паку. "
        f"Перевір `.gitignore`: шаблони даних мають бути прив'язані до кореня."
    )


def test_opys_in_key_fonds_explain_themselves(pk):
    """Прапорець, що змінює ключ справи, мусить нести підставу.

    Через півроку «чому саме цей фонд» уже не відновити, а зняти прапорець
    легко — наслідки будуть тихі.
    """
    for f in pk.fonds.values():
        if f.opys_in_key:
            assert f.note.strip(), f"{f.key}: opys_in_key без пояснення"


# ── майданчики архівів ───────────────────────────────────────────────────────
def test_the_pack_and_the_hardcoded_base_do_not_drift() -> None:
    """🔴 Адреса ДАХмО живе у двох місцях: константою в джерелі (її тримають
    наявні тести) і в паку, звідки будуються решта майданчиків. Розбіжність тут
    була б тихою: половина запитів пішла б на один хост, половина на інший."""
    from nyshporka.archives import active
    from nyshporka.sources import archium as A

    site = active().site("DAHMO", "archium")
    assert site is not None, "майданчик ДАХмО зник із паку"
    assert site.url == A.BASE


def test_a_site_without_fond_groups_says_so() -> None:
    """`/api/v1/fond-groups/` ЦДІАК віддає 500. Без цієї позначки перегляд
    показав би групи сусіднього архіву — чуже дерево під іменем цього."""
    from nyshporka.archives import active

    site = active().site("CDIAK", "archium")
    assert site is not None and site.url.startswith("https://")
    assert site.fond_groups is False
    assert site.groups == ()


def test_an_archive_may_be_written_two_ways_elsewhere() -> None:
    """На Commons файли того самого архіву лежать і під «ДАВіО», і під «ДАВО».
    Пошук за одним написанням мовчки втрачає половину, а нуль читається як
    «сканів немає»."""
    from nyshporka.archives import active

    assert active().codes_for("DAVIO", "commons") == ("ДАВіО", "ДАВО")
    assert active().codes_for("DAHMO", "duck") == ("ДАХмО",)
    # Невідомий архів дає порожньо, а не здогад: вигаданий код питав би про те,
    # чого в тій системі немає, і нуль читався б як відповідь.
    assert active().codes_for("XXX", "duck") == ()


def test_a_users_pack_adds_to_a_repository_without_erasing_its_sites(tmp_path) -> None:
    """🔴 Той самий клас вади, від якого захищає злиття по ключу, лише поверхом
    нижче: людина, що дописала архіву одну назву в чужій системі, не має
    втратити його майданчики."""
    from nyshporka.archives import pack as P

    over = tmp_path / "своє.yaml"
    over.write_text("repositories:\n  DAHMO:\n    codes:\n      duck: ІНАКШЕ\n",
                    encoding="utf-8")
    p = P.load(over)

    assert p.codes_for("DAHMO", "duck") == ("ІНАКШЕ",)
    site = p.site("DAHMO", "archium")
    assert site is not None and site.url, "майданчик зник разом із правкою кодів"
    assert p.repositories["DAHMO"].label == "ДАХмО", "загубився й підпис архіву"


# ── межі описів: знаменник покриття ──────────────────────────────────────────
def test_the_bounds_keep_the_order_they_were_written_in() -> None:
    """🔴 Покриття пишеться в порядку ітерації описів, тож перестановка ключів
    міняє байти `coverage.json` — а вони і є приймачем усього перенесення."""
    from nyshporka.archives import active

    assert list(active().opys_bounds("DAHMO", "230")) == ["1", "2", "3", "4", "5"]


def test_a_bound_carries_what_it_stands_on() -> None:
    """🔴 Саме число неповне. «1515, звірено з переліком архіву» і «231,
    максимум транскрипції» — різні за силою твердження: друге нижня оцінка,
    тож покриття по ньому завищене. Доки підстава жила в коментарі коду,
    обидві межі подавались однаково впевнено."""
    from nyshporka.archives import active

    b = active().opys_bounds("CDIAK", "224")
    assert b["1"].basis == "official" and not b["1"].is_lower_estimate
    assert b["2"].is_lower_estimate and b["3"].is_lower_estimate
    assert "переліком архіву" in b["1"].note


def test_a_fond_without_bounds_says_so_by_emptiness() -> None:
    """Порожньо ≠ нуль: покриття без знаменника не рахується взагалі, бо
    «0/0 · немає 0» читається як «усе на місці»."""
    from nyshporka.archives import active

    assert active().opys_bounds("DAVO", "904") == {}
    assert active().opys_bounds("XXX", "1") == {}


def test_the_guide_total_is_optional() -> None:
    from nyshporka.archives import active

    assert active().guide_total("DAHMO", "230") == 7925
    assert active().guide_total("CDIAK", "224") is None


def test_adding_one_bound_does_not_wipe_the_rest_of_the_fond(tmp_path) -> None:
    """🔴 Доки в записі фонду була сама губернія, заміщення коштувало мало.
    Щойно туди їдуть знаменники, ціна стає такою: дослідник, що дописав межу
    одного опису, мовчки втрачає `default_opys` — і кожна сканована тека
    дістає чужий опис у ключі справи."""
    from nyshporka.archives import pack as P

    over = tmp_path / "своє.yaml"
    over.write_text(
        'fonds:\n  - repo: CDIAK\n    fond: "224"\n'
        '    opys_last:\n      "4": {last: 12, basis: manual}\n',
        encoding="utf-8")
    p = P.load(over)

    b = p.opys_bounds("CDIAK", "224")
    assert b["4"].last == 12, "нова межа не доїхала"
    assert set(b) == {"1", "2", "3", "4"}, "дописування змило наявні межі"
    assert p.fonds[("CDIAK", "224")].default_opys == "1", "загубився опис за замовчуванням"
    assert p.fonds[("CDIAK", "224")].name, "загубилась назва фонду"


# ── довідка про фонд і будівник ключів мусять казати те саме ────────────────
def test_the_fond_card_answers_with_the_key_builder_not_beside_it() -> None:
    """🔴 Два «джерела правди» на одне питання розійшлись — і мовчки.

    `nysh archive` читав поле паку, а ключі складала бібліотека зі свого
    набору. На ДАХмО ф.230 команда відповідала «опис у ключі: ні», тоді як
    бібліотека клала справу під `DAHMO/230-1/12`. Питання задають рівно перед
    тим, як складати ключ, тож ціна розбіжності — прив'язка, яка не сходиться,
    а помічають її за чужими сторінками у своїй справі.

    ⚠ Перевіряється не збіг із паком, а збіг відповіді з тим, що справді
    станеться з ключем: саме він виконавчий.
    """
    from nyshporka import ops as O
    from nyshporka.library import _mk_key, opys_in_key

    for repo, fond, spr in [("DAHMO", "230", "13"), ("ANRM", "211", "140"),
                            ("DAHMO", "315", "159"), ("CDIAK", "224", "711")]:
        env = O.call("archive.fond", {"repo": repo, "fond": fond})
        assert env.ok, env.error
        said = bool(env.data["opys_in_key"])
        # Той самий опис, поданий будівникові: чи потрапить він у ключ.
        built = _mk_key(repo, fond, spr, "3") or ""
        really = f"{fond}-3/" in built
        assert said == really == opys_in_key(repo, fond), (
            f"{repo} {fond}: команда каже «{said}», ключ виходить «{built}» — "
            f"саме так довідка й будівник розходились")


def test_the_default_opys_answer_matches_what_the_key_will_use() -> None:
    """Той самий розкол сусіднім полем: команда відповідала «—», а сховище
    сторінок мовчки підставляло «1»."""
    from nyshporka import ops as O
    from nyshporka.library import default_opys

    for repo, fond in [("DAHMO", "230"), ("DAHMO", "315"), ("CDIAK", "224")]:
        env = O.call("archive.fond", {"repo": repo, "fond": fond})
        assert env.ok, env.error
        assert env.data["default_opys"] == default_opys(repo, fond), (
            f"{repo} {fond}: довідка про опис за замовчуванням не збігається з "
            f"тим, який підставить ключ")


# ── склад архівів: один читач, а не три ──────────────────────────────────────
def test_the_library_reads_the_pack_instead_of_its_own_copy(pk) -> None:
    """🔴 Скорочення архівів жили копією в `library` — і копія розійшлась.

    Розбіжність тиха в найгіршому місці: `nysh archive` відповідав голим кодом
    «DAZHO» там, де картка справи показувала «ДАЖО», бо архів дописали в один
    словник і забули про другий. Той самий клас розколу, що вже лікували на
    `opys_in_key`, і приймач тут той самий: читач мусить бути ОДИН.
    """
    from nyshporka.library import _REPO_LABEL

    assert pk.repo_labels() == _REPO_LABEL, (
        "склад архівів у бібліотеці розійшовся з паком — знову дві правди")
    for code in _REPO_LABEL:
        assert pk.repo_label(code) == _REPO_LABEL[code]


def test_case_registration_knows_the_same_archives_as_the_library() -> None:
    """🔴 Третя копія переліку, і вона теж уже розходилась.

    `nysh case` не знав ДАЧО й ДАЧвО, які бібліотека знала: та сама справа
    діставала архів або не діставала — залежно від того, якою командою її
    заводили.
    """
    from nyshporka.archives import active
    from nyshporka.cases.register import parse_shifra
    from nyshporka.library import _REPO_LABEL

    for code, label in sorted(_REPO_LABEL.items()):
        got = parse_shifra(f"{label} 315-1-8433")
        assert got.repo == active().canon_repo(code), (
            f"«{label}» заводиться як {got.repo}, а бібліотека знає його як {code}")


def test_registering_the_second_code_of_one_archive_keeps_one_key() -> None:
    """🔴 «ДАВіО» і «ДАВО» — той самий архів, і заводитись мусять під тим самим
    кодом.

    Інакше облік роздвоюється мовчки: нові справи, заведені другим написанням,
    пішли б у сусідній код — з окремим лічильником «на диску» для кожного.

    🔴 Канонічний код — `DAVIO`, і саме він збігається зі скороченням, яким
    архів зветься насправді. `DAVO` був ВНУТРІШНІМ кодом дослідницького
    простору й у пакет для інших їхати не мусив: код, що не відповідає жодному
    чинному скороченню, вчить писати шифру, яка не зійдеться ні з архівом, ні з
    колегою. Запис лишається рівно задля давніх ключів — і зводиться сюди.
    """
    from nyshporka.cases.register import parse_shifra

    assert parse_shifra("ДАВіО 904-24-5").repo == "DAVIO"
    assert parse_shifra("ДАВО 904-24-5").repo == "DAVIO"
    assert parse_shifra("DAVO 904-24-5").repo == "DAVIO", "давні ключі не сміють осиротіти"


def test_an_archive_added_by_the_researcher_reaches_both_readers(tmp_path) -> None:
    """Заради цього перелік і переїхав у дані: свій архів додається рядком.

    Доти чужий дослідник із власним архівом упирався в правку коду — і не в
    одному місці, а в трьох.
    """
    import nyshporka.archives.pack as P

    over = tmp_path / "archives.yaml"
    over.write_text("repositories:\n  DAMYE: {label: ДАМиЄ, aliases: [ДАМіЄ]}\n",
                    encoding="utf-8")
    p = P.load(extra=over)
    assert p.repo_label("DAMYE") == "ДАМиЄ"
    assert p.resolve_code("ДАМиЄ") == "DAMYE"
    assert p.resolve_code("ДАМіЄ") == "DAMYE", "псевдонім не доїхав"
    assert p.resolve_code("ДАХмО") == "DAHMO", "вбудовані не мали зникнути"


def test_the_two_vinnytsia_spellings_do_not_swallow_volyn(pk) -> None:
    """🔴 Волинь і Вінниця діляться скороченням, і ціна помилки тут не «не
    розпізнав», а «поклав у чужий архів».

    «ДАВО» в наших даних історично означає Вінницьку — під ним лежить увесь
    матеріал ф.904 і ф.792. Тому Волинська мусить мати ВЛАСНЕ повне написання,
    і воно не сміє бути псевдонімом «ДАВО»: інакше волинська справа тихо
    ляже у вінницький архів, і побачити це нема як.
    """
    assert pk.resolve_code("ДАВоО") == "DAVOO"
    assert pk.repo_label("DAVOO") == "ДАВоО"
    assert "ДАВО" not in pk.repositories["DAVOO"].aliases


def test_no_archive_is_shown_under_a_spelling_that_does_not_exist(pk) -> None:
    """🔴 «ДАВО» серед скорочень архівів України немає ЗОВСІМ.

    Вінницька — ДАВіО, Волинська — ДАВоО; голе «ДАВО» це наш давній КОД, під
    яким лежать ключі сховища сторінок, і нічого більше. Показувати кодом
    неіснуючу абревіатуру означає навчати нею людину — а далі вона тією ж
    абревіатурою підпише виписку, і та не зійдеться ні з чим.

    Тому канонічним кодом став `DAVIO`, а давній `DAVO` лишився записом
    сумісності: давні шифри й ключі читаються, але нічого під неіснуючим
    скороченням не показується.
    """
    assert pk.repo_label("DAVIO") == "ДАВіО"
    assert pk.repo_label("DAVO") == "ДАВіО"
    assert "ДАВО" in pk.repositories["DAVIO"].aliases
    assert pk.resolve_code("ДАВО") == "DAVIO", "давні шифри мусять і далі читатись"
    assert "ДАВО" not in set(pk.repo_labels().values())


def test_one_archive_under_two_codes_lands_in_one_place(pk) -> None:
    """🔴 `DAVO` і `DAVIO` — той самий архів, і зворотний пошук мусить давати
    один код, а не той, що трапився в словнику пізніше.

    Інакше та сама книга, занесена «ДАВіО 904-24-5», лягала б то в один архів,
    то в сусідній — залежно від порядку ключів, тобто ні від чого.
    """
    from nyshporka.pagestore.store import _label2repo

    lab = _label2repo()
    assert pk.canon_repo("DAVO") == "DAVIO"
    assert lab["давіо"] == "DAVIO"
    assert lab["даво"] == "DAVIO"
    assert lab["давоо"] == "DAVOO", "Волинь не сміє злитись із Вінницею"


def test_a_short_code_does_not_claim_a_random_folder() -> None:
    """🔴 «ДАК» і «ДАС» — три літери, і саме тому їх не можна шукати в будь-якому
    сегменті шляху: тека `das_kopii` ставала справою архіву Севастополя.

    Це той самий клас вади, від якого рятує сам цикл у `_repo_from_rel` (номер
    плівки FamilySearch ставав архівом), лише з протилежного боку.
    """
    from nyshporka.library import _repo_from_rel

    # Сегмент, що випадково склався в трилітерний код, більше не перехоплює
    # справу в архіву, названого далі по шляху.
    assert _repo_from_rel("архів/das_kopii/dahmo_315/spr-1") == "DAHMO"
    assert _repo_from_rel("архів/dak-2024/anrm/villages") == "ANRM"
    # А в СВОЇЙ позиції — slug'ом одразу під `raw` — короткий код робочий.
    assert _repo_from_rel("data/raw/dak/spr-1") == "DAK"
    # І довгий код упізнається будь-де, як і раніше.
    assert _repo_from_rel("том/moldavian/ANRM_134-2/raw/2362410") == "ANRM"
    assert _repo_from_rel("data/raw/dahmo_315/spr-8433") == "DAHMO"


# ── мішане письмо ────────────────────────────────────────────────────────────
# 🔴 Звіт користувача 29.08.2026: справа з ключем «ДАКО 705-1-1» не заводилась
# узагалі, а відмова цитувала введене — тобто на екрані стояло «не видно
# архіву» під написом «ДАКО», який людина ввела правильно. Причина: одна літера
# латинська. Шифри копіюють із сайтів архівів і з Word, де мішане письмо
# буденна річ, і на екрані підміна не видна НІКОЛИ.
MIXED_KEY_SPELLINGS = {
    "чиста кирилиця": "ДАКО 705-1-1",
    "латинська K": "ДАKО 705-1-1",
    "латинська O": "ДАКO 705-1-1",
    "латинська A": "ДAКО 705-1-1",
    "ZWSP після назви": "ДАКО​ 705-1-1",
    "крапка після назви": "ДАКО. 705-1-1",
}


@pytest.mark.parametrize("why", sorted(MIXED_KEY_SPELLINGS))
def test_a_key_that_looks_right_is_accepted_however_it_was_typed(why: str) -> None:
    """Усі шість написань виглядають на екрані ОДНАКОВО — отже й діяти мусять однаково."""
    from nyshporka.cases.register import parse_shifra

    got = parse_shifra(MIXED_KEY_SPELLINGS[why])
    assert (got.repo, got.fond, got.opys, got.spr) == ("DAKO", "705", "1", "1"), why


def test_mixed_script_never_invents_an_archive_that_is_not_in_the_pack() -> None:
    """🔴 Зведення письма — не здогад. Невідомий архів лишається невідомим.

    Інакше правка проти глухої відмови породила б гіршу ваду: тихо підставлений
    сусідній код, під яким справа лягла б у чужий облік.
    """
    from nyshporka.cases.register import RegisterError, parse_shifra

    with pytest.raises(RegisterError) as e:
        parse_shifra("ДАЩO 705-1-1")     # ДАЩО з латинською «O»
    assert "невідомий" in str(e.value)


def test_pure_latin_codes_survive_the_folding() -> None:
    """Чисто латинські коди в словнику є самі по собі — зводити їх не можна."""
    from nyshporka.cases.register import parse_shifra

    assert parse_shifra("DAHMO 315-1-8433").repo == "DAHMO"
    assert parse_shifra("ANRM 211-3-140").repo == "ANRM"


def test_the_refusal_names_the_latin_letters_it_saw() -> None:
    """Відмова мусить НАЗВАТИ підміну: на екрані її не видно.

    Доти повідомлення описувало стан, якого не існує («додайте назву архіву»
    там, де назва стояла), і людині не було з чого зрозуміти, що не так.
    """
    from nyshporka.cases.register import RegisterError, parse_shifra

    with pytest.raises(RegisterError) as e:
        parse_shifra("ДАЩO 705-1-1")
    assert "O" in str(e.value) and "латинськ" in str(e.value)


# ── дописаний архів ──────────────────────────────────────────────────────────
def test_adding_an_archive_survives_a_comma_in_its_name(tmp_path) -> None:
    """🔴🔴 Найдорожча вада кнопки «додати архів», якби її не спіймали.

    Значення підставлялось у YAML як є, тож «Archiwum Główne Akt Dawnych,
    Warszawa» робило накладку нечитабельною. А `_read` на помилці розбору
    віддає ПОРОЖНЬО — тобто пак ставав порожнім УВЕСЬ, і після цього не
    заводилась жодна шифра, навіть вбудованих архівів. Кома в назві архіву не
    екзотика; ціна їй була б рівно та вада, проти якої писалась уся ця правка,
    лише запущена власною кнопкою.
    """
    from nyshporka.archives import pack as P
    from nyshporka.cases.register import parse_shifra
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.add_repository("AGAD", "AGAD", "Archiwum Główne Akt Dawnych, Warszawa", "PL")

    assert parse_shifra("AGAD 1-2-3").repo == "AGAD"
    # І головне: вбудовані архіви живі. Саме це ламалось непомітно.
    assert parse_shifra("ДАХмО 315-1-8433").repo == "DAHMO"


@pytest.mark.parametrize("name", [
    'Archiwum: "Cyfrowe"',       # двокрапка й лапки — обидві ламають flow-мапу
    "Архів #1, {особливий}",     # решітка й дужки
    "Archiwum\tz табуляцією",
])
def test_no_punctuation_in_a_name_can_empty_the_pack(tmp_path, name) -> None:
    from nyshporka.archives import pack as P
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.add_repository("XARCH", "XARCH", name, "PL")
    pk = P.active()
    assert "XARCH" in pk.repositories, name
    assert "DAHMO" in pk.repositories, f"пак спорожнів через «{name}»"
    assert pk.repositories["XARCH"].name == name, "назву перекручено"


def test_a_broken_overlay_is_rolled_back_not_left_broken(tmp_path, monkeypatch) -> None:
    """🔴 Якщо запис усе-таки зробив файл нечитабельним — повертаємо як було.

    Лишити людину з побитою накладкою й порадою «перевірте текстом» означало б
    зламати їй застосунок кнопкою: доки файл не полагоджено руками, не
    заводиться жодна шифра.
    """
    from nyshporka.archives import pack as P
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.add_repository("AGAD", "AGAD", "Archiwum", "PL")
    was = P.overlay_path().read_text(encoding="utf-8")

    # Імітуємо запис, що ламає YAML, — так, як це зробила б будь-яка майбутня
    # регресія в складанні рядка.
    monkeypatch.setattr(P, "_norm_word", P._norm_word)          # no-op, для ясності
    orig = P.Path.write_text

    def broken(self, data, *a, **kw):                            # type: ignore[no-untyped-def]
        if self.name == P.WORKSPACE_PACK and "NAC" in str(data):
            data = "repositories: [цe: не: мапа\n"
        return orig(self, data, *a, **kw)

    monkeypatch.setattr(P.Path, "write_text", broken)
    with pytest.raises(P.PackError):
        P.add_repository("NAC", "NAC", "Narodowe", "PL")
    monkeypatch.setattr(P.Path, "write_text", orig)

    assert P.overlay_path().read_text(encoding="utf-8") == was, "файл лишили побитим"
    assert "DAHMO" in P.active().repositories, "пак лишився порожнім"


def test_an_archive_added_now_is_visible_to_every_reader_now(tmp_path) -> None:
    """🔴 «✅ додано» і «невідомий архів» в одній сесії — це поламка, а не примха.

    Словники архівів у `library` й `pagestore` збирались НА РІВНІ МОДУЛЯ, тобто
    заморожувались при імпорті. У довгому демоні це означало: людина тисне
    «Додати архів», дістає підтвердження, заводить справу — і сховище сторінок
    відповідає «невідомий архів», бо його знімок старший за кнопку. Лікувалось
    лише перезапуском, про який ніщо не повідомляло.
    """
    from nyshporka.archives import pack as P
    from nyshporka.core import workspace as W
    from nyshporka.library import _canon_repo
    from nyshporka.pagestore.store import _label2repo

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    assert _canon_repo("AGAD") == "AGAD", "код невідомого архіву лишається як є"
    P.add_repository("AGAD", "AGAD", "Archiwum Główne Akt Dawnych", "PL")

    assert _label2repo().get("agad") == "AGAD", "сховище сторінок не бачить нового архіву"
    assert _canon_repo("agad") == "AGAD", "бібліотека не бачить нового архіву"


@pytest.mark.parametrize("shape", [
    "version: 1\nrepositories:\n  OLD: {label: OLD}\n",
    "version: 1\nrepositories :\n  OLD: {label: OLD}\n",
    "version: 1\nrepositories:  # мої архіви\n  OLD: {label: OLD}\n",
    "version: 1\nrepositories:\n  OLD: {label: OLD}",          # без переводу в кінці
])
def test_a_second_archive_never_erases_the_first(tmp_path, shape) -> None:
    """🔴🔴 Найтихіша втрата з можливих: дописаний архів стирав усі попередні.

    Якір шукався ТОЧНИМ рядком «repositories:». `repositories :` і
    `repositories:  # коментар` — валідний YAML, який ця перевірка не впізнавала,
    після чого дописувався ДРУГИЙ верхньорівневий ключ. PyYAML дублікат приймає
    й лишає останній: файл читається, наш архів на місці, приймач задоволений —
    а все, що дослідник додав раніше, зникає без жодного слова.
    """
    from nyshporka.archives import pack as P
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / P.WORKSPACE_PACK).write_text(shape, encoding="utf-8")
    P.reset()

    P.add_repository("NEW", "NEW", "Новий", "PL")
    got = P.active().repositories
    assert "NEW" in got, "новий архів не додався"
    assert "OLD" in got, f"попередній архів зник: {shape!r}"
    assert "DAHMO" in got, "вбудовані архіви зникли"


def test_an_unrecognisable_repositories_block_is_refused_not_duplicated(tmp_path) -> None:
    """Плаский запис блока дописати рядком не можна — і вдавати, що можна, гірше
    за відмову: другий ключ мовчки заміщає перший."""
    from nyshporka.archives import pack as P
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / P.WORKSPACE_PACK).write_text(
        "version: 1\nrepositories: {OLD: {label: OLD}}\n", encoding="utf-8")
    P.reset()

    with pytest.raises(P.PackError) as e:
        P.add_repository("NEW", "NEW", "Новий", "PL")
    assert "руками" in str(e.value)
    assert "OLD" in P.active().repositories, "чужий запис усе одно постраждав"
