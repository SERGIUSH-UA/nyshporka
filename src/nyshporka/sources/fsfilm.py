"""🎞 Дзеркало плівок FamilySearch — і поаркушевий покажчик до них.

Фронтенд (`fsfiles.ru`) — статичний переглядач над ЧУЖИМИ файловими сховищами:
сам він нічого не віддає, а тягне з GitHub стиснуте дерево тек регіону й будує
прямі URL на сховище. Кадри там — готові цілі JPEG, без авторизації, cookies й
Referer, тобто на відміну від самого FamilySearch не треба ні сесії, ні
розширення, ні склейки тайлів.

🔑 Але головна цінність не в кадрах, а в `folder_meta`: дерево несе ПОАРКУШЕВИЙ
ПОКАЖЧИК плівки — «Л. 6-51 — Киркаешты», «Л. 52-74 — Калфа». Він відповідає
«де метрики мого села» БЕЗ ЖОДНОГО ЗАВАНТАЖЕННЯ, і саме тому `search` тут
шукає по покажчику, а не по назвах тек.

Три пастки, кожна коштувала прогону:

1. 🔴 **`imageBaseUrl` у дереві веде в нікуди.** Поле є, виглядає авторитетно —
   і дає 404 (перевірено запитом: воно лишає `/media/mihailo` у шляху). Робочу
   адресу треба ЛІЧИТИ: `rootId` без префікса `/media/mihailo`, приклеєний до
   `/storage`. Довіритись полю означало б порожню теку без пояснення.
2. 🔴 **Форма `folder_meta` різна по регіонах.** У Молдові це список словників
   (покажчик), у Пскові — голий рядок-підпис теки, тобто покажчика немає
   взагалі. Різниця тиха: `.get()` по рядку їде по символах. Тому все йде через
   `meta_entries`, а лічильники рахують ОКРЕМО записи з «Л.» — інакше
   «з покажчиком 1645» брехало б там, де шукати нічим.
3. 🔴 **`delo` й `soderzhanie` заповнені лише в ПЕРШОМУ записі блоку** — далі
   порожньо означає «та сама справа». Без протягування 90% записів лишились би
   без шифру.

`ref`: `<регіон>` або `<регіон>/<шлях у дереві>` (остання складова — плівка).
"""
from __future__ import annotations

import gzip
import io
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Manifest,
    Node,
    ProgressFn,
    Sheet,
    SourceError,
)
from nyshporka.sources.http import Fetcher, HttpError

SPA_URL = "https://fsfiles.ru/"
STORAGE_BASE = "https://geno-dbase.ru/storage"
MEDIA_PREFIX = "/media/mihailo"
SOURCES_TTL = 24 * 3600

#: «Л. 132-223», «Л. 457-…», «Л. 137».
RANGE_RE = re.compile(r"Л\.\s*(\d+)\s*(?:[-–]\s*(\d+|…|\.\.\.)?)?")


# ── дерево регіону ───────────────────────────────────────────────────────────

def norm_path(path: str) -> str:
    """Ключі дерева — відносні шляхи зі скісною в кінці; корінь = ''."""
    path = path.strip().strip("/")
    return f"{path}/" if path else ""


def parse_sources(spa_html: str) -> list[dict[str, str]]:
    """Реєстр регіонів із живої сторінки переглядача.

    Парситься сторінка, а не зашитий список: регіони там додають, і знімок у
    коді протухав би МОВЧКИ — новий архів просто не з'являвся б у застосунку,
    без жодної ознаки, що щось не так.
    """
    consts = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']*)'\s*;", spa_html))
    block = re.search(r"const GENODB_SOURCES\s*=\s*\[(.*?)\n\s*\];", spa_html, re.S)
    if not block:
        raise SourceError(
            "на сторінці дзеркала немає переліку регіонів — розмітка змінилась")
    out: list[dict[str, str]] = []
    for entry in re.findall(r"\{([^{}]*)\}", block.group(1)):
        def field(key: str, _e: str = entry) -> str | None:
            m = re.search(rf"\b{key}\s*:\s*'([^']*)'", _e)
            if m:
                return m.group(1)
            m = re.search(rf"\b{key}\s*:\s*([A-Z_][A-Z0-9_]*)", _e)
            return consts.get(m.group(1)) if m else None

        name, root_id = field("name"), field("id")
        url, slug = field("url"), field("slug")
        if name and root_id and url and slug:
            out.append({"name": name, "root_id": root_id, "url": url, "slug": slug})
    return out


