"""🗜 Щільний запис геометрії сторінки для пакета обміну: числа дельтами, не текстом.

Геометрія рядків — 84 % бакета Супряги (замір 15.11.2026: 70 ГБ із 84), і 95 % її —
полігони, тобто довгі списки пар цілих чисел, записані текстом JSON. gzip лишає від
такого тексту 28 %. Сусідні точки полігона відрізняються на кілька пікселів, тож ті
самі числа різницями у варінтах під xz займають 39 % від нинішнього gzip (той самий
замір, 12 пакетів, 5 347 сторінок).

🔴 Беззбитково, і це перевіряється на записі, а не обіцяється. `encode_page` після
кодування розкодовує назад і звіряє з оригіналом; поле, яке не лягло в щільний запис
(дробові координати, незвична вкладеність), лишається в JSON-залишку як було. Тобто
найгірший випадок — сторінка без виграшу, а не сторінка з іншими рамками.

Запис сторінки:

    MAGIC · варінт довжини залишку · залишок (JSON) · потоки полів

Залишок — `{"k": [імена щільних полів], "p": {сторінка, де щільні поля замінено на 0}}`:
порядок ключів сторінки зберігається сам. Потік поля — список елементів, кожен із
міткою: немає (`null`), плоский список цілих (рамка) або список точок однакової
довжини (полігон, базова лінія). Точка пишеться різницею від попередньої; перша
точка елемента — різницею від першої точки попереднього елемента (рядки сторінки
йдуть згори вниз, і ця різниця теж мала).

Модуль без імпортів пакета: його кличе і клієнт, і сервер порталу.
"""
from __future__ import annotations

import json
from typing import Any

MAGIC = b"NG1"

_NONE, _FLAT, _POINTS = 0, 1, 2


class GeomCodecError(ValueError):
    """Запис сторінки не розбирається."""


def _put(n: int, out: bytearray) -> None:
    """Ціле зі знаком: зигзаг + варінт (довільна довжина, як і самі цілі Python)."""
    n = (n << 1) if n >= 0 else ((-n << 1) - 1)
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)


class _Reader:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes, pos: int = 0) -> None:
        self.buf = buf
        self.pos = pos

    def left(self) -> int:
        return len(self.buf) - self.pos

    def get(self) -> int:
        buf, pos = self.buf, self.pos
        n = shift = 0
        while True:
            if pos >= len(buf):
                raise GeomCodecError("запис обірвано посеред числа")
            b = buf[pos]
            pos += 1
            n |= (b & 0x7F) << shift
            if b < 0x80:
                break
            shift += 7
        self.pos = pos
        return (n >> 1) if not n & 1 else -((n + 1) >> 1)

    def count(self) -> int:
        """Лічильник: невід'ємний і не більший за залишок запису (кожне число — щонайменше
        байт), інакше три байти оголосили б мільярд точок."""
        n = self.get()
        if n < 0 or n > self.left():
            raise GeomCodecError("лічильник більший за запис")
        return n


def _is_int(x: Any) -> bool:
    return type(x) is int  # bool — підклас int, а в JSON це інше значення


def _shape(item: Any) -> tuple[int, int] | None:
    """(мітка, довжина точки) елемента або None — у щільний запис не лягає."""
    if item is None:
        return _NONE, 0
    if type(item) is not list:
        return None
    if all(_is_int(v) for v in item):
        return _FLAT, 0
    k = len(item[0]) if type(item[0]) is list else 0
    if k == 0:
        return None
    for pt in item:
        if type(pt) is not list or len(pt) != k or not all(_is_int(v) for v in pt):
            return None
    return _POINTS, k


def _encode_field(arr: list[Any]) -> bytes | None:
    shapes = [_shape(it) for it in arr]
    if any(s is None for s in shapes):
        return None
    out = bytearray()
    _put(len(arr), out)
    prev_flat: list[int] = []
    prev_first: list[int] = []
    for item, shape in zip(arr, shapes, strict=True):
        tag, k = shape  # type: ignore[misc]
        _put(tag, out)
        if tag == _NONE:
            continue
        _put(len(item), out)
        if tag == _FLAT:
            same = len(prev_flat) == len(item)
            for i, v in enumerate(item):
                _put(v - prev_flat[i] if same else v, out)
            prev_flat = item
            continue
        _put(k, out)
        base = prev_first if len(prev_first) == k else [0] * k
        prev = base
        for pt in item:
            for i in range(k):
                _put(pt[i] - prev[i], out)
            prev = pt
        if item:
            prev_first = item[0]
    return bytes(out)


def _decode_field(r: _Reader) -> list[Any]:
    out: list[Any] = []
    prev_flat: list[int] = []
    prev_first: list[int] = []
    for _ in range(r.count()):
        tag = r.get()
        if tag == _NONE:
            out.append(None)
            continue
        n = r.count()
        if tag == _FLAT:
            same = len(prev_flat) == n
            flat = [r.get() + (prev_flat[i] if same else 0) for i in range(n)]
            out.append(flat)
            prev_flat = flat
            continue
        if tag != _POINTS:
            raise GeomCodecError(f"невідома мітка елемента {tag}")
        k = r.count()
        if k == 0 and n:
            raise GeomCodecError("точка нульової довжини")
        prev = prev_first if len(prev_first) == k else [0] * k
        pts: list[list[int]] = []
        for _ in range(n):
            if r.left() < k:
                raise GeomCodecError("запис обірвано посеред точки")
            prev = [r.get() + prev[i] for i in range(k)]
            pts.append(prev)
        out.append(pts)
        if pts:
            prev_first = pts[0]
    return out


def _same(a: Any, b: Any) -> bool:
    """Рівність із типами: у Python `1 == 1.0 == True`, а в JSON це три різні записи."""
    return json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


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
        blob = _encode_field(value)
        if blob is None or not _same(_decode_field(_Reader(blob)), value):
            continue
        names.append(key)
        streams.append(blob)
        rest[key] = 0
    head = json.dumps({"k": names, "p": rest}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    out = bytearray(MAGIC)
    n = len(head)
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    out += head
    for blob in streams:
        out += blob
    return bytes(out)


def decode_page(raw: bytes) -> dict[str, Any]:
    """Щільний запис → сторінка геометрії. Битий запис — `GeomCodecError`."""
    if raw[:len(MAGIC)] != MAGIC:
        raise GeomCodecError("не щільний запис геометрії")
    pos = len(MAGIC)
    n = shift = 0
    while True:
        if pos >= len(raw):
            raise GeomCodecError("запис обірвано в заголовку")
        b = raw[pos]
        pos += 1
        n |= (b & 0x7F) << shift
        if b < 0x80:
            break
        shift += 7
    if n > len(raw) - pos:
        raise GeomCodecError("заголовок довший за запис")
    try:
        head = json.loads(raw[pos:pos + n].decode("utf-8"))
        names, page = head["k"], head["p"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeomCodecError(f"заголовок не розбирається: {exc}") from exc
    if type(page) is not dict or type(names) is not list:
        raise GeomCodecError("заголовок не того вигляду")
    r = _Reader(raw, pos + n)
    for key in names:
        if key not in page:
            raise GeomCodecError(f"щільне поле {key!r} відсутнє в сторінці")
        page[key] = _decode_field(r)
    if r.left():
        raise GeomCodecError("після останнього поля лишились байти")
    return page
