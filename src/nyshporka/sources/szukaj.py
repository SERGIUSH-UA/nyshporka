"""🇵🇱 Szukaj w Archiwach: маніфест і качання одиниці, розвороти — по згину на сторінки.

Портал державних архівів Польщі (`core.szukaj`). Перелік сканів одиниці —
сторінки по 200 (більше портал не віддає: `delta=1000` дає ті самі 200), у
кожному пункті номер скана, id файла й хеш зображення; сам скан —
`photos.szukajwarchiwach.gov.pl/<хеш>_max`, побайтово той самий файл, що в
zip «Pobierz». Книга на 954 скани — п'ять запитів переліку.

## 🔴 З українських IP портал закритий

Заміряно 07.10.2026: і сторінки, і `photos.` віддають з України 403 від
Incapsula, а з ЄС — 200. Обійти це клієнтом не можна: блокують за адресою, а
не за відбитком. Тому два шляхи, і обидва без вигаданих даних:

    мережа    `NYSHPORKA_PROXY_URL` з виходом у ЄС; сторінки йдуть через
              `CfClient` (звичайний httpx дістає заглушку Incapsula на
              212 байтів), скани — звичайним `Fetcher`.
    zip       людина сама качає «Pobierz (xml)» у браузері з VPN, і пакет
              розкладає архів (`fetch(..., from_zip=…)`): номер скана й id
              файла — з імен, назва й роки — з xml поруч.

## Кеш маніфесту

Перелік одиниці, взятий хоч раз, лягає в простір
(`data/raw/szukaj/_crawl/units/<id>.json`), і далі маніфест читається звідти —
без мережі. Тобто проксі потрібен лише на першу появу одиниці й на самі
кадри; zip знімає й друге.

## 🔴 Скан — часто РОЗВОРОТ

Ріже `sources.skanoteka.split_and_save` (той самий детектор згину й та сама
висота 3100 сірим), карта — `_szukaj.json`: сторінка → номер скана, бік, межі
різу. Поворот «за формою кадру» тут знищив би обидві сторінки.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as _dt
import html
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

from nyshporka.core import szukaj as SZ
from nyshporka.sources.base import (
    FetchResult,
    Manifest,
    ProgressFn,
    SourceAbout,
    SourceError,
    SourceScope,
)
from nyshporka.sources.http import Fetcher, HttpError, offline
from nyshporka.sources.skanoteka import FOLD_RULE, TARGET_H, split_and_save
from nyshporka.utils.atomic import atomic_write_bytes

#: Скільки сканів на сторінку переліку. Більше портал не віддає.
DELTA = 200
#: Паралельних завантажень сканів — як у Сканотеки: державний портал, але
#: людині швидше не стане, а серверу відчутно.
JOBS = 4
#: Портлет одиниці часом відповідає «Portlet jest tymczasowo niedostępny» на
#: першому запиті й нормально на другому (07.10.2026: 1 раз із 3).
PORTLET_TRIES = 4
PORTLET_PAUSE = 2.0
#: Пауза між сторінками порталу. 🔴 Incapsula виставляє адресі виклик після
#: серії запитів (07.10.2026: ~40 сторінок за кілька хвилин, частина з браузера
#: — і далі на кожну сторінку iframe `_Incapsula_Resource`, ще й годиною
#: пізніше), а `photos.` при цьому віддає скани як і раніше. Книга — це 5
#: сторінок переліку, тож пауза майже нічого не коштує.
PAGE_DELAY = 4.0
CACHE_REL = Path("data") / "raw" / "szukaj" / "_crawl" / "units"
_SHIELD = ("_Incapsula_Resource", "Incapsula incident")

_ITEM = re.compile(
    r'data-plikId="(?P<plik>\d+)".*?photos\.szukajwarchiwach\.gov\.pl/(?P<photo>[0-9a-f]{64})_mid'
    r'.*?number-of-scan">(?P<n>\d+)<', re.I | re.S)
_TOTAL = re.compile(r"Skany\s*\((\d+)\)")
_OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
_ZESPOL = re.compile(r"/zespol/-/zespol/(\d+)")
_DOWN = "tymczasowo niedost"


class SzukajSource:
    """Szukaj w Archiwach: маніфест і качання одиниці."""

    id = SZ.SOURCE
    label = SZ.NAME
    caps = frozenset({"manifest", "fetch"})

    about = SourceAbout(
        answers="забрати скани одиниці з порталу державних архівів Польщі "
                "(гродські й земські книги, метрики, нотаріат) за її адресою",
        gives="сигнатуру, назву, роки, архів і фонд одиниці, перелік сканів і самі "
              "кадри; розворот ріжеться по згину на дві сторінки",
        not_gives="пошуку: що є у фонді — сторінка фонду на порталі; з українських "
                  "IP портал закритий (403) — потрібен проксі в ЄС або zip, "
                  "скачаний у браузері",
        where_class="переглядач архіву",
        scope=SourceScope(countries=("PL",),
                          note="державні архіви Польщі на szukajwarchiwach.gov.pl; "
                               "зокрема Холмщина, Перемишль, Люблін"),
        match_on=(), match_how=None,
        zero_means="не шукає; одиниця або є за адресою, або портал її не віддає",
        pitfalls=("з України 403 на все — це блок за адресою, а не «одиниці немає»",
                  "кадр — розворот: поворот «за формою кадру» знищить обидві сторінки",
                  "карта `_szukaj.json` — єдиний шлях назад до номера скана"),
        card="szukaj")

    def __init__(self, workspace: Path | None = None, *, pages: Any = None,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        #: Підставлені клієнти — вхід для тестів.
        self._pages_client = pages
        self._pages_http: Fetcher | None = None
        self._injected = fetcher is not None or pages is not None
        self.http = fetcher or Fetcher(delay=0.0)

    # ── сторінки порталу ─────────────────────────────────────────────────────
    def _pages(self) -> Fetcher:
        """Сторінки — через `CfClient`: httpx дістає від Incapsula заглушку.

        ⚠ Ліниво: реєстр будує джерело на кожен виклик `nysh`, а `CfClient` без
        `curl_cffi` і без `curl` відмовляє одразу.
        """
        if self._pages_http is None:
            client = self._pages_client
            if client is None:
                from nyshporka.sources.cfclient import CfClient
                from nyshporka.sources.http import proxy_url

                client = CfClient(proxy=proxy_url())
            self._pages_http = Fetcher(base=SZ.BASE, client=client,
                                       delay=0.0 if self._injected else PAGE_DELAY)
        return self._pages_http

    def _page(self, url: str) -> str:
        if offline() and not self._injected:
            raise SourceError(f"мережу вимкнено в цьому середовищі — {self.label} не опитано")
        text = ""
        for i in range(PORTLET_TRIES):
            try:
                text = str(self._pages().get(url).text)
            except HttpError as exc:
                if getattr(exc, "status", None) == 403:
                    raise SourceError(_geo_text(url)) from exc
                raise SourceError(f"сторінка порталу не відкрилась: {url} ({exc})") from exc
            if any(m in text[:4000] for m in _SHIELD):
                raise SourceError(_shield_text(url))
            if _DOWN not in text:
                return text
            if i + 1 < PORTLET_TRIES and not self._injected:
                time.sleep(PORTLET_PAUSE * (i + 1))
        raise SourceError(f"портал {PORTLET_TRIES} рази поспіль відповів «портлет тимчасово "
                          f"недоступний»: {url}")

    # ── маніфест ─────────────────────────────────────────────────────────────
    def manifest(self, ref: str, *, from_zip: Path | None = None) -> Manifest:
        """Що принесе завантаження. Кеш простору → zip → портал, у цьому порядку."""
        unit = _unit(ref)
        card = self._cached(unit)
        if card is None and from_zip is not None:
            card = _card_from_zip(unit, Path(from_zip))
        if card is None:
            card = self._card_live(unit)
            self._store(unit, card)
        return _manifest(unit, card)

    def _card_live(self, unit: SZ.Unit) -> dict[str, Any]:
        first = self._page(unit.list_url(1, DELTA))
        card = _parse_card(first)
        scans = _items(first)
        total = card.get("total")
        page = 1
        while isinstance(total, int) and len(scans) < total:
            page += 1
            got = _items(self._page(unit.list_url(page, DELTA)))
            fresh = {k: v for k, v in got.items() if k not in scans}
            if not fresh:
                break   # портал повторив сторінку — далі нічого не буде
            scans.update(fresh)
        if not scans:
            raise SourceError(f"у переліку одиниці немає жодного скана — одиниці не існує, "
                              f"сканів не виставлено або портал змінив розмітку: {unit.url}")
        if isinstance(total, int) and len(scans) != total:
            raise SourceError(f"портал назвав {total} сканів, а в переліку {len(scans)} — "
                              f"перелік обірвано, маніфест не пишу: {unit.url}")
        card["scans"] = {str(n): v for n, v in sorted(scans.items())}
        card["from"] = "portal"
        card["at"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
        return card

    def _cache_path(self, unit: SZ.Unit) -> Path | None:
        return self.workspace / CACHE_REL / f"{unit.id}.json" if self.workspace else None

    def _cached(self, unit: SZ.Unit) -> dict[str, Any] | None:
        p = self._cache_path(unit)
        if p is None:
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("scans"), dict) else None

    def _store(self, unit: SZ.Unit, card: dict[str, Any]) -> None:
        p = self._cache_path(unit)
        if p is not None:
            atomic_write_bytes(p, json.dumps(card, ensure_ascii=False, indent=1).encode("utf-8"))

    # ── качання ──────────────────────────────────────────────────────────────
    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None, split: bool = True,
              from_zip: Path | None = None) -> FetchResult:
        """Скани одиниці → сторінки в `dest` і карта `_szukaj.json`.

        `frames` — номери СКАНІВ, як на порталі. Скан, чиї сторінки вже лежать
        і названі в карті, вдруге не береться. `from_zip` — архів «Pobierz»,
        скачаний у браузері: кадри беруться з нього, мережа не потрібна.
        """
        man = self.manifest(ref, from_zip=from_zip)
        unit = _unit(man.ref)
        scans: dict[str, dict[str, Any]] = dict(man.meta.get("scans") or {})   # type: ignore[call-overload]
        numbers = sorted(int(n) for n in scans)
        if frames:
            lo, hi = frames
            numbers = [n for n in numbers if lo <= n <= hi]
            if not numbers:
                raise SourceError(f"у діапазоні {lo}-{hi} немає сканів: в одиниці {man.frames}")
        zf = zipfile.ZipFile(from_zip) if from_zip is not None else None
        in_zip = _zip_index(zf) if zf is not None else {}
        if zf is not None:
            missing = [n for n in numbers if n not in in_zip]
            if missing:
                zf.close()
                raise SourceError(f"у zip немає {len(missing)} сканів із потрібних (перший — "
                                  f"{missing[0]}): архів скачано не «wszystkie» або обірвано")
        dest.mkdir(parents=True, exist_ok=True)
        res = FetchResult(dest=dest)
        book = SZ.read_map_raw(dest) or {}
        done: dict[str, Any] = dict(book.get("frames") or {})
        todo = []
        for n in numbers:
            rec = done.get(SZ.stem(n))
            if rec and all((dest / p).is_file() for p in (rec.get("pages") or {})):
                res.skipped += 1
            else:
                todo.append(n)
        head = {"source": SZ.HOST, "url": unit.url, "unit": unit.id,
                "sygnatura": man.meta.get("sygnatura", ""), "split": split,
                "fold_rule": FOLD_RULE, "target_h": TARGET_H,
                "taken_from": "zip" if zf is not None else "photos"}
        total = len(numbers)
        count = res.skipped

        def blob_of(n: int) -> bytes:
            if zf is not None:
                return zf.read(in_zip[n])
            photo = str(scans[str(n)].get("photo") or "")
            if not photo:
                raise HttpError(f"скан {n}: у маніфесті немає адреси зображення")
            return bytes(self.http.get(SZ.photo_url(photo)).content)

        def one(n: int) -> tuple[int, dict[str, Any] | None, BaseException | None]:
            try:
                blob = blob_of(n)
                if not blob.startswith(b"\xff\xd8"):
                    raise HttpError(f"не JPEG ({len(blob)} Б)")
                if not blob.rstrip(b"\x00").endswith(b"\xff\xd9"):
                    raise HttpError("обірваний JPEG (немає кінця файла)")
                rec = split_and_save(blob, SZ.stem(n), dest, split=split)
                rec["scan"] = n
                rec["plik_id"] = scans[str(n)].get("plik", "")
                if scans[str(n)].get("photo"):
                    rec["photo"] = scans[str(n)]["photo"]
                return n, rec, None
            except Exception as exc:  # мережа, битий кадр чи битий zip — у причини
                return n, None, exc

        # zip читається з одного потоку: `ZipFile` не потокобезпечний на read.
        workers = 1 if zf is not None else JOBS
        try:
            with cf.ThreadPoolExecutor(max_workers=workers) as ex:
                for i, (n, rec, exc) in enumerate(ex.map(one, todo), 1):
                    if rec is None:
                        assert exc is not None
                        res.blame(exc)
                        res.errors.append(f"скан {n}: {exc}")
                    else:
                        done[SZ.stem(n)] = rec
                        res.frames += 1
                        res.bytes += int(rec.get("src_bytes") or 0)
                    count += 1
                    if on_progress:
                        on_progress(done=count, total=total, unit="скан")
                    if i % 50 == 0:
                        SZ.write_map(dest, {**head, "frames": done})
        finally:
            if zf is not None:
                zf.close()
        SZ.write_map(dest, {**head, "frames": done})
        whole = sum(1 for r in done.values() if len(r.get("pages") or {}) == 1)
        pages = sum(len(r.get("pages") or {}) for r in done.values())
        if split and pages != len(done):
            res.notes.append(f"сканів {len(done)} → сторінок {pages}: розвороти "
                             f"розрізано по згину, {whole} кадрів лишено цілими "
                             f"(обкладинка, вкладка або згину не видно)")
        return res


def _geo_text(url: str) -> str:
    return (f"портал відмовив (403): {url}. З українських IP szukajwarchiwach.gov.pl "
            f"закритий повністю — це блок за адресою, а не «одиниці немає». Два шляхи: "
            f"NYSHPORKA_PROXY_URL із виходом у ЄС, або скачати «Pobierz (xml)» у "
            f"браузері з VPN і розкласти архів: `nysh get szukaj <адреса> --from-zip "
            f"<skany.zip> --out <тека>`")


def _shield_text(url: str) -> str:
    return (f"захист порталу (Incapsula) віддав цій адресі сторінку-виклик замість "
            f"одиниці: {url}. Так буває після серії запитів, і пауза в хвилини не "
            f"допомагає — це не «одиниці немає». Що робити: одиниця, яку вже брали, "
            f"лежить у кеші простору й мережі не просить; нову — скачати «Pobierz "
            f"(xml)» у браузері й розкласти `nysh get szukaj <адреса> --from-zip "
            f"<skany.zip> --out <тека>`, або повторити з іншої адреси пізніше")


def _unit(ref: str) -> SZ.Unit:
    unit = SZ.from_ref(ref) or SZ.from_url(ref)
    if unit is None:
        raise SourceError(f"«{ref}» — не адреса одиниці Szukaj w Archiwach. Потрібно "
                          f"`https://www.szukajwarchiwach.gov.pl/jednostka/-/jednostka/<id>` "
                          f"або `jednostka:<id>`")
    return unit


def _text_lines(page: str) -> list[str]:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    lines = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", body)).splitlines()]
    return [x for x in lines if x]


def _parse_card(page: str) -> dict[str, Any]:
    """Картка одиниці: сигнатура, роки, архів, фонд, назва, число сканів.

    🔴 Підписи шукаються ПІСЛЯ «Sygnatura»: «Archiwum» і «Zespół» стоять ще й у
    хлібних крихтах угорі сторінки, і перший збіг давав би «Jednostka».
    """
    lines = _text_lines(page)
    out: dict[str, Any] = {}
    try:
        start = lines.index("Sygnatura")
    except ValueError:
        start = -1
    if start >= 0:
        keys = {"Sygnatura": "sygnatura", "Daty": "years", "Archiwum": "archiwum",
                "Zespół": "zespol"}
        for i in range(start, min(len(lines) - 1, start + 16)):
            key = keys.get(lines[i])
            if key and key not in out:
                out[key] = lines[i + 1]
    m = _OG_TITLE.search(page)
    if m:
        out["title"] = html.unescape(m.group(1)).strip()
    m = _TOTAL.search(page)
    if m:
        out["total"] = int(m.group(1))
    m = _ZESPOL.search(page)
    if m:
        out["zespol_id"] = m.group(1)
    if out.get("years"):
        out["years"] = re.sub(r"\s*-\s*", "-", str(out["years"]))
    return out


def _items(page: str) -> dict[int, dict[str, str]]:
    return {int(m.group("n")): {"plik": m.group("plik"), "photo": m.group("photo")}
            for m in _ITEM.finditer(page)}


def _zip_index(zf: zipfile.ZipFile) -> dict[int, str]:
    out: dict[int, str] = {}
    for name in zf.namelist():
        if not name.lower().endswith(".jpg"):
            continue
        got = SZ.parse_zip_name(name)
        if got is not None:
            out[got[1]] = name
    return out


def _card_from_zip(unit: SZ.Unit, path: Path) -> dict[str, Any]:
    """Картка з архіву «Pobierz»: перелік — з імен, назва й роки — з xml (коли є).

    Число сканів тут — те, що в архіві: портал не опитано, тож звірити повноту
    з ним нема чим, і маніфест каже про це в `from`.
    """
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceError(f"zip не відкривається: {path} ({exc})") from exc
    with zf:
        scans: dict[str, dict[str, str]] = {}
        sygns: set[str] = set()
        xml_name = ""
        for name in zf.namelist():
            got = SZ.parse_zip_name(name)
            if got is None:
                continue
            if name.lower().endswith(".jpg"):
                scans[str(got[1])] = {"plik": got[2]}
                sygns.add(got[0])
            elif name.lower().endswith(".xml") and not xml_name:
                xml_name = name
        if not scans:
            raise SourceError(f"у zip немає жодного скана з іменем порталу "
                              f"(`<сигнатура>_<скан>_<id>.jpg`): {path}")
        if len(sygns) > 1:
            raise SourceError(f"у zip скани кількох одиниць ({', '.join(sorted(sygns))}) — "
                              f"розкладати як одну не можна: {path}")
        card: dict[str, Any] = {"sygnatura": sygns.pop()}
        if xml_name:
            xml = zf.read(xml_name).decode("utf-8", "replace")
            for tag, key in (("nazwa", "title"), ("daty", "years")):
                m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
                if m and m.group(1).strip():
                    card[key] = html.unescape(m.group(1).strip())
    card["scans"] = dict(sorted(scans.items(), key=lambda kv: int(kv[0])))
    card["from"] = "zip"
    card["zip"] = str(path)
    return card


def _manifest(unit: SZ.Unit, card: dict[str, Any]) -> Manifest:
    scans = card.get("scans") or {}
    sygn = str(card.get("sygnatura") or "")
    title = " · ".join(x for x in (card.get("archiwum"), card.get("zespol"), sygn,
                                   card.get("title"), card.get("years")) if x)
    meta: dict[str, object] = {"url": unit.url, "unit": unit.ref, "sygnatura": sygn,
                               **SZ.sygn_parts(sygn),
                               "title": card.get("title", ""), "years": card.get("years", ""),
                               "archiwum_name": card.get("archiwum", ""),
                               "zespol_name": card.get("zespol", ""),
                               "zespol_id": card.get("zespol_id", ""),
                               "listed_from": card.get("from", ""), "scans": scans}
    return Manifest(source=SZ.SOURCE, ref=unit.ref, title=title or unit.url,
                    frames=len(scans), meta=meta)
