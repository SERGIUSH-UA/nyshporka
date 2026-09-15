"""📚 Збирач переліку сканів фонду з Wikimedia Commons.

Навіщо він, коли є дзеркала: дзеркало обрізає великі справи в рази (заміряно:
25 МБ проти 771 МБ на Commons), і посилання на нього виглядає як нормальна
копія. Тобто без цього переліку найповніше джерело сканів лишається невидимим,
а замість нього беруть урізане — і дізнаються про це, коли шукають запис на
сторінці, якої в копії немає.

🔴 Два тихі уроки, обидва вже сплачені:

**Підкреслення й пробіл — одна сторінка.** MediaWiki їх ототожнює, а ми ні: без
зведення той самий файл рахувався двічі, і фонд «мав» 276 сканів замість 138.

**Літера пишеться злито з номером.** Без негативного lookahead
«230-1-2640 Дзічковських» дає справу «2640д», якої в описі немає, — а справжня
2640 лишається «без скана».

**Шифру пишуть і словами.** «ЦДІАК фонд 1040, опис 1, справа 48» і
«ЦДІАК Ф. 53, о. 2, спр. 216» не мають префікса «ЦДІАК 1040-», тож обидва
канали, що шукали лише його, їх не бачили. Заміряно 14.09.2026: у ф.1040 так
названо 141 файл із 434 — серед них том актів консисторії на 816 сторінок,
який вважався відсутнім онлайн; на всьому Commons назв «фонд · опис · справа»
775, «ф. · оп. · спр.» — ще 426.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectResult, Plan, Target

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

API = "https://commons.wikimedia.org/w/api.php"

#: Колонки, які читає злиття реєстру.
FIELDS = ("opys", "spr_int", "spr_letter", "no_shifra", "size", "pagecount",
          "url", "file")

#: Скільки назв просимо однією відповіддю.
BATCH = 50
PAGE_LIMIT = 500


def norm_title(name: str) -> str:
    """Назва сторінки MediaWiki: підкреслення — той самий пробіл."""
    return " ".join((name or "").replace("_", " ").split())


def shifra_pattern(archive: str, fond: str) -> re.Pattern[str]:
    """«<архів> <фонд>-<опис>-<справа><літера>» у назві файлу.

    ⚠ Літера мусить іти злито й лише одна: пробіл перед словом — це вже назва
    справи, а не шифра.

    ⚠ Між архівом і фондом заливачі ставлять і пробіл, і дефіс
    («ЦДІАК-972-1-253»): у ф.972 дефісний варіант мали 5 файлів із 10, і всі
    вони лягали в «без шифри», тобто справа з живим сканом на Commons
    виглядала як така, що онлайн її немає.

    🔴 `(?!\\d)` після номера справи — не косметика: без нього регекс на
    злитій назві «ЦДІАК-972-1-261Справа про призначення…» відступав назад по
    цифрах і віддавав ФАНТОМНУ справу 26 замість того, щоб чесно лишити файл
    без шифри. Фантом гірший за пропуск: він виглядає як відкриття нової
    справи фонду.

    ⚠ Між фондом, описом і справою теж буває не лише дефіс: ДАЖО ф.146 заливали
    і «ДАЖО 146-01-0624», і «ДАЖО 146 01 0767», і «ДАЖО 146 -1-2621» — 15 файлів
    зі сканом лягали в «без шифри» (14.09.2026). Тому роздільник — дефіс із
    пробілами довкола або самі пробіли.
    """
    sep = r"(?:\s*[-–]\s*|[ _]+)"
    return re.compile(
        rf"{re.escape(archive)}[ _\-–]+{re.escape(fond)}{sep}(\d+){sep}(\d+)(?!\d)"
        rf"([а-яіїєґa-z]?)(?![а-яіїєґa-z])", re.IGNORECASE)


def worded_shifra_pattern(archive: str, fond: str) -> re.Pattern[str]:
    """Шифра словами: «<архів> фонд N, опис N, справа N» і «Ф. N, о. N, спр. N».

    ⚠ Після номера фонду `(?!\\d)`: без нього «фонд 10400» пішов би у фонд
    1040, тобто чужа справа лягла б у реєстр як своя.

    ⚠ Файл, де названо лише фонд і опис («ЦДІАК фонд 1040 опис 1.pdf»), —
    це скан самого опису, а не справа; він лишається без шифри.
    """
    return re.compile(
        rf"{re.escape(archive)}\W+(?:фонд|ф)\W*{re.escape(fond)}(?!\d)\W*"
        rf"(?:опис|оп|о\.)\W*(\d+)(?!\d)\W*(?:справа|спр)\W*(\d+)(?!\d)"
        rf"([а-яіїєґa-z]?)(?![а-яіїєґa-z])", re.IGNORECASE)


def worded_fond_pattern(archive: str, fond: str) -> re.Pattern[str]:
    """Назва належить фонду, записаному словами («ЦДІАК фонд 1040…», «Ф. 1040»).

    Канали за словесною формою ширші за префікс «<архів> <фонд>-»: префікс
    «ЦДІАК фонд 1040» ловить і фонд 10400. Тому знайдене ними проходить цей
    фільтр, а чуже відсікається, а не лягає в реєстр рядком «без шифри».
    """
    return re.compile(
        rf"{re.escape(archive)}\W+(?:фонд|ф)\W*{re.escape(fond)}(?!\d)",
        re.IGNORECASE)


#: «… .pdf page152 1.jpeg» — сторінка, вирізана з уже залитого PDF, а не том справи.
_PAGE_DERIVATIVE = re.compile(r"\.pdf[ _]+page\d+(?:[ _]+\d+)?\.(?:jpe?g|png|tiff?)$",
                              re.IGNORECASE)


def is_page_derivative(title: str) -> bool:
    """Файл-сторінка, вирізаний із PDF справи.

    🔴 ДАЖО 1-74-99: поруч із PDF на 1344 сторінки лежать 1344 такі JPEG, і
    злиття склало їх як 1345 «томів» — поле `commons_parts` на 834 КБ, яке
    ламало звичайне читання реєстру (`csv` падав на ліміті поля), а число
    файлів фонду завищувалось із ~2290 до 3634 (14.09.2026).
    """
    return bool(_PAGE_DERIVATIVE.search(title or ""))


def parse_shifra(title: str, codes: tuple[str, ...],
                 fond: str) -> tuple[str, str, str] | None:
    """Опис, справа, літера з назви файлу — хоч цифрами, хоч словами.

    ⚠ Опис і номер справи віддаються без провідних нулів: «ДАЖО 146-01-0624» —
    це опис 1, справа 624, як у Вікіджерелах і Качиному Інспекторі, а злиття
    ключ не нормалізує. Без цього справи ДАЖО ф.146 стояли в реєстрі двічі — з
    назвою без скана і зі сканом без назви: 154 через опис «01» і ще 20 через
    номер «00419» (14.09.2026).
    """
    for code in codes:
        for pattern in (shifra_pattern(code, fond), worded_shifra_pattern(code, fond)):
            m = pattern.search(title)
            if m:
                opys, spr = m.group(1), m.group(2)
                return (str(int(opys)) if opys.isdigit() else opys,
                        str(int(spr)), (m.group(3) or "").lower())
    return None


class CommonsCollector:
    """Перелік сканів фонду, що лежать на Commons."""

    id = "commons"
    label = "Wikimedia Commons"
    filename = "commons.tsv"
    source_id = "commons"
    caps = frozenset({"opys", "scans", "online"})

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Any = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher

    def _http(self) -> Any:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.sources.http import Fetcher, app_ua

        # 🔴 Свій User-Agent, а не браузерний: Wikimedia відмовляє клієнтам,
        # які себе не називають, і має рацію — інакше в її логах усі однакові.
        return Fetcher(base="https://commons.wikimedia.org",
                       headers={"User-Agent": app_ua()})

    def _codes(self, repo: str) -> tuple[str, ...]:
        from nyshporka.archives import active

        return active().codes_for(repo, "commons")

    def plan(self, target: Target) -> Plan:
        codes = self._codes(target.repo)
        if not codes:
            return Plan(
                collector=self.id, ready=False,
                needs={"codes.commons": "як цей архів підписують на Commons"},
                why=(f"невідомо, як архів {target.repo} зветься на Commons. "
                     f"Здогад тут шкідливий: запит про архів, якого там немає, "
                     f"дає нуль, а нуль читається як «сканів немає». "
                     f"Додайте `codes.commons` у config/archives.yaml."))
        # На кожне написання: два префіксні обходи й три пошуки плюс батчі
        # метаданих; точне число знати наперед не можна — воно залежить від
        # того, скільки файлів знайдеться, і чесніше цього не вигадувати.
        return Plan(collector=self.id, ready=True, requests=len(codes) * 5,
                    opys=target.opys)

    # ── обхід ────────────────────────────────────────────────────────────────
    def _api(self, http: Any, params: dict[str, str]) -> dict[str, Any]:
        q = {"format": "json", "formatversion": "2", **params}
        url = "/w/api.php?" + "&".join(
            f"{k}={quote(str(v))}" for k, v in q.items())
        r = http.get(url)
        try:
            data: dict[str, Any] = json.loads(getattr(r, "text", "") or "{}")
        except ValueError:
            return {}
        return data

    def _all_images(self, http: Any, prefix: str) -> list[str]:
        """Префіксний обхід: усі файли, чия назва починається з `prefix`."""
        names: list[str] = []
        cont: str | None = None
        while True:
            params = {"action": "query", "list": "allimages",
                      "aiprefix": prefix, "ailimit": str(PAGE_LIMIT)}
            if cont:
                params["aicontinue"] = cont
            data = self._api(http, params)
            names += [str(x.get("name") or "")
                      for x in data.get("query", {}).get("allimages", [])]
            cont = (data.get("continue") or {}).get("aicontinue")
            if not cont:
                return names

    def _search(self, http: Any, phrase: str) -> list[str]:
        """Пошук за назвою, усіма сторінками видачі.

        ⚠ Він ловить те, чого не бачить префікс, — інший регістр і файли, у
        яких перед шифрою щось стоїть. Один канал тут не досить, і це не
        обережність: два канали на живому фонді дають різні множини.

        🔴 Гортається до кінця. Перша сторінка — 500 назв, а фонд, записаний
        словами, на Commons буває більшим; без гортання хвіст видачі мовчки
        зникав би, і справа з живим сканом виглядала б як відсутня.
        """
        names: list[str] = []
        offset = 0
        while True:
            data = self._api(http, {
                "action": "query", "list": "search",
                "srsearch": f'intitle:"{phrase}"', "srnamespace": "6",
                "srlimit": str(PAGE_LIMIT), "sroffset": str(offset)})
            names += [str(x.get("title") or "").removeprefix("File:")
                      for x in data.get("query", {}).get("search", [])]
            nxt = (data.get("continue") or {}).get("sroffset")
            if not nxt or int(nxt) <= offset:
                return names
            offset = int(nxt)

    def _names(self, http: Any, code: str, fond: str) -> list[str]:
        """Усі назви фонду одного написання архіву.

        Канали шифри цифрами («ЦДІАК 1040-») віддають своє без фільтра, як і
        раніше: там уже є файли, названі по-людськи, і вони мають лишитись
        видними. Канали шифри словами ширші, тож їхнє проходить фільтр фонду.
        """
        names = [*self._all_images(http, f"{code} {fond}-"),
                 *self._search(http, f"{code} {fond}-")]
        belongs = worded_fond_pattern(code, fond)
        worded = [*self._all_images(http, f"{code} фонд {fond}"),
                  *self._search(http, f"{code} фонд {fond}"),
                  *self._search(http, f"{code} ф {fond}")]
        return names + [n for n in worded if belongs.search(norm_title(n))]

    def _imageinfo(self, http: Any, names: list[str]) -> dict[str, dict[str, Any]]:
        """Розмір і кількість сторінок — батчами.

        🔴 Саме POST. Півсотні назв кирилицею не влазять у адресу: сервер
        відповідає 414 на URL понад ~8 КБ, і виглядає це як «файлів немає».
        """
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(names), BATCH):
            chunk = names[i:i + BATCH]
            r = http.post("/w/api.php", data={
                "action": "query", "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "titles": "|".join("File:" + n for n in chunk),
                "format": "json", "formatversion": "2"})
            try:
                data = json.loads(getattr(r, "text", "") or "{}")
            except ValueError:
                continue
            for p in data.get("query", {}).get("pages", []):
                title = norm_title(str(p.get("title") or "").removeprefix("File:"))
                ii = (p.get("imageinfo") or [{}])[0]
                if title:
                    out[title] = ii
        return out

    # ── збирання ─────────────────────────────────────────────────────────────
    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        http = self._http()
        codes = self._codes(target.repo)

        names: dict[str, str] = {}          # нормалізована назва → як її пишуть
        for i, code in enumerate(codes):
            if on_progress is not None:
                on_progress(done=i, total=len(codes), unit="написання",
                            note=f"{code} · знайдено {len(names)}")
            for raw in self._names(http, code, target.fond):
                key = norm_title(raw)
                if key:
                    names.setdefault(key, key)

        info = self._imageinfo(http, sorted(names))
        rows: list[dict[str, Any]] = []
        without = 0
        no_meta = 0
        for title in sorted(names):
            ii = info.get(title) or {}
            if not ii:
                no_meta += 1
            row = self._row(title, ii, codes, target.fond)
            if row is None:
                continue
            if row["no_shifra"]:
                without += 1
            rows.append(row)
        if on_progress is not None:
            on_progress(done=len(codes), total=len(codes), unit="написання")

        touched = tuple(sorted({str(r["opys"]) for r in rows if r["opys"]}))
        out = dest / self.filename
        kept = 0
        if not dry_run:
            # 🔴 Рядки без шифри зводяться за НАЗВОЮ ФАЙЛУ, а не за описом: опис
            # у них порожній, і злиття вважало їх «чужим описом», тож кожен
            # перезбір долучав старі до нових, а файл, чию назву тепер
            # розібрано, лишався ще й дублем «без шифри». Але й просто
            # переписати їх не можна: частину колись знайшли ручним запитом
            # («Протоколи Київської ревізійної комісії…» у ф.481), і цей обхід
            # їх не бачить — викинути означало б сховати живий скан.
            have = {r["file"] for r in rows}
            _, old = T.read_tsv(out)
            carried = [r for r in old if not r.get("opys") and r.get("file") not in have]
            kept = T.merge_into(out, FIELDS, [*rows, *carried], touched=(*touched, ""))
            kept += len(carried)

        blind: list[Blind] = []
        if without:
            blind.append(Blind(
                kind="no_shifra", count=without,
                why=("файли, у назві яких шифри немає: у реєстр вони лягли з "
                     "позначкою, а не зникли — інакше скан, названий по-людськи, "
                     "виглядав би як відсутній")))
        if no_meta:
            blind.append(Blind(
                kind="no_imageinfo", count=no_meta,
                why=("файли без метаданих: розмір і кількість сторінок невідомі, "
                     "тож звірити завантажене з обіцяним по них не вийде")))
        return CollectResult(
            collector=self.id, out=out, rows=len(rows), kept=kept,
            opys_seen=touched, opys_collected=touched,
            quality=self._quality(rows), blind=tuple(blind))

    def _row(self, title: str, ii: dict[str, Any], codes: tuple[str, ...],
             fond: str) -> dict[str, Any] | None:
        if is_page_derivative(title):
            return None
        opys, spr, letter = parse_shifra(title, codes, fond) or ("", "", "")
        return {
            "opys": opys, "spr_int": spr, "spr_letter": letter,
            # 🔴 Файл без шифри не викидається. Скани, названі по-людськи, теж
            # існують, і мовчазне зникнення читалось би як «його немає».
            "no_shifra": "" if spr else "1",
            "size": ii.get("size") or "", "pagecount": ii.get("pagecount") or "",
            "url": ii.get("url") or "", "file": title,
        }

    @staticmethod
    def _quality(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "із шифрою": sum(1 for r in rows if r.get("spr_int")),
            "з розміром": sum(1 for r in rows if r.get("size")),
            "зі сторінками": sum(1 for r in rows if r.get("pagecount")),
        }
