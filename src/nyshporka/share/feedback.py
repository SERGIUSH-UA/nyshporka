"""📮 Відгук про Нишпорку на портал: текст, знімки екрана, журнали.

Лише явна дія людини (кнопка в консолі, `nysh feedback`, агент із `confirm`) і
лише з ключем Супряги. Портал приймає три кроки (`/v1/feedback`, кожне вкладення
окремим `PUT` до 1 МБ, `complete`) — див. `app/routers/vidhuk.py` порталу.

🔴 Що йде з машини — людина бачить ДО відправки (`preview`):

* **Текст і журнали очищено** (`scrub`): домашня тека, ім'я користувача й корінь
  простору замінено мітками, підписи посилань сховища вирізано.
* **Знімки — перекодовано тут же** у WebP без метаданих (Pillow), ≤ 1600 px: так
  вони влазять у 1 МБ, і EXIF з координатами не їде. Портал перекодовує ще раз.
* **Файли — лише з білого списку** (PNG/JPEG/WebP і .txt/.log/.json), до п'яти.
  Інше не читається взагалі: агент, якого вмовили «приклади цей файл», не
  відправить канон чи ключі під виглядом журналу з чужим розширенням.
"""
from __future__ import annotations

import base64
import getpass
import io
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KINDS = ("vada", "ideia", "pytannia")
IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp"})
TEXT_EXT = frozenset({".txt", ".log", ".json"})
MAX_FILES = 5
MAX_TEXT = 5000
#: Стеля одного вкладення на порталі — 1 МБ; знімок стискаємо до 900 КБ.
MAX_IMAGE = 900 * 1024
#: Журнал — до половини мегабайта; довший обрізається з ПОЧАТКУ (хвіст важливіший).
MAX_LOG = 512 * 1024
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000
#: Скільки взагалі читати з диска заради одного файла.
MAX_READ = 25 * 1024 * 1024

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SIGNED = re.compile(r"(https?://[^\s?\"']+)\?[^\s\"']*(?:X-Amz-|Signature=|sig=)[^\s\"']*",
                     re.IGNORECASE)


class FeedbackError(ValueError):
    """Що не так — людською мовою."""


@dataclass
class Attachment:
    kind: str          # image | text
    name: str
    data: bytes
    note: str = ""

    @property
    def content_type(self) -> str:
        return "image/webp" if self.kind == "image" else "text/plain; charset=utf-8"

    def as_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "size": len(self.data), "note": self.note}


# ── очищення ─────────────────────────────────────────────────────────────────
def _variants(p: Path) -> list[str]:
    s = str(p)
    out = {s, p.as_posix(), s.replace("\\", "\\\\")}
    return sorted((v for v in out if len(v) > 3), key=len, reverse=True)


def scrub(text: str) -> str:
    """Прибрати з тексту те, що вказує на людину чи її машину.

    Корінь простору → `<простір>`, домашня тека → `~`, ім'я користувача →
    `<user>`, підписи посилань сховища → вирізано. Порядок важливий: простір
    часто лежить у домашній теці, тож його замінюємо першим.
    """
    out = _SIGNED.sub(r"\1?<підпис вирізано>", str(text or ""))
    try:
        from nyshporka.core.workspace import workspace

        root: Path | None = workspace().root
    except Exception:
        root = None
    pairs: list[tuple[str, str]] = []
    if root is not None:
        pairs += [(v, "<простір>") for v in _variants(Path(root))]
    pairs += [(v, "~") for v in _variants(Path.home())]
    for old, new in pairs:
        # Заміна — без груп і зворотних скісних (`~`, `<простір>`), тож рядком.
        out = re.sub(re.escape(old), new, out, flags=re.IGNORECASE)
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    if len(user) >= 3:
        out = re.sub(rf"(?<![\w]){re.escape(user)}(?![\w])", "<user>", out, flags=re.IGNORECASE)
    return out


