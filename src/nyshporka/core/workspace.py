"""🗂 Робочий простір — де лежать дані дослідження.

Досі відповідь була одна й неявна: «там, звідки запущено репозиторій». 23 модулі
рахували `ROOT = Path(__file__).resolve().parents[N]` кожен сам, і від нього —
`data/`, `reports/`. Поки код і дані живуть в одному дереві, це працює; щойно
пакет стає встановлюваним, `parents[N]` вказує в `site-packages`, де жодних
даних немає.

Тут з'являється явне поняття простору й **маркер-файл `nyshporka.toml`** у його
корені. Маркер, а не прихована тека (`.nyshporka/` губиться при копіюванні й
архівуванні) і не евристика «є тека data/» (вона є всюди).

🔑 Головне у цьому модулі — **останній фолбек**. Якщо ні аргументу, ні env, ні
маркера немає, простір береться з розташування самого пакета — тобто рівно так,
як його рахували всі 23 модулі досі. Тому переведення модуля на `workspace()`
не змінює жодного шляху доти, доки хтось свідомо не вкаже інший простір. Це
робить перехід нульового ризику: спершу з'являється механізм, і лише потім —
нова поведінка.

Три сутності, які досі були злиті в одному `ROOT`, тут розведені:

  простір  — скани, канон, звіти. Власність дослідника, він її бачить і переносить.
  ресурси  — шаблони, статика, дані пакета. Їдуть у wheel (див. `core.resources`).
  стан     — «який простір відкривали востаннє». Поза простором, у профілі ОС.
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

MARKER = "nyshporka.toml"

#: Простір беруть звідси, якщо не вказано інакше.
ENV_WORKSPACE = "NYSHPORKA_WORKSPACE"
#: Додаткові корені зі справами поза простором (архів на іншому диску).
ENV_CASE_ROOTS = "NYSHPORKA_CASE_ROOTS"
#: Застарілі аліаси з дослідницького репо, з якого виділено пакет. Лишені на
#: один реліз, щоб не поламати наявні ярлики й скрипти; читаються після основних.
ENV_LEGACY_WORKSPACE = "MEGEN_ROOT"
ENV_LEGACY_CASE_ROOTS = "MEGEN_CASE_ROOTS"

#: Пакет лежить у `<корінь>/src/nyshporka/core/workspace.py` → parents[3] == корінь.
_PACKAGE_ANCHOR = Path(__file__).resolve().parents[3]


class WorkspaceError(RuntimeError):
    """Простір не знайдено або він непридатний."""


class NoProjectError(WorkspaceError):
    """Команда проєктного шару запущена з кореня Майстерні без проєкту."""


#: Тека проєктів усередині Майстерні. Проєкт лежить лише тут — і саме тому
#: перелік проєктів можна взяти з диска, без окремого реєстру.
PROJECTS_DIR = "projects"


# ── валідація кореня ─────────────────────────────────────────────────────────
def _forbidden_roots() -> set[Path]:
    """Місця, які не можна робити простором.

    🔴 Це не педантизм, а гард безпеки. `under_raw()` пропускає шлях, якщо він
    під одним із коренів простору, — а шлях у в'ювер сторінок приходить із
    HTTP-запиту. Простір, що дорівнює `C:\\` чи домівці, перетворює цей гард на
    «дозволено все», і зламаною виявиться не програма, а межа між нею й рештою
    диска. Доки простір задавав розробник, питання не стояло; щойно його
    вибирає майстер першого запуску — стоїть.
    """
    out = {Path(p).resolve() for p in (Path.home(), Path.home() / "Desktop",
                                       Path.home() / "Documents",
                                       Path.home() / "Downloads")}
    for env in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "windir"):
        val = os.environ.get(env)
        if val:
            out.add(Path(val).resolve())
    out.update({Path("/"), Path("/usr"), Path("/etc"), Path("/home")})
    return out


def validate_root(root: Path) -> Path:
    """Абсолютний перевірений корінь простору — або `WorkspaceError` із поясненням."""
    p = Path(root).expanduser()
    p = Path(os.path.abspath(p))
    if p.parent == p:
        raise WorkspaceError(
            f"корінь диска не може бути робочим простором: {p} — "
            f"створіть окрему теку, напр. {Path.home() / 'Документи' / 'Нишпорка'}")
    if p in _forbidden_roots():
        raise WorkspaceError(
            f"це системна або надто широка тека: {p} — потрібна власна тека простору")
    # Глибина < 2 від кореня диска («D:\\скани») лишає під гардом майже весь том.
    if len(p.parts) < 3:
        raise WorkspaceError(
            f"надто високо в дереві: {p} — простір має лежати щонайменше на два "
            f"рівні від кореня диска, інакше гард шляхів охоплює майже весь том")
    return p


# ── модель ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Workspace:
    """Корінь простору + похідні шляхи.

    Похідні — властивості, а не поля: так вони не «застигають» у момент
    створення й лишаються правильними, якщо простір колись перемкнуть.

    🔴 Два корені. `root` — проєкт (рід чи замовлення): канон, профіль, вердикти,
    журнал пошуку, звіти. `hub` — Майстерня: кадри, прочитане, реєстр справ,
    моделі — те, що однакове для будь-якого проєкту. Кожна властивість шляху
    знає, чия вона, тож код, що просить `ws.raw`, не мусить знати про проєкти.
    Поки `hub_root` не задано, обидва корені — той самий каталог (старий
    простір працює як є).
    """

    root: Path
    name: str = ""
    #: Корені зі справами поза простором (архів на іншому диску, монтування).
    extra_case_roots: tuple[Path, ...] = field(default=())
    #: Звідки взявся корінь — для діагностики й повідомлень майстра.
    origin: str = "package"
    #: Пресет секцій із маркера (`None` — не вказано).
    preset: str | None = None
    #: Явний перелік секцій із маркера (`None` — не вказано, діє пресет).
    listed_sections: tuple[str, ...] | None = None
    #: Чому профіль секцій не прочитався. Показує `doctor` і банер демона.
    sections_problem: str = ""
    #: Версія ключів справ (`core.casekey.KEYS_VERSION`). Маркер без поля `keys`
    #: — простір, заведений до опису в ключі: читається як 1. Простір, зібраний
    #: прямо в коді (тести, `use()`), — поточний: старих ключів у ньому немає.
    keys: int = 2
    #: (mtime_ns, розмір) маркера, з якого прочитано `keys`; `None` — простір
    #: зібрано в коді, і його `keys` — остаточна відповідь (`keys_now`).
    marker_stamp: tuple[int, int] | None = None
    #: Тека стору тексту поза `data/derived` (маркер: `text_store`). Стор —
    #: найбільший файл простору (десятки ГБ), і місце йому там, де швидкий диск,
    #: а не там, де лежить репозиторій. `None` — у `derived`, як завжди.
    text_store_dir: Path | None = None
    #: Корінь Майстерні, якщо проєкт лежить окремо від неї. `None` — простір
    #: старого типу: Майстерня й проєкт в одному каталозі.
    hub_root: Path | None = None
    #: Ім'я проєкту (тека в `projects/`). `None` — корінь Майстерні: або хаб
    #: старого типу, де проєкт лежить у самому корені, або чистий хаб.
    project: str | None = None
    #: Майстерня без власного проєкту (`[workspace] hub_only = true`). Тоді в
    #: корені хаба проєктного шару немає зовсім, і звертання до нього — помилка.
    hub_only: bool = False
    #: Чужий проєкт, відкритий з іншого (`--project`) — лише для читання.
    readonly: bool = False

    @property
    def hub(self) -> Path: return self.hub_root or self.root

    @property
    def hub_marker(self) -> Path: return self.hub / MARKER

    @property
    def proot(self) -> Path:
        """Корінь проєктного шару — або відмова в чистому хабі.

        🔴 Межа механічна: без неї команда, запущена з кореня Майстерні,
        тихо читала б (і писала б) `хаб/data/canonical` — канон, якого там
        немає й не має бути, а знахідка падала б «нікому».
        """
        if self.hub_only and self.project is None:
            raise NoProjectError(
                "команда проєктного шару (канон, профіль, вердикти, журнал, звіти) "
                "запущена з кореня Майстерні — вкажіть проєкт: "
                "nysh --project <ім'я> … або запустіть її в теці проєкту")
        return self.root

    # ── Майстерня: факти про справу й машину ─────────────────────────────────
    @property
    def hub_data(self) -> Path: return self.hub / "data"

    @property
    def raw(self) -> Path: return self.hub_data / "raw"

    #: Похідне Майстерні: реєстр справ, бібліотека, газетир, кеші читання.
    #: Похідне проєкту (база роду, граф, журнал пошуку) — `project_derived`.
    @property
    def derived(self) -> Path: return self.hub_data / "derived"

    #: Сховище сторінок. ⚠ Поки що цілком у Майстерні; розщеплення на факт
    #: аркуша (Майстерня) і перегляд під ціль (проєкт) — хвиля 3.
    @property
    def pages(self) -> Path: return self.hub_data / "pages"

    @property
    def spotter(self) -> Path: return self.hub_data / "spotter"

    #: Ручні прив'язки прогонів до справ (`overrides.json`).
    @property
    def cases(self) -> Path: return self.hub_data / "cases"

    #: Постійний стор доказів-кропів. Файл один на машину; цитата на нього
    #: живе в каноні проєкту.
    @property
    def citations(self) -> Path: return self.hub_data / "source" / "citations"

    #: Обмін прочитаним: журнал походження і прийняті пакети.
    #:
    #: 🔴 У `data`, а не в `derived`. Пакет, з якого взято факт, — доказ-файл, і
    #: він мусить пережити чистку похідного: інакше цитата провисне рівно тоді,
    #: коли кеш приберуть.
    @property
    def share(self) -> Path: return self.hub_data / "share"

    @property
    def htr_reports(self) -> Path: return self.hub / "reports" / "htr"

    # ── проєкт: рід чи замовлення ────────────────────────────────────────────
    @property
    def data(self) -> Path: return self.proot / "data"

    @property
    def canonical(self) -> Path: return self.data / "canonical"

    #: Похідне проєкту: база роду (`nyshporka.sqlite`), граф, мапа місць,
    #: журнал пошуку.
    @property
    def project_derived(self) -> Path: return self.data / "derived"

    #: Кандидати на злиття з каноном (`matching`).
    @property
    def candidates(self) -> Path: return self.data / "candidates"

    #: Стан пошуку роду (`clan_hunt/state.json`).
    @property
    def clan_hunt(self) -> Path: return self.data / "clan_hunt"

    @property
    def reports(self) -> Path: return self.proot / "reports"

    @property
    def config(self) -> Path: return self.proot / "config"

    @property
    def marker(self) -> Path: return self.root / MARKER

    @property
    def profile(self) -> tuple[str | None, tuple[str, ...] | None, str]:
        """Профіль секцій — з маркера на диску, а не зі знімка процесу.

        🔴 Не педантизм. Демон резолвить простір один раз на старті й живе
        годинами; `nysh sections` — окремий процес, який міняє файл. Зі
        знімком браузер показував би вимкнене як увімкнене доти, доки
        застосунок не перезапустять, — тобто налаштування «не діяли б», і
        причину цього побачити не було б звідки.

        Читання дешеве (кілька рядків TOML) і ще й з memo за mtime.
        """
        live = _profile_on_disk(self.marker, _mtime(self.marker))
        # Проєкт без власного профілю секцій живе з профілем Майстерні.
        if (self.hub_root is not None and live is not None
                and live[0] is None and live[1] is None and not live[2]):
            live = _profile_on_disk(self.hub_marker, _mtime(self.hub_marker))
        if live is not None:
            return live
        return self.preset, self.listed_sections, self.sections_problem

    @property
    def sections(self) -> frozenset[str]:
        """Активні секції застосунку.

        🔴 Профіль із помилкою не валить застосунок: береться дефолт, а причина
        лишається в `sections_problem` і доїжджає до `doctor` та банера демона.
        Падати тут означало б зробити застосунок незапускним через одну
        друкарську помилку в текстовому файлі, який людина редагує руками.
        """
        from nyshporka.core import sections as S

        preset, listed, _ = self.profile
        try:
            return S.resolve(preset=preset, explicit=listed)
        except S.SectionError:
            return S.resolve()

    def case_roots(self) -> list[Path]:
        """Корені, з яких дозволено брати теки справ.

        Перший — завжди `data/raw` (канонічне місце), далі архівні корені поза
        простором. Відсіюються неіснуючі: на іншій машині диска просто немає, і
        мовчазний неіснуючий корінь у гарді нічого не дає, крім плутанини.

        🔴 Це розширення зони гарда, тому перелік завжди явний, ніколи не
        «будь-який абсолютний шлях».
        """
        roots = [self.raw]
        roots += [p for p in self.extra_case_roots if p.is_dir()]
        return roots


# ── резолвер ─────────────────────────────────────────────────────────────────
def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh) or {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _read_marker(path: Path) -> dict[str, Any]:
    return _read_toml(path).get("workspace") or {}


def read_project_table(root: Path) -> dict[str, Any] | None:
    """Таблиця `[project]` маркера теки — або `None`, якщо це не проєкт."""
    got = _read_toml(root / MARKER).get("project")
    return got if isinstance(got, dict) else None


def _hub_above(project_root: Path) -> Path:
    """Майстерня, у якій лежить проєкт.

    🔴 Проєкт лежить лише в `<хаб>/projects/<ім'я>/`. Не «будь-який маркер
    вище»: тоді проєкт, скопійований деінде, тихо пристав би до чужої
    Майстерні, а перелік проєктів (обхід `projects/`) його б не бачив.
    """
    hub = project_root.parent.parent
    if (project_root.parent.name != PROJECTS_DIR or not (hub / MARKER).is_file()
            or read_project_table(hub) is not None):
        raise WorkspaceError(
            f"{project_root} — тека проєкту ([project] у {MARKER}), але вона не "
            f"лежить у Майстерні: проєкт має бути в <хаб>/{PROJECTS_DIR}/<ім'я>/, "
            f"а в корені хаба — його {MARKER} з таблицею [workspace]")
    return hub


def _env_case_roots() -> tuple[Path, ...] | None:
    raw = os.environ.get(ENV_CASE_ROOTS)
    if raw is None:
        raw = os.environ.get(ENV_LEGACY_CASE_ROOTS)
    if raw is None:
        return None
    return tuple(Path(s) for s in raw.split(os.pathsep) if s.strip())


def _find_marker_upwards(start: Path) -> Path | None:
    try:
        cur = Path(start).resolve()
    except OSError:
        return None
    for cand in (cur, *cur.parents):
        if (cand / MARKER).is_file():
            return cand
    return None


def _looks_like_workspace(path: Path) -> bool:
    """Чи це справді простір, а не випадкова тека (напр. `site-packages`)."""
    return (path / MARKER).is_file() or (path / "data").is_dir()


#: Ім'я теки простору за замовчуванням. Кирилицею: її бачить людина, а не код.
#: Живе тут, бо його потребують обидві сторони — і пошук наявного простору
#: (нижче), і вибір місця під новий (`setup.wizard`). Дві копії розійшлися б
#: мовчки: перейменування в одній стороні лишило б другу шукати старе ім'я.
DEFAULT_DIRNAME = "Нишпорка"


def _home_candidates() -> tuple[Path, ...]:
    """Звичні місця, де може лежати вже створений простір.

    ⚠ Не плутати з `setup.wizard.default_root()`: той обирає, куди покласти
    новий простір, і тому обходить теки, що синхронізуються з хмарою. Тут
    питання протилежне — знайти дослідження, яке людина вже завела; якщо воно
    лежить у OneDrive, воно однаково її, і «не знайшлось» гірше за повільний
    обхід.
    """
    home = Path.home()
    return (home / DEFAULT_DIRNAME,
            home / "Documents" / DEFAULT_DIRNAME,
            home / "Документи" / DEFAULT_DIRNAME)


def _build(root: Path, origin: str, *, readonly: bool = False) -> Workspace:
    """Простір із маркера теки.

    Тека проєкту (`[project]` у маркері) бере Майстерню з маркера хаба над
    собою: корені справ, стор тексту, версію ключів — усе, що про машину й
    матеріал. Від проєкту — лише ім'я і, якщо заданий, профіль секцій.
    """
    ptab = read_project_table(root)
    if ptab is None:
        return _build_hub(root, origin)
    hub = _hub_above(root)
    base = _build_hub(hub, origin)
    own = ptab if ("preset" in ptab or "sections" in ptab) else None
    preset, listed, problem = ((base.preset, base.listed_sections, base.sections_problem)
                               if own is None else _read_sections(own))
    return replace(base, root=root, hub_root=hub, project=root.name,
                   name=str(ptab.get("name") or root.name),
                   preset=preset, listed_sections=listed, sections_problem=problem,
                   readonly=readonly)


def _build_hub(root: Path, origin: str) -> Workspace:
    cfg = _read_marker(root / MARKER)
    # Порядок джерел коренів: env перебиває маркер (ескейп-хетч на чужій машині),
    # маркер перебиває дефолт. Дефолт тут порожній: додаткові корені — це завжди
    # чиясь конкретна машина, тож у пакеті їм місця немає. Хто тримає архів на
    # окремому диску, вписує його в маркер свого простору.
    env_roots = _env_case_roots()
    if env_roots is not None:
        extra: tuple[Path, ...] = env_roots
    elif cfg.get("case_roots"):
        extra = tuple(Path(str(s)) for s in cfg["case_roots"])
    else:
        extra = ()
    preset, listed, problem = _read_sections(cfg)
    return Workspace(root=root, name=str(cfg.get("name") or ""),
                     extra_case_roots=extra, origin=origin,
                     preset=preset, listed_sections=listed,
                     sections_problem=problem, keys=_keys_version(cfg),
                     marker_stamp=_stamp_of(root / MARKER),
                     text_store_dir=(root / str(cfg["text_store"])
                                     if cfg.get("text_store") else None),
                     hub_only=bool(cfg.get("hub_only")))


def _stamp_of(marker: Path) -> tuple[int, int] | None:
    try:
        st = marker.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _keys_version(cfg: dict[str, Any]) -> int:
    """Версія ключів із маркера. Поля немає або воно негодяще — 1 (старі ключі).

    🔴 Помилка в бік «старі» безпечна: запис відмовить і назве команду переносу,
    яка на просторі без старих ключів лише поставить позначку. Помилка в бік
    «нові» тихо писала б нові ключі поруч зі старими.
    """
    try:
        return max(1, int(cfg.get("keys") or 1))
    except (TypeError, ValueError):
        return 1


def _mtime(path: Path) -> float:
    """Час зміни маркера — ключ memo. 0.0 означає «файлу немає»."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@lru_cache(maxsize=8)
