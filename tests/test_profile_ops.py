"""🎯 Профіль роду: завести з вікна — і не втратити те, що написано рукою.

Три властивості, без яких ця форма шкідливіша за її відсутність:

    вихід    — «профілю немає» віддає ДАНІ для форми, а не голу відмову;
    цілість  — файл із коментарями формою не переписується НІКОЛИ;
    приймач  — сирий текст лягає на диск лише тоді, коли він резолвиться.

Друга найважливіша. Конфіг дослідника — це до сотні рядків, у яких коментарями
записані заміри («668 хітів → 662»). Прохід через дамп лишає файл валідним і
стирає їх усі: жоден автоматичний приймач такої втрати не бачить, а помічають
її через тиждень, коли відновити нема з чого.
"""
from __future__ import annotations

from pathlib import Path

import pytest

#: Файл, писаний рукою: коментар із заміром, конфузери й рецепт синтетики —
#: тобто рівно те, чого форма не знає й не має права зачепити.
HAND = """\
# Чий рід шукаємо.
fallback: rid

profiles:
  rid:
    surname:
      display: Ярошинський
      paradigm: adj_skyi
      stems:
        uk: Ярошин
      # 🔴 ф.474-1-192 кадр 00090 (звірено оком): «Жолынвскій» дав full=85.7
      confusers:
        - zolynwskiego
    synth:
      - ["nom_m@uk", 1.0]
"""


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    (tmp_path / "config").mkdir(parents=True)
    P.reset()
    yield tmp_path
    P.reset()
    W.reset()


def _call(name: str, payload: dict | None = None):
    from nyshporka import ops as O

    return O.call(name, payload or {})


# ── вихід із порожнього стану ────────────────────────────────────────────────
def test_no_profile_is_an_answer_not_a_refusal(space):
    """🔴 Та сама вада, що вже виправлена в `cases.list`.

    Конверт відмови не має `data` — отже, саме тоді, коли треба намалювати
    форму заведення, екран не діставав ні переліку парадигм, ні шляху до файла,
    ні кнопки. Вихід зникав рівно там, де був потрібен.
    """
    env = _call("profile.show")
    assert env.ok, env.error
    d = env.data
    assert d["present"] is False and d["why"]
    assert d["paradigms"] and d["orthographies"]        # форму є з чого зібрати
    assert d["path"].endswith("research_profile.yaml")
    assert [w.code for w in env.warnings] == ["no_profile"]
    assert [n.op for n in env.next] == ["profile.set"]


def test_the_warning_does_not_invent_a_stranger(space):
    """🔴 Тут стояло «пошук працюватиме на прізвище чужого дослідження».

    Це неправда: `q` у пошуку обов'язкове, дефолтного прізвища в пакеті немає
    ніде. Попередження лякало вигаданим ризиком і ховало справжній — тож текст
    не має права повернутись.
    """
    text = " ".join(w.text for w in _call("profile.show").warnings)
    assert "чуж" not in text, text
    assert "написання" in text


# ── заведення ────────────────────────────────────────────────────────────────
def test_creating_a_profile_gives_spellings_right_away(space):
    env = _call("profile.set", {"display": "Ліщинський",
                                "stems": {"pl": "Liszczyn"},
                                "roots": ["лищинськ"]})
    assert env.ok, env.error
    d = env.data
    assert d["mode"] == "created" and d["present"] is True
    # Приймач кроку зі скіла: людина мусить упізнати своє в породжених формах.
    assert "Ліщинський" in d["spellings"]
    assert any(x.startswith("Liszczyn") for x in d["spellings"])
    assert Path(d["path"]).is_file()


def test_a_missing_stem_is_named_out_loud(space):
    """⚠ Без основи на дореформену орфографію метрики XIX ст. не шукаються.

    Мовчання тут коштує найдорожче: пошук працює, нуль виглядає як відповідь,
    а половини написань ніхто й не питав.
    """
    env = _call("profile.set", {"display": "Ліщинський"})
    codes = [w.code for w in env.warnings]
    assert "stems_partial" in codes
    assert "ru_prereform" in " ".join(w.text for w in env.warnings)