def meta_entries(raw: Any) -> list[dict[str, str]]:
    """Вміст `folder_meta[<тека>]` → однорідний список записів (див. пастку 2)."""
    if not raw:
        return []
    if isinstance(raw, str):
        # Рядок трактується як `listy`: далі в ньому не знайдеться «Л.», і запис
        # просто не потрапить у відбір кадрів — саме те, що треба.
        return [{"listy": raw}]
    if isinstance(raw, dict):
        return [raw]
    out: list[dict[str, str]] = []
    for e in raw:
        if isinstance(e, dict):
            out.append(e)
        elif e:
            out.append({"listy": str(e)})
    return out


def entry_name(listy: str) -> str:
    """«Л. 132-223 - Резина» → «Резина»."""
    parts = re.split(r"\s+-\s+", listy, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def entry_range(listy: str) -> tuple[int, int | None] | None:
    """«Л. 132-223» → (132, 223); «Л. 457-…» → (457, None); «Л. 137» → (137, 137)."""
    m = RANGE_RE.search(listy)
    if not m:
        return None
    start, tail = int(m.group(1)), m.group(2)
    if tail is None:
        return (start, start) if "-" not in listy.split(" - ")[0] else (start, None)
    if tail.isdigit():
        return start, int(tail)
    return start, None


def film_entries(tree: dict[str, Any], path: str, film: str) -> list[dict[str, Any]]:
    """Записи покажчика плівки: протягнутий шифр і закриті межі.

    Відкриту межу («Л. 457-…») закриваємо СУСІДОМ по цій же плівці, а не «до
    кінця плівки»: інакше один запис тягнув би пів справи чужих сіл — тобто
    відповідь «метрики вашого села на кадрах 457-991» була б хибною на 400
    аркушів, і хибною правдоподібно.
    """
    parent = tree.get(norm_path(path), {})
    meta = meta_entries((parent.get("folder_meta") or {}).get(film))
    frames = len((tree.get(norm_path(path) + film + "/") or {}).get("files") or [])
    out: list[dict[str, Any]] = []
    delo = soder = ""
    for e in meta:
        delo = (e.get("delo") or "").strip() or delo
        soder = (e.get("soderzhanie") or "").strip() or soder
        listy = (e.get("listy") or "").strip()
        rng = entry_range(listy)
        out.append({"film": film, "path": norm_path(path) + film, "frames": frames,
                    "delo": delo, "soder": soder, "listy": listy,
                    "name": entry_name(listy),
                    "start": rng[0] if rng else None,
                    "end": rng[1] if rng else None,
                    "end_inferred": False})
    for i, r in enumerate(out):
        if r["start"] is not None and r["end"] is None:
            nxt = next((o["start"] for o in out[i + 1:]
                        if o["start"] and o["start"] > r["start"]), None)
            r["end"] = (nxt - 1) if nxt else frames
            r["end_inferred"] = True
    return out


def _fold(s: str) -> str:
    return s.casefold().replace("ё", "е").replace("є", "е").replace("i", "и")


class FilmMirrorSource:
    """Дзеркало плівок FS. Дерева регіонів кешуються в робочому просторі."""

    id = "fsfilm"
    label = "Дзеркало плівок FamilySearch"
    caps = frozenset({"search", "browse", "manifest", "fetch"})

    CACHE_REL = Path("data") / "cache" / "fsfiles"

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None,
                 cache_dir: Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self.http = fetcher or Fetcher(delay=0.0)
        self._cache = Path(cache_dir) if cache_dir else None
        self._trees: dict[str, dict[str, Any]] = {}
        self._sources: list[dict[str, str]] | None = None

    @property
    def cache_dir(self) -> Path:
        if self._cache is not None:
            return self._cache
        if self.workspace is None:
            raise SourceError("дзеркалу плівок потрібен робочий простір для кешу дерев")
        return self.workspace / self.CACHE_REL

    # ── реєстр і дерева ──────────────────────────────────────────────────────

    def sources(self, *, refresh: bool = False) -> list[dict[str, str]]:
        if self._sources is not None and not refresh:
            return self._sources
        cached = self.cache_dir / "sources.json"
        if not refresh and cached.is_file() and \
                time.time() - cached.stat().st_mtime < SOURCES_TTL:
            self._sources = json.loads(cached.read_text(encoding="utf-8"))
            return self._sources
        html = self.http.get(SPA_URL).text
        self._sources = parse_sources(html)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(self._sources, ensure_ascii=False),
                          encoding="utf-8")
        return self._sources

    def source(self, slug: str) -> dict[str, str]:
        for s in self.sources():
            if s["slug"] == slug:
                return s
        known = ", ".join(sorted(s["slug"] for s in self.sources()))
        raise SourceError(f"регіону {slug!r} немає. Є: {known}")

    def tree(self, slug: str, *, refresh: bool = False) -> dict[str, Any]:
        if slug in self._trees and not refresh:
            return self._trees[slug]
        blob = self.cache_dir / f"{slug}.json.gz"
        # 🔴 Нульовий блоб — слід ОБІРВАНОГО запису (скінчився диск, Ctrl-C), і
        # він отруйний: `exists()` каже «є», докачки не буде ніколи, а регіон
        # тихо випадає з обходу під виглядом помилки. Порожній файл = кешу нема.
        if blob.exists() and blob.stat().st_size == 0:
            blob.unlink()
        if refresh or not blob.exists():
            src = self.source(slug)
            buf = io.BytesIO(self.http.get(src["url"]).content)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = blob.with_name(blob.name + ".part")
            try:
                tmp.write_bytes(buf.getvalue())
                tmp.replace(blob)
            finally:
                tmp.unlink(missing_ok=True)
        data = json.loads(gzip.decompress(blob.read_bytes()).decode("utf-8"))
        tree: dict[str, Any] = data["tree"]
        tree["_rootId"] = data.get("rootId", "")
        self._trees[slug] = tree
        return tree

    # ── адресація ────────────────────────────────────────────────────────────

    @staticmethod
    def split_ref(ref: str) -> tuple[str, str]:
        parts = [p for p in ref.replace("\\", "/").split("/") if p]
        if not parts:
            raise SourceError("порожня адреса")
        return parts[0], "/".join(parts[1:])

    @staticmethod
    def parse_url(url: str) -> str:
        """`https://fsfiles.ru/#moldova%2F…%2F2086525` → `moldova/…/2086525`."""
        frag = urllib.parse.urlparse(url).fragment or url.split("#", 1)[-1]
        parts = [p for p in urllib.parse.unquote(frag).split("/") if p]
        if not parts:
            raise SourceError(f"у посиланні немає шляху: {url!r}")
        return "/".join(parts)

    def frame_url(self, slug: str, path: str, name: str) -> str:
        """Робоча адреса кадру. НЕ `imageBaseUrl` із дерева — див. пастку 1."""
        root = self.source(slug)["root_id"]
        if not root.startswith(MEDIA_PREFIX):
            raise SourceError(
                f"несподіваний rootId {root!r} — правило /storage не діє, і "
                f"вгадувати адресу тут не можна")
        rel = root[len(MEDIA_PREFIX):] + norm_path(path) + name
        return STORAGE_BASE + urllib.parse.quote(rel)

    # ── контракт ─────────────────────────────────────────────────────────────

    def browse(self, ref: str | None = None) -> list[Node]:
        if not ref:
            return [Node(ref=s["slug"], label=s["name"]) for s in self.sources()]
        slug, path = self.split_ref(ref)
        tree = self.tree(slug)
        key = norm_path(path)
        nd = tree.get(key)
        if nd is None:
            raise SourceError(f"теки немає у дереві регіону {slug}: {path!r}")
        out: list[Node] = []
        for name in nd.get("folders") or []:
            sub = tree.get(key + name + "/") or {}
            n_files = len(sub.get("files") or [])
            out.append(Node(
                ref=f"{slug}/{key}{name}",
                label=name,
                # Тека з кадрами і без — різні речі для користувача: перша це
                # плівка, яку качають, друга — просто рівень дерева.
                kind="case" if n_files else "folder",
                frames=n_files or None))
        return out

    def search(self, q: str, *, limit: int = 30, regions: list[str] | None = None
               ) -> list[Hit]:
        """Пошук по ПОАРКУШЕВОМУ покажчику — без жодного завантаження.

        🔴 Шукаються тільки регіони, чиї дерева ВЖЕ в кеші. Тягнути всі (десятки
        мегабайтів) заради одного запиту не можна, але й мовчати про це не
        можна: інакше нуль означав би «немає», хоча дивились у трьох регіонах
        із двадцяти. Тому перелік оглянутого повертається у `note` кожної
        знахідки, а порожній кеш — це відмова, а не нуль.

        ⚠ Назва в покажчику — це те, що написав УКЛАДАЧ плівки, а не звірений
        топонім. Спіймано на «Резині»: у Молдові два різні села з назвами, що в
        російській передачі збігаються, і покажчик веде не туди, куди читається.
        Приймач простий і дешевий — подивитись СУСІДНІ записи того самого тому:
        вони називають округу, і округа розрізняє те, чого не розрізняє назва.
        """
        needle = _fold(q).strip()
        if not needle:
            return []
        slugs = regions or [p.name[:-len(".json.gz")]
                            for p in sorted(self.cache_dir.glob("*.json.gz"))]
        if not slugs:
            raise SourceError(
                "жодного дерева регіону ще не завантажено, тож покажчик порожній "
                "і нуль тут нічого не означав би. Спершу подивіться регіон — "
                "`nysh browse fsfilm` покаже перелік, а `nysh browse fsfilm "
                "<регіон>` заодно принесе його дерево.")
        out: list[Hit] = []
        for slug in slugs:
            try:
                tree = self.tree(slug)
            except (SourceError, OSError, ValueError):
                continue
            for path, nd in tree.items():
                if not isinstance(nd, dict) or not nd.get("folder_meta"):
                    continue
                for film in nd["folder_meta"]:
                    for r in film_entries(tree, path.rstrip("/"), film):
                        if r["start"] is None or not r["name"]:
                            continue
                        if needle not in _fold(r["name"]):
                            continue
                        out.append(Hit(
                            source=self.id,
                            ref=f"{slug}/{r['path']}",
                            title=f"{r['name']} · {r['listy']}",
                            years=r["soder"],
                            place=r["name"],
                            shifra=r["delo"],
                            frames=r["frames"] or None,
                            acquirable=True,
                            note=f"плівка {film}, регіон {slug}"))
                        if len(out) >= limit:
                            return out
        return out

    def manifest(self, ref: str) -> Manifest:
        slug, path = self.split_ref(ref)
        tree = self.tree(slug)
        nd = tree.get(norm_path(path))
        if nd is None:
            raise SourceError(f"теки немає у дереві регіону {slug}: {path!r}")
        files = list(nd.get("files") or [])
        key = norm_path(path).rstrip("/")
        parent, _, film = key.rpartition("/")
        rows = film_entries(tree, parent, film) if film else []
        sheets = tuple(
            Sheet(frm=r["start"], to=r["end"] or r["start"],
                  label=" ".join(x for x in (r["name"], r["delo"], r["soder"]) if x)
                        + (" ~межа з сусіда" if r["end_inferred"] else ""))
            for r in rows if r["start"] is not None)
        return Manifest(
            source=self.id, ref=ref,
            title=f"плівка {film}" if film else path,
            frames=len(files), sheets=sheets,
            meta={"region": slug, "path": norm_path(path), "files": files,
                  # Скільки записів покажчика справді поаркушеві, а скільки —
                  # просто підписи теки. Без цього розрізнення «покажчик є»
                  # обіцяло б відповідь там, де її немає.
                  "sheet_rows": len(sheets), "meta_rows": len(rows)})

    def fetch(self, ref: str, dest: Path, *,
              frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        slug, path = self.split_ref(ref)
        man = self.manifest(ref)
        raw = man.meta.get("files")
        files: list[str] = [str(x) for x in raw] if isinstance(raw, list) else []
        if frames:
            # Кадри рахуються з ОДИНИЦІ — так їх нумерує і покажчик аркушів, і
            # сам користувач; зсув на один тут означав би читати не те село.
            lo, hi = frames
            files = files[max(0, lo - 1):hi]
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        res = FetchResult(dest=dest)
        total = len(files)
        # 🔴 Спинятись після серії невдач, а не молотити ретраями. Хост тут —
        # приватний одинак, і різниця між «нас відсікли» та «сервер ліг» ззовні
        # не видна; у обох випадках правильна дія одна — припинити.
        misses = 0
        with self.http.client() as c:
            for done, name in enumerate(files, 1):
                dst = dest / name
                if dst.exists() and dst.stat().st_size > 0:
                    res.skipped += 1
                else:
                    try:
                        blob = self.http.get(self.frame_url(slug, path, name),
                                             client=c).content
                        dst.write_bytes(blob)
                        res.frames += 1
                        res.bytes += len(blob)
                        misses = 0
                    except (HttpError, OSError) as exc:
                        res.errors.append(f"{name}: {exc}")
                        misses += 1
                        if misses >= 10:
                            res.errors.append(
                                "10 кадрів поспіль не взялись — спиняюсь. "
                                "Перевірити, чи хост живий, пробою з іншого IP.")
                            break
                if on_progress:
                    on_progress(done=done, total=total, unit="кадр")
        return res