def _profile_on_disk(marker: Path, _stamp: float,
                     ) -> tuple[str | None, tuple[str, ...] | None, str] | None:
    """Профіль секцій прямо з файлу. `None` — маркера немає.

    `_stamp` в аргументах саме для того, щоб memo протухало разом із файлом:
    інакше кеш тримав би старий профіль рівно так само, як його тримав знімок
    простору, і виправлення нічого не змінило б.
    """
    if not _stamp:
        return None
    full = _read_toml(marker)
    table = full.get("project")
    return _read_sections(table if isinstance(table, dict) else (full.get("workspace") or {}))


def _read_sections(cfg: dict[str, Any]) -> tuple[str | None, tuple[str, ...] | None, str]:
    """Профіль секцій із маркера: (пресет, явний перелік, проблема).

    Перевіряємо тут, щоб причина була конкретною («невідома секція htrr»), а не
    зводилась до мовчазного повернення до дефолту десь усередині.
    """
    from nyshporka.core import sections as S

    raw_preset = cfg.get("preset")
    preset = str(raw_preset).strip() if raw_preset else None
    raw_listed = cfg.get("sections")
    listed: tuple[str, ...] | None = None
    if isinstance(raw_listed, (list, tuple)):
        listed = tuple(str(s).strip() for s in raw_listed if str(s).strip())
    elif raw_listed is not None:
        return preset, None, f"поле sections має бути переліком, а не {type(raw_listed).__name__}"

    try:
        S.resolve(preset=preset, explicit=listed)
    except S.SectionError as exc:
        return preset, listed, str(exc)
    return preset, listed, ""


