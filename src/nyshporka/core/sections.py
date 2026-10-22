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

Секція — набір екранів і операцій, який вмикається одним рішенням у профілі
простору. Тут — самі дані й чисті функції над ними: ні читання файлів, ні
реєстру операцій. Так модуль лишається перевірюваним без простору, а профіль
читає `core.workspace`, який і так уміє маркер.

🔴 Секція `core` вимкненню не підлягає. Без неї немає ні переліку справ, ні
черги робіт, ні перевірки машини — тобто немає застосунку, а є набір екранів,
у яких нічого не відкрити.

🔴 Оголошена секція ≠ показана секція. `lab` існує тут як місце для спотера й
трену, які ще живуть у приватному репозиторії. Поки в ній немає жодної
операції, вона не потрапляє в навігацію: порожня вкладка — це та сама обіцянка
без входу. Коли спотер переїде, він додасться сюди даними, а не новим
механізмом.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Пресет, який діє, коли профіль мовчить. Саме `researcher` — щоб поява
#: механізму не змінила поведінку просторів, чий маркер про секції нічого не
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
        why_uk="Розмітка рядків і навчання Писаря на своїх почерках "
               "(`nysh train`).",
        why_en="Line annotation and training the Cyrillic engine on your own "
               "hands (`nysh train`).",
    ),
)

#: Пресети — те, що обирають у майстрі першого запуску. Не «рівні доступу»:
#: людина будь-коли вмикає окрему секцію поверх пресету.
#:
#: 🔴 `catalog` існує не для повноти ряду. Це єдиний набір без читання, тобто
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
    "lab": ("train",),
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

#: Екран фронту → секція. Джерело правди одне й лежить тут, а не в `app.js`:
#: друга копія розходиться тихо, і розходження виглядає як зникла кнопка.
SCREENS: dict[str, str] = {
    "home": "core",
    "cases": "core",
    "newcase": "core",
    # Новий проєкт — вікно з Огляду Майстерні (`SCREEN_ACTION`), не вкладка.
    "newproject": "core",
    "jobs": "core",
    # 🔴 «Рід» у `core`, а не в «Дослідженні»: він вирішує, як працює пошук,
    # і замкнути його всередині секції, яку вимикають, означало б «увімкни
    # частину застосунку, щоб налаштувати те, від чого вона залежить».
    "profile": "core",
    "sources": "material",
    "geog": "material",
    "fonds": "material",
    "library": "material",
    # 🔴 Перегляд аркушів належить «Матеріалам», а не «Читанню»: він
    # відповідає на питання «що це за папери» й не потребує прогону.
    # У секції читання він зник би в того, хто ще нічого не читав —
    # тобто рівно в того, кому найпотрібніший.
    "frames": "material",
    "read": "htr",
    # 🔴 Перелік прогонів належить «Читанню», а не «Дослідженню»: він
    # відповідає на питання «що ця машина вже прочитала», і потрібен
    # саме тому, хто читає скани й ще не брався за пошук прізвища. У
    # дослідницькій секції він зник би з набору «аматор».
    "runs": "htr",
    # Черга справ — поруч із читанням: це те саме читання, лише кількох справ
    # поспіль і з рештою кроків навколо нього.
    "queue": "htr",
    "view": "htr",
    # 🔴 «Пошук» — в основі: заради нього застосунок і ставлять («Нишпорка» —
    # той, хто шукає). У «Дослідженні» його не було в пресеті `amateur`, який
    # читає рукописи, — тобто прочитане не було чим шукати.
    "search": "core",
    "sift": "research",
    "eye": "research",
    "export": "research",
    # Сайт родини збирається з канону — тієї самої секції, що веде канон.
    "site": "research",
    # Закладки роду на Огляді проєкту (хвиля 7в).
    "canon": "research",
    "hyp": "research",
    "research": "research",
    "history": "research",
    "cloud": "htr",
    # Супряга: її операції (`share.*`) живуть у секції читання — вкладки теж,
    # інакше без читання вкладка вела б у відмову «секція вимкнена».
    "give": "htr",
    "pull": "htr",
    "cards": "htr",
    "sprofile": "htr",
    # lab
    "sets": "lab",
    "label": "lab",
}

#: Екрани поза секціями — доступні завжди.
#:
#: 🔴 `settings` не має гейта навмисно: саме ним вмикають і вимикають секції.
#: Замкнути його всередині секції означало б, що вимкнена секція неможливо
#: увімкнути назад — і виглядало б це як поламаний застосунок, а не як вибір.
UNGATED_SCREENS: frozenset[str] = frozenset({"settings"})


