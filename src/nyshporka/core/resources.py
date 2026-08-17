"""📦 Ресурси ПАКЕТА — те, що їде разом із кодом, а не з даними дослідника.

Досі `console/paths.py` рахував одним і тим самим `ROOT` дві принципово різні
речі: `templates/`+`static/` (це код — вони версіонуються разом із ним і
однакові в усіх користувачів) і `data/`+`reports/` (це дослідження — у кожного
своє). Поки код і дані лежать в одному дереві, різниці не видно. Щойно пакет
стає встановлюваним, вона стає фатальною: workspace вкаже на теку дослідника,
і застосунок піде шукати `console.html` серед його сканів.

Тому дві прив'язки розведені: `core.workspace` знає, де ДАНІ, цей модуль — де КОД.

🔴 Скрипти теж тут, і це не формальність. `paths.ORCHESTRATOR` був ВІДНОСНИМ
рядком на скрипт-оркестратор у теці скриптів, який працював лише завдяки
`cwd=ROOT` у `create_subprocess_exec`. Тобто запуск субпроцесів мовчки залежав від того, що
корінь даних збігається з коренем коду — а весь сенс workspace саме в тому, що
вони перестають збігатися. Ця гілка ламається першою, тому шлях до скрипта
резолвиться тут і абсолютно.

⚠ Заміна відносного шляху на абсолютний безпечна лише тому, що обидва
анти-double-run гарди звіряють БАЗОВЕ ім'я (`"htr_case_run" in cmd`,
`"spotter_v23_dino_case" in cmd`), а не шлях цілком (`run_manager._job_pid_alive`,
`htr_manager._shard_pids_alive`). Якщо колись звірятимуть шлях — це місце треба
переглянути разом із ними.
"""
from __future__ import annotations

from pathlib import Path

#: `src/nyshporka/core/resources.py` → parents[3] == корінь дерева з кодом.
#: Після переїзду в пакет тут з'явиться `importlib.resources`; поки що ресурси
#: лежать поруч із `src/`, як і були.
CODE_ROOT = Path(__file__).resolve().parents[3]

#: Куди ресурси переїдуть, коли пакет стане встановлюваним. Перевіряється ПЕРШИМ,
#: тож переїзд можна робити потеково, не чіпаючи жодного споживача.
_BUNDLED = Path(__file__).resolve().parent.parent / "_web"


class ResourceMissing(RuntimeError):
    """Ресурс пакета не знайдено — установка неповна."""


def _pick(bundled: Path, source: Path, what: str) -> Path:
    if bundled.is_dir():
        return bundled
    if source.is_dir():
        return source
    raise ResourceMissing(
        f"не знайдено {what}: ні {bundled}, ні {source}. "
        f"Схоже, пакет установлено неповно — переустановіть або запустіть із репозиторію.")


def templates_dir() -> Path:
    """Jinja-шаблони й `console.html`."""
    return _pick(_BUNDLED / "templates", CODE_ROOT / "templates", "теки templates")


def static_dir() -> Path:
    """CSS і ES-модулі фронтенду."""
    return _pick(_BUNDLED / "static", CODE_ROOT / "static", "теки static")


def scripts_dir() -> Path:
    """Виконувані скрипти конвеєра (раннери HTR, оркестратор спотера)."""
    return _pick(_BUNDLED / "scripts", CODE_ROOT / "scripts", "теки scripts")


def script(name: str) -> str:
    """Абсолютний шлях до скрипта — таким, яким його можна класти в командний рядок.

    Повертає `str`, а не `Path`: усі споживачі одразу кладуть це в список
    аргументів субпроцесу, і зайве перетворення лише додавало б шуму.
    """
    return str(scripts_dir() / name)
