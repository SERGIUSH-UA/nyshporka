"""📜 Збирач переліку справ фонду з Вікіджерел — сторінки опису проєкту «Архів:».

Волонтери проєкту «Архів:» транскрибують таблиці описів фондів на Вікіджерела
(`Архів:<архів>/<фонд>/<опис>`), часто з колонкою «Посилання на FamilySearch» —
номером групи зображень (DGS) кожної справи. Тобто це повний перелік опису з
роками й аркушами там, де інші джерела бачать лише свою частину.

🔴 **Навіщо окремий збирач.** Зведений покажчик прив'язує до парафії лише частину
щорічної серії книг консисторії, а роки його «справ» бувають не роками томів.
Заміряно 06.10.2026: серія метрик повіту — щорічні томи
1795–1862, поділені за абеткою сіл; покажчик дав 16 томів із ~60, і «онлайн
немає» стояло там, де потрібний том лежав на FamilySearch. Повний перелік із
плівками був на сторінці опису у Вікіджерелах — і брався руками.

Код архіву — `codes.wikisource`, далі `codes.commons` («Архів:» на Вікіджерелах
і на Commons — один волонтерський проєкт з однаковими кодами), далі підпис
архіву в паку (`label`: ДАЖО, ДАХмО, ЦДІАК — саме так проєкт їх і пише), далі
його псевдоніми («ІР НБУВ» при підписі «ІРНБУВ»). Це не
мовчазний здогад: план перевіряє, що під кодом є сторінки, і без них називає
перебрані коди — тоді архів зветься там інакше, і треба `codes.wikisource`.

⚠ Аркуші в описі — аркуші справи, не сторінки PDF і не кадри плівки.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Blind, CollectResult, Plan, Target

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

HOST = "https://uk.wikisource.org"
#: Простір назв «Архів:» на українських Вікіджерелах.
NS_ARCHIVE = 116
#: Назв у пачці запиту текстів — стеля MediaWiki для звичайного клієнта.
BATCH = 50
PAGE_LIMIT = 500
DELAY = 0.35
#: Секунд на запит із відповіддю — для кошторису. Замір 06.10.2026: ДАЖО ф.1
#: оп.78 — перелік сторінок фонду й 8 пачок текстів, 9 запитів за ~15 с.
SEC_PER_REQ = 1.7

#: Колонки, які читає злиття реєстру (`fonds/merge/sources.py`, ранг 60).
FIELDS = ("opys", "spr_raw", "spr_int", "spr_letter", "title", "year_from",
          "year_to", "folios", "church", "places", "uezd", "commons_file",
          "fs_film", "src", "spr_to", "note")


# ── розбір вікітексту ────────────────────────────────────────────────────────
#: Назва колонки шапки (нормалізована) → поле.
_COL_ALIAS = {
    "назва": "title", "заголовок": "title",
    "назва (заголовок одиниці зберігання)": "title",
    "церква": "church", "храм": "church",
    "нас. пункти": "places", "нас.пункти": "places", "населені пункти": "places",
    "населений пункт": "places", "село": "places", "місцевість": "places",
    "повіт": "uezd", "уїзд": "uezd",
    "дати": "years", "роки": "years", "рік": "years", "крайні дати": "years",
    "губернія/воєводство": "gubernia", "губернія": "gubernia",
    "арк.": "folios", "аркушів": "folios", "аркуші": "folios", "к-сть арк.": "folios",
    "кількість аркушів": "folios",
    "примітки": "note", "примітка": "note",
    # 🔴 Колонка FS — уся відповідь на «чи можна подивитись справу вже зараз»: у
    # ЦДІАК ф.224 вона несе DGS для 99% справ опису. Без аліаса реєстр радив
    # замовлення в архіві для справ, які лежать онлайн.
    "посилання на familysearch": "fs", "familysearch": "fs", "fs": "fs",
    "плівка fs": "fs", "dgs": "fs",
}

#: Підпис першої колонки, за яким таблицю визнаємо таблицею справ.
_NUM_HEADS = {"№", "n", "номер справи", "№ справи", "№ спр.", "№ спр"}

_SPR_LINK_RE = re.compile(r"^\[\[/([^/\]|]+)/?(?:\|[^\]]*)?\]\]$")
_COMMONS_RE = re.compile(r"\[\[\s*c:\s*[Ff]ile\s*:\s*([^\]|]+)")
_FS_DGS_RE = re.compile(r"imageGroupNumbers=([0-9_]+[A-Za-z0-9:_-]*)")
#: Посилання на плівку FamilySearch іншими адресами: `/search/film/<DGS>`,
#: `/film/<DGS>`, `/dgs/<DGS>`.
_FS_PATH_RE = re.compile(r"/(?:search/film|film|dgs)/(\d+)")
_TAG_RE = re.compile(r"<[^>]*>")


def _nbsp(s: str) -> str:
    """Нерозривні пробіли → звичайні.

    🔴 Трапляються і в шапці («Крайні\\xa0дати»), і в комірках, і обидва рази
    мовчки: назва колонки не збігається з аліасом — і зникає вся колонка.
    """
    return s.replace("\u00a0", " ").replace("\u202f", " ")


def _cell(raw: str) -> str:
    """Комірка без атрибутів: `style="…" | текст` → `текст`.

    ⚠ Атрибут відрізається лише тоді, коли одинарна `|` стоїть поза `[[…]]` і
    `{{…}}`: у посиланні `[[/2а/|2а]]` і в шаблоні `{{FS|dgs=…|item=2}}`
    вертикальна риска — частина комірки.
    """
    s = _nbsp(raw).strip()
    depth = 0
    for i, ch in enumerate(s):
        if s.startswith(("[[", "{{"), i):
            depth += 1
        elif s.startswith(("]]", "}}"), i) and depth:
            depth -= 1
        elif ch == "|" and depth == 0 and "=" in s[:i]:
            return s[i + 1:].strip()
    return s


def iter_table_rows(txt: str) -> Iterator[tuple[bool, list[str]]]:
    """Рядки кожної wikitable сторінки: (шапка?, комірки).

    🔴 Розбір за РОЗМІТКОЮ таблиці, а не за рядком тексту: однорядковий запис
    (`|[[/2а/]]||Назва||Роки||Аркушів`) і багаторядковий (кожна комірка своїм
    рядком) дають ті самі комірки. Регекс по рядку на другому форматі давав 0
    справ без жодної помилки.

    ⚠ Лише всередині `{| … |}`: шаблон сторінки (`| назва = …`) теж починається
    з `|` і поза таблицею став би «рядком справи».
    """
    depth = 0
    cells: list[str] = []
    header = False

    def flush() -> Iterator[tuple[bool, list[str]]]:
        nonlocal cells, header
        if cells:
            yield header, cells
        cells, header = [], False

    for raw in txt.splitlines():
        line = raw.strip()
        if line.startswith("{|"):
            depth += 1
            yield from flush()
            continue
        if not depth:
            continue
        if line.startswith("|}"):
            yield from flush()
            depth -= 1
            continue
        if line.startswith("|-"):
            yield from flush()
            continue
        if line.startswith("|+"):
            continue
        if line.startswith("!"):
            header = True
            cells += [_cell(c) for c in re.split(r"!!|\|\|", line[1:])]
        elif line.startswith("|"):
            cells += [_cell(c) for c in line[1:].split("||")]
        elif cells:
            cells[-1] = f"{cells[-1]} {_nbsp(line)}".strip()
    yield from flush()


def _head_name(cell: str) -> str:
    """Назва колонки без розмітки, виносок і хвоста після розриву рядка.

    🔴 Шапка буває з поясненням через `<br/>`: «Посилання на FamilySearch<br/>для
    відсутніх справ». Точний аліас таку колонку не впізнавав, і вся колонка
    плівок зникала мовчки — саме вона й була відповіддю «справа онлайн».
    """
    c = cell.lower()
    c = re.split(r"<br\s*/?>", c)[0]
    c = _TAG_RE.sub("", c)
    c = re.sub(r"\[\[[^\]]*\|([^\]]*)\]\]", r"\1", c)
    c = re.sub(r"[\[\]'{}]|class=.*|style=.*", "", c)
    return " ".join(c.split())


def parse_header(cells: list[str]) -> dict[int, str] | None:
    """Комірки шапки → {позиція комірки після номера: поле}, або None."""
    if not cells:
        return None
    if _head_name(cells[0]) not in _NUM_HEADS:
        return None
    out: dict[int, str] = {}
    for i, c in enumerate(cells[1:]):            # cells[0] — сам «№»
        name = _head_name(c)
        key = _COL_ALIAS.get(name)
        if key is None:
            # «Примітки (стан збереження)» — та сама колонка з уточненням.
            key = next((v for k, v in _COL_ALIAS.items()
                        if len(k) >= 4 and name.startswith(k + " ")), None)
        if key and key not in out.values():
            out[i] = key
    return out or None


def parse_years(rik: str) -> tuple[str, str]:
    """Рядок дат → (найраніший, найпізніший).

    🔴 min/max, а не перший/останній: комірка дат буває несортованим переліком
    («1860-80, 1851, 1846»), і краї рядка давали `year_from > year_to` — справа
    випадала з фільтра за роками в обидва боки.
    """
    nums = [int(n) for n in re.findall(r"1[6-9]\d\d", rik or "")]
    if not nums:
        return "", ""
    return str(min(nums)), str(max(nums))


def _folios(cell: str) -> str:
    """Перше ціле число комірки. «126+3» — 126 аркушів і 3 вкладні, а не 1263."""
    m = re.search(r"\d+", cell or "")
    return m.group(0) if m else ""


def _spr_cell(cell: str) -> str:
    m = _SPR_LINK_RE.match(cell.strip())
    return (m.group(1) if m else cell).strip()


def _dgs(cell: str) -> str:
    """Номер плівки FamilySearch (DGS) з комірки чи поля картки, або порожньо.

    🔴 Лише з адреси, що несе саме DGS, або з комірки, яка вся є числом.
    Довільне довге число з посилання — не плівка: в ark-адресі образу
    (`…/ark:/61903/3:1:…?i=12&cat=1938521`) це номер запису каталогу, і
    справа отримала б чужу плівку, яка до того ж перекривала б таблицю.
    """
    m = _FS_DGS_RE.search(cell or "") or _FS_PATH_RE.search(cell or "")
    if m:
        return m.group(1)
    bare = re.fullmatch(r"[\s\[\]]*([0-9]{6,})[\s\[\]]*", cell or "")
    return bare.group(1) if bare else ""


def parse_opys_page(txt: str) -> list[dict[str, str]]:
    """Таблиця справ зі сторінки опису → рядки.

    🔴 Колонки — за ШАПКОЮ, не за позицією. Позиційна схема (`Назва | Роки |
    Аркушів`) на фонді з іншою розкладкою не падає, а бреше: у ЦДІАК ф.224
    2944 справи приїхали з однаковим заголовком «Метрична книга» і роками з
    комірки церкви.

    Село, церква й повіт вливаються в заголовок (фільтри шукають у ньому) і
    ще віддаються окремими полями.
    """
    rows: list[dict[str, str]] = []
    cols: dict[int, str] | None = None
    for is_head, cells in iter_table_rows(txt):
        if is_head:
            head = parse_header(cells)
            if head:
                cols = head
            continue
        spr_raw = _spr_cell(cells[0])
        num = T.case_number(spr_raw)
        if not num:
            continue
        rest = cells[1:]
        got: dict[str, str] = {}
        if cols:
            for i, key in cols.items():
                if i < len(rest):
                    got[key] = rest[i]
        else:                                    # таблиця без шапки — давня схема
            got = {"title": rest[0] if rest else "",
                   "years": rest[1] if len(rest) > 1 else "",
                   "folios": rest[2] if len(rest) > 2 else ""}
        parts = [got.get("title", "")]
        if got.get("church"):
            parts.append(got["church"])
        if got.get("places"):
            parts.append(got["places"])
        if got.get("uezd"):
            parts.append(f"{got['uezd']} пов.")
        yf, yt = parse_years(got.get("years", ""))
        rows.append({
            "spr_raw": spr_raw, "spr_int": str(num[0]), "spr_letter": num[1],
            "spr_to": T.group_end(spr_raw),
            "title": " · ".join(p for p in (x.strip() for x in parts) if p),
            "year_from": yf, "year_to": yt,
            "folios": _folios(got.get("folios", "")),
            "church": got.get("church", ""), "places": got.get("places", ""),
            "uezd": got.get("uezd", ""), "note": got.get("note", ""),
            "fs_film": _dgs(got.get("fs", "")),
        })
    return rows


def field(txt: str, name: str) -> str:
    """Значення поля шаблону: `| назва = …`."""
    m = re.search(rf"\|\s*{name}\s*=\s*([^\n|}}]*)", txt)
    return m.group(1).strip() if m else ""


def parse_case_page(txt: str) -> dict[str, str] | None:
    """Картка справи `{{Архіви/справа}}` → поля; не картка — None.

    ⚠ Частину карток набрано шаблоном опису, а не справи — беремо обидва.
    """
    if "Архіви/справа" not in txt and "Архіви/опис" not in txt:
        return None
    yf, yt = parse_years(field(txt, "рік"))
    cm = _COMMONS_RE.search(txt) or _COMMONS_RE.search(field(txt, "link_commons"))
    commons = cm.group(1).strip() if cm else ""
    if not commons and field(txt, "link_commons"):
        commons = re.sub(r"^[Ff]ile\s*:\s*", "", field(txt, "link_commons"))
    return {"title": field(txt, "назва"), "year_from": yf, "year_to": yt,
            "commons_file": commons, "fs_film": _dgs(field(txt, "link_FS"))}


def merge_case(row: dict[str, str], card: dict[str, str]) -> None:
    """Картка уточнює рядок таблиці.

    🔴 Порожнє з картки не затирає непорожнє з таблиці: картка часто не має
    `link_FS`, і так ЦДІАК ф.1040 втрачав DGS у 312 із 314 справ опису.
    """
    row["src"] = "both"
    row["commons_file"] = card["commons_file"] or row.get("commons_file", "")
    row["fs_film"] = card["fs_film"] or row.get("fs_film", "")
    if card["title"] and not row.get("title"):
        row["title"] = card["title"]
    if card["year_from"] and not row.get("year_from"):
        row["year_from"], row["year_to"] = card["year_from"], card["year_to"]


# ── збирач ───────────────────────────────────────────────────────────────────
class WikisourceError(RuntimeError):
    """Вікіджерела відповіли не відповіддю: збій, помилка API, неповна пачка.

    🔴 Саме виняток, а не порожньо: порожня відповідь читалась як «сторінок
    немає» чи «опис не транскрибовано», а злиття реєстру викидало старі рядки
    опису, якого цей запуск нібито торкнувся.
    """


class WikisourceCollector:
    """Перелік справ фонду зі сторінок опису «Архів:» на Вікіджерелах."""

    id = "wikisource"
    label = "Вікіджерела (Архів:)"
    filename = "wikisource.tsv"
    #: Самі Вікіджерела копій не віддають — сторінка опису лише називає їх.
    source_id = ""
    caps = frozenset({"opys", "titles", "years", "folios", "online"})

    def __init__(self, workspace: Path | None = None, *, fetcher: Any = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher

    def _http(self) -> Any:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.sources.http import Fetcher, app_ua

        # Свій User-Agent: Wikimedia відмовляє клієнтам, що себе не називають.
        return Fetcher(base=HOST, delay=DELAY, headers={"User-Agent": app_ua()})

    def _codes(self, repo: str) -> tuple[str, ...]:
        from nyshporka.archives import active

        pack = active()
        r = pack.repositories.get(str(repo or "").upper())
        label = (str(getattr(r, "label", "") or ""),) if r else ()
        # Псевдоніми — останніми: підпис паку буває без пробілу («ІРНБУВ»), а
        # проєкт пише «ІР НБУВ», і саме так його знають псевдоніми архіву.
        aliases = tuple(str(a) for a in (getattr(r, "aliases", ()) or ())) if r else ()
        out: list[str] = []
        for c in (*pack.codes_for(repo, "wikisource"), *pack.codes_for(repo, "commons"),
                  *label, *aliases):
            if c and c not in out:
                out.append(c)
        return tuple(out)

    def _api(self, http: Any, params: dict[str, str]) -> dict[str, Any]:
        q = {"format": "json", "formatversion": "2", **params}
        url = "/w/api.php?" + "&".join(f"{k}={quote(str(v))}" for k, v in q.items())
        return self._json(http.get(url))

    @staticmethod
    def _json(r: Any) -> dict[str, Any]:
        """Тіло відповіді API як JSON; збій чи `error` — `WikisourceError`."""
        status = int(getattr(r, "status_code", 200) or 200)
        text = str(getattr(r, "text", "") or "")
        try:
            data = json.loads(text)
        except ValueError:
            raise WikisourceError(
                f"Вікіджерела відповіли не JSON (HTTP {status}): "
                f"{' '.join(text.split())[:120]}") from None
        if not isinstance(data, dict):
            raise WikisourceError(f"Вікіджерела відповіли не об'єктом (HTTP {status})")
        err = data.get("error")
        if err:
            e = err if isinstance(err, dict) else {"info": str(err)}
            raise WikisourceError(f"помилка API Вікіджерел: {e.get('code', '')} "
                                  f"{e.get('info', '')}".strip())
        return data

    def _titles(self, http: Any, code: str, fond: str) -> list[str]:
        """Усі сторінки фонду в просторі «Архів:».

        🔴 Префікс — з кінцевою `/`: без неї фонд 23 тягнув би й сторінки
        фондів 230–239.
        """
        out: list[str] = []
        cont: str | None = None
        while True:
            params = {"action": "query", "list": "allpages",
                      "apnamespace": str(NS_ARCHIVE), "apprefix": f"{code}/{fond}/",
                      "aplimit": str(PAGE_LIMIT)}
            if cont:
                params["apcontinue"] = cont
            data = self._api(http, params)
            out += [str(p.get("title") or "")
                    for p in data.get("query", {}).get("allpages", [])]
            cont = (data.get("continue") or {}).get("apcontinue")
            if not cont:
                return out

    @staticmethod
    def classify(titles: list[str], code: str, fond: str
                 ) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
        """Назви → ({опис: сторінка опису}, [(опис, номер, сторінка справи)])."""
        base = rf"^[^:]+:{re.escape(code)}/{re.escape(fond)}/"
        opys_re = re.compile(base + r"([^/]+)$")
        case_re = re.compile(base + r"([^/]+)/([^/]+)$")
        opysy: dict[str, str] = {}
        cases: list[tuple[str, str, str]] = []
        for t in titles:
            t = t.replace("_", " ")
            if (m := opys_re.match(t)):
                opysy[m.group(1)] = t
            elif (m := case_re.match(t)):
                cases.append((m.group(1), m.group(2), t))
        return opysy, cases

    def _texts(self, http: Any, titles: list[str],
               on_progress: ProgressFn | None = None) -> dict[str, str]:
        """Вікітекст сторінок — пачками.

        🔴 Саме POST: півсотні кириличних назв не влазять у адресу (414 на URL
        понад ~8 КБ), і це виглядало б як «сторінок немає».

        🔴 Кожна запитана назва мусить повернутись — текстом або позначкою
        «сторінки немає». Інакше `WikisourceError`: опис без тексту лягав би в
        «не транскрибовано», а злиття стирало б його рядки з реєстру.
        """
        out: dict[str, str] = {}
        total = math.ceil(len(titles) / BATCH)
        for n, i in enumerate(range(0, len(titles), BATCH)):
            if on_progress is not None:
                on_progress(done=n, total=total, unit="пачка",
                            note=f"сторінок {len(out)} із {len(titles)}")
            out.update(self._batch(http, titles[i:i + BATCH]))
        if on_progress is not None:
            on_progress(done=total, total=total, unit="пачка")
        return out

    def _batch(self, http: Any, titles: list[str]) -> dict[str, str]:
        """Одна пачка назв — з продовженнями (`continue`), доки API їх дає."""
        base = {"action": "query", "prop": "revisions", "rvprop": "content",
                "rvslots": "main", "titles": "|".join(titles),
                "format": "json", "formatversion": "2"}
        out: dict[str, str] = {}
        seen: set[str] = set()
        alias: dict[str, str] = {}
        cont: dict[str, str] = {}
        for _ in range(len(titles) + 2):
            data = self._json(http.post("/w/api.php", data={**base, **cont}))
            q = data.get("query") or {}
            for nm in q.get("normalized") or []:
                alias[str(nm.get("from") or "")] = str(nm.get("to") or "")
            for pg in q.get("pages") or []:
                title = str(pg.get("title") or "")
                revs = pg.get("revisions") or []
                if revs:
                    main = (revs[0].get("slots") or {}).get("main") or {}
                    out[title] = str(main.get("content") or "")
                    seen.add(title)
                elif pg.get("missing") or pg.get("invalid"):
                    seen.add(title)
            more = data.get("continue")
            if not isinstance(more, dict) or not more:
                break
            cont = {str(k): str(v) for k, v in more.items()}
        lost = [t for t in titles if alias.get(t, t) not in seen]
        if lost:
            raise WikisourceError(
                f"Вікіджерела не віддали {len(lost)} із {len(titles)} сторінок "
                f"пачки ({', '.join(lost[:3])}…) — опис не зібрано, щоб не "
                f"видати неповний перелік за повний")
        return out

    def _scope(self, http: Any, target: Target
               ) -> tuple[str, dict[str, str], list[tuple[str, str, str]]]:
        """Код, під яким фонд знайшовся, і його сторінки в межах описів цілі."""
        for code in self._codes(target.repo):
            opysy, cases = self.classify(self._titles(http, code, target.fond),
                                         code, target.fond)
            if opysy or cases:
                if target.opys:
                    want = set(target.opys)
                    opysy = {o: t for o, t in opysy.items() if o in want}
                    cases = [c for c in cases if c[0] in want]
                return code, opysy, cases
        return "", {}, []

    def plan(self, target: Target) -> Plan:
        if not self._codes(target.repo):
            return Plan(
                collector=self.id, ready=False,
                needs={"codes.commons": "як цей архів підписаний у проєкті «Архів:»"},
                why=(f"невідомо, як архів {target.repo} зветься у Вікіджерелах і на "
                     f"Commons. Здогад дав би запит про сторінки, яких немає, а нуль "
                     f"читався б як «опису немає»."))
        try:
            code, opysy, cases = self._scope(self._http(), target)
        except (OSError, RuntimeError) as exc:
            # `HttpError` і `WikisourceError` — обидва RuntimeError. Збій
            # мережі — «не готові», а не виняток, що валить `registry build`.
            return Plan(collector=self.id, ready=False,
                        why=f"Вікіджерела не відповіли: {exc}")
        if not code:
            tried = ", ".join(self._codes(target.repo))
            return Plan(collector=self.id, ready=False,
                        needs={"codes.wikisource": "як архів підписаний у «Архів:»"},
                        why=(f"у Вікіджерелах немає сторінок «Архів:<код>/{target.fond}/…» "
                             f"під кодами {tried}. Або опис фонду там не транскрибовано, "
                             f"або архів зветься інакше — тоді `codes.wikisource` у "
                             f"config/archives.yaml"))
        found = tuple(sorted({*opysy, *(c[0] for c in cases)}))
        absent = self._absent(target, found)
        if target.opys and not found:
            return Plan(collector=self.id, ready=False,
                        why=(f"описів {', '.join(absent)} ф.{target.fond} у Вікіджерелах "
                             f"під кодом {code} немає — інші описи цього фонду там "
                             f"є. Нуль тут означав би «справ немає», а це не так"))
        n = 1 + math.ceil(len(opysy) / BATCH) + math.ceil(len(cases) / BATCH)
        return Plan(collector=self.id, ready=True, opys=found, requests=n,
                    eta_sec=n * SEC_PER_REQ,
                    why=(f"описів {', '.join(absent)} у Вікіджерелах немає"
                         if absent else ""))

    @staticmethod
    def _absent(target: Target, found: tuple[str, ...]) -> tuple[str, ...]:
        """Запитані описи, яких серед сторінок фонду немає."""
        return tuple(o for o in (target.opys or ()) if o not in found)

    def collect(self, target: Target, *, dest: Path,
                on_progress: ProgressFn | None = None,
                refresh: bool = False, dry_run: bool = False) -> CollectResult:
        http = self._http()
        code, opysy, cases = self._scope(http, target)
        if not code:
            raise WikisourceError(
                f"сторінок фонду {target.fond} у Вікіджерелах не знайдено — див. "
                f"`nysh registry plan`")
        texts = self._texts(http, [*opysy.values(), *(c[2] for c in cases)], on_progress)

        reg: dict[tuple[str, str, str], dict[str, str]] = {}
        empty: list[str] = []
        for opys, title in sorted(opysy.items()):
            got = parse_opys_page(texts.get(title, ""))
            if not got:
                empty.append(opys)
            for r in got:
                reg[(opys, r["spr_int"], r["spr_letter"])] = {
                    "opys": opys, **r, "commons_file": "", "src": "opys_page"}
        not_cards = 0
        for opys, spr_raw, title in cases:
            card = parse_case_page(texts.get(title, ""))
            num = T.case_number(spr_raw)
            if card is None or num is None:
                not_cards += 1
                continue
            key = (opys, str(num[0]), num[1])
            if key in reg:
                merge_case(reg[key], card)
            else:
                reg[key] = {"opys": opys, "spr_raw": spr_raw, "spr_int": str(num[0]),
                            "spr_letter": num[1], "folios": "", "src": "case_page",
                            **card}
        # 🔴 «Вільний номер» і «Справа вибула» стоять у таблиці опису рядками
        # нарівні зі справами; пущені в реєстр, вони стають фантомами в черзі, за
        # якою замовляють документи. Те саме правило, що в збирачі покажчика.
        from nyshporka.fonds.collect.duck import is_void

        rows = [r for r in reg.values() if not is_void(r.get("title", ""))]
        voids = [r for r in reg.values() if is_void(r.get("title", ""))]
        wanted = tuple(sorted({*opysy, *(c[0] for c in cases)}))
        out = dest / self.filename
        void_path = dest / "wikisource_void.tsv"
        # 🔴 Сторінка опису без розібраної таблиці — не «справ немає»: таблицю
        # перенесли, переверстали чи ще не дописали. Опис, який уже зібрано
        # раніше, тоді лишається як був — інакше повторне збирання стирало
        # перелік, а `no_table` поруч казало, що нуль нічого не означає.
        held = set(empty) & {str(r.get("opys") or "") for r in T.read_tsv(out)[1]}
        if held:
            rows = [r for r in rows if r.get("opys") not in held]
            voids = [r for r in voids if r.get("opys") not in held]
        touched = tuple(o for o in wanted if o not in held)
        kept = 0
        extra: tuple[Path, ...] = ()
        if not dry_run:
            kept = T.merge_into(out, FIELDS, rows, touched=touched)
            if voids:
                T.merge_into(void_path, FIELDS, voids, touched=touched)
                extra = (void_path,)

        blind: list[Blind] = []
        if voids:
            blind.append(Blind(
                kind="void", count=len(voids), where=void_path,
                why=("позиції «вільний номер» і «справа вибула» — не справи; у "
                     "реєстрі вони стали б фантомами в черзі замовлень")))
        if empty:
            blind.append(Blind(
                kind="no_table", count=len(empty),
                why=(f"сторінки описів без таблиці справ ({', '.join(empty[:5])}): "
                     f"опис ще не транскрибовано — нуль тут не означає «справ немає»"
                     + (f"; раніше зібраний перелік опису {', '.join(sorted(held))} "
                        f"лишено як був" if held else ""))))
        if not_cards:
            blind.append(Blind(
                kind="not_a_card", count=not_cards,
                why="підсторінки справ без шаблону картки або з нерозбірним номером"))
        absent = self._absent(target, wanted)
        if absent:
            blind.append(Blind(
                kind="opys_absent", count=len(absent),
                why=(f"описів {', '.join(absent[:5])} у Вікіджерелах немає — цей "
                     f"збирач про них нічого не каже, нуль тут не «справ немає»")))
        non_numeric = [o for o in wanted if not o.isdigit()]
        if non_numeric:
            blind.append(Blind(
                kind="non_numeric_opys", count=len(non_numeric),
                why=(f"нечислові описи ({', '.join(non_numeric[:5])}) — звірити з "
                     f"описом фонду")))
        return CollectResult(
            collector=self.id, out=out, extra=extra, rows=len(rows), kept=kept,
            opys_seen=wanted, opys_collected=touched,
            quality=self._quality(rows), blind=tuple(blind),
            notes=(f"код архіву у Вікіджерелах: {code}",) if code else ())

    @staticmethod
    def _quality(rows: list[dict[str, str]]) -> dict[str, int]:
        return {
            "із заголовком": sum(1 for r in rows if r.get("title")),
            "з роками": sum(1 for r in rows if r.get("year_from")),
            "з плівкою FamilySearch": sum(1 for r in rows if r.get("fs_film")),
            "з файлом Commons": sum(1 for r in rows if r.get("commons_file")),
        }
