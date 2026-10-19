"""🗂 Каталог довідників із релізу: знайти найновіший `catalog-*`, звірити, поставити.

Довідники — це дані, а не версія програми: вони виходять окремим релізом
`catalog-РРРР-ММ-ДД` з одним архівом `nyshporka-catalog-<дата>.zip`. Доти їх
ставив лише інсталятор, а `nysh update` оновлював тільки код — і новий домен
пака не доходив до тих, хто оновлювався командою: церкви ~1772 і поселення
Wikidata (0.14.0) до 19.10.2026 не мав ніхто, крім автора.

🔴 **Без звірки не ставиться нічого.** Обірваний файл виглядав би як пак і
відповідав би нулями. GitHub віддає sha256 кожного файлу релізу (`digest`), і
архів приймається лише з тим самим хешем і розміром — та сама звірка, що в
`install/windows.ps1` і `install/unix.sh`.

🔴 **Сторінки релізів гортаються.** `catalog-*` виходить рідко, звичайні
релізи — щотижня, тож єдиний `catalog-*` рано чи пізно зсувається за першу
сотню. Читати лише першу сторінку означало б тихий кінець оновлень.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from nyshporka.catalog import store

API = "https://api.github.com/repos/SERGIUSH-UA/nyshporka/releases?per_page=100"
#: Скільки сторінок по 100 релізів гортати — запас на роки.
MAX_PAGES = 10
TIMEOUT = 20.0
TAG = re.compile(r"^catalog-\d{4}-\d{2}-\d{2}$")
ASSET = re.compile(r"^nyshporka-catalog-.*\.zip$")


class CatalogFetchError(RuntimeError):
    """Каталог не завантажився або не пройшов звірку — нічого не поставлено."""


@dataclass(frozen=True)
class CatalogRelease:
    tag: str = ""
    name: str = ""          # ім'я архіву — воно ж позначка `origin`
    url: str = ""
    size: int = 0
    sha256: str = ""
    why: str = ""           # чому не знаємо (мережа, немає релізу)

    @property
    def known(self) -> bool:
        return bool(self.tag and self.url and self.sha256)


def _get_json(url: str, timeout: float) -> Any:
    req = Request(url, headers={"Accept": "application/vnd.github+json",
                                "User-Agent": "nyshporka-catalog"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest(timeout: float = TIMEOUT, *, get_json: Any = None) -> CatalogRelease:
    """Найновіший опублікований `catalog-*` з архівом і його sha256.

    Мережа мовчить чи релізу немає — `why`, а не виняток: «не знаємо» не
    поламка, і `nysh update` мусить дійти до кінця.
    """
    from nyshporka.sources.http import offline

    if offline():
        return CatalogRelease(why="мережу вимкнено в цьому середовищі — релізи не питали")
    fetch = get_json or _get_json
    found: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            rows = fetch(f"{API}&page={page}", timeout)
        except Exception as exc:
            if page == 1:
                return CatalogRelease(why=f"до GitHub не дійшли ({type(exc).__name__})")
            break                      # уже прочитане чесніше за повну відмову
        if not rows:
            break
        found += [r for r in rows if isinstance(r, dict) and not r.get("draft")
                  and TAG.match(str(r.get("tag_name") or ""))]
    if not found:
        return CatalogRelease(why="на GitHub немає жодного релізу catalog-*")
    rel = max(found, key=lambda r: str(r["tag_name"]))
    for a in rel.get("assets") or []:
        name = str(a.get("name") or "")
        if not ASSET.match(name):
            continue
        digest = str(a.get("digest") or "")
        if not digest.startswith("sha256:"):
            return CatalogRelease(tag=rel["tag_name"], name=name,
                                  why="реліз не назвав sha256 архіву — без звірки не ставлю")
        return CatalogRelease(tag=str(rel["tag_name"]), name=name,
                              url=str(a.get("browser_download_url") or ""),
                              size=int(a.get("size") or 0), sha256=digest.split(":", 1)[1])
    return CatalogRelease(tag=str(rel["tag_name"]), why="у релізі немає архіву каталогу")


def is_current(rel: CatalogRelease) -> bool:
    """Чи стоять уже довідники саме з цього архіву (позначка `origin`)."""
    return bool(rel.name) and store.origin() == rel.name


def download(rel: CatalogRelease, dest: Path, *, timeout: float = 120.0,
             opener: Any = None) -> Path:
    """Скачати архів у `dest` і звірити sha256 та розмір. Невідповідність — геть."""
    if not rel.known:
        raise CatalogFetchError(rel.why or "реліз каталогу невідомий")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / rel.name
    part = out.with_name(out.name + ".part")
    h = hashlib.sha256()
    n = 0
    req = Request(rel.url, headers={"User-Agent": "nyshporka-catalog"})
    try:
        with (opener or urlopen)(req, timeout=timeout) as resp, part.open("wb") as fh:
            while block := resp.read(1 << 20):
                fh.write(block)
                h.update(block)
                n += len(block)
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise CatalogFetchError(f"архів не завантажився ({type(exc).__name__}: {exc})") from exc
    if (rel.size and n != rel.size) or h.hexdigest() != rel.sha256:
        part.unlink(missing_ok=True)
        raise CatalogFetchError(
            f"архів не пройшов звірку (розмір {n} проти {rel.size}, sha256 "
            f"{h.hexdigest()[:12]}… проти {rel.sha256[:12]}…) — нічого не поставлено")
    part.replace(out)
    return out


def install_from(src: Path, *, domain: str = "", origin: str = "") -> list[Path]:
    """Покласти паки з теки, `.zip` чи `.sqlite` у каталог. → поставлені файли.

    Кожен файл лягає через сусідній `.part`: обрив копіювання не лишає
    напівфабрикату під бойовим іменем.
    """
    dst = store.catalog_dir()
    dst.mkdir(parents=True, exist_ok=True)
    tmpdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if src.is_file() and src.suffix.lower() == ".zip":
            tmpdir = tempfile.TemporaryDirectory(prefix="nysh-catalog-")
            with zipfile.ZipFile(src) as zf:
                zf.extractall(tmpdir.name)
            src = Path(tmpdir.name)
        files = ([src] if src.is_file() else
                 sorted(p for p in src.rglob("*.sqlite") if p.is_file()))
        done: list[Path] = []
        for f in files:
            if domain and store._read_meta(f).get("domain") != domain:
                continue
            target = dst / f.name
            tmp = target.with_name(target.name + ".part")
            shutil.copy2(f, tmp)
            tmp.replace(target)
            done.append(target)
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()
    store.invalidate()
    if origin and not domain and done:
        store.set_origin(origin)
    return done


@dataclass(frozen=True)
class UpdateResult:
    state: str              # current · installed · would-install · unknown
    release: CatalogRelease
    installed: tuple[str, ...] = ()


def update(*, apply: bool = True, rel: CatalogRelease | None = None) -> UpdateResult:
    """Свіжий каталог, якщо на машині не він. `apply=False` — лише подивитись.

    🔴 Помилка звірки чи завантаження — `CatalogFetchError`: старі паки при цьому
    лишаються як були, бо нове кладеться лише після звірки всього архіву.
    """
    rel = rel or latest()
    if not rel.known:
        return UpdateResult("unknown", rel)
    if is_current(rel):
        return UpdateResult("current", rel)
    if not apply:
        return UpdateResult("would-install", rel)
    with tempfile.TemporaryDirectory(prefix="nysh-catalog-dl-") as tmp:
        zp = download(rel, Path(tmp))
        done = install_from(zp, origin=rel.name)
    return UpdateResult("installed", rel, tuple(p.name for p in done))
