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
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

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
    from nyshporka.sources.base import ProgressFn

BASE = "https://commons.wikimedia.org"


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
        url = ("/w/api.php?action=query&prop=imageinfo&iiprop=url|size|mime"
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
