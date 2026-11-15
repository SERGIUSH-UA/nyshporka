"""🗜 Щільний запис геометрії сторінки для пакета обміну: числа різницями, не текстом.

Геометрія рядків — 84 % бакета Супряги (замір 15.11.2026: 70 ГБ із 84), і 95 % її —
полігони, тобто довгі списки пар цілих чисел, записані текстом JSON. gzip лишає від
такого тексту 28 %. Сусідні точки полігона відрізняються на кілька пікселів, тож ті
самі числа різницями під xz займають близько 40 % від нинішнього gzip (той самий
замір на пакетах пулу).

🔴 Беззбитково, і це перевіряється на записі, а не обіцяється. `encode_page` після
кодування розкодовує назад і звіряє з оригіналом; поле, яке не лягло в щільний запис
(дробові координати, незвична вкладеність), лишається в JSON-залишку як було. Тобто
найгірший випадок — сторінка без виграшу, а не сторінка з іншими рамками.

Запис сторінки (усі числа — little-endian):

    MAGIC · u32 довжина залишку · залишок (JSON) · потоки полів

Залишок — `{"k": [імена щільних полів], "p": {сторінка, де щільні поля замінено на 0}}`:
порядок ключів сторінки зберігається сам. Потік поля:

    u32 кількість · опис (int32) · u32 кількість · різниці (int8) · код типу ·
    u32 кількість · великі різниці

Опис — число елементів і на кожен: мітка та розміри (немає / плоский список цілих /
список точок однакової довжини). Різниці: для точок — стовпцями (усі x, потім усі y),
кожна від попередньої, а перша — від першої точки попереднього елемента (рядки
сторінки йдуть згори вниз, тож і ця різниця мала). Майже всі вони влазять у байт;
та, що не влазить, лишає на своєму місці `-128`, а сама йде в окремий масив
найвужчого типу, у який влазять усі такі (`h`, `i`, `q`). Один байт на число xz жме
і краще, і швидше, ніж масив int16 заради кількох широких значень на сторінку.

🔴 Масивами `array`, а не циклом по числу: перша версія писала варінти побайтово в
Python і кодувала 0,4 МБ пакета за секунду — пакування справи тривало б удесятеро
довше, ніж із gzip (замір 15.11.2026, 25 пакетів пулу).

Модуль без імпортів пакета: його кличе і клієнт, і сервер порталу.
"""
from __future__ import annotations

import json
import struct
import sys
from array import array
from itertools import accumulate, chain
from typing import Any

MAGIC = b"NG2"

_NONE, _FLAT, _POINTS = 0, 1, 2
_U32 = struct.Struct("<I")
#: Типи масиву великих різниць від найвужчого: (код, найменше, найбільше).
_TYPES = (("h", -2 ** 15, 2 ** 15 - 1), ("i", -2 ** 31, 2 ** 31 - 1),
          ("q", -2 ** 63, 2 ** 63 - 1))
_I32_MAX = 2 ** 31 - 1
#: Мітка в масиві байтів: «справжня різниця — наступна в масиві великих».
_ESC = -128
_SIZE = {"b": 1, "h": 2, "i": 4, "q": 8}
_BIG = sys.byteorder == "big"
_INT, _LIST = {int}, {list}


class GeomCodecError(ValueError):
    """Запис сторінки не розбирається."""


def _pack(code: str, values: list[int]) -> bytes:
    a = array(code, values)
    if _BIG:
        a.byteswap()
    return _U32.pack(len(values)) + a.tobytes()


def _encode_field(arr: list[Any]) -> bytes | None:
    """Потік поля або None — поле в щільний запис не лягає й лишається в залишку."""
    meta: list[int] = [len(arr)]
    data: list[int] = []
    prev_flat: list[int] = []
    prev_first: list[int] = []
    for item in arr:
        if item is None:
            meta.append(_NONE)
            continue
        if type(item) is not list:
            return None
        kinds = set(map(type, item))
        if kinds <= _INT:                       # плоский список цілих (і порожній)
            meta += (_FLAT, len(item))
            if len(prev_flat) == len(item):
                data += [a - b for a, b in zip(item, prev_flat, strict=True)]
            else:
                data += item
            prev_flat = item
            continue
        if kinds != _LIST:
            return None
        k = len(item[0])
        if k == 0 or set(map(len, item)) != {k} \
                or not set(map(type, chain.from_iterable(item))) <= _INT:
            return None
        meta += (_POINTS, len(item), k)
        base = prev_first if len(prev_first) == k else [0] * k
        for i in range(k):
            col = [pt[i] for pt in item]
            data.append(col[0] - base[i])
            data += [a - b for a, b in zip(col[1:], col, strict=False)]
        prev_first = item[0]
    big = [v for v in data if not -127 <= v <= 127]
    small = [v if -127 <= v <= 127 else _ESC for v in data] if big else data
    lo, hi = (min(big), max(big)) if big else (0, 0)
    code = next((c for c, low, high in _TYPES if low <= lo and hi <= high), "")
    if not code or max(meta) > _I32_MAX:
        return None                             # число поза int64 — нехай їде текстом
    return _pack("i", meta) + _pack("b", small) + code.encode("ascii") + _pack(code, big)


