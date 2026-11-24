"""📦 Пакет опису `.nyshopys`: tar.gz із трьох файлів.

| файл | що |
|---|---|
| `manifest.json` | шифра опису, джерела, рушії, якість, нормалізація, ліцензія |
| `pages.jsonl`   | текст кожної сторінки джерела голосами |
| `rows.jsonl`    | справи з прив'язкою до сторінки (координати в частках) |

Робоча тека, з якої пакується, — ті самі три файли нестиснутими. Ключі рядків
`rk` рахує пакувальник: з робочої теки їх не беруть. Власні назви для словника
фонду (`name_records`) не везуться: вони виводяться з рядків на будь-якому
кінці, і похідному полю в пакеті нема чого вірити. Правила підстановки —
окремий етап зі своєю схемою, у пакет схеми 1 вони не входять.

Пакет відтворюваний: ті самі дані дають ті самі байти (порядок членів сталий,
`mtime` нуль), тож sha256 пакета — його ідентичність.

🔴 Читання розраховане на чужі байти (сервер): лише відомі імена, лише
звичайні файли, стеля на кожен файл і на весь пакет, без дублів.
"""
from __future__ import annotations

import gzip
import io
import json
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.opysy import gates as G
from nyshporka.opysy import names as N
from nyshporka.opysy.schema import SCHEMA, Manifest, Page, Row, row_key

SUFFIX = ".nyshopys"
MANIFEST = "manifest.json"
PAGES = "pages.jsonl"
ROWS = "rows.jsonl"
MEMBERS = (MANIFEST, PAGES, ROWS)

#: Стелі під опис, а не під справу: найбільший опис, який ми читали, — тисяча сторінок
#: тексту на кілька МБ. Сервер тримає пакет у пам'яті цілим.
MAX_MANIFEST_BYTES = 1 << 20
MAX_MEMBER_BYTES = 64 << 20
MAX_TOTAL_BYTES = 128 << 20


class BundleError(Exception):
    """Пакет битий, чужий чи завеликий — з причиною для людини."""


@dataclass
class Contents:
    manifest: dict[str, Any]
    pages: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


# ── Робоча тека ───────────────────────────────────────────────────────────


def _jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BundleError(f"{path.name}, рядок {i}: не JSON ({exc.msg})") from exc
            if not isinstance(item, dict):
                raise BundleError(f"{path.name}, рядок {i}: очікувався об'єкт")
            out.append(item)
    return out


def read_workdir(work: Path) -> Contents:
    """Робоча тека опису → сирий вміст (без перевірок схеми — це робота воріт)."""
    mpath = work / MANIFEST
    if not mpath.exists():
        raise BundleError(f"у {work} немає {MANIFEST}")
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BundleError(f"{MANIFEST}: не JSON ({exc.msg})") from exc
    if not isinstance(manifest, dict):
        raise BundleError(f"{MANIFEST}: очікувався об'єкт")
    return Contents(manifest=manifest, pages=_jsonl(work / PAGES), rows=_jsonl(work / ROWS))


# ── Пакування ─────────────────────────────────────────────────────────────


@dataclass
class PackReport:
    verdict: G.Verdict
    summary: dict[str, Any]
    file: Path | None = None
    sha256: str = ""
    bytes: int = 0


def name_records(rows: list[Row]) -> list[dict[str, Any]]:
    """Власні назви нормалізованих рядків: слово, чи позначене, фолд-основа.

    Сирі рядки без нормалізації сюди поки не йдуть: з великої там пише рушій
    навмання. Як збирати назви з них — вирішує етап словника фонду.
    """
    common = N.common_stems()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not r.title_norm.strip():
            continue
        marked = {w for m in N.marks(r.title_norm) for w in N.WORD_RX.findall(m)}
        seen: set[str] = set()
        for w in N.proper_names(r.title_norm, common):
            if w in seen:
                continue
            seen.add(w)
            out.append({"rk": r.rk, "name": w, "marked": w in marked, "stem": N.stem(w)})
    return out


def prepare(c: Contents) -> tuple[Manifest | None, list[Page], list[Row], G.Verdict]:
    """Розбір + ключі рядків + ворота. Ключ `rk` з робочої теки не береться."""
    for raw in c.rows:
        raw.pop("rk", None)
    m, pages, rows, v = G.parse(c.manifest, c.pages, c.rows)
    if m is None or not v.passed:
        return m, pages, rows, v
    for row in rows:
        row.rk = row_key(m.sources, row)
    v.extend(G.check(m, pages, rows))
    return m, pages, rows, v


def pack(work: Path, dest: Path, *, tool: str = "") -> PackReport:
    """Робоча тека → `.nyshopys`, лише якщо ворота пропустили."""
    c = read_workdir(work)
    m, pages, rows, v = prepare(c)
    summary = G.summary(m, pages, rows) if m is not None else {}
    rep = PackReport(verdict=v, summary=summary)
    if m is None or not v.passed:
        return rep
    if tool and not m.tool:
        m.tool = tool
    blob = encode(m, pages, rows)
    dest = dest if dest.suffix == SUFFIX else dest.with_suffix(SUFFIX)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(dest)
    import hashlib

    rep.file = dest
    rep.sha256 = hashlib.sha256(blob).hexdigest()
    rep.bytes = len(blob)
    return rep


