"""Спільне для обох боків Зводу: формат, відбитки, безпечне розпакування."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = "zvid"
#: Версія формату пакета. Клієнт старішої версії пакет відкидає, а не читає
#: наполовину: невідоме поле в маніфесті означає правило, якого він не знає.
VERSION = 1
SUFFIX = ".zvid"
ANSWER_SUFFIX = ".answer.zvid"
MANIFEST = "manifest.json"
META = "meta.json"
CONTEXT = "context.md"
#: Стан пісочниці помічника: маніфест + коли взято.
STATE = "zvid.json"
TASKS = "tasks"
PAGES = "pages"

_ALIAS_RE = re.compile(r"^zv-\d{2,3}$")
_ID_RE = re.compile(r"^zv\d{8}-[0-9a-f]{6}$")


class ZvidError(ValueError):
    """Пакет зіпсований, чужий, неповний — або відповідь не проходить ворота."""


def valid_alias(name: str) -> bool:
    return bool(_ALIAS_RE.match(name))


def valid_id(pack_id: str) -> bool:
    return bool(_ID_RE.match(pack_id))


def frames_sha(cut_meta: dict[str, Any], pages: list[str]) -> str:
    """Відбиток рамок рядків набору.

    🔴 Мітка прив'язана до `сторінка + індекс`, а індекс дає нарізка. Якщо
    власник перерізав набір, поки пакет був у помічника, рядок N відповіді ліг
    би під кроп M — тихо й без жодної помилки. Тому відповідь приймається лише
    на ті самі рамки, з яких пакет пакувався.
    """
    pm = cut_meta.get("pages") or {}
    payload = {pg: {"boxes": (pm.get(pg) or {}).get("boxes") or [],
                    "n": (pm.get(pg) or {}).get("n_lines")} for pg in sorted(pages)}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def member_path(name: str) -> PurePosixPath:
    """Шлях члена архіву — лише відносний і без виходу вгору.

    Пакет приходить від іншої людини: `../../.bashrc` чи `C:/…` усередині zip
    без цієї перевірки записалися б поза пісочницею (zip slip).
    """
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]) or not p.parts:
        raise ZvidError(f"у пакеті неприпустимий шлях: {name!r}")
    return p


def read_json_member(zf: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        got = json.loads(zf.read(name).decode("utf-8"))
    except KeyError:
        raise ZvidError(f"у пакеті немає {name}") from None
    except (UnicodeDecodeError, ValueError) as exc:
        raise ZvidError(f"{name} не читається: {exc}") from None
    if not isinstance(got, dict):
        raise ZvidError(f"{name} — не об'єкт")
    return got


def open_zip(path: Path) -> zipfile.ZipFile:
    if not path.is_file():
        raise ZvidError(f"файла немає: {path}")
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ZvidError(f"{path.name} — не пакет Зводу (не zip)") from None
    for info in zf.infolist():
        member_path(info.filename)
    return zf


def check_manifest(m: dict[str, Any]) -> None:
    if m.get("format") != FORMAT:
        raise ZvidError("це не пакет Зводу (format ≠ zvid)")
    if int(m.get("version") or 0) > VERSION:
        raise ZvidError(f"пакет формату v{m.get('version')}, а цей клієнт знає до v{VERSION} — "
                        "онови Нишпорку: nysh update")
    if not valid_id(str(m.get("id") or "")):
        raise ZvidError(f"неприпустимий id пакета: {m.get('id')!r}")
    for s in m.get("sets") or []:
        if not valid_alias(str(s.get("name") or "")):
            raise ZvidError(f"неприпустиме ім'я набору в пакеті: {s.get('name')!r}")


def version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in re.split(r"[.+-]", v):
        if not part.isdigit():
            break
        out.append(int(part))
    return tuple(out)


def base_dir() -> Path:
    """Де живуть пісочниці помічника — поза його дослідженням.

    Розпакований пакет — це чужі набори; покладені в простір людини, вони
    змішались би з її справами в реєстрі й у пошуку.
    """
    from nyshporka.core.appdirs import data_dir

    return data_dir() / "zvid"