def resolve(explicit: str | Path | None = None) -> Workspace:
    """Знайти простір. Порядок джерел — від найявнішого до найзагальнішого."""
    if explicit:
        return _build(validate_root(Path(explicit)), "explicit")

    for env in (ENV_WORKSPACE, ENV_LEGACY_WORKSPACE):
        val = os.environ.get(env)
        if val:
            return _build(validate_root(Path(val)), f"env:{env}")

    found = _find_marker_upwards(Path.cwd())
    if found is not None:
        return _build(validate_root(found), "marker")

    last = _load_last_used()
    if last is not None and _looks_like_workspace(last):
        return _build(validate_root(last), "last-used")

    # 🏠 Звичне місце — щабель, якого тут бракувало, хоч у `propose()` він був.
    # Через це майстер простір знаходив, а кожна команда — ні: досить було
    # протухнути записові стану (його перебиває будь-який `nysh init` у
    # тимчасовій теці, а такі теки прибирають), і людина, що поставила
    # застосунок місяць тому, читала «робочий простір не знайдено» про
    # дослідження, яке спокійно лежить у себе вдома. Береться лише те, що вже
    # є простором, — порожня тека з таким іменем нічого не означає.
    for candidate in _home_candidates():
        if _looks_like_workspace(candidate):
            return _build(validate_root(candidate), "default")

    # 🔑 Фолбек на розташування пакета — те, що всі модулі робили досі. Він діє
    # лише якщо там справді дані: у встановленому пакеті `site-packages` даних
    # немає, і мовчазна робота «в нікуди» була б гіршою за чесну відмову.
    if _looks_like_workspace(_PACKAGE_ANCHOR):
        return Workspace(root=_PACKAGE_ANCHOR,
                         extra_case_roots=_env_case_roots() or (),
                         origin="package")

    # 🔴 Зниклий простір називається окремим рядком. «Не знайдено» на місці
    # дослідження, яке ще вчора відкривалось, читається як втрата даних;
    # знати, що зник саме записаний шлях, — різниця між «шукати теку» і
    # «шукати бекап».
    gone = (f"\n  ⚠ останній відкритий простір {last} більше не існує"
            if last is not None else "")
    raise WorkspaceError(
        f"робочий простір не знайдено.{gone}"
        f"\nВкажіть його одним зі способів:\n"
        f"  • змінна середовища {ENV_WORKSPACE}=<тека>\n"
        f"  • файл {MARKER} у корені простору (шукається вгору від поточної теки)\n"
        "  • nysh --workspace <тека> <команда> — разово, на один запуск\n"
        "  • nysh init <тека> — створити простір")