def _dumps_jsonl(items: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n"
                   for x in items).encode("utf-8")


def manifest_json(m: Manifest) -> dict[str, Any]:
    """Маніфест для пакета. 🔴 `normalization_exchange` — лише коли увімкнено: сервер зі старим
    піном пакета (схема `extra="forbid"`) інакше відкидав би КОЖЕН пакет нового клієнта, а
    маніфести без обміну лишаються байт у байт такими, як до поля (25.11.2026)."""
    d = m.model_dump(by_alias=True, mode="json")
    if not d.get("normalization_exchange"):
        d.pop("normalization_exchange", None)
    return d


def encode(m: Manifest, pages: list[Page], rows: list[Row]) -> bytes:
    """Відтворювані байти пакета: сталий порядок, `mtime` нуль, gzip без часу."""
    members = {
        MANIFEST: json.dumps(manifest_json(m), ensure_ascii=False,
                             sort_keys=True, indent=1).encode("utf-8"),
        PAGES: _dumps_jsonl([p.model_dump(mode="json") for p in pages]),
        ROWS: _dumps_jsonl([r.model_dump(mode="json") for r in rows]),
    }
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in MEMBERS:
            data = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


# ── Читання (чужі байти) ──────────────────────────────────────────────────


def decode(blob: bytes) -> Contents:
    """Байти пакета → вміст. Будь-яка вада — `BundleError` з причиною.

    🔴 Номер схеми читається РАНІШЕ, ніж судяться імена файлів: пакет новішої
    схеми може нести файл, якого ця сторона не знає, і людина має почути
    «онови Нишпорку», а не «чужий файл».
    """
    try:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")  # noqa: SIM115 — закривається нижче
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise BundleError(f"не пакет опису (не tar.gz або обрізаний): {exc}") from exc
    got: dict[str, bytes] = {}
    foreign: list[str] = []
    total = 0
    with tar:
        try:
            for info in tar:
                if info.name not in MEMBERS:
                    foreign.append(info.name[:80])
                    total += max(info.size, 0)
                    if total > MAX_TOTAL_BYTES or len(foreign) > 16:
                        raise BundleError("пакет більший за стелю розпакування")
                    continue
                if not info.isfile():
                    raise BundleError(f"{info.name}: не звичайний файл")
                if info.name in got:
                    raise BundleError(f"{info.name} у пакеті двічі")
                cap = MAX_MANIFEST_BYTES if info.name == MANIFEST else MAX_MEMBER_BYTES
                if info.size > cap:
                    raise BundleError(f"{info.name}: {info.size} байт — більше за стелю {cap}")
                total += info.size
                if total > MAX_TOTAL_BYTES:
                    raise BundleError("пакет більший за стелю розпакування")
                fh = tar.extractfile(info)
                got[info.name] = fh.read(info.size + 1) if fh is not None else b""
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise BundleError(f"пакет не дочитався: {exc}") from exc
    if MANIFEST not in got:
        raise BundleError(f"у пакеті немає {MANIFEST}")
    try:
        manifest = json.loads(got[MANIFEST].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"{MANIFEST}: не JSON у UTF-8 ({exc})") from exc
    if not isinstance(manifest, dict):
        raise BundleError(f"{MANIFEST}: очікувався об'єкт")
    got_schema = manifest.get("schema")
    if isinstance(got_schema, int) and got_schema > SCHEMA:
        raise BundleError(f"схема пакета {got_schema} новіша, ніж знає цей бік ({SCHEMA}): "
                          "онови Нишпорку (або сервер ще не оновлено)")
    if foreign:
        raise BundleError(f"чужий файл у пакеті: {', '.join(foreign[:3])}")
    missing = [n for n in MEMBERS if n not in got]
    if missing:
        raise BundleError(f"у пакеті бракує: {', '.join(missing)}")
    return Contents(manifest=manifest, pages=_lines(got[PAGES], PAGES),
                    rows=_lines(got[ROWS], ROWS))


def _lines(blob: bytes, name: str) -> list[dict[str, Any]]:
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError(f"{name}: не UTF-8") from exc
    out: list[dict[str, Any]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleError(f"{name}, рядок {i}: не JSON ({exc.msg})") from exc
        if not isinstance(item, dict):
            raise BundleError(f"{name}, рядок {i}: очікувався об'єкт")
        out.append(item)
    return out


def verify(blob: bytes) -> tuple[Contents, G.Verdict]:
    """Прийом чужого пакета: розібрати й прогнати ворота заново.

    🔴 Ключі рядків рахуються заново й звіряються з тими, що приніс пакет
    (`gates._gate_binding`, правило `row_bad_key`): чужому ключу не вірять.
    """
    c = decode(blob)
    m, pages, rows, v = G.parse(c.manifest, c.pages, c.rows)
    if m is not None and v.passed:
        v.extend(G.check(m, pages, rows))
        missing_rk = sum(1 for r in rows if not r.rk)
        if missing_rk:
            v.refuse(f"{missing_rk} рядків без ключа rk (пакет зібрано не пакувальником)",
                     rule="row_no_key", field="rows.rk")
    return c, v
