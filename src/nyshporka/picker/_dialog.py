"""🪟 Дитина, яка показує системне вікно вибору. Запускається окремим процесом.

Чому окремим процесом, а не потоком у демоні: Tk вимагає головного потоку свого
процесу, а там крутиться цикл подій застосунку. Заразом виходять три речі, яких
інакше не буває: падіння Tk не валить демона; вбивство процесу гарантовано
закриває вікно (іншого способу закрити системний діалог ззовні не існує); а
підозріло довге очікування має кого вбивати.

Запит приходить рядком JSON у stdin, відповідь іде рядком у stdout із міткою.

🔴 Мітка обов'язкова. На Linux Tk і Gtk пишуть попередження просто в потоки
(«Gtk-Message: Failed to load module…»), і батько, який читає «останній рядок»,
дістав би сміття замість шляху. З міткою він бере свій рядок, а решту складає в
пояснення відмови — тобто попередження не губляться, але й не видають себе за
відповідь.

Модуль — єдине місце в пакеті, де є `import tkinter`, і імпорт стоїть усередині
функції: батьківський бік мусить лишатись придатним там, де Tk немає взагалі.
"""
from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from typing import Any

#: Мітка рядка з відповіддю.
SENTINEL = "@@PICK@@ "


def _tk_root(*, raise_it: bool = True) -> Any:
    """Невидиме вікно-власник із заявкою бути поверх усіх.

    🔴 Вікно-власник потрібне не для краси. Системний діалог, відкритий без
    батька, дістає за власника робочий стіл — і не успадковує «поверх усіх».
    Тобто саме та вада, заради якої тут стоїть `-topmost`, лишалась би
    невилікуваною: вікно так само ховалось би за браузером.

    🔴 `raise_it=False` для перевірки спроможності. `focus_force` відбирає фокус
    у того, хто зараз працює, і на Windows встигає блимнути в панелі задач —
    навіть над схованим вікном. Питання «чи вміє ця машина показати діалог»
    ставиться фоном і не сміє смикати екран людини: перевірка, яку видно, гірша
    за відсутню, бо виглядає як застосунок, що живе власним життям.
    """
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()                     # порожнє сіре вікно нікому не потрібне
    if not raise_it:
        return root
    # Менеджер вікон не зобов'язаний уміти ні того, ні того — і там, де не вміє,
    # вікно просто лишиться там, куди його поклала система.
    with contextlib.suppress(Exception):
        root.attributes("-topmost", True)
    with contextlib.suppress(Exception):
        root.update_idletasks()
        root.lift()
        root.focus_force()
    return root


def _types(raw: list[Any]) -> list[tuple[str, str]]:
    """Фільтри у вигляді, якого хоче Tk: [(підпис, "*.jpg *.png"), …]."""
    out: list[tuple[str, str]] = []
    for item in raw or []:
        if isinstance(item, dict):
            label = str(item.get("label") or "файли")
            pats = item.get("patterns") or []
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            label, pats = str(item[0]), item[1]
        else:
            continue
        if isinstance(pats, str):
            pats = [pats]
        mask = " ".join(str(x) for x in pats) or "*.*"
        out.append((label, mask))
    if out:
        out.append(("усі файли", "*.*"))
    return out


def answer(req: dict[str, Any], root_factory: Callable[[], Any] | None = None,
           dialogs: Any = None) -> dict[str, Any]:
    """Відповідь на один запит. Виділено окремо, щоб перевірятись без екрана.

    `root_factory` і `dialogs` підмінні: приймач ганяється в середовищі, де
    жодного вікна показати не можна, і мусить перевіряти розбір запиту й форму
    відповіді, не торкаючись Tk.
    """
    mode = str(req.get("mode") or "dir")
    if mode == "probe":
        # Найдешевша чесна перевірка: вікно справді створюється й гаситься.
        # Наявність пакета `tkinter` цього не доводить — бібліотека Tk може бути
        # відсутня в системі, і дізнаєшся про це рівно в мить показу.
        #
        # 🔴 без підняття й фокуса: перевірку не має бути видно. Інакше вона
        # смикає екран того, хто зараз працює, і виглядає це не як перевірка, а
        # як застосунок, що сам відкриває вікна.
        root = (root_factory or (lambda: _tk_root(raise_it=False)))()
        with contextlib.suppress(Exception):
            root.destroy()
        return {"state": "ready"}

    if dialogs is None:
        from tkinter import filedialog as dialogs

    root = (root_factory or _tk_root)()
    title = str(req.get("title") or "")
    start = str(req.get("start") or "")
    types = _types(req.get("types") or [])
    name = str(req.get("name") or "")
    try:
        if mode == "dir":
            got = dialogs.askdirectory(parent=root, title=title, initialdir=start,
                                       mustexist=True)
            paths = [got] if got else []
        elif mode == "files":
            got = dialogs.askopenfilenames(parent=root, title=title,
                                           initialdir=start, filetypes=types)
            paths = list(got or [])
        elif mode == "save":
            got = dialogs.asksaveasfilename(parent=root, title=title,
                                            initialdir=start, initialfile=name,
                                            filetypes=types)
            paths = [got] if got else []
        else:
            got = dialogs.askopenfilename(parent=root, title=title,
                                          initialdir=start, filetypes=types)
            paths = [got] if got else []
    finally:
        with contextlib.suppress(Exception):
            root.destroy()

    paths = [str(p) for p in paths if p]
    # 🔴 Порожній вибір — це «скасував», окремий стан. Звести його до порожнього
    # списку означало б зробити скасування невідрізнимим від «вікно не
    # відкрилось» і від «людина не відповіла», а лікуються вони по-різному.
    return {"state": "picked" if paths else "cancelled", "paths": paths}


def main(argv: list[str] | None = None) -> int:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw or "{}")
    except ValueError as exc:
        out = {"state": "error", "error": f"запит не читається: {exc}"}
    else:
        try:
            out = answer(req)
        except Exception as exc:
            # Причина мусить дійти до людини названою. Голий текст системи
            # («ImportError: libtk8.6.so») сам по собі не каже, що робити, але
            # без нього не сказати й того.
            out = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(SENTINEL + json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":   # pragma: no cover — точка входу процесу
    raise SystemExit(main())
