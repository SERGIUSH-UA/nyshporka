"""🎓 Матеріал для навчання з робочої теки опису — окремо від пакета `.nyshopys`.

Пакет — публічна частина опису: текст сторінок, таблиця справ, нормалізовані назви. Матеріал для
навчання не публікується: його бере лише власник Нишпорки за умовами Засік, які людина прийняла на
порталі (`/zasiky/umovy`). Сервер без прийнятих умов не прийме ні опису, ні матеріалу.

Що їде — за ПЕРЕЛІКОМ дозволених файлів (`IMENA`), а не «вся тека»: робоча тека несе й локальні
шляхи з іменем користувача (`opys.json:pdf`, `_htr_meta.json:case_dir`).

| у архіві | звідки | навіщо |
|---|---|---|
| `navchannia.json` | складає збирач | схема, пакет, до якого матеріал, лічильники |
| `opys.json` | паспорт без шляхів | шифра, джерело (адреса, sha256), сторінки |
| `opys_meta.json` | метадані агента | форма, колонки, скільки справ, сторінки таблиці |
| `table.tsv` | таблиця справ | номер, звідки номер (`no_src`: прочитано / добудовано), статус |
| `run[-голос]/NNNN.txt` | прочитане рядок у рядок | текст голосу |
| `run[-голос]/NNNN.lines.json.gz` | рамки й полігони рядків | геометрія (рядок `i` ↔ рядок тексту `i`) |
| `run[-голос]/model.json` | з `_htr_meta.json` — лише модель і передобробка | чим прочитано |
| `dochyt/dochyt.json` | рамки кропів колонки № і плям | де кроп на сторінці |
| `dochyt/kropy/<id>.jpg` | кроп номера, сірий JPEG | пара «зображення → номер» |
| `dochyt/kropy_out/<id>.txt` | читання кропу рушієм | що рушій бачив у кропі |
| `vl/NNNN.md`, `vl/NNNN.blocks.json` | машинопис: розмітка рушія друку | |

🔴 Мітка номера — не текст рушія, а номер таблиці з `no_src` і статусом. Номер, підтверджений
ланцюжком, — правда про справу, але кроп міг загубити першу цифру («313» на кропі, 1313 у таблиці).
Тому їде і читання кропу, і рамка: пару «кроп → номер» відбирає навчання, а не збирач.

Перевірка (`perevirka`) — та сама на обох кінцях: сервер імпортує цей модуль, як ворота пакета.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = 1
FILE = "navchannia.json"

#: Дозволені імена в архіві. Голос — `run` або `run-<тег>` (другий голос, `nysh read --with`).
IMENA = re.compile(
    r"^(?:navchannia\.json|opys\.json|opys_meta\.json|table\.tsv"
    r"|run(?:-[A-Za-z0-9_.]{1,40})?/(?:\d{4}\.txt|\d{4}\.lines\.json\.gz|model\.json)"
    r"|dochyt/(?:dochyt\.json|kropy/\d{4}__[a-z]\d{3}\.jpg|kropy_out/\d{4}__[a-z]\d{3}\.txt)"
    r"|vl/\d{4}\.(?:md|blocks\.json))$")

#: Стелі під найбільший опис, який ми бачили (тисяча сторінок): ф.445 оп.5 — 2,4 МБ на 29 сторінок
#: (737 кропів колонки №), тобто ~82 МБ на тисячу. Кропи — JPEG, стиснення їх не зменшує.
MAX_ARKHIV = 128 << 20         # стиснутий архів (як увесь пакет)
MAX_ROZHORNUTO = 192 << 20     # усе розпаковане
MAX_FAILIV = 60_000
MAX_KROP = 256 << 10
MAX_FAIL = 8 << 20

#: Поля `_htr_meta.json`, що їдуть (`model.json`). Решта — шляхи, машина, час.
_MODEL_POLIA = ("model", "engine", "script", "enhance", "seg_height", "pysar_fp16", "pp_fp16",
                "version")
#: Поля паспорта, що їдуть. Без `pdf` і `published`: це локальні шляхи.
_PASPORT_POLIA = ("repo", "fond", "opys", "form", "pages", "title", "years", "language")
_DZHERELO_POLIA = ("kind", "url", "page_link", "label", "sha256")

_JPEG = b"\xff\xd8\xff"


class NavchanniaError(ValueError):
    """Архів матеріалу битий, чужий чи завеликий — з причиною для людини."""


@dataclass
class Zvit:
    """Що в архіві: лічильники для відповіді людині й запису на сервері."""

    failiv: int = 0
    storinok: int = 0
    kropiv: int = 0
    golosy: list[str] = field(default_factory=list)
    bytes: int = 0

    def as_json(self) -> dict[str, Any]:
        return {"failiv": self.failiv, "storinok": self.storinok, "kropiv": self.kropiv,
                "golosy": list(self.golosy), "bytes": self.bytes}


# ── Збирання (клієнт) ─────────────────────────────────────────────────────────


def _golosy(d: Path) -> list[Path]:
    """Теки прочитаного: головна `run` і `run-<тег>` другого голосу."""
    out = [d / "run"] if (d / "run").is_dir() else []
    out += sorted(p for p in d.glob("run-*") if p.is_dir() and IMENA.match(f"{p.name}/model.json"))
    return out


def _model(run: Path) -> dict[str, Any]:
    f = run / "_htr_meta.json"
    try:
        got = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        got = {}
    return {k: got[k] for k in _MODEL_POLIA if isinstance(got, dict) and k in got}


def zibraty(d: Path, *, paket_sha256: str = "", tool: str = "") -> tuple[bytes, Zvit]:
    """Робоча тека опису → байти архіву (tar.gz) і що в ньому.

    Береться лише те, що є: опис, прочитаний на іншій машині без дочиту, їде без кропів."""
    from nyshporka.opysy import workdir as W

    pas = W.load(d)
    chleny: dict[str, bytes] = {}
    zvit = Zvit()

    def _dodaty(name: str, data: bytes) -> None:
        if IMENA.match(name):
            chleny[name] = data

    dzherelo = {k: (pas.get("source") or {}).get(k, "") for k in _DZHERELO_POLIA}
    _dodaty("opys.json", json.dumps({**{k: pas.get(k) for k in _PASPORT_POLIA},
                                     "source": dzherelo}, ensure_ascii=False, indent=1).encode())
    for name in ("opys_meta.json", "table.tsv"):
        if (d / name).is_file():
            _dodaty(name, (d / name).read_bytes())
    for run in _golosy(d):
        _dodaty(f"{run.name}/model.json", json.dumps(_model(run), ensure_ascii=False).encode())
        n = 0
        for f in sorted(run.iterdir()):
            if f.is_file() and re.fullmatch(r"\d{4}\.(?:txt|lines\.json\.gz)", f.name):
                _dodaty(f"{run.name}/{f.name}", f.read_bytes())
                n += f.suffix == ".txt"
        if n:
            zvit.golosy.append(run.name)
            zvit.storinok = max(zvit.storinok, n)
    dd = W.dochyt_dir(d)
    if (dd / "dochyt.json").is_file():
        _dodaty("dochyt/dochyt.json", (dd / "dochyt.json").read_bytes())
    for pidteka in ("kropy", "kropy_out"):
        for f in sorted((dd / pidteka).glob("*")) if (dd / pidteka).is_dir() else []:
            if f.is_file():
                _dodaty(f"dochyt/{pidteka}/{f.name}", f.read_bytes())
    vl = W.vl_dir(d)
    for f in sorted(vl.glob("*")) if vl.is_dir() else []:
        if f.is_file():
            _dodaty(f"vl/{f.name}", f.read_bytes())
    zvit.kropiv = sum(1 for n in chleny if n.startswith("dochyt/kropy/"))
    chleny[FILE] = json.dumps({"schema": SCHEMA, "paket_sha256": paket_sha256, "tool": tool,
                               "storinok": zvit.storinok, "kropiv": zvit.kropiv,
                               "golosy": zvit.golosy}, ensure_ascii=False).encode()
    zvit.failiv = len(chleny)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(chleny):
            info = tarfile.TarInfo(name)
            info.size = len(chleny[name])
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(chleny[name]))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=6) as gz:
        gz.write(raw.getvalue())
    blob = out.getvalue()
    zvit.bytes = len(blob)
    if len(blob) > MAX_ARKHIV:
        raise NavchanniaError(f"матеріал для навчання {len(blob) >> 20} МБ — більше за стелю "
                              f"{MAX_ARKHIV >> 20} МБ")
    return blob, zvit


# ── Перевірка (сервер і клієнт) ──────────────────────────────────────────────


def perevirka(blob: bytes) -> Zvit:
    """Чужі байти архіву → що в ньому. Будь-яка вада — `NavchanniaError`.

    🔴 Лише відомі імена, лише звичайні файли, без дублів, стеля на кожен файл і на все розпаковане;
    кроп — JPEG за підписом. Нічого не розпаковується на диск."""
    if len(blob) > MAX_ARKHIV:
        raise NavchanniaError(f"архів більший за стелю {MAX_ARKHIV >> 20} МБ")
    try:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")  # noqa: SIM115 — закривається нижче
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise NavchanniaError(f"не архів матеріалу (не tar.gz або обрізаний): {exc}") from exc
    zvit = Zvit(bytes=len(blob))
    bachyv: set[str] = set()
    vsoho = 0
    storinky: dict[str, int] = {}
    manifest: dict[str, Any] | None = None
    with tar:
        try:
            for info in tar:
                name = info.name
                if not IMENA.match(name):
                    raise NavchanniaError(f"чужий файл в архіві: {name[:80]}")
                if not info.isfile():
                    raise NavchanniaError(f"{name}: не звичайний файл")
                if name in bachyv:
                    raise NavchanniaError(f"{name} в архіві двічі")
                bachyv.add(name)
                if len(bachyv) > MAX_FAILIV:
                    raise NavchanniaError(f"файлів в архіві понад {MAX_FAILIV}")
                cap = MAX_KROP if name.endswith(".jpg") else MAX_FAIL
                if info.size > cap:
                    raise NavchanniaError(f"{name}: {info.size} байт — більше за стелю {cap}")
                vsoho += info.size
                if vsoho > MAX_ROZHORNUTO:
                    raise NavchanniaError("архів розгортається більшим за стелю")
                fh = tar.extractfile(info)
                data = fh.read(info.size + 1) if fh is not None else b""
                if name.endswith(".jpg"):
                    if not data.startswith(_JPEG):
                        raise NavchanniaError(f"{name}: не JPEG")
                    zvit.kropiv += 1
                elif name == FILE:
                    try:
                        manifest = json.loads(data.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise NavchanniaError(f"{FILE}: не JSON ({exc})") from exc
                elif name.endswith(".txt") and "/" in name and not name.startswith("dochyt/"):
                    golos = name.split("/", 1)[0]
                    storinky[golos] = storinky.get(golos, 0) + 1
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise NavchanniaError(f"архів не дочитався: {exc}") from exc
    if not isinstance(manifest, dict):
        raise NavchanniaError(f"в архіві немає {FILE}")
    if manifest.get("schema") != SCHEMA:
        raise NavchanniaError(f"схема матеріалу {manifest.get('schema')!r}, а цей бік знає "
                              f"{SCHEMA}: онови Нишпорку (або сервер ще не оновлено)")
    if "opys.json" not in bachyv:
        raise NavchanniaError("в архіві немає opys.json")
    zvit.failiv = len(bachyv)
    zvit.golosy = sorted(storinky)
    zvit.storinok = max(storinky.values(), default=0)
    return zvit
