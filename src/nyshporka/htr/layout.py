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

🗜 Геометрія лежить СТИСНУТОЮ: `<стор>.lines.json.gz` (з 0.40.0; ідея №11 порталу).
Полігони рядків, записані текстом JSON, — найбільша частина простору: 46 КБ на
сторінку в середньому, а gzip лишає ~28 %. Старі прогони мають простий
`<стор>.lines.json`, і читаються обидві форми; `nysh disk compact` переводить
старе один раз. Усередині — той самий JSON байт у байт.

🔴 Імені файлу геометрії поза цим модулем у коді не пишуть: читати —
`geometry_path`/`read_geometry`, писати — `write_geometry`, перебирати —
`geometry_stems`. Запобіжник — `tests/test_geometry_one_door.py`. Виняток —
формат пулу Супряги (`share/`): там файл їде як `*.lines.json`, бо старі
клієнти учасників інакше пакета не приймуть.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any

#: Скільки разів пробуємо відкинути хвіст `-<тег>`. Голос буває складений
#: (`-diak_v4`, `-beam4`), але вкладених голосів не буває: побічний вихід
#: рахується з основного прогону, а не з іншого побічного.
_MAX_STRIP = 1


#: Суфікс стиснутої геометрії — так пишуть усі писачі.
GZ_SUFFIX = ".lines.json.gz"
#: Суфікс простої геометрії старих прогонів і пулу Супряги.
PLAIN_SUFFIX = ".lines.json"
#: Порядок пошуку: стиснута первинна. Обидві поруч бувають лише після обриву
#: між заміною й видаленням простої; `.gz` тоді цілий (атомарна заміна) і той
#: самий або новіший.
GEOMETRY_SUFFIXES = (GZ_SUFFIX, PLAIN_SUFFIX)
#: Рівень gzip: 6 — замір 03.11.2026, 28 % від простого; 9 дає на відсоток менше
#: при вдвічі довшому записі.
GZ_LEVEL = 6


def geometry_name(stem: str) -> str:
    """Ім'я файлу, яке пишуть писачі (і яке видно в повідомленнях)."""
    return f"{stem}{GZ_SUFFIX}"


def geometry_stem(name: str) -> str | None:
    """Стем сторінки з імені файлу геометрії; `None` — це не геометрія."""
    for suf in GEOMETRY_SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)]
    return None


def geometry_path(directory: Path, stem: str) -> Path | None:
    """Файл геометрії сторінки в ЦІЙ теці (без гілок голосу) або `None`."""
    for suf in GEOMETRY_SUFFIXES:
        f = directory / f"{stem}{suf}"
        if f.is_file():
            return f
    return None


def has_geometry(directory: Path, stem: str) -> bool:
    return geometry_path(directory, stem) is not None


def geometry_files(directory: Path, stem: str) -> list[Path]:
    """Усі файли геометрії сторінки, що є на диску (для перенесення й видалення)."""
    return [f for suf in GEOMETRY_SUFFIXES
            if (f := directory / f"{stem}{suf}").is_file()]


def geometry_bytes(path: Path) -> bytes:
    """Сирий JSON геометрії, розтиснутий за суфіксом. `OSError`/`ValueError` — далі."""
    raw = path.read_bytes()
    if path.name.endswith(".gz"):
        try:
            return gzip.decompress(raw)
        except (OSError, EOFError) as e:      # gzip.BadGzipFile — підклас OSError
            raise ValueError(f"{path.name}: битий gzip ({e})") from e
    return raw


def read_geometry(path: Path) -> dict[str, Any]:
    """Геометрія сторінки як словник. Битий файл — `ValueError`, не порожнеча."""
    data = json.loads(geometry_bytes(path).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: геометрія не словник")
    return data


def load_geometry(directory: Path, stem: str) -> dict[str, Any] | None:
    """Геометрія сторінки цієї теки; немає або не читається — `None`.

    Битий `.gz` (обірваний запис) поруч із цілим простим файлом не сліпить:
    читається наступна форма.
    """
    for f in geometry_files(directory, stem):
        try:
            return read_geometry(f)
        except (OSError, ValueError):
            continue
    return None


def gz_blob(raw: bytes) -> bytes:
    """Стиснути сирий JSON детерміновано (mtime=0): той самий вміст — ті самі байти."""
    return gzip.compress(raw, compresslevel=GZ_LEVEL, mtime=0)


def write_geometry_bytes(directory: Path, stem: str, raw: bytes) -> Path:
    """Записати сирий JSON геометрії стиснутим і прибрати просту копію сторінки."""
    from nyshporka.utils.atomic import atomic_write_bytes

    out = atomic_write_bytes(directory / geometry_name(stem), gz_blob(raw))
    (directory / f"{stem}{PLAIN_SUFFIX}").unlink(missing_ok=True)
    return out


def write_geometry(directory: Path, stem: str, payload: dict[str, Any]) -> Path:
    """Записати геометрію сторінки (стиснутою, полігони без точок на прямій).
    Простий файл тієї самої сторінки прибирається: інакше лишилися б дві різні
    правди про одні рамки."""
    from nyshporka.htr.geom_simplify import simplify_payload

    return write_geometry_bytes(
        directory, stem,
        json.dumps(simplify_payload(payload), ensure_ascii=False).encode("utf-8"))


def thinned_bytes(raw: bytes) -> bytes:
    """Сирий JSON геометрії з прорідженими полігонами (`htr.geom_simplify`).

    Нічого викинути — ті самі байти, а не переписаний JSON: старий прогін, у
    якого прорідити нічого, стискається байт у байт.
    """
    from nyshporka.htr.geom_simplify import simplify_payload

    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        return raw
    thin = simplify_payload(data)
    if thin == data:
        return raw
    return json.dumps(thin, ensure_ascii=False).encode("utf-8")


def remove_geometry(directory: Path, stem: str) -> None:
    for f in geometry_files(directory, stem):
        f.unlink(missing_ok=True)


def geometry_stems(directory: Path) -> set[str]:
    """Стеми сторінок теки, що мають геометрію, — одним `scandir`, обидві форми."""
    out: set[str] = set()
    try:
        with os.scandir(directory) as it:
            for e in it:
                stem = geometry_stem(e.name)
                if stem is not None and e.is_file():
                    out.add(stem)
    except OSError:
        pass
    return out


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
    own = geometry_path(run_dir, stem)
    if own is not None:
        return own, ""

    parent = parent_run_dir(run_dir)
    for _ in range(_MAX_STRIP):
        if parent is None:
            break
        candidate = geometry_path(parent, stem)
        if candidate is None:
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
    own = geometry_stems(run_dir)
    if own:
        return sorted(own)
    parent = parent_run_dir(run_dir)
    if parent is None or not parent.is_dir():
        return []
    return sorted(geometry_stems(parent))