@dataclass(frozen=True)
class NavGroup:
    """Група бічного меню консолі.

    🔴 Меню ділиться за тим, ДЕ ЖИВУТЬ ДАНІ, а не за етапами роботи: людина
    мусить бачити, що належить роду, а що спільне на всю Майстерню (правила
    інтерфейсу, 22.10.2026; `docs/agents/screens.md`, «Три питання»). Блок —
    рівень меню з підписом, група — розкривний пункт усередині блоку. Секції
    лишаються тим, чим були: вимикачами частин застосунку. Екран вимкненої
    секції випадає з групи, а група без жодного екрана не показується.
    """

    id: str
    label_uk: str
    label_en: str
    screens: tuple[str, ...]
    #: блок меню: `own` — проєкт, `hub` — сама Майстерня, `shared`, `service`
    block: str = "shared"
    #: розкривна група з підписом; `False` — пункти стоять просто в блоці
    fold: bool = True

    def label(self, lang: str = "uk") -> str:
        return self.label_en if lang == "en" else self.label_uk


#: Блоки меню в порядку показу. `own` є лише в проєкті, `hub` — лише в
#: Майстерні без проєкту.
BLOCKS: tuple[str, ...] = ("own", "hub", "shared", "service")

#: Групи меню; екрани всередині — у порядку пунктів. Огляд стоїть у двох
#: блоках: у проєкті це Огляд роду, у Майстерні — Огляд Майстерні.
NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup("project", "Рід", "Family",
             ("home", "canon", "hyp", "sift", "research", "history", "site", "profile"),
             block="own", fold=False),
    NavGroup("hub", "Майстерня", "Workshop", ("home",), block="hub", fold=False),
    NavGroup("material", "Матеріали", "Materials",
             ("library", "cases", "frames", "sources", "geog", "fonds")),
    NavGroup("reading", "Читання", "Reading", ("read", "queue", "runs", "cloud", "view")),
    NavGroup("search", "Пошук", "Search", ("search", "eye")),
    NavGroup("share", "Супряга", "Commons", ("give", "pull", "cards")),
    NavGroup("service", "Сервіс", "Service", ("jobs", "export", "settings"),
             block="service", fold=False),
    NavGroup("lab", "Лабораторія", "Lab", ("sets", "label"), block="service"),
)

#: Екрани, що належать проєкту: у Майстерні без проєкту їх немає в меню, а
#: перехід на них показує вибір проєкту замість відмови операції.
PROJECT_SCREENS: frozenset[str] = frozenset(
    {"profile", "site", "sift", "canon", "hyp", "research", "history"})

#: Шар даних екрана — мітка в заголовку сторінки («де я»).
#:
#: `own` — висновки проєкту; `shared` — спільне Майстерні; `mixed` — спільне
#: з позначками для проєкту (бібліотека, пошук); `service` — робота машини;
#: `context` — Огляд: у проєкті це огляд роду, у Майстерні — її власний.
LAYERS: dict[str, str] = {
    **dict.fromkeys(PROJECT_SCREENS, "own"),
    "home": "context",
    **dict.fromkeys(("library", "search", "eye"), "mixed"),
    **dict.fromkeys(("sources", "geog", "fonds", "cases", "newcase", "frames", "read",
                     "queue", "runs", "cloud", "view", "export", "give", "pull", "cards",
                     "sprofile"), "shared"),
    **dict.fromkeys(("jobs", "sets", "label", "settings", "newproject"), "service"),
}

#: Дія сторінки — кнопкою в її заголовку.
#: 🔴 «Завести справу» стояла кроком «Нових тек», і людина її не знаходила
#: (чат Нишпорки, 19.10.2026); у шапці вона виявилась зайвою (дослідник,
#: 21.10.2026). Місце — сторінки, де з'являється матеріал. «Новий проєкт» —
#: лише в Майстерні без проєкту (вирішує консоль).
SCREEN_ACTION: dict[str, str] = {"library": "newcase", "cases": "newcase",
                                 "home": "newproject"}


def group_of(screen: str) -> str | None:
    """Група екрана; екран-крок (`newcase`) — група сторінки, що його відкриває.

    Огляд стоїть у двох блоках; тут — перший (проєктний), бо питання «до чого
    належить екран» для Майстерні й проєкту відповідає консоль.
    """
    for g in NAV_GROUPS:
        if screen in g.screens:
            return g.id
    for scr, act in SCREEN_ACTION.items():
        if act == screen:
            return group_of(scr)
    return None

