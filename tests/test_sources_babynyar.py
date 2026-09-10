"""🕯 Бабин Яр: розбір переліків, адреси кадрів, каталог і завантаження.

Мережі тут немає навмисно: тест розбору, який ходить на живий сайт, червоніє
від профілактики й зеленіє від того, що розмітка ще не змінилась.
"""
from __future__ import annotations

import base64
import csv
import json
from pathlib import Path

import pytest

from nyshporka.sources.babynyar import (
    BabynYarSource,
    _count,
    frame_urls,
    s3_name,
    table_rows,
)
from nyshporka.sources.base import SourceError
from nyshporka.sources.cfclient import challenged

# ── зразки розмітки, зняті з живого майданчика 09.09.2026 ────────────────────

# 🔴 Фонди й описи приходять з API, а не зі сторінки «фонди архіву»: та
# гортається, і перший аркуш неповний (ДАМО: 75 фондів із 97).
# ⚠ Два фонди одного архіву навмисно розрізняються лише префіксом: «R-6453» і
# «6453» — різні фонди, і зведення їх за першим числом підсунуло б чужий опис.
FUNDS_API = r'''{"total": 2, "page_size": 100, "page_number": 1, "page_next": null, "results": [{"id": 207, "number": "R-6453", "name": "Книги РАЦС Хмельницького району", "descriptions": [{"id": 401, "number": "1", "annotation": "Опис №1"}], "archive": {"id": 34, "short_name": "ДАХО"}}, {"id": 999, "number": "6453", "name": "Зовсім інший фонд", "descriptions": [{"id": 402, "number": "1", "annotation": "Опис №1"}], "archive": {"id": 34, "short_name": "ДАХО"}}, {"id": 96, "number": "484", "name": "Колекція метричних книг", "descriptions": [{"id": 218, "number": "1", "annotation": "Опис №1"}], "archive": {"id": 36, "short_name": "ДАМО"}}]}'''

#: Знаменник розбору: скільки справ в описі за словами самого майданчика.
COUNT_API = '{"id": 401, "cases_count": 3}'

CASES_HTML = """
<table><tbody>
<tr><td>1</td><td><a href="/archive/case/26918">Книга реєстрації актів про
розірвання шлюбу за 1931-1932 рр.</a></td><td>1931 - 1932</td><td>529</td></tr>
<tr><td>2</td><td><a href="/archive/case/26919">Книга про народження</a></td>
<td>16.01.1932 - 16.06.1932</td><td>0</td></tr>
<tr><td>вільний номер</td><td><a href="/archive/case/26920">-</a></td>
<td></td><td></td></tr>
</tbody></table>
"""


def _media(path: str) -> str:
    blob = base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")
    return f"https://media.babynyar.org/SIGN/size:2000:2000:0/{blob}.jpg"


FRAME_1 = _media("s3://archive-files/DAKhmO/funds/R-6453/1/3/image00001_oeO4F2Z.jpg")
FRAME_2 = _media("s3://archive-files/DAKhmO/funds/R-6453/1/3/image00002_TqlQnWf.jpg")

CASE_HTML = f"""
<div class="photo-item" data-full="{FRAME_1}"><img src="thumb1.jpg"></div>
<div class="photo-item" data-full="{FRAME_2}"><img src="thumb2.jpg"></div>
"""


#: Другий опис — із ВЛАСНИМИ справами: `case_id` на майданчику унікальні, і
#: обхід тепер на цьому стоїть (повтор пропускає вже відомі справи).
CASES_HTML_402 = CASES_HTML.replace("/archive/case/269", "/archive/case/279")


def _crawl_answers(count_402: int = 3) -> dict[str, str]:
    """Відповіді для обходу ДАХмО: два описи й скільки справ обіцяє кожен."""
    return {"/api/archive/funds/": FUNDS_API,
            "/api/archive/descriptions/401/": COUNT_API,
            "/api/archive/descriptions/402/":
                f'{{"id": 402, "cases_count": {count_402}}}',
            "/archive/desc/401": CASES_HTML,
            "/archive/desc/402": CASES_HTML_402}