def _validated(path: str | Path, source: str) -> Path:
    """`validate_root()`, але з назвою джерела в помилці.

    🔴 Джерела перевіряються мовчки й по черзі, тож без цього людина, у якої
    змінна вказує на корінь диска, читає «корінь диска не може бути робочим
    простором» і не має жодного способу дізнатись, яке з п'яти джерел цей шлях
    назвало — а лікуються вони по-різному.
    """
    try:
        return validate_root(Path(path))
    except WorkspaceError as exc:
        raise WorkspaceError(f"{source}: {exc}") from exc


def propose(explicit: str | Path | None = None, *, default: Path) -> tuple[Path, str]:
    """Куди покласти простір, якого ще може не бути, — і звідки взявся цей шлях.

    🔴 Це не `resolve()`, і різниця не косметична. `resolve()` відповідає на
    «де вже лежить дослідження», тому його остання гілка вважає простором будь-яку
    теку, у якій є `data/`. Для пошуку наявного це правильно; для вибору місця під
    новий — ні: майстер запропонував би створити простір у теці пакета, а у
    встановленому колесі це поруч із `site-packages`, звідки дерево змиває
    найближчий `pip install --upgrade`. «Знайти наявне» і «обрати місце для
    нового» — різні питання, і однією драбиною вони не відповідаються.

    Отже драбина тут та сама, мінус гілка розташування пакета, плюс останній
    щабель `default` — типове місце, яке передає той, хто знає про машину
    (`setup.wizard`), бо «де в цієї ОС тека документів і чи вона не в хмарі» —
    не знання рівня `core`.

    Нічого не створює й не пише: на цьому тримається обіцянка `wizard.plan()`
    «порахувати, що станеться».
    """
    if explicit:
        return _validated(explicit, "вказаний шлях"), "explicit"

    for env in (ENV_WORKSPACE, ENV_LEGACY_WORKSPACE):
        val = os.environ.get(env)
        if val:
            return _validated(val, f"{env}={val}"), f"env:{env}"

    found = _find_marker_upwards(Path.cwd())
    if found is not None:
        return _validated(found, f"{MARKER} у {found}"), "marker"

    last = _load_last_used()
    if last is not None and _looks_like_workspace(last):
        return _validated(last, "останній відкритий простір"), "last-used"

    return _validated(default, "типове місце"), "default"

