"""📎 Докази канону: кроп у постійний стор, хеш і маніфест.

🔴 Доказ кладеться в стор ДО того, як факт іде в канон. Цитата, що посилається
на тимчасовий файл (кроп у теці прогону, кеш, чернетка), провисає, щойно кеш
почистять, — і виглядає при цьому так само, як жива.

🔴 Доказ — вирізка рядка сірим JPEG, а не аркуш. Аркуш важить мегабайти, у
git-сторі їх сотні, а читач однаково шукає на ньому один рядок. Тому стеля
2 МБ, і понад неї файл не приймається: зменшення роздільності без питання
зробило б нечитабельним саме те, що мало доводити.

Стор: `data/source/citations/<походження>/`, маніфест —
`data/source/citations/MANIFEST_citations.json` (запис: `secured_to`, `sha256`,
`cited_by`, `size`). `cited_by` руками не ведуть: його дописує індекс канону
з посилань у картках.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.canon.check import evidence_refs, manifest_path
from nyshporka.utils.atomic import atomic_write_bytes, read_json, write_json

#: Стеля одного доказу. Та сама, що в pre-commit хуку канону.
MAX_BYTES = 2 * 1024 * 1024
JPEG_QUALITY = 85
_PROVENANCE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_NAME = re.compile(r"[^\w.-]+", re.UNICODE)


class EvidenceError(ValueError):
    """Доказ не прийнято — з поясненням, що зробити."""


@dataclass
class Secured:
    path: str
    sha256: str
    size: int
    existed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size,
                "existed": self.existed}


def store_dir(root: Path) -> Path:
    return root / "data" / "source" / "citations"


def _to_grey_jpeg(src: Path) -> bytes:
    from PIL import Image, ImageOps

    try:
        with Image.open(src) as opened:
            im = ImageOps.exif_transpose(opened)
            buf = io.BytesIO()
            im.convert("L").save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except OSError as exc:
        raise EvidenceError(f"{src.name}: це не зображення, яке можна відкрити ({exc})") from exc
    return buf.getvalue()


def add(root: Path, src: Path, provenance: str, *, name: str = "",
        overwrite: bool = False) -> Secured:
    """Покласти зображення в стор доказів сірим JPEG і записати в маніфест.

    Той самий вміст під тим самим іменем — не помилка: повертається наявний
    запис (`existed=True`), тож повторний виклик безпечний.
    """
    if not _PROVENANCE.match(provenance):
        raise EvidenceError(
            f"походження «{provenance}»: латиниця в нижньому регістрі, цифри, «-» і «_» "
            f"(назва архіву чи зібрання, напр. «dahmo», «oral», «press»)")
    if not src.is_file():
        raise EvidenceError(f"файлу немає: {src}")
    stem = _NAME.sub("_", (name or src.stem)).strip("_.")
    if not stem:
        raise EvidenceError("ім'я доказу порожнє — задайте --name")
    blob = _to_grey_jpeg(src)
    if len(blob) > MAX_BYTES:
        raise EvidenceError(
            f"{src.name}: {len(blob) / 1048576:.1f} МБ навіть сірим JPEG — це аркуш, а не "
            f"рядок. Виріжте рядок (`nysh text crop`) і покладіть вирізку")
    sha = hashlib.sha256(blob).hexdigest()

    dest = store_dir(root) / provenance / f"{stem}.jpg"
    rel = dest.relative_to(root).as_posix()
    existed = False
    if dest.exists():
        have = hashlib.sha256(dest.read_bytes()).hexdigest()
        if have == sha:
            existed = True
        elif not overwrite:
            raise EvidenceError(
                f"{rel} уже є з іншим вмістом. Інше ім'я (--name) або --overwrite, "
                f"якщо це свідома заміна того самого доказу")
    if not existed:
        atomic_write_bytes(dest, blob)

    man = manifest_path(root)
    records: dict[str, Any] = read_json(man, default={}) or {}
    key = next((k for k, v in records.items() if (v.get("secured_to") or k) == rel), rel)
    rec = records.get(key, {})
    rec.update({"secured_to": rel, "sha256": sha, "size": len(blob)})
    rec.setdefault("cited_by", [])
    records[key] = rec
    write_json(man, records, indent=1)
    return Secured(path=rel, sha256=sha, size=len(blob), existed=existed)


def refresh_cited_by(root: Path, files: dict[str, Path]) -> dict[str, Any]:
    """Дописати в маніфест, хто з карток посилається на який доказ.

    🔴 Лише дописує, не стирає. `cited_by` читає галерея сайту, і посилання, яке
    картка дає в незвичній формі (перелік, скорочений шлях), не варте того,
    щоб мовчки прибрати доказ із публікації. Записи, на які вже жодна картка
    не посилається, повертаються окремим переліком — їх видно, і рішення за
    людиною.
    """
    man = manifest_path(root)
    if not man.is_file():
        return {"records": 0, "added": 0, "unreferenced": []}
    records: dict[str, Any] = read_json(man, default={}) or {}
    # Руками `cited_by` писали трьома способами («I…», «I….md», повний шлях до
    # картки). Галерея сайту бере з нього ID сторінки, тож форма одна: ім'я
    # файлу картки з `.md`.
    normalised = 0
    for rec in records.values():
        before = list(rec.get("cited_by") or [])
        after = list(dict.fromkeys(_owner_name(x) for x in before if isinstance(x, str)))
        if after != before:
            rec["cited_by"] = after
            normalised += 1
    by_target = {(v.get("secured_to") or k): k for k, v in records.items()}
    referenced: set[str] = set()
    added = 0
    for _eid, path in sorted(files.items()):
        owner = path.name
        for ref in evidence_refs(path.read_text(encoding="utf-8")):
            key = by_target.get(ref) or (ref if ref in records else None)
            if key is None:
                continue
            referenced.add(key)
            cited = records[key].setdefault("cited_by", [])
            if owner not in cited:
                cited.append(owner)
                added += 1
    if added or normalised:
        write_json(man, records, indent=1)
    unreferenced = sorted(k for k in records if k not in referenced)
    return {"records": len(records), "added": added, "normalised": normalised,
            "unreferenced": unreferenced}


def _owner_name(ref: str) -> str:
    name = ref.replace("\\", "/").rsplit("/", 1)[-1]
    return name if name.endswith(".md") else f"{name}.md"
