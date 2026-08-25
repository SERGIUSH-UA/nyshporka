"""🧩 Секції застосунку — що з нього ввімкнено на цій машині.

Нишпорку ставлять дуже різні люди. Один прийшов подивитись, у якому фонді
лежать метрики його села, і сканів у нього немає взагалі. Другий має три тисячі
кадрів і відеокарту. Третій — автор, якому потрібна лабораторія. Досі всі троє
бачили однаковий застосунок, і кожен зайвий екран коштував дорожче, ніж
здається:

* екран «Читання» на машині без рушіїв — це обіцянка без входу, той самий клас
  вад, проти якого написано `test_no_dead_ends`;
* `torch` в інсталяторі — 2.5 ГБ тому, хто не збирався читати рукопис;
* лабораторним речам (спотер, синтетика, трен) не було куди приїхати з
  приватного репозиторію: у продуктовому UI не існувало поняття «це не для всіх».

Секція — набір ЕКРАНІВ і ОПЕРАЦІЙ, який вмикається одним рішенням у профілі
простору. Тут — самі дані й чисті функції над ними: ні читання файлів, ні
реєстру операцій. Так модуль лишається перевірюваним без простору, а профіль
читає `core.workspace`, який і так уміє маркер.

🔴 Секція `core` вимкненню не підлягає. Без неї немає ні переліку справ, ні
черги робіт, ні перевірки машини — тобто немає застосунку, а є набір екранів,
у яких нічого не відкрити.

🔴 Оголошена секція ≠ показана секція. `lab` існує тут як МІСЦЕ для спотера й
трену, які ще живуть у приватному репозиторії. Поки в ній немає жодної
операції, вона не потрапляє в навігацію: порожня вкладка — це та сама обіцянка
без входу. Коли спотер переїде, він додасться сюди даними, а не новим
механізмом.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Пресет, який діє, коли профіль мовчить. Саме `researcher` — щоб поява
#: механізму НЕ змінила поведінку просторів, чий маркер про секції нічого не
#: знає: усі наявні простори такі, і мовчазне звуження застосунку після
#: оновлення виглядало б як зникла половина програми.
DEFAULT_PRESET = "researcher"


@dataclass(frozen=True)
class Section:
    """Секція застосунку. Ярлики тут обома мовами, бо їх читає і CLI, і фронт."""

    id: str
    label_uk: str
    label_en: str
    #: Навіщо секція — рядок для екрана налаштувань і `nysh sections`.
    why_uk: str
    why_en: str
    #: Чи можна вимкнути. Незнімна рівно одна — `core`.
    required: bool = False

    def label(self, lang: str = "uk") -> str:
        return self.label_en if lang == "en" else self.label_uk

    def why(self, lang: str = "uk") -> str:
        return self.why_en if lang == "en" else self.why_uk


SECTIONS: tuple[Section, ...] = (
    Section(
        id="core",
        label_uk="Основа", label_en="Core",
        why_uk="Справи, черга робіт, перевірка машини. Без цього застосунку немає.",
        why_en="Cases, job queue, machine check. Without it there is no app.",
        required=True,
    ),
    Section(
        id="material",
        label_uk="Матеріали", label_en="Materials",
        why_uk="Де взагалі є документи: каталоги архівів, газетир, описи фондів, "
               "завантаження справ.",
        why_en="Where the documents are at all: archive catalogues, gazetteer, "
               "fond inventories, downloading cases.",
    ),
    Section(
        id="htr",
        label_uk="Читання", label_en="Reading",
        why_uk="Машинне читання рукопису й гортач сторінок. Потребує рушіїв "
               "(`nysh htr install`).",
        why_en="Machine reading of handwriting and the page viewer. Needs the "
               "engines (`nysh htr install`).",
    ),
    Section(
        id="research",
        label_uk="Дослідження", label_en="Research",
        why_uk="Пошук прізвища в прочитаному, облік переглянутого оком, експорт.",
        why_en="Searching a surname in what was read, tracking what the eye has "
               "seen, export.",
    ),
    Section(
        id="lab",
        label_uk="Лабораторія", label_en="Lab",
        why_uk="Розмітка, синтетика, тренування моделей. Поки порожня — місце "
               "для того, що ще не приїхало.",
        why_en="Annotation, synthetic data, model training. Empty for now — a "
               "place for what has not arrived yet.",
    ),
)

#: Пресети — те, що обирають у майстрі першого запуску. Не «рівні доступу»:
#: людина будь-коли вмикає окрему секцію поверх пресету.
#:
#: 🔴 `catalog` існує не для повноти ряду. Це єдиний набір БЕЗ читання, тобто
#: єдиний, який не тягне torch (~2.5 ГБ), — і він точно описує найпершого
#: відвідувача: у нього ще немає ні сканів, ні відеокарти, він питає «де взагалі
#: метрики мого села». Обидва вкладені зрізи відповідають на це одразу після
#: встановлення, тож набір робочий, а не урізаний.
PRESETS: dict[str, frozenset[str]] = {
    "catalog": frozenset({"core", "material"}),
    "amateur": frozenset({"core", "material", "htr"}),
    "researcher": frozenset({"core", "material", "htr", "research"}),
    "lab": frozenset({"core", "material", "htr", "research", "lab"}),
}

#: Extras пакета, потрібні секції. Порожньо — вистачає ядра.
#: Читає інсталятор: ставити 2.5 ГБ рушіїв тому, хто їх вимкнув, немає підстав.
EXTRAS: dict[str, tuple[str, ...]] = {
    "core": ("app",),
    "material": ("archives",),
    "htr": ("htr",),
    "research": (),
    "lab": (),
}


def extras_for(active: Iterable[str]) -> tuple[str, ...]:
    """Extras, які треба поставити для цих секцій — у порядку оголошення."""
    on = frozenset(active)
    out: list[str] = []
    for sec in SECTIONS:
        if sec.id not in on:
            continue
        out += [x for x in EXTRAS.get(sec.id, ()) if x not in out]
    return tuple(out)


def install_target(preset: str) -> str:
    """Рядок для `pip install` під пресет: `nyshporka[app,archives]`."""
    extras = extras_for(preset_sections(preset))
    return f"nyshporka[{','.join(extras)}]" if extras else "nyshporka"

#: Екран фронту → секція. Джерело правди ОДНЕ й лежить тут, а не в `app.js`:
#: друга копія розходиться тихо, і розходження виглядає як зникла кнопка.
SCREENS: dict[str, str] = {
    "home": "core",
    "cases": "core",
    "newcase": "core",
    "jobs": "core",
    "sources": "material",
    "geog": "material",
    "fonds": "material",
    "library": "material",
    "read": "htr",
    # 🔴 Перелік прогонів належить «Читанню», а не «Дослідженню»: він
    # відповідає на питання «що ця машина вже прочитала», і потрібен
    # саме тому, хто читає скани й ще не брався за пошук прізвища. У
    # дослідницькій секції він зник би з набору «аматор».
    "runs": "htr",
    "view": "htr",
    "search": "research",
    "sift": "research",
    "eye": "research",
    "export": "research",
}


class SectionError(ValueError):
    """Невідома секція або пресет — із переліком того, що є."""


# ── довідки ──────────────────────────────────────────────────────────────────
def all_sections() -> tuple[Section, ...]:
    return SECTIONS


def ids() -> frozenset[str]:
    return frozenset(s.id for s in SECTIONS)


def get(section_id: str) -> Section | None:
    return next((s for s in SECTIONS if s.id == section_id), None)


def required_ids() -> frozenset[str]:
    return frozenset(s.id for s in SECTIONS if s.required)


def preset_names() -> tuple[str, ...]:
    return tuple(PRESETS)


def screens_of(section_id: str) -> tuple[str, ...]:
    return tuple(scr for scr, sec in SCREENS.items() if sec == section_id)


# ── розв'язання профілю ──────────────────────────────────────────────────────
def preset_sections(name: str) -> frozenset[str]:
    """Секції пресету. Незнайомий пресет — помилка з переліком, не тихий дефолт."""
    got = PRESETS.get(name)
    if got is None:
        raise SectionError(
            f"невідомий пресет «{name}». Є: {', '.join(sorted(PRESETS))}")
    return got | required_ids()


def unknown(names: Iterable[str]) -> tuple[str, ...]:
    """Те з переліку, чого не існує. Порожній кортеж — усе гаразд."""
    known = ids()
    return tuple(sorted({str(n) for n in names} - known))


def resolve(*, preset: str | None = None,
            explicit: Iterable[str] | None = None) -> frozenset[str]:
    """Активні секції з профілю.

    Порядок джерел: явний перелік перебиває пресет, пресет перебиває дефолт.
    Обов'язкові додаються завжди — маркер, у якому забули `core`, має дати
    робочий застосунок, а не порожню шапку.

    🔴 Невідоме ім'я — помилка, а не тиха втрата. Людина, яка написала в
    маркері `htr` замість `reading`, мусить це побачити; мовчазне «взяли
    дефолт» виглядає як «застосунок не слухає, що я пишу».
    """
    if explicit is not None:
        names = {str(s).strip() for s in explicit if str(s).strip()}
        bad = unknown(names)
        if bad:
            raise SectionError(
                f"невідомі секції: {', '.join(bad)}. Є: {', '.join(sorted(ids()))}")
        return frozenset(names) | required_ids()
    return preset_sections(preset or DEFAULT_PRESET)


def preset_of(active: Iterable[str]) -> str | None:
    """Ім'я пресету, який дає рівно цей набір, або `None` для власного набору."""
    got = frozenset(active) | required_ids()
    return next((n for n, s in PRESETS.items() if (s | required_ids()) == got), None)