def _take(raw: bytes, pos: int, code: str) -> tuple[list[int], int]:
    """Масив із запису: лічильник не може обіцяти більше, ніж лишилось байтів."""
    if len(raw) - pos < 4:
        raise GeomCodecError("запис обірвано перед масивом")
    (n,) = _U32.unpack_from(raw, pos)
    pos += 4
    size = n * _SIZE[code]
    if size > len(raw) - pos:
        raise GeomCodecError("лічильник більший за запис")
    a = array(code)
    a.frombytes(raw[pos:pos + size])
    if _BIG:
        a.byteswap()
    return a.tolist(), pos + size


def _decode_field(raw: bytes, pos: int) -> tuple[list[Any], int]:
    meta, pos = _take(raw, pos, "i")
    data, pos = _take(raw, pos, "b")
    if pos >= len(raw):
        raise GeomCodecError("запис обірвано перед великими різницями")
    code = chr(raw[pos])
    if code not in ("h", "i", "q"):
        raise GeomCodecError(f"невідомий тип масиву {code!r}")
    big, pos = _take(raw, pos + 1, code)
    if big or _ESC in data:
        if data.count(_ESC) != len(big):
            raise GeomCodecError("великих різниць не стільки, скільки міток")
        rest = iter(big)
        data = [next(rest) if v == _ESC else v for v in data]
    if not meta or meta[0] < 0:
        raise GeomCodecError("опис поля порожній")
    out: list[Any] = []
    prev_flat: list[int] = []
    prev_first: list[int] = []
    m = 1
    d = 0
    try:
        for _ in range(meta[0]):
            tag = meta[m]
            if tag == _NONE:
                out.append(None)
                m += 1
                continue
            n = meta[m + 1]
            if tag == _FLAT:
                m += 2
                if n < 0 or d + n > len(data):
                    raise GeomCodecError("різниць менше, ніж обіцяє опис")
                flat = data[d:d + n]
                d += n
                if len(prev_flat) == n:
                    flat = [a + b for a, b in zip(flat, prev_flat, strict=True)]
                out.append(flat)
                prev_flat = flat
                continue
            if tag != _POINTS:
                raise GeomCodecError(f"невідома мітка елемента {tag}")
            k = meta[m + 2]
            m += 3
            if n <= 0 or k <= 0 or d + n * k > len(data):
                raise GeomCodecError("різниць менше, ніж обіцяє опис")
            base = prev_first if len(prev_first) == k else [0] * k
            cols = []
            for i in range(k):
                col = data[d:d + n]
                d += n
                col[0] += base[i]
                cols.append(accumulate(col))
            pts = [list(pt) for pt in zip(*cols, strict=True)]
            out.append(pts)
            prev_first = pts[0]
    except IndexError as exc:
        raise GeomCodecError("опис поля обірвано") from exc
    if m != len(meta) or d != len(data):
        raise GeomCodecError("в описі чи різницях лишилось зайве")
    return out, pos


def _dump(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def encode_page(payload: dict[str, Any]) -> bytes:
    """Сторінка геометрії → щільний запис. Розкодовується назад рівно в ту саму сторінку."""
    if type(payload) is not dict:
        raise GeomCodecError("сторінка геометрії — не об'єкт")
    names: list[str] = []
    streams: list[bytes] = []
    rest = dict(payload)
    for key, value in payload.items():
        if type(value) is not list or not value:
            continue
        try:
            blob = _encode_field(value)
        except (TypeError, OverflowError):
            blob = None
        # 🔴 Рівність із типами: у Python `1 == 1.0 == True`, а в JSON це три різні записи.
        if blob is None or _dump(_decode_field(blob, 0)[0]) != _dump(value):
            continue
        names.append(key)
        streams.append(blob)
        rest[key] = 0
    head = _dump({"k": names, "p": rest}).encode("utf-8")
    return b"".join((MAGIC, _U32.pack(len(head)), head, *streams))


def decode_page(raw: bytes) -> dict[str, Any]:
    """Щільний запис → сторінка геометрії. Битий запис — `GeomCodecError`."""
    if raw[:len(MAGIC)] != MAGIC:
        raise GeomCodecError("не щільний запис геометрії")
    pos = len(MAGIC)
    if len(raw) - pos < 4:
        raise GeomCodecError("запис обірвано в заголовку")
    (n,) = _U32.unpack_from(raw, pos)
    pos += 4
    if n > len(raw) - pos:
        raise GeomCodecError("заголовок довший за запис")
    try:
        head = json.loads(raw[pos:pos + n].decode("utf-8"))
        names, page = head["k"], head["p"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeomCodecError(f"заголовок не розбирається: {exc}") from exc
    if type(page) is not dict or type(names) is not list:
        raise GeomCodecError("заголовок не того вигляду")
    pos += n
    for key in names:
        if type(key) is not str or key not in page:
            raise GeomCodecError(f"щільне поле {key!r} відсутнє в сторінці")
        page[key], pos = _decode_field(raw, pos)
    if pos != len(raw):
        raise GeomCodecError("після останнього поля лишились байти")
    return page
