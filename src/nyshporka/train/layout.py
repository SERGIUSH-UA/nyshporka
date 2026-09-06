"""📐 Де в просторі живе лабораторія — одне джерело шляхів для всіх модулів.

Шляхи тут, а не в кожному модулі окремо: інакше збірник корпусу і вкладка
розмітки одного дня дивилися б у різні теки, і розбіжність виглядала б як
«наборів немає» там, де вони є.

Два кореня за класом даних (`setup/packs.py`: незамінне — не в кеш):

* `data/train/` — **незамінне**: мітки, звірені оком, і кропи, до яких вони
  прив'язані. Кропи відтворювані лише поки живий кеш сегментації прогону, і
  в дослідницькому конвеєрі саме вони й зникли разом з однією знесеною текою
  (49 наборів із 51 лишились мітками без картинок).
* `data/derived/train/` — **відтворюване**: корпуси й прогони трену. Дорого,
  але з міток і рецепта збирається знову.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace

SETS = "sets"
CROPS = "crops"
CORPORA = "corpora"
RUNS = "runs"

#: Ім'я набору, корпусу чи прогону — те, що стане текою. Без слешів і крапок
#: спереду: ці імена приходять із командного рядка й з браузера, і гард тут
#: той самий, що в `htr_store._case_dir` для імен прогонів.
NAME_RE = re.compile(r"^[\w][\w.\-]*$", re.UNICODE)


def valid_name(name: str) -> bool:
    return bool(name) and bool(NAME_RE.match(name)) and ".." not in name


def _ws(ws: Workspace | None) -> Workspace:
    return ws if ws is not None else workspace()


def train_root(ws: Workspace | None = None) -> Path:
    """Незамінне: `data/train`."""
    return _ws(ws).data / "train"


def sets_root(ws: Workspace | None = None) -> Path:
    return train_root(ws) / SETS


def crops_root(ws: Workspace | None = None) -> Path:
    return train_root(ws) / CROPS


def derived_root(ws: Workspace | None = None) -> Path:
    """Відтворюване: `data/derived/train`."""
    return _ws(ws).derived / "train"


def corpora_root(ws: Workspace | None = None) -> Path:
    return derived_root(ws) / CORPORA


def runs_root(ws: Workspace | None = None) -> Path:
    return derived_root(ws) / RUNS


def config_root(ws: Workspace | None = None) -> Path:
    """Рецепти й джерела: `config/train`."""
    return _ws(ws).config / "train"


def models_root(ws: Workspace | None = None) -> Path:
    """Куди лягають просунуті ваги — та сама тека, яку читає `htr/run.model_dirs`."""
    return _ws(ws).spotter / "models"


def run_id_for(corpus: str, recipe: str, params: dict[str, Any]) -> str:
    """Детермінований ідентифікатор прогону трену.

    🔴 Не час і не випадкове число. Повторний `start` з тим самим корпусом і
    тими самими параметрами мусить підхопити СВІЙ прогін (перевірити стан,
    докачати ваги), а не завести другий: у хмарі другий прогін — це другий
    рахунок, локально — друга карта на ніч.
    """
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")
    fp = hashlib.blake2b(blob, digest_size=4).hexdigest()
    return f"{corpus}__{recipe}__{fp}"
