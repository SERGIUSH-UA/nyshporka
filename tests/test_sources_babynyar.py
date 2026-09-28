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


@pytest.fixture(autouse=True)
def _bez_vshytoho_indeksu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двійники описують сайт самі — вшитий індекс фондів їх не доповнює."""
    import nyshporka.sources.babynyar as B

    monkeypatch.setattr(B, "known_funds", lambda: ())

# ── зразки розмітки, зняті з живого майданчика 09.09.2026 ────────────────────

# 🔴 26.09.2026 майданчик прибрав JSON-API: архіви, фонди й описи тепер
# розбираються зі сторінок. Розмітка нижче — з живих `/archive/`,
# `/archive/<id>` і `/archive/fund/<id>` того дня.
# ⚠ Два фонди одного архіву навмисно розрізняються лише префіксом: «R-6453» і
# «6453» — різні фонди, і зведення їх за першим числом підсунуло б чужий опис.
ARCHIVES_HTML = """
<div class="content">
 <div class="archive-card"> <a href="/archive/34"> Державний архів Хмельницької області </a> </div>
 <div class="archive-card"> <a href="/archive/36"> Державний архів Миколаївської області </a> </div>
</div>
"""


def _fond_row(fid: int, number: str, name: str, dates: str, n: int) -> str:
    return (f'<tr> <td class="archive-col-fit">{number}</td> <td class="archive-col-grow"> '
            f'<a href="/archive/fund/{fid}"> {name} </a> </td> '
            f'<td class="archive-col-grow"> {dates} </td> <td class="archive-col-fit">{n}</td> </tr>')


def _desc_row(did: int, number: str, cases: int) -> str:
    return (f'<tr> <td class="archive-col-fit">{number}</td> <td class="archive-col-grow"> '
            f'<a href="/archive/desc/{did}"> Опис №{number} </a> </td> '
            f'<td class="archive-col-fit"> 1921 - 1940 </td> '
            f'<td class="archive-col-fit">{cases}</td> </tr>')


def _table(rows: str) -> str:
    return f"<table><thead><tr><th>№</th></tr></thead><tbody>{rows}</tbody></table>"


ARCH_34_HTML = _table(_fond_row(207, "R-6453", "Книги РАЦС Хмельницького району",
                                "1921 - 1940", 1)
                      + _fond_row(999, "6453", "Зовсім інший фонд", "", 1))
ARCH_36_HTML = _table(_fond_row(96, "484", "Колекція метричних книг", "1780 - 1920", 1))


def _fund_html(did: int, cases: int) -> str:
    return _table(_desc_row(did, "1", cases))


#: Відповіді дерева без справ: архіви, фонди й описи з числом справ.
TREE = {"/archive/fund/207": _fund_html(401, 3),
        "/archive/fund/999": _fund_html(402, 3),
        "/archive/fund/96": _fund_html(218, 3),
        "/archive/34": ARCH_34_HTML,
        "/archive/36": ARCH_36_HTML}

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
    """Відповіді для обходу ДАХмО: два описи й скільки справ обіцяє кожен.

    ⚠ `/archive/` — останнім: двійник шукає підрядок, а цей шлях є в кожній
    адресі майданчика.
    """
    return {**TREE,
            "/archive/fund/999": _fund_html(402, count_402),
            "/archive/desc/401": CASES_HTML,
            "/archive/desc/402": CASES_HTML_402,
            "/archive/": ARCHIVES_HTML}


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


def test_s3_name_refuses_a_name_that_leaves_the_case_folder() -> None:
    r"""🔴 Шлях s3 приходить із HTML сайту й стає іменем файла кадру.

    `rpartition("/")` не зрізає `\`, тож без гарда `..\..\x` на Windows
    записав би тіло відповіді за межі теки справи (аудит 29.09.2026).
    """
    import base64

    for evil in (r"s3://b/f/..\..\..\raw\x.jpg", "s3://b/f/C:x.jpg",
                 "s3://b/f/con.jpg"):
        blob = base64.urlsafe_b64encode(evil.encode()).decode().rstrip("=")
        assert s3_name(f"https://img.example/sig/size:1/{blob}.jpg") == "", evil


def test_s3_name_survives_a_url_that_is_not_imgproxy() -> None:
    assert s3_name("https://example.org/plain.jpg") == ""


def test_challenge_page_is_recognised() -> None:
    assert challenged("<html><title>Just a moment...</title>")
    assert not challenged("<html><table><tr><td>1</td></tr></table>")


# ── дерево ───────────────────────────────────────────────────────────────────

def test_browse_walks_archive_to_case() -> None:
    cf = _Cf({**TREE, "/archive/desc/401": CASES_HTML})
    src = BabynYarSource(client=cf)
    assert [n.ref for n in src.browse("arch:34")] == ["fond:207", "fond:999"]
    assert [n.ref for n in src.browse("fond:207")] == ["desc:401"]
    cases = src.browse("desc:401")
    assert cases[0].ref == "case:26918"
    assert cases[0].frames == 529
    # ⚠ Нуль копій лишається нулем, а не «невідомо»: справа в описі є, сканів немає.
    assert cases[1].frames == 0


def test_browse_of_one_archive_reads_only_its_page() -> None:
    """Перегляд архіву — одна сторінка цього архіву, а не весь майданчик."""
    cf = _Cf(TREE)
    assert [n.ref for n in BabynYarSource(client=cf).browse("arch:36")] == ["fond:96"]
    assert not any(u.endswith("/archive/34") for u in cf.seen)


def test_the_gone_api_is_not_asked() -> None:
    """🔴 `/api/archive/…` дає 404 з 26.09.2026 — туди не ходимо зовсім."""
    cf = _Cf({**TREE, "/archive/desc/401": CASES_HTML})
    src = BabynYarSource(client=cf)
    src.browse("arch:34")
    src.browse("fond:207")
    src.browse("desc:401")
    assert not any("/api/" in u for u in cf.seen)


def test_fund_page_gives_the_case_count_denominator() -> None:
    """Число справ опису — з таблиці фонду, без окремого запиту."""
    cf = _Cf(TREE)
    src = BabynYarSource(client=cf)
    assert src.cases_count("401") is None, "фонд ще не читали — не вигадуємо"
    src.descriptions("207")
    asked = len(cf.seen)
    assert src.cases_count("401") == 3
    assert len(cf.seen) == asked


def test_fund_dates_become_bounds() -> None:
    src = BabynYarSource(client=_Cf(TREE))
    fund = src.funds("34")[0]
    assert (fund["start_date"], fund["end_date"]) == ("1921", "1940")
    assert src.funds("34")[1]["start_date"] == ""


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
    """🔴 Кожен зайвий прохід наближає відсічку.

    Заміряно 09.09.2026: перегляд архіву плюс збирання фонду брали перелік
    двічі, і Cloudflare показав виклик саме на другому проході.
    """
    cf = _Cf(TREE)
    src = BabynYarSource(client=cf)
    src.browse("arch:34")
    src.browse("arch:34")
    src.funds("34")
    assert sum(u.endswith("/archive/34") for u in cf.seen) == 1


def test_the_fund_list_expires_so_a_daemon_sees_new_funds() -> None:
    """⚠ Вічний кеш у живому демоні ховав би фонди, викладені після старту."""
    cf = _Cf(TREE)
    src = BabynYarSource(client=cf)
    src.funds("34")
    taken, rows = src._arch_cache["34"]
    src._arch_cache["34"] = (taken - src.FUNDS_TTL_SEC - 1, rows)
    src.funds("34")
    assert sum(u.endswith("/archive/34") for u in cf.seen) == 2


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
    src = BabynYarSource(tmp_path, client=_Cf({"/archive/": ARCHIVES_HTML}))
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


# ── сторінка фонду й вшитий індекс ───────────────────────────────────────────

#: Розмітка живої `/archive/fund/96` 27.09.2026 (скорочено): ф.484 ДАМО, якого
#: немає на сторінці архіву.
FUND_96_HTML = """
<div class="aside-nav"> <div class="aside-nav-item"> <a href="/archive/">Архів</a>
<span>/</span> </div> <div class="aside-nav-item"> <a href="/archive/36">ДАМО</a>
<span>/</span> </div> <div class="aside-nav-item"> Фонд 484 </div> </div>
<p class="aside-title">Фонд 484</p>
<p class="aside-descr"> Колекція метричних книг установ релігійних культів </p>
""" + _table(_desc_row(218, "1", 1491).replace("1921 - 1940", "1804 - 1925"))


def test_fund_page_says_everything_about_the_fund() -> None:
    from nyshporka.sources.babynyar import fund_page

    got = fund_page(FUND_96_HTML)
    assert got is not None
    assert (got["number"], got["archive"]) == ("484", {"id": 36, "short_name": "ДАМО"})
    assert got["name"].startswith("Колекція метричних книг")
    assert (got["start_date"], got["end_date"]) == ("1804", "1925")
    assert got["descriptions"] == [{"id": 218, "number": "1", "annotation": "Опис №1",
                                    "cases_count": 1491}]
    assert fund_page("<html>не фонд</html>") is None


def test_hidden_fund_comes_from_the_shipped_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Сторінка архіву ДАМО не показує ф.484 — індекс повертає його."""
    import nyshporka.sources.babynyar as B

    monkeypatch.setattr(B, "known_funds", lambda: (
        {"id": 96, "number": "484", "name": "Колекція метричних книг",
         "archive": {"id": 36, "short_name": "ДАМО"}, "start_date": "1804",
         "end_date": "1925", "descriptions": [{"id": 218, "number": "1"}]},
        {"id": 207, "number": "R-6453", "name": "дубль видимого",
         "archive": {"id": 34}, "descriptions": []},
    ))
    arch_36 = _table(_fond_row(95, "298", "Видимий фонд", "", 1))
    src = BabynYarSource(client=_Cf({**TREE, "/archive/36": arch_36}))
    assert [f["number"] for f in src.funds("36")] == ["298", "484"]
    assert src.funds("36")[1]["z_indeksu"] is True
    # Видимий на сторінці фонд із індексу не задвоюється.
    assert [f["id"] for f in src.funds("34")] == [207, 999]


def test_shipped_index_is_valid_if_present() -> None:
    """Індекс у пакеті — справжні фонди з архівом і описами, без дублів."""
    import json

    from nyshporka.sources.babynyar import KNOWN_FUNDS

    if not KNOWN_FUNDS.exists():
        pytest.skip("індексу в пакеті немає")
    funds = json.loads(KNOWN_FUNDS.read_text(encoding="utf-8"))["funds"]
    assert funds, "порожній індекс — гірше за відсутній: виглядає як відповідь"
    ids = [f["id"] for f in funds]
    assert len(ids) == len(set(ids))
    for f in funds:
        assert f["number"] and (f.get("archive") or {}).get("id"), f


# ── запобіжники темпу ────────────────────────────────────────────────────────

def test_cooldown_after_a_challenge_that_did_not_pass(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """🔴 Відсіч, що не минула, — пауза для всієї машини, а не нова серія.

    26–27.09.2026 повтори поспіль лише подовжували відсіч годинами.
    """
    import nyshporka.core.xrate as X
    from nyshporka.sources.cfclient import CfClient, ShieldError

    monkeypatch.setattr(X, "default_state_dir", lambda: tmp_path)

    class _Shield(CfClient):
        def __post_init__(self) -> None:
            self.via = "curl"
            self.asked = 0

        def get(self, url: str) -> _R:  # type: ignore[override]
            self.asked += 1
            raise ShieldError("виклик не минув")

    shield = _Shield()
    src = BabynYarSource(client=shield)
    with pytest.raises(SourceError):
        src.page("/archive/")
    assert (tmp_path / "babynyar-cooldown").exists()

    # Другий виклик — навіть іншим процесом — у мережу не йде.
    with pytest.raises(SourceError) as exc:
        BabynYarSource(client=shield).page("/archive/36")
    assert shield.asked == 1
    assert "не стукає" in str(exc.value)


def test_expired_cooldown_lets_requests_through(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import time

    import nyshporka.core.xrate as X
    from nyshporka.sources import babynyar as B

    monkeypatch.setattr(X, "default_state_dir", lambda: tmp_path)
    (tmp_path / "babynyar-cooldown").write_text(str(time.time() - 1), encoding="utf-8")
    assert B._okholodzhennia_do() is None


def test_real_pages_share_one_machine_wide_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Справжній транспорт іде крізь спільну чергу, а не власну паузу."""
    from nyshporka.sources import babynyar as B

    class _NoNet:
        def __init__(self, **_kw: object) -> None:
            pass

    monkeypatch.setattr(B, "CfClient", _NoNet)
    http = B.BabynYarSource()._cf()
    assert http.limiter is not None and http.limiter.key == B.RATE_KEY
    assert (http.limiter.max_events, http.delay) == (B.RATE_MAX, 0.0)