def clean_text(text: str, limit: int = MAX_TEXT) -> str:
    s = _CONTROL.sub("", str(text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    s = scrub(s)
    if len(s) > limit:
        raise FeedbackError(f"задовгий текст: до {limit} знаків (зараз {len(s)})")
    return s


# ── діагностика ──────────────────────────────────────────────────────────────
def diag(lang: str = "") -> dict[str, str]:
    """Версія, система, спосіб установки, набори — те, що людина побачить у перегляді."""
    from nyshporka import __version__
    from nyshporka.setup import update as U

    if U.tool_env():
        how = "uv tool"
    elif "site-packages" in Path(__file__).as_posix():
        how = "pip"
    else:
        how = "розробка"
    out = {
        "version": __version__,
        "os": f"{platform.system()} {platform.release()}".strip(),
        "python": platform.python_version(),
        "install": how,
        "preset": U.preset_now(U.install_info().get("preset", "")),
        "htr": "так" if U.has_htr() else "ні",
        "fast": "так" if U.has_fast() else "ні",
    }
    if lang:
        out["lang"] = lang[:8]
    return out


# ── вкладення ────────────────────────────────────────────────────────────────
def _safe_name(name: str, ext: str) -> str:
    stem = re.split(r"[\\/]", str(name or ""))[-1].rsplit(".", 1)[0]
    stem = re.sub(r"[^\w.\-]", "_", stem).strip("._") or "fail"
    return f"{stem[:60]}{ext}"


def image(raw: bytes, name: str = "znimok.png") -> Attachment:
    """Знімок → WebP без метаданих, ≤ 1600 px і ≤ 900 КБ. Формат — за вмістом."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not raw:
        raise FeedbackError(f"{name}: порожній файл")
    if len(raw) > MAX_READ:
        raise FeedbackError(f"{name}: завеликий файл (до {MAX_READ // (1 << 20)} МБ)")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise FeedbackError(f"{name}: підходять лише PNG, JPEG або WebP")
            w, h = im.size
            if w * h > MAX_PIXELS or w < 1 or h < 1:
                raise FeedbackError(f"{name}: завелика картинка за пікселями")
            if im.format == "JPEG":
                im.draft(None, (MAX_SIDE, MAX_SIDE))
            im.load()
            pic = ImageOps.exif_transpose(im)
            pic = pic.convert("RGBA" if pic.mode in ("RGBA", "LA", "P") else "RGB")
    except FeedbackError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError,
            SyntaxError) as exc:
        raise FeedbackError(f"{name}: не схоже на картинку або пошкоджено") from exc
    for side, quality in ((MAX_SIDE, 82), (MAX_SIDE, 65), (1200, 60), (900, 55)):
        p = pic.copy()
        p.thumbnail((side, side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        p.save(buf, "WEBP", quality=quality, method=5)
        if buf.tell() <= MAX_IMAGE:
            return Attachment("image", _safe_name(name, ".webp"), buf.getvalue(),
                              note=f"{p.size[0]}×{p.size[1]}")
    raise FeedbackError(f"{name}: не вдалося стиснути до {MAX_IMAGE // 1024} КБ")


def log(raw: bytes | str, name: str = "zhurnal.txt") -> Attachment:
    """Журнал: UTF-8, без керівних символів, очищений; довгий — лише хвіст."""
    s = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
    s = _CONTROL.sub("", s.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n"))
    s = scrub(s)
    note = ""
    b = s.encode("utf-8")
    if len(b) > MAX_LOG:
        b = b[-MAX_LOG + 64:]
        b = b[b.find(b"\n") + 1:] if b"\n" in b[:4096] else b
        s = "… (початок обрізано)\n" + b.decode("utf-8", errors="ignore")
        note = "лише кінець"
    if not s.strip():
        raise FeedbackError(f"{name}: порожній журнал")
    ext = Path(str(name)).suffix.lower()
    return Attachment("text", _safe_name(name, ext if ext in TEXT_EXT else ".txt"),
                      s.encode("utf-8"), note=note)


def from_path(path: str) -> Attachment:
    """Файл із диска — лише з білого списку розширень і з межею читання."""
    p = Path(path).expanduser()
    ext = p.suffix.lower()
    if ext not in IMAGE_EXT | TEXT_EXT:
        raise FeedbackError(f"{p.name}: прикласти можна лише картинку (PNG, JPEG, WebP) "
                            "або текстовий журнал (.txt, .log, .json)")
    if not p.is_file():
        raise FeedbackError(f"{p.name}: файла немає")
    if ext in IMAGE_EXT:
        if p.stat().st_size > MAX_READ:
            raise FeedbackError(f"{p.name}: завеликий файл (до {MAX_READ // (1 << 20)} МБ)")
        return image(p.read_bytes(), p.name)
    with p.open("rb") as fh:
        size = p.stat().st_size
        if size > 4 * MAX_LOG:
            fh.seek(size - 4 * MAX_LOG)
        return log(fh.read(), p.name)


def prepare(paths: list[str] | None = None, images: list[dict[str, Any]] | None = None,
            logs: list[dict[str, Any]] | None = None) -> list[Attachment]:
    """Усі вкладення: шляхи (агент, CLI) і вміст із браузера (консоль)."""
    out: list[Attachment] = []
    total = len(paths or []) + len(images or []) + len(logs or [])
    if total > MAX_FILES:
        raise FeedbackError(f"вкладень до {MAX_FILES}, а не {total}")
    for path in paths or []:
        out.append(from_path(path))
    for x in images or []:
        data = str((x or {}).get("data") or "")
        data = data.split(",", 1)[1] if data.startswith("data:") else data
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as exc:
            raise FeedbackError("знімок пошкоджено при передачі") from exc
        out.append(image(raw, str((x or {}).get("name") or "znimok.png")))
    for x in logs or []:
        out.append(log(str((x or {}).get("text") or ""), str((x or {}).get("name") or "zhurnal.txt")))
    return out


# ── перегляд і відправка ─────────────────────────────────────────────────────
def logged_in() -> bool:
    from nyshporka.share.upload import token

    return bool(token())


def preview(text: str, kind: str, attachments: list[Attachment],
            with_diag: bool = True, lang: str = "") -> dict[str, Any]:
    """Рівно те, що піде на портал, — показати людині перед відправкою."""
    if kind not in KINDS:
        raise FeedbackError(f"вид відгуку: {', '.join(KINDS)}")
    body = clean_text(text)
    if not body:
        raise FeedbackError("напишіть, що сталося чи що пропонуєте")
    from nyshporka.share.catalog import base_url

    return {"kind": kind, "text": body, "diag": diag(lang) if with_diag else {},
            "files": [a.as_json() for a in attachments], "logged_in": logged_in(),
            "to": base_url()}


def _put(url: str, data: bytes, content_type: str, auth: str) -> None:
    from nyshporka.share.upload import _syrovyi_put
    from nyshporka.sources.http import app_ua, proxy_url

    headers = {"Authorization": f"Bearer {auth}", "User-Agent": app_ua(),
               "Content-Type": content_type}
    try:
        resp = _syrovyi_put(url, content=data, headers=headers, timeout=60.0, proxy=proxy_url())
    except Exception as exc:  # обрив мережі
        raise FeedbackError(f"вкладення не відправилось: {exc}") from exc
    if resp.status_code >= 400:
        raise FeedbackError(f"портал не прийняв вкладення: {resp.status_code} "
                            f"{resp.text[:200]}")


def send(text: str, kind: str, attachments: list[Attachment], with_diag: bool = True,
         lang: str = "") -> dict[str, Any]:
    """Відправити. Без входу в Супрягу — відмова з командою входу."""
    import json

    from nyshporka.share import catalog
    from nyshporka.share.upload import token
    from nyshporka.sources.http import HttpError

    auth = token()
    if not auth:
        raise FeedbackError("потрібен вхід у Супрягу: nysh share login")
    p = preview(text, kind, attachments, with_diag, lang)
    home = catalog.base_url()
    files = [{"kind": a.kind, "name": a.name, "size": len(a.data)} for a in attachments]
    url = f"{home}/feedback"
    try:
        resp = catalog._fetcher(url, auth=auth, accept_json=True).post(url, json_body={
            "kind": kind, "text": p["text"], "diag": p["diag"], "files": files, "lang": lang})
        got = json.loads(resp.text if hasattr(resp, "text") else str(resp))
    except HttpError as exc:
        raise FeedbackError(f"портал не прийняв відгук: {catalog.reason(exc)}") from exc
    except catalog.PoolError as exc:
        raise FeedbackError(str(exc)) from exc
    vid = int(got["id"])
    for n, a in enumerate(attachments, 1):
        _put(f"{home}/feedback/{vid}/files/{n}", a.data, a.content_type, auth)
    done_url = f"{home}/feedback/{vid}/complete"
    try:
        catalog._fetcher(done_url, auth=auth, accept_json=True).post(done_url, json_body={})
    except HttpError as exc:
        raise FeedbackError(f"відгук №{vid} не завершено: {catalog.reason(exc)}") from exc
    from nyshporka.share.login import site_url

    return {"id": vid, "files": len(attachments), "url": f"{site_url()}/kabinet/moi-vidhuky"}
