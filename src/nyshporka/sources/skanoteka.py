"""📚 Сканотека ПТГ: качання одиниці фонду, розвороти — по згину на сторінки.

Польське генеалогічне товариство виставляє скани судових, нотаріальних і
адресних книг (зокрема ЦДІАК ф.2 — київські гродські книги XVI–XVIII ст.) на
одному рушії з кількома базами (`core.skanoteka.HOSTS`). Сторінка одиниці
`https://<база>.genealodzy.pl/id<фонд>-sy<одиниця>-se` перелічує всі файли
(`plik=001.jpg…`), а сам файл віддає роздавач `metbox` за двома токенами:
`dir` — сталий на одиницю, `znak` — на сайт. Один запит сторінки перегляду
дає адреси всіх файлів, далі качання йде без браузера й без входу.

## 🔴 Кадр Сканотеки часто — РОЗВОРОТ, але не завжди

Замір на ф.2 ЦДІАК: кадр 5800×4800 … 6500×4912, ≈6 МБ, дві сторінки поруч.
Різ по згину робить із нього дві сторінки (`185_L.jpg`, `185_R.jpg`), і саме
їх читає рушій. Але в тій самій книзі трапляються обкладинки (портретний
кадр — один аркуш) і вкладки (широкий аркуш, рядки через усю ширину), а
бувають і книги, зняті по аркушу. Тому різ — ворота, а не правило: кадр
ріжеться лише тоді, коли згин видно впевнено, інакше лишається цілим (`185.jpg`).
`--whole` (`fetch(..., split=False)`) не ріже нічого.

🔴 Нормалізацію орієнтації за формою кадру тут вмикати НЕ МОЖНА: «ширина >
висоти» на розвороті — не «аркуш лежить», а дві сторінки, і поворот знищив би
обидві.

## Карта сканів

`_skanoteka.json` поруч із кадрами: для кожного скана — його сторінки, бік і
x згину. Це єдиний зв'язок сторінки декоду з номером скана в джерелі
(`core.skanoteka.read_map`), і з неї пакет для Супряги бере `src` кожної
сторінки. Два люди, що взяли ту саму одиницю цим джерелом, отримують ті самі
імена й ті самі `src`, і чужий текст лягає на свої кадри точно.

Кадр зберігається сірим, висотою 3100: замір на скані 185 справи 160 показав,
що вилов від зменшення не падає (55 рядків і обидві згадки топоніма в обох
розмірах), а місця на диску йде втричі менше. Оригінал перекачується за картою.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from nyshporka.core import skanoteka as SK
from nyshporka.sources.base import (
    FetchResult,
    Manifest,
    ProgressFn,
    SourceAbout,
    SourceError,
    SourceScope,
)
from nyshporka.sources.http import Fetcher, HttpError, offline

#: Висота сторінки після зменшення — та сама, що в `cloud.frames` (TARGET_HEIGHT).
TARGET_H = 3100
JPEG_Q = 90
#: Паралельних завантажень. Сайт товариства тримається на внесках; більше —
#: не швидше для людини, зате відчутно для них.
JOBS = 4
#: Версія правила різу. Ті самі вхідні кадри й та сама версія дають ті самі
#: сторінки — на цьому тримається точне зіставлення чужого тексту з своїми кадрами.
FOLD_RULE = 1

_PLIK = re.compile(r"plik=(\d+)\.jpg")
_METBOX = re.compile(r"https://metbox\d*\.genealodzy\.pl/\d+/metryka_get\.php\?[^\"'\s<>]+")

#: У скільки разів текст обабіч має бути «активніший» за саму смугу згину.
FOLD_GUTTER_RATIO = 2.5
#: Пом'якшений поріг того ж відношення — діє ЛИШЕ разом із другою ознакою нижче.
FOLD_GUTTER_RATIO_SOFT = 1.9
#: Друга, незалежна ознака: згин тихий проти ВСЬОГО кадру. Замір на 4 300
#: кадрах ф.2: пропущені розвороти дають 0.20-0.50 медіанної активності кадру,
#: вкладки й обкладинки — 0.94-0.95.
FOLD_QUIET_OF_MEDIAN = 0.6
#: Частка ширини вікна навколо центру, де шукається найтихіша колонка.
FOLD_WINDOW = 0.14
#: Крок проби колонок для медіани по кадру: повний обхід удвічі дорожчий за
#: саму детекцію, а медіана від нього не рухається.
FOLD_MEDIAN_STRIDE = 8


class SkanotekaSource:
    """Сканотека ПТГ: маніфест і качання одиниці фонду."""

    id = SK.SOURCE
    label = SK.NAME
    caps = frozenset({"manifest", "fetch"})

    about = SourceAbout(
        answers="забрати скани одиниці фонду з бази Сканотеки ПТГ за її адресою",
        gives="перелік файлів одиниці (назва фонду й одиниці, роки) і самі кадри; "
              "розворот ріжеться по згину на дві сторінки",
        not_gives="пошуку й покажчика: що є у фонді — сторінка фонду на сайті; "
                  "номер одиниці не обов'язково = номер справи архівного опису",
        where_class="переглядач архіву",
        scope=SourceScope(note="бази skanoteka, sadowe, notariaty, meldunkowe на "
                               "genealodzy.pl; зокрема ЦДІАК ф.2 (sadowe, id1703)"),
        match_on=(), match_how=None,
        zero_means="не шукає; одиниця або є за адресою, або сайт її не віддає",
        pitfalls=("кадр — розворот: поворот «за формою кадру» знищить обидві сторінки",
                  "карта сканів `_skanoteka.json` — єдиний шлях назад до номера "
                  "скана; без неї посилання на знахідку не відкрити"),
        card="skanoteka")

    def __init__(self, workspace: Path | None = None, *, fetcher: Fetcher | None = None) -> None:
        self._fetcher = fetcher
        self.http = fetcher or Fetcher(delay=0.0)

    # ── маніфест ─────────────────────────────────────────────────────────────
    def manifest(self, ref: str) -> Manifest:
        unit = _unit(ref)
        page = self._unit_page(unit)
        files = _files(page)
        if not files:
            raise SourceError(f"на сторінці одиниці немає жодного файла — одиниці "
                              f"не існує або сайт змінив розмітку: {unit.url}")
        info = _labels(page)
        title = " · ".join(x for x in (info.get("Zespół"), info.get("Jednostka"),
                                       info.get("Lata")) if x)
        return Manifest(source=self.id, ref=unit.ref, title=title or unit.url,
                        frames=len(files),
                        meta={"url": unit.url, "unit": unit.ref, "files": files,
                              "years": info.get("Lata", ""),
                              "zespol": info.get("Zespół", ""),
                              "jednostka": info.get("Jednostka", "")})

    def _unit_page(self, unit: SK.Unit) -> str:
        if offline() and self._fetcher is None:
            raise SourceError(f"мережу вимкнено в цьому середовищі — {self.label} не опитано")
        try:
            return str(self.http.get(unit.url).text)
        except HttpError as exc:
            raise SourceError(f"сторінка одиниці не відкрилась: {unit.url} ({exc})") from exc

    # ── качання ──────────────────────────────────────────────────────────────
    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None, split: bool = True) -> FetchResult:
        """Скани одиниці → сторінки в `dest` і карта `_skanoteka.json`.

        Докачування: скан, чиї сторінки вже лежать і названі в карті, не
        береться вдруге. `frames` — номери СКАНІВ (з одиниці), як на сайті.
        """
        man = self.manifest(ref)
        unit = _unit(man.ref)
        raw = man.meta.get("files")
        files = [str(x) for x in raw] if isinstance(raw, list) else []
        if frames:
            # Діапазон — НОМЕРИ сканів, як їх показує сайт, а не позиції в переліку.
            lo, hi = frames
            files = [f for f in files if lo <= int(f) <= hi]
            if not files:
                raise SourceError(f"у діапазоні {lo}-{hi} немає сканів: в одиниці "
                                  f"{man.frames}")
        dest.mkdir(parents=True, exist_ok=True)
        res = FetchResult(dest=dest)
        book = SK.read_map_raw(dest) or {}
        done: dict[str, Any] = dict(book.get("frames") or {})
        todo = []
        for stem in files:
            rec = done.get(stem)
            if rec and all((dest / p).is_file() for p in (rec.get("pages") or {})):
                res.skipped += 1
            else:
                todo.append(stem)
        if not todo:
            return res
        base, dir_tok, znak = self._tokens(unit, files[0])
        head = {"source": f"{unit.host}.genealodzy.pl", "url": unit.url,
                "fond_id": int(unit.fond) if unit.fond.isdigit() else unit.fond,
                "unit": unit.unit, "split": split, "fold_rule": FOLD_RULE,
                "target_h": TARGET_H, "dir": dir_tok, "znak": znak}
        total = len(files)
        count = res.skipped

        def one(stem: str) -> tuple[str, dict[str, Any] | None, BaseException | None]:
            url = f"{base}?op=download&dir={dir_tok}&znak={znak}&plik={stem}.jpg"
            try:
                blob = bytes(self.http.get(url).content)
                if not blob.startswith(b"\xff\xd8"):
                    raise HttpError(f"не JPEG ({len(blob)} Б)")
                if not blob.rstrip(b"\x00").endswith(b"\xff\xd9"):
                    raise HttpError("обірваний JPEG (немає кінця файла)")
                return stem, split_and_save(blob, stem, dest, split=split), None
            except Exception as exc:  # мережа або битий кадр — у причини
                return stem, None, exc

        with cf.ThreadPoolExecutor(max_workers=JOBS) as ex:
            for i, (stem, rec, exc) in enumerate(ex.map(one, todo), 1):
                if rec is None:
                    assert exc is not None
                    res.blame(exc)
                    res.errors.append(f"скан {stem}: {exc}")
                else:
                    done[stem] = rec
                    res.frames += 1
                    res.bytes += int(rec.get("src_bytes") or 0)
                count += 1
                if on_progress:
                    on_progress(done=count, total=total, unit="скан")
                if i % 50 == 0:
                    SK.write_map(dest, {**head, "frames": done})
        SK.write_map(dest, {**head, "frames": done})
        whole = sum(1 for r in done.values() if len(r.get("pages") or {}) == 1)
        pages = sum(len(r.get("pages") or {}) for r in done.values())
        if split and pages != len(done):
            res.notes.append(f"сканів {len(done)} → сторінок {pages}: розвороти "
                             f"розрізано по згину, {whole} кадрів лишено цілими "
                             f"(обкладинка, вкладка або згину не видно)")
        return res

    def _tokens(self, unit: SK.Unit, first: str) -> tuple[str, str, str]:
        """Адреса роздавача й токени `dir`/`znak` — зі сторінки перегляду."""
        page = self.http.get(unit.scan_url(first)).text
        m = _METBOX.search(str(page))
        if not m:
            raise SourceError(f"на сторінці перегляду немає адреси роздавача metbox — "
                              f"сайт змінив розмітку: {unit.scan_url(first)}")
        q = html.unescape(m.group(0))
        base = q.split("?", 1)[0]
        d = re.search(r"[?&]dir=([^&]+)", q)
        z = re.search(r"[?&]znak=([^&]+)", q)
        if not (d and z):
            raise SourceError(f"адреса роздавача без dir/znak: {base}")
        return base, d.group(1), z.group(1)


def _unit(ref: str) -> SK.Unit:
    unit = SK.from_ref(ref) or SK.from_url(ref)
    if unit is None:
        raise SourceError(f"«{ref}» — не адреса одиниці Сканотеки. Потрібно "
                          f"`https://<база>.genealodzy.pl/id<фонд>-sy<одиниця>-se` "
                          f"або `unit:<база>/<фонд>/<одиниця>`")
    return unit


def _files(page: str) -> list[str]:
    """Стеми файлів одиниці за номером, без повторів (`001`, `002`…).

    🔴 За НОМЕРОМ, а не в порядку сторінки: сайт виводить перелік сіткою по
    стовпцях (001, 127, 253, … 002, 128, …), і діапазон «185-186», узятий за
    позицією, віддав скани 279 і 405 (жива перевірка на ЦДІАК 2-1-160).
    """
    return sorted(set(_PLIK.findall(page)), key=lambda s: (int(s), s))


def _labels(page: str) -> dict[str, str]:
    """Підписи сторінки одиниці: `Zespół`, `Jednostka`, `Lata`."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    lines = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", body)).splitlines()]
    lines = [x for x in lines if x]
    out: dict[str, str] = {}
    for i, x in enumerate(lines[:-1]):
        key = x.rstrip(":")
        if x.endswith(":") and key in ("Zespół", "Jednostka", "Lata") and key not in out:
            out[key] = lines[i + 1]
    return out


