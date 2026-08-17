"""📖 Зразкова справа: пройти застосунок наскрізь ДО власних сканів.

Найдорожче питання людини, яка щойно поставила Нишпорку, — «а воно взагалі
працює?». Досі відповісти на нього було нічим: `nysh doctor` каже, чого бракує
машині, але прогнати на чомусь справжньому не було на чому, і перевірити задум
можна було, лише вклавши три тисячі власних сканів і почекавши ніч.

Тому в пакет вкладено три аркуші справи ДАХмО ф.315 оп.1 спр.159 (1821-1822) —
**з готовим машинним декодом обома голосами**. Це навмисно: ваги моделей у цій
версії ще не викладені, тож «прочитати» зразок нічим, зате все, що йде ПІСЛЯ
читання, працює одразу — гортач із рамкою рядка, пошук у декоді, реєстр справ,
сховище прочитаного. Тобто зразок показує саме той ланцюг, заради якого
застосунок і ставлять, і не вдає, ніби ваги вже є.

🔴 Кадри лежать у пакеті В ОРИГІНАЛЬНІЙ роздільності, і зменшувати їх не можна:
рамки рядків у `.lines.json` записані в координатах оригіналу, тож ужате
зображення тихо зсунуло б кожен кроп. Ціна — 6.2 МБ у колесі.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nyshporka.core.workspace import Workspace

#: Тека справи у просторі користувача (під `data/raw`).
CASE_DIR = "sample-315-159"
#: Прогони: основний голос і другий. Імена такі ж, як у справжніх прогонів, —
#: зразок має виглядати як звичайна робота, а не як окремий режим.
RUN_MAIN = "sample-315-159"
RUN_SIDE = "sample-315-159-diak"
CASE_KEY = "DAHMO/315/159"

_VOICES = {"pysar": RUN_MAIN, "diak": RUN_SIDE}


def sample_dir() -> Path | None:
    """Тека зразка всередині пакета — або None, якщо вона не доїхала в колесо.

    Шлях від `__file__`, як і решта даних пакета (`archives/data`,
    `htr/data`): `importlib.resources` тут не вживається ніде, і заводити другий
    спосіб заради одного модуля означало б мати два місця, де це ламається.
    """
    d = Path(__file__).resolve().parent / "data" / "sample"
    return d if (d / "sample.json").is_file() else None


def describe() -> dict[str, Any] | None:
    """Сайдкар зразка: шифра, кадри, голоси, походження."""
    d = sample_dir()
    if d is None:
        return None
    try:
        data: dict[str, Any] = json.loads((d / "sample.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def installed(ws: Workspace) -> bool:
    """Чи розгорнутий зразок у цьому просторі.

    Приймач — КАДРИ на диску, а не запис у якомусь стані: тека справи могла
    поїхати разом із простором або бути прибрана руками, і тоді «встановлено»
    означало б показувати кнопку гортача, за якою немає аркуша.
    """
    case = ws.raw / CASE_DIR
    return case.is_dir() and any(case.glob("*.jpg"))


def install(ws: Workspace, *, force: bool = False) -> dict[str, Any]:
    """Розгорнути зразок у просторі. Повертає, що саме з'явилось.

    Ідемпотентно: наявні файли не переписуються, доки не сказано `force`. Мета
    прогону натомість пишеться щоразу — саме в ній стоїть `case_dir`, а він
    залежить від того, ДЕ цей простір лежить.
    """
    src = sample_dir()
    if src is None:
        raise FileNotFoundError(
            "зразкова справа не доїхала в цю збірку пакета — перевстановлення "
            "має її повернути (`nysh doctor` покаже, чи все на місці)")

    case = ws.raw / CASE_DIR
    case.mkdir(parents=True, exist_ok=True)
    frames: list[str] = []
    for f in sorted((src / "frames").iterdir()):
        dst = case / f.name
        if force or not dst.exists():
            shutil.copy2(f, dst)
        if f.suffix.lower() == ".jpg":
            frames.append(f.name)

    runs: list[str] = []
    for voice, run_name in _VOICES.items():
        out = ws.htr_reports / run_name
        out.mkdir(parents=True, exist_ok=True)
        vsrc = src / "decode" / voice
        if not vsrc.is_dir():
            continue
        for f in sorted(vsrc.iterdir()):
            if f.name == "_htr_meta.json":
                continue
            dst = out / f.name
            if force or not dst.exists():
                shutil.copy2(f, dst)
        meta = json.loads((vsrc / "_htr_meta.json").read_text(encoding="utf-8"))
        # 🔴 Шлях ВІДНОСНИЙ, і це не дрібниця. Простір переносять між дисками й
        # віддають колезі; абсолютний шлях пережив би такий переїзд лише до
        # першого відкриття гортача. Саме на цьому й горять хмарні прогони:
        # у їхній меті лишається `/tmp/htrcase/…` орендованого боксу, і аркуш
        # потім нема звідки взяти. `under_raw` відносний шлях приймає, рахуючи
        # його від кореня простору.
        meta["case_dir"] = f"data/raw/{CASE_DIR}"
        meta["case_key"] = CASE_KEY
        (out / "_htr_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        runs.append(run_name)

    info = describe() or {}
    return {"case_dir": str(case), "case_key": CASE_KEY, "frames": frames,
            "runs": runs, "shifra": info.get("shifra", ""),
            "frames_total": info.get("frames_total")}