# ── «останній використаний» ──────────────────────────────────────────────────
def _state_path() -> Path | None:
    """Файл стану поза простором — інакше «який простір відкривали» жив би в
    просторі, якого ще не знайдено."""
    try:
        from platformdirs import user_state_dir
    except ImportError:
        return None
    return Path(user_state_dir("Nyshporka", appauthor=False)) / "state.json"


def _load_last_used() -> Path | None:
    path = _state_path()
    if path is None or not path.is_file():
        return None
    try:
        import json
        val = json.loads(path.read_text(encoding="utf-8")).get("workspace")
    except (OSError, ValueError):
        return None
    return Path(val) if val else None


def state_all() -> dict[str, Any]:
    """Увесь файл стану користувача. Немає — порожньо, і це не помилка."""
    path = _state_path()
    if path is None or not path.is_file():
        return {}
    try:
        import json
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def state_set(**fields: Any) -> None:
    """Дописати поля у стан користувача, не чіпаючи решти.

    🔴 Саме дописати. Доти єдиний писар (`remember`) перезаписував файл цілком,
    і будь-яке друге поле в ньому зникало б при наступному відкритті простору —
    мовчки, бо на вигляд стан лишався справним.
    """
    path = _state_path()
    if path is None:
        return
    try:
        import json

        from nyshporka.utils.atomic import atomic_write_text

        atomic_write_text(path, json.dumps({**state_all(), **fields},
                                           ensure_ascii=False))
    except OSError:
        pass  # запам'ятати не вдалось — це зручність, а не умова роботи


