"""📐 Розкладка теки прогону: де лежить текст, а де геометрія рядків.

Прогін пише текст у теку прогону, а ПОБІЧНІ ГОЛОСИ (ансамбль, beam) — у
сестринські теки `<прогін>-<тег>`. Геометрію рядків (`<стор>.lines.json`) при
цьому пише лише основна тека, і це не пропуск: побічні виходи рахуються з ТІЄЇ
САМОЇ сегментації, тими самими кропами й вирівняні по масці основного тексту.
Рядок N теки голосу — це рядок N основної теки, тож і рамка в нього та сама.
Класти копію файла в кожну теку голосу означало б дублювати ті самі байти й
дати їм шанс розійтися.

🔴 Але споживач, який бере текст і геометрію З ОДНІЄЇ теки, на гілці голосу
лишається без рамок. Заміряно на двох кампаніях простору `rodovid-shupyky`:

    spr-1283:          txt=366  lines=366
    spr-1283-diak_v4:  txt=366  lines=0

Тому правило резолву живе тут, поруч із раннером, який цю розкладку й створює.

🔴 Резолв САМОПЕРЕВІРНИЙ. Ім'я теки голосу не відрізнити від імені справи з
дефісом (`230-1-2а`, `spr-1739`), тож нічого не вгадуємо: піднімаємось на рівень
вище лише тоді, коли сусідня тека справді існує, справді має рамки, і число
рядків у ній ЗБІГАЄТЬСЯ з нашим. Розбіжність означає, що припущення про
вирівнювання не діє, — і тоді краще відмовити, ніж вирізати чужий рядок.
"""

from __future__ import annotations

from pathlib import Path

#: Скільки разів пробуємо відкинути хвіст `-<тег>`. Голос буває складений
#: (`-diak_v4`, `-beam4`), але вкладених голосів не буває: побічний вихід
#: рахується з основного прогону, а не з іншого побічного.
_MAX_STRIP = 1


def geometry_name(stem: str) -> str:
    return f"{stem}.lines.json"


def parent_run_dir(run_dir: Path) -> Path | None:
    """Тека основного прогону для гілки голосу. `None` — це вже основна.

    Ім'я гілки будується як `<прогін>-<тег>`, тож кандидат — це відкинутий
    останній сегмент. Існування теки перевіряє викликач: тут лише форма імені.
    """
    name = run_dir.name
    head, sep, tag = name.rpartition("-")
    if not sep or not head or not tag:
        return None
    return run_dir.parent / head


def _line_count(path: Path) -> int | None:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return None


def resolve_geometry(run_dir: Path, stem: str) -> tuple[Path | None, str]:
    """Файл рамок для сторінки `stem` прогону `run_dir`.

    Повертає `(шлях, причина_відмови)`. Один із двох завжди порожній.

    Порядок: своя тека → тека основного прогону (якщо ця схожа на гілку голосу
    і число рядків збігається).
    """
    own = run_dir / geometry_name(stem)
    if own.is_file():
        return own, ""

    parent = parent_run_dir(run_dir)
    for _ in range(_MAX_STRIP):
        if parent is None:
            break
        candidate = parent / geometry_name(stem)
        if not candidate.is_file():
            break
        mine = _line_count(run_dir / f"{stem}.txt")
        theirs = _line_count(parent / f"{stem}.txt")
        if mine is None or theirs is None:
            break
        if mine != theirs:
            # 🔴 Мовчки різати не можна: рамка під індексом N належала б іншому
            # рядку, і кроп прийшов би не з того місця сторінки — а це рівно та
            # помилка, яку око не спіймає, бо картинка виглядає осмисленою.
            return None, (
                f"рамки є в {parent.name}, але рядків там {theirs}, а тут {mine} — "
                f"вирівнювання не діє, кроп був би не з того рядка")
        return candidate, ""

    if parent is not None and (parent / f"{stem}.txt").is_file():
        return None, (
            f"ні в {run_dir.name}, ні в {parent.name} немає {geometry_name(stem)}")
    return None, f"немає {geometry_name(stem)} у {run_dir.name}"


def pages_with_geometry(run_dir: Path) -> list[str]:
    """Сторінки прогону, для яких рамки взагалі є (з урахуванням гілки голосу).

    Потрібно там, де інструмент перебирає прогін цілком і мусить назвати
    знаменник: «рамок немає для N сторінок із M» — це інше твердження, ніж
    «входжень немає».
    """
    own = {p.name[: -len(".lines.json")] for p in run_dir.glob("*.lines.json")}
    if own:
        return sorted(own)
    parent = parent_run_dir(run_dir)
    if parent is None or not parent.is_dir():
        return []
    return sorted(p.name[: -len(".lines.json")] for p in parent.glob("*.lines.json"))
