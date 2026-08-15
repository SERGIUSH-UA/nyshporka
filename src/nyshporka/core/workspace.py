"""🗂 Робочий простір — де лежать ДАНІ дослідження.

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
import sys
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

MARKER = "nyshporka.toml"

#: Простір беруть звідси, якщо не вказано інакше.
ENV_WORKSPACE = "NYSHPORKA_WORKSPACE"
#: Додаткові корені зі справами поза простором (архів на іншому диску).
ENV_CASE_ROOTS = "NYSHPORKA_CASE_ROOTS"
#: Застарілі аліаси з дослідницького репо, з якого виділено пакет. Лишені на
#: один реліз, щоб не поламати наявні ярлики й скрипти; читаються ПІСЛЯ основних.
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
    під одним із коренів простору, — а шлях у в'ювер сторінок приходить ІЗ
    HTTP-ЗАПИТУ. Простір, що дорівнює `C:\\` чи домівці, перетворює цей гард на
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
    #: Корені зі справами ПОЗА простором (архів на іншому диску, монтування).
    extra_case_roots: tuple[Path, ...] = field(default=())
    #: Звідки взявся корінь — для діагностики й повідомлень майстра.
    origin: str = "package"

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

    def case_roots(self) -> list[Path]:
        """Корені, з яких дозволено брати теки справ.

        Перший — завжди `data/raw` (канонічне місце), далі архівні корені поза
        простором. Відсіюються неіснуючі: на іншій машині диска просто немає, і
        мовчазний неіснуючий корінь у гарді нічого не дає, крім плутанини.

        🔴 Це РОЗШИРЕННЯ зони гарда, тому перелік завжди явний, ніколи не
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


def _build(root: Path, origin: str) -> Workspace:
    cfg = _read_marker(root / MARKER)
    # Порядок джерел коренів: env перебиває маркер (ескейп-хетч на чужій машині),
    # маркер перебиває дефолт. Дефолт тут ПОРОЖНІЙ: додаткові корені — це завжди
    # чиясь конкретна машина, тож у пакеті їм місця немає. Хто тримає архів на
    # окремому диску, вписує його в маркер свого простору.
    env_roots = _env_case_roots()
    if env_roots is not None:
        extra: tuple[Path, ...] = env_roots
    elif cfg.get("case_roots"):
        extra = tuple(Path(str(s)) for s in cfg["case_roots"])
    else:
        extra = ()
    return Workspace(root=root, name=str(cfg.get("name") or ""),
                     extra_case_roots=extra, origin=origin)


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

    # 🔑 Фолбек на розташування пакета — те, що всі модулі робили досі. Він діє
    # ЛИШЕ якщо там справді дані: у встановленому пакеті `site-packages` даних
    # немає, і мовчазна робота «в нікуди» була б гіршою за чесну відмову.
    if _looks_like_workspace(_PACKAGE_ANCHOR):
        return Workspace(root=_PACKAGE_ANCHOR,
                         extra_case_roots=_env_case_roots() or (),
                         origin="package")

    raise WorkspaceError(
        "робочий простір не знайдено. Вкажіть його одним зі способів:\n"
        f"  • змінна середовища {ENV_WORKSPACE}=<тека>\n"
        f"  • файл {MARKER} у корені простору (шукається вгору від поточної теки)\n"
        "  • аргумент --workspace")


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

    Викликати ДО імпорту доменних модулів: ті беруть корінь на рівні модуля,
    і після їхнього імпорту перемикання вже нічого не змінить.
    """
    global _override
    _override = root if isinstance(root, Workspace) else _build(
        validate_root(Path(root)), "explicit")
    return _override


def reset() -> None:
    """Скинути кеш — для тестів."""
    global _override
    _override = None
    _cached.cache_clear()


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