def remember(ws: Workspace) -> None:
    """Запам'ятати простір як останній використаний (для майстра наступного разу)."""
    state_set(workspace=str(ws.root))


# ── доступ ───────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _cached() -> Workspace:
    return resolve()


_override: Workspace | None = None


def workspace() -> Workspace:
    """Активний простір. Резолвиться один раз за процес."""
    return _override if _override is not None else _cached()


def use(root: str | Path | Workspace, *, readonly: bool = False) -> Workspace:
    """Явно задати простір (CLI `--workspace`, майстер, тести).

    Викликати до імпорту доменних модулів: ті беруть корінь на рівні модуля,
    і після їхнього імпорту перемикання вже нічого не змінить.

    ⚠ Тут не пишеться «останній використаний» (це робить `wizard.create()`).
    Цю функцію кличе кожен запуск із `--workspace` і кожен тест; запис стану
    звідси зробив би разовий прапорець липким — він перевизначав би всі
    наступні команди, і причину цього не було б де побачити.
    """
    global _override
    _override = root if isinstance(root, Workspace) else _build(
        validate_root(Path(root)), "explicit", readonly=readonly)
    return _override


@contextmanager
def using(ws: Workspace) -> Iterator[Workspace]:
    """Тимчасово стати в іншому просторі — і повернутись, навіть після помилки.

    Для дій, що мусять записати в щойно заведений проєкт (профіль роду в
    `project new`), не перемикаючи простір процесу назавжди.
    """
    global _override
    prev = _override
    _override = ws
    try:
        yield ws
    finally:
        _override = prev