#: Операція → екран, на якому людина її бачить.
#:
#: 🔴 Потрібна саме як дані, а не як угода про імена: `catalog.search` живе на
#: екрані «Джерела», `fond.rows` — на «Фондах», `cases.bind` — на «Прогонах».
#: Вивести це з імені неможливо, а вгадування дало б кнопку, яка веде не туди.
#:
#: Заради чого: конверт уже несе пораду «→ далі: <операція>» (`envelope.next`),
#: і командний рядок з агентом її друкують. Без цієї мапи браузер може лише
#: показати ім'я операції — тобто сказати людині те, чого вона не натисне.
OP_SCREEN: dict[str, str] = {
    "site.build": "site",
    "site.status": "site",
    "site.rebuild": "site",
    # core
    "workspace.info": "home",
    # Проєкти Майстерні: новий — вікном, перелік — картками на Огляді.
    "project.new": "newproject",
    "project.list": "home",
    "project.style": "home",
    # Огляд проєкту стоїть на «що вирішити».
    "canon.next": "home",
    # Закладки роду. Канон лише читається й перевіряється: картки веде агент
    # файлами, консоль кладе доказ у стор і дає доручення.
    "canon.check": "canon",
    "canon.cards": "canon",
    "canon.card": "canon",
    "evidence.add": "canon",
    "canon.hyps": "hyp",
    "canon.hyp": "hyp",
    "reports.list": "research",
    "reports.read": "research",
    "history.log": "history",
    "history.diff": "history",
    "history.save": "history",
    "history.restore": "history",
    "history.auto": "history",
    "cloud.state": "cloud",
    "cloud.go": "cloud",
    "cloud.stop": "cloud",
    "cloud.fetch": "cloud",
    "share.suggest": "give",
    "share.push": "give",
    "share.pack": "give",
    "share.pull": "pull",
    "share.import": "pull",
    "share.inspect": "pull",
    "share.list": "cards",
    "share.card": "cards",
    "share.withdraw": "cards",
    "share.setup": "sprofile",
    "share.stats": "sprofile",
    "setup.check": "home",
    "sample.install": "home",
    "profile.show": "profile",
    "profile.set": "profile",
    "profile.source": "profile",
    # ⬆️ Версія й оновлення — у налаштуваннях: питання про застосунок, а не
    # про дослідження.
    "update.check": "settings",
    "sections.show": "settings",
    "sections.set": "settings",
    "job.query": "jobs",
    "cases.list": "cases",
    "cases.build": "cases",
    "intake.list": "cases",
    "intake.aside": "cases",
    "case.show": "cases",
    "case.register": "newcase",
    "case.check": "newcase",
    "material.look": "newcase",
    # material
    "sources.list": "sources",
    "catalog.search": "sources",
    "catalog.sweep": "sources",
    "catalog.crawl": "sources",
    "catalog.browse": "sources",
    "catalog.manifest": "sources",
    "acquire.start": "sources",
    "catalog.packs": "geog",
    "geog.find": "geog",
    "geog.card": "geog",
    "geog.near": "geog",
    # ⛪ церкви ~1772 живуть на тому ж екрані, що й газетир: питання одне —
    # «що відомо про село», лише зріз інший (реєстри XVIII ст., не архів)
    "church.find": "geog",
    "church.card": "geog",
    "church.near": "geog",
    "fond.list": "fonds",
    "fond.rows": "fonds",
    "fond.take": "fonds",
    "archive.fond": "fonds",
    # 🔴 Обидві — на «Завести справу»: саме там валідатор вимагає назву архіву,
    # і саме там людина впирається, коли її архіву в паку немає.
    "archives.list": "newcase",
    "archive.add": "newcase",
    "registry.collectors": "fonds",
    "registry.plan": "fonds",
    "registry.collect": "fonds",
    "registry.merge": "fonds",
    "library.list": "library",
    "library.verdict": "library",
    "case.frames": "frames",
    "case.frame": "frames",
    # htr
    "htr.env": "read",
    "htr.case_info": "read",
    "read.plan": "read",
    "read.start": "read",
    "runs.list": "runs",
    "queue.status": "queue",
    "queue.add": "queue",
    "queue.retry": "queue",
    "queue.set": "queue",
    "queue.drop": "queue",
    "queue.stop": "queue",
    "queue.start": "queue",
    # 🔴 Прив'язка нічийного прогону — на «Прогонах», а не в «Моїх справах»:
    # питання «чия це робота» ставить саме той, хто дивиться на перелік
    # прогонів і бачить справу без шифри.
    "cases.bind": "runs",
    "page.text": "view",
    "page.lines": "view",
    "page.view": "view",
    # пошук — в основі (див. `SCREENS`)
    "search.run": "search",
    "search.find": "search",
    "search.scopes": "search",
    "search.index": "search",
    "search.state": "search",
    "text.grep": "search",
    "text.index": "search",
    "text.state": "search",
    "text.ctx": "search",
    "text.crop": "search",
    "text.voices": "search",
    "text.coverage": "search",
    "text.whatis": "search",
    "text.find": "search",
    "text.sheet": "search",
    "text.verdicts": "eye",
    "pages.status": "eye",
    "pages.note": "eye",
    "pages.show": "eye",
    "records.add": "eye",
    "export.case": "export",
    # lab
    "train.sets": "sets",
    "train.doctor": "sets",
    "train.cut": "sets",
    "train.voices": "sets",
    "train.glossary": "sets",
    "train.hint": "sets",
    "train.export": "sets",
    "train.import": "sets",
    "train.gates": "sets",
    "train.sheets": "sets",
    "train.queue": "label",
    "train.line": "label",
    "train.page": "label",
    "train.save": "label",
    "train.stats": "label",
    "train.suggest": "label",
    "train.view": "label",
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