class _R:
    """Відповідь двійника — рівно те, що читає `Fetcher._send`."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=httpx.Request("GET", "x"),
                response=httpx.Response(self.status_code))


class _Cf:
    """Двійник клієнта за Cloudflare: відповідає за хвостом адреси.

    `fail` — скільки перших запитів відповісти 503, щоб перевірити відступ.
    """

    def __init__(self, answers: dict[str, str], *, fail: int = 0) -> None:
        self.answers = answers
        self.seen: list[str] = []
        self.fail = fail

    def get(self, url: str) -> _R:
        self.seen.append(url)
        if self.fail > 0:
            self.fail -= 1
            return _R("", 503)
        for tail, body in self.answers.items():
            if url.endswith(tail) or tail in url:
                return _R(body)
        raise AssertionError(f"двійник не знає адреси: {url}")


# ── розбір ───────────────────────────────────────────────────────────────────

def test_table_rows_reads_all_four_columns() -> None:
    rows = table_rows(CASES_HTML, "case")
    assert [r[0] for r in rows] == ["26918", "26919", "26920"]
    assert rows[0][1][0] == "1"
    assert rows[0][1][3] == "529"


def test_frame_urls_take_data_full_not_thumbnails() -> None:
    """🔴 Мініатюра підписана окремо: «підняти» її правкою `size:` не можна."""
    got = frame_urls(CASE_HTML)
    assert got == [FRAME_1, FRAME_2]
    assert all("size:2000:2000:0" in u for u in got)


def test_s3_name_recovers_the_original_frame_name() -> None:
    """Без цього завантажений кадр нічим звірити з оригіналом на сайті."""
    assert s3_name(FRAME_1) == "image00001_oeO4F2Z.jpg"


def test_s3_name_survives_a_url_that_is_not_imgproxy() -> None:
    assert s3_name("https://example.org/plain.jpg") == ""


def test_challenge_page_is_recognised() -> None:
    assert challenged("<html><title>Just a moment...</title>")
    assert not challenged("<html><table><tr><td>1</td></tr></table>")


# ── дерево ───────────────────────────────────────────────────────────────────

def test_browse_walks_archive_to_case() -> None:
    cf = _Cf({"/api/archive/funds/": FUNDS_API, "/archive/desc/401": CASES_HTML})
    src = BabynYarSource(client=cf)
    assert [n.ref for n in src.browse("arch:34")] == ["fond:207", "fond:999"]
    assert [n.ref for n in src.browse("fond:207")] == ["desc:401"]
    cases = src.browse("desc:401")
    assert cases[0].ref == "case:26918"
    assert cases[0].frames == 529
    # ⚠ Нуль копій лишається нулем, а не «невідомо»: справа в описі є, сканів немає.
    assert cases[1].frames == 0


def test_browse_of_one_archive_leaves_out_the_others() -> None:
    """⚠ `?archive=` сервер приймає й ІГНОРУЄ — відсів мусить бути в нас."""
    src = BabynYarSource(client=_Cf({"/api/archive/funds/": FUNDS_API}))
    assert [n.ref for n in src.browse("arch:36")] == ["fond:96"]


def test_funds_page_of_the_site_is_not_used_for_lookup() -> None:
    """🔴 Сторінка «фонди архіву» ГОРТАЄТЬСЯ, і перший аркуш неповний.

    Заміряно на ДАМО: 75 фондів із 97, і серед відрізаних лежала ф.484 —
    найбільша колекція метричних книг майданчика. Двійник не знає цієї адреси
    навмисно: якщо код по неї піде, тест упаде, а не мовчки недорахує фондів.
    """
    cf = _Cf({"/api/archive/funds/": FUNDS_API})
    BabynYarSource(client=cf).browse("arch:36")
    # ⚠ Саме префікс, а не підрядок: адреса API «/api/archive/funds/» містить
    # шлях сторінки цілком, і наївна перевірка червоніла б завжди.
    assert not any(u.startswith("https://babynyar.org/archive/funds/")
                   for u in cf.seen)


def test_catalog_pages_go_through_the_polite_fetcher(monkeypatch) -> None:
    """🔴 Сторінки каталогу йдуть крізь `Fetcher`: відступ на 5xx, а не падіння.

    Доти вони йшли просто в клієнт — без паузи й без повторів, тож обхід ~900
    сторінок бив сайт на повній швидкості й валився на першому тимчасовому 502.
    """
    import nyshporka.sources.http as H

    monkeypatch.setattr(H.time, "sleep", lambda _s: None)
    cf = _Cf({"/archive/desc/401": CASES_HTML}, fail=2)
    cases = BabynYarSource(client=cf).browse("desc:401")
    assert [c.ref for c in cases][:1] == ["case:26918"]
    assert len(cf.seen) == 3, "два 503 мусять повторитись, а не впасти"


def test_a_real_4xx_is_a_refusal_not_a_crash() -> None:
    """404 — відповідь, а не збій: джерело каже про неї словами, а не трасою."""
    class _NotFound(_Cf):
        def get(self, url: str) -> _R:
            self.seen.append(url)
            return _R("", 404)

    with pytest.raises(SourceError) as exc:
        BabynYarSource(client=_NotFound({})).browse("desc:401")
    assert "404" in str(exc.value)


def test_the_fund_list_is_fetched_once_not_per_call() -> None:
    """🔴 Перелік фондів — 7 сторінок API, і кожен зайвий прохід наближає відсічку.

    Заміряно 09.09.2026: перегляд архіву плюс збирання фонду брали перелік
    двічі, і Cloudflare показав виклик саме на другому проході.
    """
    cf = _Cf({"/api/archive/funds/": FUNDS_API})
    src = BabynYarSource(client=cf)
    src.browse("arch:34")
    src.browse("arch:36")
    src.funds("34")
    assert sum("/api/archive/funds/" in u for u in cf.seen) == 1


def test_the_fund_list_expires_so_a_daemon_sees_new_funds(monkeypatch) -> None:
    """⚠ Вічний кеш у живому демоні ховав би фонди, викладені після старту."""
    cf = _Cf({"/api/archive/funds/": FUNDS_API})
    src = BabynYarSource(client=cf)
    src.funds()
    assert src._funds_cache is not None
    src._funds_cache = (src._funds_cache[0] - src.FUNDS_TTL_SEC - 1,
                        src._funds_cache[1])
    src.funds()
    assert sum("/api/archive/funds/" in u for u in cf.seen) == 2


class _ScriptedCf:
    """`CfClient` без мережі й без годинника: відповідає за списком."""

    def __new__(cls, bodies: list[str]):
        from nyshporka.sources.cfclient import CfClient, Response

        class _C(CfClient):
            def __post_init__(self) -> None:
                self.via = "curl"
                self.slept: list[float] = []
                self.asked = 0

            def _once(self, url: str) -> Response:
                self.asked += 1
                return Response(200, bodies.pop(0).encode(), url)

        c = _C()
        c._sleep = c.slept.append  # type: ignore[method-assign]
        return c


CHALLENGE = "<html><title>Just a moment...</title></html>"


def test_a_passing_challenge_is_waited_out_not_fatal() -> None:
    """🔴 Виклик за темпом МИНАЄ — заміряно: 3 з 3 проходили через 20 с.

    Перша версія вважала його фатальним і писала «чекати марно», тож обхід
    ~900 сторінок падав кожні 12-24 запити.
    """
    c = _ScriptedCf([CHALLENGE, CHALLENGE, "<table>справжня сторінка</table>"])
    r = c.get("https://babynyar.org/archive/desc/1")
    assert "справжня" in r.text
    assert c.asked == 3
    assert c.slept == [c.CHALLENGE_PAUSE_SEC] * 2


def test_a_challenge_that_does_not_pass_is_named_not_swallowed() -> None:
    """Виклик, що не минув після всіх пауз, — відмова словами, а не порожня сторінка."""
    from nyshporka.sources.cfclient import ShieldError

    c = _ScriptedCf([CHALLENGE] * 10)
    with pytest.raises(ShieldError) as exc:
        c.get("https://babynyar.org/archive/desc/1")
    assert c.asked == c.CHALLENGE_RETRIES + 1
    assert "минає за ~20 с" in str(exc.value)
    # ⚠ Порада про інший шлях — лише тому, хто ним ще не ходить.
    assert "cfshield" in str(exc.value)


def test_crawl_writes_the_catalog_and_speaks_the_cli_contract(tmp_path: Path) -> None:
    """🔴 `nysh crawl` друкує `stats['inventories']` — ключ, спільний з ARCHIUM.

    Перша версія повертала `descriptions`, і команда впала б на `KeyError`
    наприкінці обходу, тобто після десятків хвилин роботи. Приймач — рівно ті
    ключі, які читає CLI, а не «щось повернулось».
    """
    cf = _Cf(_crawl_answers())
    src = BabynYarSource(tmp_path, client=cf)
    stats = src.crawl(("34",))
    assert {"fonds", "skipped", "inventories", "cases"} <= set(stats)
    assert (stats["fonds"], stats["inventories"], stats["cases"]) == (2, 2, 6)
    # Той самий заголовок у двох описах — дві справи, кожна зі своїм id.
    assert {h.ref for h in src.search("розірвання")} == {"case:26918", "case:27918"}
    # ⚠ Чужий архів у каталог не лягає: обхід просили лише про ДАХмО.
    assert not any("/archive/desc/218" in u for u in cf.seen)


def test_crawl_resumes_instead_of_starting_over(tmp_path: Path) -> None:
    """Перерваний обхід уже коштував запитів — пройдені описи не перечитуються."""
    cf = _Cf(_crawl_answers())
    src = BabynYarSource(tmp_path, client=cf)
    src.crawl(("34",))
    asked = len(cf.seen)
    again = src.crawl(("34",))
    assert (again["skipped"], again["inventories"]) == (2, 0)
    assert len(cf.seen) == asked, "другий прохід не мав іти в мережу взагалі"


def test_crawl_refuses_an_archive_id_the_site_does_not_have(tmp_path: Path) -> None:
    """⚠ Порожній обхід читався б як «архів порожній» — тут відмова з причиною."""
    src = BabynYarSource(tmp_path, client=_Cf({"/api/archive/funds/": FUNDS_API}))
    with pytest.raises(SourceError) as exc:
        src.crawl(("999",))
    assert "id" in str(exc.value)


def test_scan_counts_keep_their_thousands() -> None:
    """🔴 «1 234» — тисяча двісті тридцять чотири кадри, а не один.

    Лічильник брався першим числом, як номер справи, і роздільник тисяч —
    зокрема нерозривний пробіл — робив справу на тисячу кадрів одноаркушною.
    """
    assert _count("1 234") == 1234
    assert _count("1\u00a0234") == 1234
    assert _count("0") == 0
    assert _count("") is None
    html = CASES_HTML.replace("<td>529</td>", "<td>1 234</td>")
    cases = BabynYarSource(client=_Cf({"/archive/desc/401": html})).browse("desc:401")
    assert cases[0].frames == 1234


def test_a_short_opys_is_not_marked_done_and_is_named(tmp_path: Path) -> None:
    """🔴 Опис, що віддав менше справ, ніж обіцяє сайт, не вважається пройденим.

    Інакше обрізаний перелік ліг би в каталог як повний, і пошук відповідав би
    нулем там, де справа є, — просто не прочиталась.
    """
    src = BabynYarSource(tmp_path, client=_Cf(_crawl_answers(count_402=5)))
    stats = src.crawl(("34",))
    assert stats["short"] == 1
    state = json.loads((tmp_path / BabynYarSource.STATE_REL)
                       .read_text(encoding="utf-8"))
    assert state["descs_done"] == ["401"]
    assert state["descs_short"] == {"402": [3, 5]}
    # Пошук каже про неповноту разом зі знахідкою, а не мовчить.
    assert "неповний" in src.search("розірвання")[0].note
    # Повтор перечитує лише неповний опис — і не задвоює вже взятих справ.
    again = src.crawl(("34",))
    assert (again["skipped"], again["inventories"], again["cases"]) == (1, 1, 0)
    ids = [r["case_id"] for r in src._catalog_rows()]
    assert len(ids) == len(set(ids)) == 6


def test_an_interrupted_write_leaves_no_duplicates_and_no_torn_row(
        tmp_path: Path) -> None:
    """🔴 Обрив між дописом рядків і записом стану давав дублі каталогу.

    Тут змодельовано найгірше: справа вже лежить у каталозі, стану немає, а
    останній рядок обірвано посередині. Повтор мусить і не задвоїти справу, і
    не приклеїти новий рядок до обірваного.
    """
    cat = tmp_path / BabynYarSource.CATALOG_REL
    cat.parent.mkdir(parents=True)
    head = "\t".join(BabynYarSource.CATALOG_FIELDS)
    row = "\t".join(["34", "ДАХО", "DAHMO", "207", "R-6453", "Книги РАЦС",
                     "401", "1", "26918", "1", "1931 - 1932", "529", "Книга"])
    cat.write_text(f"{head}\n{row}\n34\tДАХО\tDAH", encoding="utf-8")
    stats = BabynYarSource(tmp_path, client=_Cf(_crawl_answers())).crawl(("34",))
    assert stats["cases"] == 5, "справу 26918 вдруге не пишемо"
    with cat.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(rows) == 6
    assert all(None not in r and None not in r.values() for r in rows)
    assert len({r["case_id"] for r in rows}) == 6


def test_crawl_state_is_written_atomically(tmp_path: Path, monkeypatch) -> None:
    """🔴 Стан обходу — через `.part` і заміну, а не прямим записом.

    Напівзаписаний стан читався як порожній, і наступний обхід перечитував
    усе — з дублями всього каталогу.
    """
    import nyshporka.sources.babynyar as B

    wrote: list[Path] = []
    real = B.atomic_write_bytes

    def spy(path: Path, data: bytes) -> None:
        wrote.append(Path(path))
        real(path, data)

    monkeypatch.setattr(B, "atomic_write_bytes", spy)
    BabynYarSource(tmp_path, client=_Cf(_crawl_answers())).crawl(("34",))
    assert tmp_path / BabynYarSource.STATE_REL in wrote


def test_proxy_credentials_never_reach_the_command_line(monkeypatch) -> None:
    """🔴 Командний рядок процесу видно всім користувачам машини (`ps`).

    Проксі з логіном і паролем ішов у curl аргументом — пароль лежав відкрито
    весь час кожного запиту. Тепер він іде конфігом через stdin.
    """
    import types

    import nyshporka.sources.cfclient as C

    monkeypatch.setattr(C, "have_curl_cffi", lambda: False)
    monkeypatch.setattr(C, "have_curl", lambda: True)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], **kw: object) -> object:
        calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=0, stdout=b"<table>ok</table>\n200",
                                     stderr=b"")

    monkeypatch.setattr(C.subprocess, "run", fake_run)
    c = C.CfClient(proxy="socks5://user:s3cr3t@10.0.0.1:1080")
    try:
        r = c.get("https://babynyar.org/archive/desc/1")
    finally:
        c.close()
    assert r.status_code == 200 and "ok" in r.text
    cmd, kw = calls[-1]
    assert not any("s3cr3t" in a for a in cmd)
    assert "--config" in cmd
    assert b"s3cr3t" in kw["input"]  # type: ignore[operator]

    calls.clear()
    c = C.CfClient()
    try:
        c.get("https://babynyar.org/archive/desc/1")
    finally:
        c.close()
    cmd, kw = calls[-1]
    assert "--config" not in cmd and "input" not in kw


def test_curl_config_cannot_be_hijacked_by_the_value() -> None:
    """⚠ Лапка чи перевод рядка в значенні не дописують у конфіг чужої опції."""
    from nyshporka.sources.cfclient import curl_config

    cfg = curl_config({"proxy": 'http://h"\nurl = "http://evil'}).decode()
    assert cfg.count("\n") == 1, "перевод рядка лише в кінці — одна опція"
    assert '\\"' in cfg and "\\n" in cfg


def test_browse_refuses_an_address_it_does_not_understand() -> None:
    with pytest.raises(SourceError):
        BabynYarSource(client=_Cf({})).browse("плівка:7")


# ── каталог ──────────────────────────────────────────────────────────────────

def _catalog(ws: Path) -> None:
    p = ws / BabynYarSource.CATALOG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    head = "\t".join(BabynYarSource.CATALOG_FIELDS)
    row = "\t".join(["34", "ДАХО", "DAHMO", "207", "R-6453",
                     "Книги РАЦС Хмельницького району", "401", "1", "26918",
                     "1", "1931 - 1932", "529",
                     "Книга реєстрації актів про розірвання шлюбу"])
    p.write_text(f"{head}\n{row}\n", encoding="utf-8")


def test_search_without_catalog_refuses_instead_of_answering_zero(tmp_path: Path) -> None:
    """🔴 Нуль тут означав би «в архіві такого немає» — а питати нема чим."""
    src = BabynYarSource(tmp_path, client=_Cf({}))
    with pytest.raises(SourceError) as exc:
        src.search("розірвання")
    assert "nysh crawl babynyar" in str(exc.value)


def test_search_finds_by_case_title(tmp_path: Path) -> None:
    _catalog(tmp_path)
    got = BabynYarSource(tmp_path, client=_Cf({})).search("розірвання")
    assert [h.ref for h in got] == ["case:26918"]
    assert got[0].repo == "DAHMO"
    assert got[0].frames == 529
    assert got[0].acquirable


def test_search_also_looks_at_the_fund_name(tmp_path: Path) -> None:
    """🔴 Тут топонім стоїть у назві ФОНДУ, а не в заголовку справи."""
    _catalog(tmp_path)
    got = BabynYarSource(tmp_path, client=_Cf({})).search("Хмельницького району")
    assert [h.ref for h in got] == ["case:26918"]


def test_find_case_matches_shifra_field_by_field(tmp_path: Path) -> None:
    _catalog(tmp_path)
    src = BabynYarSource(tmp_path, client=_Cf({}))
    assert [h.ref for h in src.find_case("R-6453", "1", "1")] == ["case:26918"]
    assert src.find_case("R-6453", "1", "2") == []
    # ⚠ Чужий архів із тим самим номером фонду не має відповідати.
    assert src.find_case("R-6453", "1", "1", repo="DAKO") == []


def test_find_case_prefers_the_exact_fond_but_never_answers_a_false_zero(
        tmp_path: Path) -> None:
    """🔴 «R-6453» і «6453» — два фонди одного архіву.

    Точний збіг фонду витісняє сусіда за числом. Але шифру часто набирають без
    «Р-», і коли точного фонду в каталозі немає, нуль був би хибним: відповідає
    фонд за числом, а шифра з префіксом видна в знахідці.
    """
    _catalog(tmp_path)
    src = BabynYarSource(tmp_path, client=_Cf({}))
    assert [h.ref for h in src.find_case("6453", "1", "1")] == ["case:26918"]

    both = tmp_path / "both"
    _catalog(both)
    p = both / BabynYarSource.CATALOG_REL
    row = "\t".join(["34", "ДАХО", "DAHMO", "208", "6453", "Дореволюційний фонд",
                     "402", "1", "30001", "1", "1850", "10", "Метрична книга"])
    p.write_text(p.read_text(encoding="utf-8") + row + "\n", encoding="utf-8")
    src = BabynYarSource(both, client=_Cf({}))
    assert [h.ref for h in src.find_case("6453", "1", "1")] == ["case:30001"]
    assert [h.ref for h in src.find_case("Р-6453", "1", "1")] == ["case:26918"]


# ── справа ───────────────────────────────────────────────────────────────────

def test_manifest_counts_frames_and_says_the_resolution_ceiling(tmp_path: Path) -> None:
    _catalog(tmp_path)
    src = BabynYarSource(tmp_path, client=_Cf({"/archive/case/26918": CASE_HTML}))
    m = src.manifest("case:26918")
    assert m.frames == 2
    assert m.meta["max_side_px"] == 2000
    assert "2000 px" in str(m.meta["resolution"])
    assert m.meta["shifra"]["fond"] == "R-6453"


def test_manifest_on_a_case_without_scans_names_the_real_reason() -> None:
    """🔴 Код відповіді той самий (200), тож розрізняє їх лише перелік кадрів."""
    src = BabynYarSource(client=_Cf({"/archive/case/26919": "<html>порожньо</html>"}))
    with pytest.raises(SourceError) as exc:
        src.manifest("case:26919")
    assert "НЕоцифрована" in str(exc.value)


class _Media:
    """Двійник медіа-хоста: він під Cloudflare не стоїть, ходить httpx."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def client(self):
        from contextlib import nullcontext

        return nullcontext(self)

    def get(self, url: str, client: object = None):
        self.asked.append(url)
        return type("R", (), {"content": b"\xff\xd8jpeg"})()