def test_a_second_profile_lands_next_to_the_first(space):
    _call("profile.set", {"display": "Ліщинський"})
    env = _call("profile.set", {"display": "Сікорський"})
    assert env.ok and env.data["mode"] == "added"
    names = [x["name"] for x in _call("profile.show").data["available"]]
    assert names == ["ліщинський", "сікорський"]
    # Активним лишається перший: `fallback` уже стоїть, і мовчки переставляти
    # його означало б завтра шукати інший рід і ніде про це не сказати.
    assert _call("profile.show").data["display"] == "Ліщинський"


def test_an_empty_surname_is_refused(space):
    env = _call("profile.set", {"display": "   "})
    assert not env.ok and "порожнє" in env.error


# ── цілість написаного рукою ─────────────────────────────────────────────────
def test_a_hand_written_file_is_never_rewritten_by_the_form(space):
    """🔴 Головний приймач цього модуля.

    Форма знає п'ять полів. Файл дослідника має ще шість, і в коментарях біля
    них лежать заміри. Дамп лишив би файл валідним і стер би все інше — тобто
    втрата була б тихою і повною.
    """
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(HAND, encoding="utf-8")
    from nyshporka.core import profile as P

    P.reset()
    # Ім'я передається так само, як його передає екран: він бере його з
    # показаного профілю, а не вигадує з прізвища — інакше правка мовчки
    # заводила б ДРУГИЙ профіль замість того, який людина щойно бачила.
    env = _call("profile.set", {"name": "rid", "display": "Ярошинський",
                                "stems": {"uk": "Ярошин", "pl": "Jaroszyn"}})
    assert not env.ok, "форма переписала файл, писаний рукою"
    assert cfg.read_text(encoding="utf-8") == HAND, "файл усе одно зачепило"
    assert [n.op for n in env.next] == ["profile.source"]


def test_a_field_the_form_does_not_know_blocks_the_write(space):
    """Навіть без коментарів: зникнути не має право й саме поле."""
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(
        "fallback: rid\nprofiles:\n  rid:\n    surname:\n"
        "      display: Ярошинський\n      paradigm: adj_skyi\n"
        "      stems:\n        uk: Ярошин\n"
        "      confusers:\n        - zolynwskiego\n", encoding="utf-8")
    from nyshporka.core import profile as P

    P.reset()
    was = cfg.read_text(encoding="utf-8")
    env = _call("profile.set", {"name": "rid", "display": "Ярошинський",
                                "stems": {"uk": "Ярошин", "pl": "Jaroszyn"}})
    assert not env.ok and "не лише те, що показано" in env.error
    assert cfg.read_text(encoding="utf-8") == was


def test_a_profile_the_form_made_stays_editable(space):
    """⚠ Зворотний бік: якби відмовляло завжди, форма правила б лише раз."""
    _call("profile.set", {"display": "Ліщинський", "roots": ["лищинськ"]})
    env = _call("profile.set", {"name": "ліщинський", "display": "Ліщинський",
                                "stems": {"pl": "Liszczyn"},
                                "roots": ["лищинськ", "ищинс"]})
    assert env.ok, env.error
    assert env.data["mode"] == "updated"
    assert env.data["stems"]["pl"] == "Liszczyn"
    assert env.data["roots"] == ["лищинськ", "ищинс"]
    # Пояснення заготовки лишились на місці — вони теж коментарі.
    assert "🔴 Основа" in Path(env.data["path"]).read_text(encoding="utf-8")


# ── сирий текст ──────────────────────────────────────────────────────────────
def test_the_source_is_read_without_writing(space):
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(HAND, encoding="utf-8")
    env = _call("profile.source", {})
    assert env.ok and env.data["written"] is False
    assert env.data["text"] == HAND
    assert "read_only" in [w.code for w in env.warnings]


def test_broken_yaml_never_reaches_the_disk(space):
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(HAND, encoding="utf-8")
    env = _call("profile.source", {"text": "profiles: [обірвано\n"})
    assert not env.ok and "YAML" in env.error
    assert cfg.read_text(encoding="utf-8") == HAND