# ── різ розвороту ────────────────────────────────────────────────────────────
def _col_activity(g: Any, lo: int, hi: int) -> list[float]:
    """Скільки «тексту» в кожній колонці: сума перепадів яскравості вниз по колонці.

    Рядок письма дає часті переходи світле↔темне, порожнє поле — майже жодного.
    Цим згин відрізняється від тексту надійніше, ніж яскравістю: на плоско
    розкритій книзі згин СВІТЛИЙ, а не темний.
    """
    band = g.crop((lo, 0, hi, g.height))
    w, h = band.size
    px = band.load()
    step = max(1, h // 220)
    out = []
    for x in range(w):
        prev, acc = px[x, 0], 0
        for y in range(step, h, step):
            cur = px[x, y]
            acc += abs(cur - prev)
            prev = cur
        out.append(acc / max(1, h // step))
    return out


def _median_activity(g: Any) -> float:
    w, h = g.size
    px = g.load()
    step = max(1, h // 220)
    vals = []
    for x in range(0, w, FOLD_MEDIAN_STRIDE):
        prev, acc = px[x, 0], 0
        for y in range(step, h, step):
            cur = px[x, y]
            acc += abs(cur - prev)
            prev = cur
        vals.append(acc / max(1, h // step))
    vals.sort()
    return vals[len(vals) // 2] if vals else 1e-6


def find_fold(im: Any) -> int | None:
    """x згину або None, якщо згину впевнено не видно.

    🔴 ЗГИН — ЦЕ ПОРОЖНЯ СМУГА МІЖ ДВОМА БЛОКАМИ ТЕКСТУ, А НЕ ТЕМНА ЛІНІЯ.
    «Найтемніша колонка» різала шкіряну палітурку по плямах; «темна смуга
    крізь усю висоту» пропускала розвороти плоско розкритої книги, де згин
    світлий. Тому шукається найтихіша колонка у вікні центру, і вона
    визнається згином лише тоді, коли обабіч текст помітно активніший.
    """
    g = im.convert("L")
    w = g.width
    lo, hi = int(w * (0.5 - FOLD_WINDOW)), int(w * (0.5 + FOLD_WINDOW))
    if hi - lo < 8:
        return None
    act = _col_activity(g, lo, hi)
    k = max(1, (hi - lo) // 60)
    sm = [sum(act[max(0, i - k):i + k + 1]) / len(act[max(0, i - k):i + k + 1])
          for i in range(len(act))]
    i_min = min(range(len(sm)), key=lambda i: sm[i])
    side = max(3, (hi - lo) // 6)
    left = sorted(sm[:side])[side // 2]
    right = sorted(sm[-side:])[side // 2]
    quiet = sm[i_min] if sm[i_min] > 0 else 1e-6
    ratio = min(left, right) / quiet
    if ratio >= FOLD_GUTTER_RATIO:
        return lo + i_min
    # Одного відношення замало: воно падає, коли одна зі сторінок слабо
    # записана (138 справжніх розворотів із 4 300 лишались цілими). Друга ознака
    # незалежна — чи тихий згин проти всього кадру; у вкладки середина така ж
    # активна, як краї.
    if ratio >= FOLD_GUTTER_RATIO_SOFT and quiet <= FOLD_QUIET_OF_MEDIAN * _median_activity(g):
        return lo + i_min
    return None


def split_and_save(raw: bytes, stem: str, out: Path, *, split: bool = True,
                   target_h: int = TARGET_H, quality: int = JPEG_Q) -> dict[str, Any]:
    """Скан → одна або дві сторінки на диску. Повертає запис карти."""
    from PIL import Image

    from nyshporka.utils.atomic import atomic_write_bytes

    im = Image.open(BytesIO(raw))
    im.load()
    w, h = im.size
    rec: dict[str, Any] = {"src": f"{stem}.jpg", "src_w": w, "src_h": h,
                           "src_bytes": len(raw), "pages": {}}
    parts: list[tuple[str, tuple[int, int, int, int]]] = [("", (0, 0, w, h))]
    if not split:
        rec["split_skipped"] = "різ вимкнено (--whole)"
    elif w < h:
        # Портретний кадр у розворотній книзі — обкладинка чи один аркуш.
        rec["split_skipped"] = "портретний кадр — один аркуш, не розворот"
    else:
        fold = find_fold(im)
        if fold is None:
            # 🔴 «Згину не видно» найчастіше означає «це не розворот»: у книги
            # вшивали вкладки, рядки яких ідуть через усю ширину, і різ навпіл
            # розрізав би кожен рядок посередині.
            rec["split_skipped"] = "згину не видно — вкладка або один аркуш; лишено цілим"
        else:
            rec["fold_x"] = fold
            parts = [("L", (0, 0, fold, h)), ("R", (fold, 0, w, h))]
    for side, box in parts:
        p = im.crop(box).convert("L")
        if p.height > target_h:
            p = p.resize((round(p.width * target_h / p.height), target_h),
                         Image.Resampling.LANCZOS)
        name = f"{stem}_{side}.jpg" if side else f"{stem}.jpg"
        buf = BytesIO()
        p.save(buf, "JPEG", quality=quality, optimize=True)
        atomic_write_bytes(out / name, buf.getvalue())
        rec["pages"][name] = {"side": side or "-", "box": list(box),
                              "w": p.width, "h": p.height}
    return rec