def test_fetch_names_frames_by_page_and_by_archive_filename(tmp_path: Path) -> None:
    media = _Media()
    src = BabynYarSource(client=_Cf({"/archive/case/26918": CASE_HTML}), media=media)
    res = src.fetch("case:26918", tmp_path / "case")
    assert res.frames == 2
    assert sorted(p.name for p in (tmp_path / "case").iterdir()) == [
        "0001_image00001_oeO4F2Z.jpg", "0002_image00002_TqlQnWf.jpg"]


def test_fetch_honours_a_frame_range(tmp_path: Path) -> None:
    media = _Media()
    src = BabynYarSource(client=_Cf({"/archive/case/26918": CASE_HTML}), media=media)
    res = src.fetch("case:26918", tmp_path / "case", frames=(2, 2))
    assert res.frames == 1
    assert [p.name for p in (tmp_path / "case").iterdir()] == [
        "0002_image00002_TqlQnWf.jpg"]


def test_fetch_skips_what_is_already_on_disk(tmp_path: Path) -> None:
    dest = tmp_path / "case"
    dest.mkdir()
    (dest / "0001_image00001_oeO4F2Z.jpg").write_bytes(b"x")
    src = BabynYarSource(client=_Cf({"/archive/case/26918": CASE_HTML}),
                         media=_Media())
    res = src.fetch("case:26918", dest)
    assert (res.frames, res.skipped) == (1, 1)
