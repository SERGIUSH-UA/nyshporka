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
from collections.abc import Iterable
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

    # дані дослідження
    @property
    def data(self) -> Path: return self.root / "data"

    @property
    def raw(self) -> Path: return self.data / "raw"

    @property
    def derived(self) -> Path: return self.data / "derived"

    @property
    def canonical(self) -> Path: return self.data / "canonical"

    @property
    def pages(self) -> Path: return self.data / "pages"

    @property
    def spotter(self) -> Path: return self.data / "spotter"

    @property
    def reports(self) -> Path: return self.root / "reports"

    @property
    def htr_reports(self) -> Path: return self.reports / "htr"

    @property
    def config(self) -> Path: return self.root / "config"

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
def _read_marker(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return (tomllib.load(fh) or {}).get("workspace") or {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


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


def _build(root: Path, origin: str) -> Workspace:
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
                     sections_problem=problem)


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
    return _read_sections(_read_marker(marker))


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


def remember(ws: Workspace) -> None:
    """Запам'ятати простір як останній використаний (для майстра наступного разу)."""
    path = _state_path()
    if path is None:
        return
    try:
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"workspace": str(ws.root)}, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass  # запам'ятати не вдалось — це зручність, а не умова роботи


# ── доступ ───────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _cached() -> Workspace:
    return resolve()


_override: Workspace | None = None


def workspace() -> Workspace:
    """Активний простір. Резолвиться один раз за процес."""
    return _override if _override is not None else _cached()


def use(root: str | Path | Workspace) -> Workspace:
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
        validate_root(Path(root)), "explicit")
    return _override


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

    marker = ws.marker
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
    marker.write_text(text, encoding="utf-8")

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

    marker = ws.marker
    text = marker.read_text(encoding="utf-8") if marker.is_file() else "[workspace]\n"
    listed = ", ".join(f'"{str(r).replace(chr(92), "/")}"' for r in kept)
    # Порожній перелік знімається рядком, а не лишається `[]`: маркер читає
    # людина, і `case_roots = []` виглядає як налаштування, якого вона не
    # робила.
    text = _marker_set(text, "case_roots",
                       f"case_roots = [{listed}]" if kept else None)
    marker.write_text(text, encoding="utf-8")

    global _override
    _override = replace(ws, extra_case_roots=tuple(kept))
    _cached.cache_clear()
    return True


def _marker_set(text: str, key: str, line: str | None) -> str:
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
    return text.rstrip("\n") + "\n" + line + "\n"


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
    text = marker.read_text(encoding="utf-8") if marker.is_file() else "[workspace]\n"

    name = S.preset_of(resolved)
    if name is not None:
        text = _marker_set(text, "preset", f'preset = "{name}"')
        text = _marker_set(text, "sections", None)
        listed: tuple[str, ...] | None = None
    else:
        listed = tuple(sorted(resolved))
        joined = ", ".join(f'"{s}"' for s in listed)
        text = _marker_set(text, "sections", f"sections = [{joined}]")
        text = _marker_set(text, "preset", None)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(text, encoding="utf-8")

    global _override
    _override = replace(ws, preset=name, listed_sections=listed, sections_problem="")
    _cached.cache_clear()
    return resolved


def reset() -> None:
    """Скинути кеш — для тестів."""
    global _override
    _override = None
    _cached.cache_clear()
    _profile_on_disk.cache_clear()


def root() -> Path:
    """Скорочення для 23 модулів, яким потрібен лише корінь."""
    return workspace().root


def describe() -> str:
    """Однорядковий опис для `doctor` і банерів."""
    try:
        ws = workspace()
    except WorkspaceError as exc:
        return f"простір не визначено ({exc.args[0].splitlines()[0]})"
    extra = ", ".join(str(p) for p in ws.case_roots()[1:]) or "—"
    return (f"{ws.name or ws.root.name} · {ws.root} · джерело: {ws.origin} · "
            f"архівні корені: {extra} · python {sys.version_info.major}."
            f"{sys.version_info.minor}")
