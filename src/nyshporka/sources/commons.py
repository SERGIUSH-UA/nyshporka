"""📚 Wikimedia Commons як джерело справ.

🔴 Навіщо, коли є дзеркала архівів. Дзеркало обрізає великі справи в рази —
заміряно: 25 МБ проти 771 МБ на Commons, — і посилання на нього виглядає як
нормальна копія. Людина завантажує «справу», шукає в ній запис, не знаходить і
робить висновок про документ, а не про копію.

Пошуку тут немає навмисно. Commons знає назви файлів, а не заголовки справ, і
його нуль читався б як «в архіві такого немає». Що існує у фонді — відповідає
збирач реєстру (`nysh registry collect commons`), і саме звідти беруться адреси.

Адресація (`ref`): `file:<точна назва файлу на Commons>`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import quote

from nyshporka.core.casekey import LETTERS, OPYS_TOKEN
from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Manifest,
    Node,
    SourceAbout,
    SourceError,
    SourceScope,
)
from nyshporka.sources.http import Fetcher, HttpError, app_ua

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nyshporka.sources.base import ProgressFn

BASE = "https://commons.wikimedia.org"


def _sha1_of(path: Path) -> str:
    import hashlib

    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


_LET = LETTERS
#: Між фондом, описом і справою — дефіс (з пробілами довкола чи без) або самі
#: пробіли: ДАЖО ф.146 заливали і «146-01-0624», і «146 01 0767», і «146 -1-2621».
_SEP = r"(?:\s*[-–]\s*|[ _]+)"
_REPO_WORD = r"(?P<repo>[A-Za-zА-Яа-яІЇЄҐіїєґ']+)"
#: Опис буває літерним: `2д`, `1d`, `5доп` — та сама цеглина, що скрізь у пакеті.
_OPYS = rf"(?P<opys>{OPYS_TOKEN})"
#: 🔴 Літера справи — одна й злито; за нею ні літери, ні цифри. «…-261Справа
#: про…» не дає ні фантомної справи 26, ні «261С»: такий файл лишається без
#: шифри (фантом гірший за пропуск — він виглядає як відкриття справи).
_SPR = rf"(?P<spr>\d+)(?P<lit>[{_LET}]?)(?![{_LET}\d])"
_FOND = r"(?P<fond>(?:[А-ЯЄІЇҐA-Z]{1,2}-)?\d+)"

#: «ДАХмО 227-2д-905 …», «ДАХмО 227-1-6563а …», «ЦДІАК-972-1-253. …», «ДАЖО 146 01 0767».
_COMPACT = re.compile(
    rf"{_REPO_WORD}[\s_.\-–]*(?P<fmark>ф(?:онд)?\.?\s*)?{_FOND}(?!\d)(?P<s1>{_SEP}){_OPYS}"
    rf"(?P<s2>{_SEP}){_SPR}", re.IGNORECASE)
#: «ДАХмО Ф.227, о.2, с.6026», «Ф. 227 О. 5доп С. 291», «Фонд 227, опись 6д, дело 34».
#: Опис фонду без справи («фонд 227 опис 1 том 1») сюди не влучає: після опису
#: мусить стояти позначка справи.
_WORDED = re.compile(
    rf"{_REPO_WORD}\W+(?:фонд|ф)\W*{_FOND}(?!\d)\W*(?:опис[ьи]?|оп|о)\W*{_OPYS}"
    rf"(?![\d])\W*(?:справа|спр|дело|дел|д|с)\W*{_SPR}", re.IGNORECASE)
_YEAR = re.compile(r"(?:17|18|19|20)\d\d")


class TitleShifra(NamedTuple):
    """Шифра, знайдена в назві файла: слово архіву як написане, номери — показові."""

    repo_word: str
    fond: str
    opys: str
    spr: str


def title_of_ref(ref: str) -> str:
    """Назва файла з адреси `file:<назва>` (чи повного посилання); інакше порожньо."""
    from urllib.parse import unquote

    text = unquote((ref or "").strip())
    for prefix in ("https://commons.wikimedia.org/wiki/",
                   "http://commons.wikimedia.org/wiki/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    kind, _, ident = text.partition(":")
    return ident.strip() if kind.strip().lower() in ("file", "файл") else ""


def _plain(num: str) -> str:
    """Без провідних нулів: «01» → «1», «6д» лишається."""
    m = re.match(r"(\d+)(.*)$", num)
    return f"{int(m.group(1))}{m.group(2)}" if m else num


def title_shifras(title: str, *, years_ok: bool = False) -> Iterator[TitleShifra]:
    """🔴 ЄДИНИЙ розбір шифри в назві файла Commons — для паспорта `nysh get` і
    для збирача реєстру опису (`fonds.collect.commons.parse_shifra`).

    Доти їх було два, і вони розходились: збирач реєстру не бачив жодної з
    форм `227-2д-905`, `227-1d-356`, `Ф. 227 О. 5доп С. 291`, а паспорт — форми
    через пробіли `ДАЖО 146 01 0767`. Справа, яку `nysh get` уже називав, у
    реєстрі опису лишалась «без шифри», і `cases take` її не знаходив.

    Віддає всі кандидати в порядку появи; архів і фонд відбирає викликач.
    Номери — без провідних нулів, опис і літера — у показовому письмі (`2д`,
    `6563а`), як і всюди в паспортах.

    `years_ok=False`: голе чотирицифрове 1700–2099 без «ф.» фондом не
    береться («ДАХмО 2021-1-12» — рік). Збирач, що знає свій фонд, ставить
    `True`: у нього фонд 2081 — це фонд 2081.
    """
    from nyshporka.core.casekey import show_letter, show_part

    text = title or ""
    for pattern in (_COMPACT, _WORDED):
        for m in pattern.finditer(text):
            if pattern is _COMPACT:
                if (not years_ok and not m.group("fmark")
                        and _YEAR.fullmatch(m.group("fond"))):
                    continue
                # Через самі пробіли («ДАЖО 146 1 3099») шифру нічим не відрізнити
                # від ряду років: «ДАХмО 315 1858 1859» — не опис 1858.
                if (not m.group("s1").strip(" _") and not m.group("s2").strip(" _")
                        and _YEAR.fullmatch(m.group("opys"))):
                    continue
            yield TitleShifra(
                repo_word=m.group("repo"), fond=m.group("fond"),
                opys=_plain(show_part(m.group("opys"))),
                spr=_plain(m.group("spr")) + show_letter(m.group("lit")))


def shifra_of_title(title: str) -> dict[str, str]:
    """Шифра справи з назви файла Commons: `archive/fond/inv/spr`, або `{}`.

    Архів — той самий код, що скрізь у пакеті (`archives.pack`: ДАХмО → DAHMO).
    Не розібралось (архів невідомий, це опис фонду, а не справа) — порожньо:
    вигадана шифра приписує теці чужу справу.
    """
    from nyshporka.archives.pack import active

    pk = active()
    for got in title_shifras(title):
        code = pk.resolve_code(got.repo_word)
        if code:
            return {"archive": pk.canon_repo(code), "fond": got.fond,
                    "inv": got.opys, "spr": got.spr}
    return {}


def shifra_line_of_title(title: str) -> str:
    """Та сама шифра одним рядком для паспорта: «ДАХмО 227-2д-905»; або порожньо.

    Рядок — у тій формі, яку бібліотека читає з паспорта (`library._sidecar_case`).
    """
    from nyshporka.archives.pack import active

    got = shifra_of_title(title)
    if not got:
        return ""
    label = active().repo_label(got["archive"]) or got["archive"]
    return f"{label} {got['fond']}-{got['inv']}-{got['spr']}"


def shifra_of_ref(source: str, ref: str) -> dict[str, str]:
    """Поля шифри для паспорта завантаження; не Commons чи не розібрано — `{}`."""
    if source != "commons":
        return {}
    return shifra_of_title(title_of_ref(ref))


class CommonsSource:
    """Завантаження справи з Commons. Каталог веде збирач реєстру."""

    id = "commons"
    label = "Wikimedia Commons"
    caps = frozenset({"manifest", "fetch"})
    about = SourceAbout(
        answers="повні томи й описи фондів, викладені волонтерами",
        gives="файл справи чи опису: кількість сторінок і завантаження",
        not_gives="пошуку — Commons знає назви файлів, а не заголовки справ",
        where_class="Commons / Вікіджерела",
        scope=SourceScope(note="лише фонди, які хтось виклав; адреси дає збирач "
                               "реєстру (`nysh registry collect commons`)"),
        match_on=(), match_how=None,
        zero_means="не шукає; що існує у фонді — реєстр опису",
        pitfalls=("файл буває витягом однієї парафії, а не справою",
                  "дзеркала обрізають великі справи: 25 МБ проти 771 МБ на Commons"))

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self.http = fetcher or Fetcher(base=BASE, headers={"User-Agent": app_ua()})

    def _name(self, ref: str) -> str:
        # 🔴 Регістр і мова простору імен — як люди їх приносять: `File:` у
        # полі link_commons Вікіджерел, `Файл:` в українських вікі, повна
        # адреса сторінки з браузера. Вимога рівно `file:` відмовляла саме
        # тому, хто скопіював назву звідти, де вона стоїть.
        from urllib.parse import unquote

        tekst = unquote(ref.strip())
        for prefix in ("https://commons.wikimedia.org/wiki/",
                       "http://commons.wikimedia.org/wiki/"):
            if tekst.lower().startswith(prefix):
                tekst = tekst[len(prefix):]
        kind, _, ident = tekst.partition(":")
        # `_` не міняємо на пробіл: з назви складається ім'я файлу на диску,
        # і завантажене раніше мусить упізнаватись. Commons приймає обидва.
        ident = ident.strip()
        if kind.strip().lower() not in ("file", "файл") or not ident:
            raise SourceError(
                f"незрозуміла адреса: {ref!r} — тут очікується "
                f"`file:<назва файлу на Commons>`")
        return ident

    def _info(self, name: str) -> dict[str, Any]:
        url = ("/w/api.php?action=query&prop=imageinfo&iiprop=url|size|mime|sha1"
               f"&titles={quote('File:' + name)}&format=json&formatversion=2")
        try:
            data = json.loads(self.http.get(url).text)
        except (HttpError, ValueError) as exc:
            raise SourceError(f"Commons не відповів про «{name}»: {exc}") from exc
        pages = data.get("query", {}).get("pages") or []
        if not pages or pages[0].get("missing"):
            raise SourceError(f"на Commons немає файлу «{name}»")
        ii: dict[str, Any] = (pages[0].get("imageinfo") or [{}])[0]
        if not ii.get("url"):
            raise SourceError(f"«{name}» є, але адреси завантаження не має")
        return ii

    def manifest(self, ref: str) -> Manifest:
        """Скільки це важить і скільки має сторінок — до завантаження.

        Справа архіву тут — сотні мегабайтів; питання «що я зараз качаю»
        мусить мати відповідь до того, як почалось, а не після.
        """
        name = self._name(ref)
        ii = self._info(name)
        # 🔴 `pagecount` є лише в багатосторінкових (PDF/DjVu). Для JPG і TIFF
        # його немає — і це «не знаю», а не «нуль сторінок». Поки обидва
        # стани зводились до нуля, `fetch` на тому самому полі рахував уже
        # одиницю: маніфест обіцяв нуль, результат звітував один.
        raw = ii.get("pagecount")
        pages = int(raw) if raw else None
        return Manifest(source=self.id, ref=ref, title=name, frames=pages,
                        bytes_estimate=int(ii.get("size") or 0),
                        meta={"url": str(ii.get("url") or ""),
                              "mime": str(ii.get("mime") or "")})

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        """Завантажити файл справи цілком.

        ⚠ `frames` тут не діє: справа приходить одним файлом (як правило PDF),
        і «взяти кадри 12-80» означало б порізати документ — це робота
        читання, а не завантаження. Мовчки проігнорувати межі не можна:
        людина отримала б повний файл, вважаючи, що взяла частину.
        """
        name = self._name(ref)
        if frames is not None:
            raise SourceError(
                "Commons віддає справу одним файлом, тож окремі кадри звідси "
                "не беруться — качається все, а сторінки вибирає читання")
        ii = self._info(name)
        url, want = str(ii["url"]), int(ii.get("size") or 0)
        from nyshporka.utils.fsname import UnsafeName, safe_filename

        try:
            out = dest / safe_filename(name.replace("/", "_"))
        except UnsafeName as exc:
            raise SourceError(f"назва файла на Commons не годиться для диска: {exc}") from exc
        res = FetchResult(dest=dest)
        if out.is_file() and out.stat().st_size == want and want:
            # 🔴 Одиниці — сторінки, як і в маніфесті: приймач повноти рахує
            # `frames + skipped`. Доти тут стояло `skipped = 1` (файл) поруч із
            # `frames = pagecount`, і повторне завантаження цілого файла давало
            # «узято сторінок + 1» — тобто `partial` і код виходу 1.
            res.skipped = int(ii.get("pagecount") or 1)
            res.frames = 0
            res.bytes = want
            return res

        def _tick(done: int) -> None:
            if on_progress is not None:
                on_progress(done=done, total=want or None, unit="байт", note=name)

        try:
            # 🔴 Розмір, названий Commons, — стеля качання (аудит 29.09.2026).
            # Більше за нього файл однаково не ляже (звірка нижче), тож
            # дочитувати зайве не було сенсу — а без стелі сервер міг
            # заповнити диск раніше, ніж звірка встигла б відмовити.
            got = self.http.download(url, out, on_chunk=_tick, max_bytes=want)
        except (HttpError, OSError) as exc:
            res.errors.append(f"{name}: {exc}")
            return res

        # 🔴 Звірка з обіцяним розміром, а не «файл є». Обірвана закачка під
        # правильним іменем ляже в облік як повна справа, і виявиться це тоді,
        # коли в ній шукатимуть запис, якого немає в недовантаженій частині.
        if want and got != want:
            out.unlink(missing_ok=True)
            res.errors.append(
                f"{name}: отримано {got} байт замість {want} — файл неповний, "
                f"тож у теку справи він не ліг")
            return res
        # 🔴 Розмір сходиться і в склеєного з хибних шматків файла: тепер
        # завантаження дочитується через `Range`, і шматок від іншої версії
        # файла на Commons дав би правильну довжину й биті сторінки. Commons
        # каже свій SHA-1 — з ним і звіряємо.
        want_sha1 = str(ii.get("sha1") or "").lower()
        if want_sha1:
            got_sha1 = _sha1_of(out)
            if got_sha1 != want_sha1:
                out.unlink(missing_ok=True)
                res.errors.append(
                    f"{name}: SHA-1 {got_sha1} не збігається з тим, що каже Commons "
                    f"({want_sha1}) — файл битий, у теку справи він не ліг")
                return res
        res.frames = int(ii.get("pagecount") or 1)
        res.bytes = got
        return res

    # ── те, чого це джерело не вміє ──────────────────────────────────────────
    # Протокол вимагає всі чотири методи, а `caps` каже, які з них справжні.
    # Відповідь «не вмію» мусить бути доступною й тому, хто спитав попри `caps`.

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """🔴 Не порожній список, а відмова.

        Commons знає назви файлів, а не заголовки справ, тож нуль звідси
        читався б як «в архіві такого немає» — найдорожча відповідь у
        генеалогії, бо вона закриває напрям пошуку.
        """
        raise SourceError(
            "Commons шукає по назвах файлів, а не по заголовках справ. "
            "Що існує у фонді, каже "
            "`nysh registry collect commons --repo <архів> --fond <номер>`.")

    def browse(self, ref: str | None = None) -> list[Node]:
        raise SourceError(
            "у Commons немає дерева фондів — сховище пласке, а перелік справ "
            "фонду складає `nysh registry collect commons`.")
