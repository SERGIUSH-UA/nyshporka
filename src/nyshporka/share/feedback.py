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
  Інше не читається взагалі. Текст із диска — лише з простору (крім `data/`,
  де лежать дані родин) і з теки стану Нишпорки; `.json` — лише з теки стану;
  посилання (symlink) — ні. Перегляд показує початок і кінець кожного журналу:
  агент, якого вмовили «приклади цей файл», не відправить конфіг із ключами чи
  дані замовника непомітно для людини (рецензія безпеки 23.10.2026).
* **Ключ — лише на довірену адресу** (`catalog.may_send_key`), як і в
  `share push`: підміна `NYSHPORKA_TOLOKA` не виманює обліковий запис.
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
#: Тека профілю будь-якого користувача: `<диск>:\Users\Ім'я Прізвище`, коротке `PETRYK~1`,
#: `file:///<диск>:/Users/…`, UNC `\\ПК\c$\Users\…`, WSL `/mnt/c/Users/…`, `/home/…`,
#: macOS `/Users/…`. Сегмент імені — до наступного розділювача.
_PROFILE = re.compile(
    r"(?:\\\\[^\\/\s]+\\[a-z]\$|[a-z]:|/mnt/[a-z])?[\\/]+(?:users|home)[\\/]+[^\\/\r\n\"'<>]+",
    re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[\w\-.~+/=]{8,}")
_SECRET = re.compile(r"(?i)\b(token|api[_-]?key|secret|password|passwd|authorization)"
                     r"(\s*[:=]\s*)(?!bearer\b)(?!<)[\"']?[^\s\"',;]{6,}")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
#: Межа після шляху: кінець, розділювач, пробіл чи розділовий знак — не літера.
_EDGE = r"(?=$|[\\/\s\"',;:)\]])"


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
        out: dict[str, Any] = {"kind": self.kind, "name": self.name, "size": len(self.data),
                               "note": self.note}
        if self.kind == "text":
            # Людина бачить, ЩО в журналі, а не лише ім'я й розмір.
            lines = self.data.decode("utf-8", errors="replace").splitlines()
            out["excerpt"] = (lines if len(lines) <= 12
                              else [*lines[:6], f"… ще {len(lines) - 12} рядків …", *lines[-6:]])
        return out


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
        out = re.sub(re.escape(old) + _EDGE, new, out, flags=re.IGNORECASE)
    out = _PROFILE.sub("~", out)
    out = _EMAIL.sub("<e-mail>", out)
    out = _BEARER.sub(r"\1 <ключ>", out)
    out = _SECRET.sub(r"\1\2<вирізано>", out)
    out = _IPV4.sub("<ip>", out)
    names = []
    try:
        names.append(getpass.getuser())
    except Exception:
        pass
    try:
        names.append(platform.node())
    except Exception:
        pass
    for name, label in zip(names, ("<user>", "<host>"), strict=False):
        if len(name) >= 3:
            # Підкреслення — теж межа: «petryk_screenshot» несе ім'я так само.
            out = re.sub(rf"(?<![^\W_]){re.escape(name)}(?![^\W_])", label, out,
                         flags=re.IGNORECASE)
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
    stem = scrub(stem)
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


def _state_dir() -> Path:
    from platformdirs import user_state_dir

    return Path(user_state_dir("Nyshporka", appauthor=False)).resolve()


def _text_allowed(real: Path, ext: str) -> bool:
    """Текст із диска — з простору (крім `data/`) чи з теки стану; `.json` — лише стан."""
    state = _state_dir()
    if real.is_relative_to(state):
        return True
    if ext == ".json":
        return False
    try:
        from nyshporka.core.workspace import workspace

        root = Path(workspace().root).resolve()
    except Exception:
        return False
    return real.is_relative_to(root) and not real.is_relative_to(root / "data")


def from_path(path: str) -> Attachment:
    """Файл із диска — лише з білого списку, без посилань і з межею читання."""
    p = Path(path).expanduser()
    ext = p.suffix.lower()
    if ext not in IMAGE_EXT | TEXT_EXT:
        raise FeedbackError(f"{p.name}: прикласти можна лише картинку (PNG, JPEG, WebP) "
                            "або текстовий журнал (.txt, .log, .json)")
    if p.is_symlink():
        raise FeedbackError(f"{p.name}: посилання на файл не прикладаються — лише сам файл")
    if not p.is_file():
        raise FeedbackError(f"{p.name}: файла немає")
    real = p.resolve()
    if ext in TEXT_EXT and not _text_allowed(real, ext):
        raise FeedbackError(f"{p.name}: журнал прикладається лише з простору (крім data/) "
                            "чи з теки стану Нишпорки; інший текст скопіюйте у відгук сам")
    if ext in IMAGE_EXT:
        if p.stat().st_size > MAX_READ:
            raise FeedbackError(f"{p.name}: завеликий файл (до {MAX_READ // (1 << 20)} МБ)")
        return image(real.read_bytes(), p.name)
    with real.open("rb") as fh:
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
    from nyshporka.share.catalog import base_url, may_send_key

    home = base_url()
    return {"kind": kind, "text": body, "diag": diag(lang) if with_diag else {},
            "files": [a.as_json() for a in attachments], "logged_in": logged_in(),
            "to": home, "trusted": may_send_key(home)}


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
    # 🔴 Ключ — лише на довірену адресу, як у `share push` (`upload._tok_i_dim`).
    if not catalog.may_send_key(home):
        raise FeedbackError(f"адреса {home} не довірена — ключ Супряги туди не їде "
                            f"(свій сервер: {catalog.ENV_TRUST})")
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