def add_case_root(path: str | Path) -> Path:
    """Оголосити теку зі сканами поза простором — і записати це в маркер.

    🔴 Розширення зони гарда, тому воно явне і зберігається у файлі, який
    людина може прочитати. Мовчазне «пущу будь-який абсолютний шлях» зняло б
    єдину перепону між запитом із браузера й рештою диска.

    Записується в `nyshporka.toml`, бо простір переносять разом із маркером:
    інакше після переїзду скани «зникали б» без сліду, чому.
    """
    p = validate_root(Path(path))
    if not p.is_dir():
        raise WorkspaceError(f"теки немає: {p}")
    ws = workspace()
    if p == ws.raw or p in ws.case_roots():
        return p

    marker = ws.hub_marker
    text = marker.read_text(encoding="utf-8") if marker.is_file() else "[workspace]\n"
    roots = [str(x).replace("\\", "/") for x in ws.extra_case_roots]
    roots.append(str(p).replace("\\", "/"))
    listed = ", ".join(f'"{r}"' for r in roots)
    line = f"case_roots = [{listed}]"
    # Рядок може бути закоментованим зразком із майстра, наявним значенням або
    # відсутнім зовсім — усі три випадки трапляються на живому просторі.
    if re.search(r"(?m)^\s*case_roots\s*=", text):
        text = re.sub(r"(?m)^\s*case_roots\s*=.*$", line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    _write_marker(marker, text)

    global _override
    _override = replace(ws, extra_case_roots=(*ws.extra_case_roots, p))
    _cached.cache_clear()
    return p


def remove_case_root(path: str | Path) -> bool:
    """Зняти оголошений корінь справ. `True`, якщо він там був.

    🔴 Зворотна дія обов'язкова саме тому, що пряма — оголошення — робиться
    одним рухом і легко помиляється: не та тека, тимчасовий диск, флешка
    колеги. Доки зняти корінь було нічим, єдиним виходом лишалось правити
    маркер руками — тобто редагувати файл, якого людина не заводила, з ризиком
    зачепити решту.

    ⚠ Файли не чіпаються жодні. Зникає лише видимість: справи з цієї теки
    випадуть із реєстру після наступної збірки, а самі скани лишаться на місці.
    """
    p = Path(path).expanduser()
    ws = workspace()
    key = os.path.normcase(str(p))
    kept = [r for r in ws.extra_case_roots if os.path.normcase(str(r)) != key]
    if len(kept) == len(ws.extra_case_roots):
        return False

    marker = ws.hub_marker
    text = marker.read_text(encoding="utf-8") if marker.is_file() else "[workspace]\n"
    listed = ", ".join(f'"{str(r).replace(chr(92), "/")}"' for r in kept)
    # Порожній перелік знімається рядком, а не лишається `[]`: маркер читає
    # людина, і `case_roots = []` виглядає як налаштування, якого вона не
    # робила.
    text = _marker_set(text, "case_roots",
                       f"case_roots = [{listed}]" if kept else None)
    _write_marker(marker, text)

    global _override
    _override = replace(ws, extra_case_roots=tuple(kept))
    _cached.cache_clear()
    return True


def _marker_set(text: str, key: str, line: str | None,
                table: str = "workspace") -> str:
    """Вписати, замінити або зняти рядок `key = …` у тексті маркера.

    Той самий прийом, що й для `case_roots`: рядок може бути закоментованим
    зразком із майстра, наявним значенням або відсутнім зовсім.
    """
    pattern = rf"(?m)^\s*{re.escape(key)}\s*=.*$"
    if re.search(pattern, text):
        if line is None:
            return re.sub(pattern + r"\n?", "", text, count=1)
        return re.sub(pattern, line, text, count=1)
    if line is None:
        return text
    # 🔴 Новий ключ — усередину таблиці `[workspace]`, а не в кінець файлу.
    # Маркер може нести інші таблиці нижче (сусідні проєкти тримають там свої
    # корені), і рядок, дописаний у хвіст, потрапляє в ЧУЖУ таблицю, де його
    # ніхто не читає: `nysh sections enable` рапортує успіх, а секція лишається
    # вимкненою. Спіймано на просторі з таблицею сусідніх проєктів у хвості маркера.
    head = re.search(rf"(?m)^\s*\[{re.escape(table)}\]\s*$", text)
    if head is None:
        return text.rstrip("\n") + "\n" + line + "\n"
    nxt = re.search(r"(?m)^\s*\[", text[head.end():])
    end = head.end() + nxt.start() if nxt else len(text)
    body = text[head.end():end].rstrip("\n")
    tail = text[end:]
    return text[:head.end()] + body + "\n" + line + "\n" + ("\n" if nxt else "") + tail


def set_sections(active: Iterable[str]) -> frozenset[str]:
    """Записати активні секції в маркер простору.

    🔴 Зберігаємо пресет, коли набір точно йому дорівнює, і явний перелік —
    лише коли він власний. Причина не косметична: простір із записаним
    пресетом отримає секцію, додану в майбутній версії, а простір із застиглим
    переліком — ні, і людина ніколи не дізнається, що щось з'явилось.

    Двох правд у файлі не лишається: записуючи одне, друге знімаємо.
    """
    from nyshporka.core import sections as S

    resolved = S.resolve(explicit=list(active))
    ws = workspace()
    marker = ws.marker
    # Проєкт тримає свій профіль секцій у `[project]`, Майстерня — у `[workspace]`.
    table = "project" if ws.project else "workspace"
    text = marker.read_text(encoding="utf-8") if marker.is_file() else f"[{table}]\n"

    name = S.preset_of(resolved)
    if name is not None:
        text = _marker_set(text, "preset", f'preset = "{name}"', table)
        text = _marker_set(text, "sections", None, table)
        listed: tuple[str, ...] | None = None
    else:
        listed = tuple(sorted(resolved))
        joined = ", ".join(f'"{s}"' for s in listed)
        text = _marker_set(text, "sections", f"sections = [{joined}]", table)
        text = _marker_set(text, "preset", None, table)
    _write_marker(marker, text)

    global _override
    _override = replace(ws, preset=name, listed_sections=listed, sections_problem="")
    _cached.cache_clear()
    return resolved


def keys_now() -> int:
    """Версія ключів простору з маркера НА ДИСКУ.

    🔴 `Workspace.keys` резолвиться раз за процес, а перенос (`nysh cases rekey`)
    і відкат ідуть з іншого термінала. Демон, що пам'ятав `keys = 2` після
    відкату, писав би нові імена файлів у простір, який повернувся на старі.
    Тому маркер, що змінився від резолву, перечитується. Простір, зібраний у
    коді (тести, майстер до запису маркера), — свій `keys`.
    """
    ws = workspace()
    if ws.marker_stamp is None:
        return ws.keys
    now = _stamp_of(ws.hub_marker)
    if now is None or now == ws.marker_stamp:
        return ws.keys
    return _marker_keys(str(ws.hub_marker), *now)


@lru_cache(maxsize=4)
def _marker_keys(path: str, mtime_ns: int, size: int) -> int:
    return _keys_version(_read_marker(Path(path)))


def refresh_keys() -> None:
    """Перечитати версію ключів з маркера (маркер щойно повернуто з архіву)."""
    global _override
    if _override is not None and _override.marker_stamp is not None:
        _override = replace(_override, keys=_keys_version(_read_marker(_override.hub_marker)),
                            marker_stamp=_stamp_of(_override.hub_marker))
    elif _override is not None:
        _override = replace(_override, keys=_keys_version(_read_marker(_override.hub_marker)))
    _cached.cache_clear()


def set_keys_version(version: int) -> None:
    """Записати версію ключів справ у маркер простору (`cases.rekey`, майстер)."""
    global _override
    ws = workspace()
    marker = ws.hub_marker
    text = marker.read_text(encoding="utf-8") if marker.is_file() else "[workspace]\n"
    _write_marker(marker, _marker_set(text, "keys", f"keys = {int(version)}"))
    if _override is not None:
        _override = replace(_override, keys=int(version),
                            marker_stamp=(_stamp_of(marker) if _override.marker_stamp
                                          is not None else None))
    _cached.cache_clear()


def _write_marker(marker: Path, text: str) -> None:
    """Маркер простору — атомарно.

    🔴 Від цього файла залежить резолв простору взагалі: обрізаний Ctrl+C або
    повним диском TOML ронив би `workspace()` на КОЖНОМУ наступному запуску, і
    лагодити його довелося б руками.
    """
    from nyshporka.utils.atomic import atomic_write_text

    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(marker, text)


def reset() -> None:
    """Скинути кеш — для тестів."""
    global _override
    _override = None
    _cached.cache_clear()
    _profile_on_disk.cache_clear()


def root() -> Path:
    """Скорочення для 23 модулів, яким потрібен лише корінь."""
    return workspace().root


def mode_label(ws: Workspace) -> str:
    """Де стоїть простір: у проєкті, у корені Майстерні чи в старому просторі."""
    ro = " (лише читання)" if ws.readonly else ""
    if ws.project is not None:
        return f"проєкт «{ws.project}» у Майстерні {ws.hub}{ro}"
    if ws.hub_only:
        return "корінь Майстерні (проєкту немає)"
    return "Майстерня й проєкт в одному корені"


def describe() -> str:
    """Однорядковий опис для `doctor` і банерів."""
    try:
        ws = workspace()
    except WorkspaceError as exc:
        return f"простір не визначено ({exc.args[0].splitlines()[0]})"
    extra = ", ".join(str(p) for p in ws.case_roots()[1:]) or "—"
    return (f"{ws.name or ws.root.name} · {ws.root} · {mode_label(ws)} · джерело: {ws.origin} · "
            f"архівні корені: {extra} · python {sys.version_info.major}."
            f"{sys.version_info.minor}")