def test_valid_yaml_that_does_not_resolve_is_refused_too(space):
    """🔴 Дві перевірки, а не одна.

    Файл, у якому `fallback` показує в нікуди, читається без помилки й
    ламається аж у пошуку — тобто далеко від того місця, де його зіпсували.
    """
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(HAND, encoding="utf-8")
    env = _call("profile.source", {"text": "fallback: нема\nprofiles: {}\n"})
    assert not env.ok and "немає профілю" in env.error
    assert cfg.read_text(encoding="utf-8") == HAND


def test_the_previous_version_is_kept(space):
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(HAND, encoding="utf-8")
    env = _call("profile.source", {"text": HAND.replace("Ярошин", "Ярошын")})
    assert env.ok, env.error
    assert (space / "config" / "research_profile.yaml.bak").read_text(
        encoding="utf-8") == HAND


def test_a_broken_file_is_a_state_of_its_own(space):
    """🔴 «Не читається» і «немає» лікуються по-різному.

    Перше — правкою тексту, друге — заведенням. Показати перше як друге
    означає послати людину заводити наново поверх того, що вже є.
    """
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text("profiles: [обірвано\n", encoding="utf-8")
    from nyshporka.core import profile as P

    P.reset()
    env = _call("profile.show")
    assert env.ok, env.error
    assert env.data.get("broken"), env.data
    # Текст усе одно віддається — інакше редактор не покаже, що саме лагодити.
    assert env.data["source"] == "profiles: [обірвано\n"


# ── командний рядок і вікно роблять те саме ──────────────────────────────────
def test_the_cli_writes_through_the_same_operation(space):
    """🔴 Реєстр операцій існує саме для цього: дія оголошується один раз.

    Доти `nysh profile init` писав файл повз нього, тобто той самий запис жив
    у двох місцях — і розійтись вони могли мовчки.
    """
    import re
    from pathlib import Path as _P

    cli = (_P(__file__).resolve().parents[1]
           / "src" / "nyshporka" / "cli.py").read_text(encoding="utf-8")
    block = cli[cli.index('@profile_app.command("init")'):]
    block = block[:block.index("\ndef profile_cmd")]
    assert 'O.call("profile.set"' in block
    assert not re.search(r"\bwrite_config\b", block)


# ── тиха втрата: основа є, а таблиці для неї немає ───────────────────────────
def test_a_stem_the_paradigm_cannot_decline_is_said_out_loud(space):
    """🔴 Найтихіша втрата з усіх, які тут бувають.

    `Paradigm.forms()` на невідомій орфографії повертає порожньо БЕЗ помилки, а
    `all_spellings()` просто ітерує по заданих основах. Тож профіль із
    польською основою і парадигмою, у якої польської таблиці немає, давав нуль
    польських написань — і жодної ознаки, що щось загубилось. Людина бачить
    список написань, вважає його повним і закриває напрям, якого не шукали.

    Сусідній приймач (`stems_partial`) ловить ЗВОРОТНИЙ випадок — основи немає.
    На цей не було нічого.
    """
    env = _call("profile.set", {"display": "Іванов", "paradigm": "noun_ov",
                                 "orth": "ru_prereform",
                                 "stems": {"ru_prereform": "Иванов",
                                           "pl": "Iwanow"}})
    assert env.ok, env.error
    codes = {w.code for w in env.warnings}
    assert "paradigm_gap" in codes, (
        f"про непокриту орфографію не сказано нічого: {codes}")
    gap = next(w for w in env.warnings if w.code == "paradigm_gap")
    assert "pl" in gap.text and "noun_ov" in gap.text


def test_a_paradigm_that_covers_everything_stays_quiet(space):
    """Попередження мусить мовчати там, де втрати немає, — інакше його
    перестануть читати."""
    env = _call("profile.set", {"display": "Лут", "paradigm": "noun_bare",
                                 "orth": "ru_prereform",
                                 "stems": {"ru_prereform": "Лут", "uk": "Лут"}})
    assert env.ok, env.error
    assert "paradigm_gap" not in {w.code for w in env.warnings}
    # І та сама перевірка по суті: жіноче написання справді породилось.
    assert "Лутова" in env.data["spellings"], env.data["spellings"]
