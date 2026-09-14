"""📚 Commons: перелік сканів фонду й завантаження справи."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import pytest

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Target
from nyshporka.fonds.collect.commons import (
    FIELDS,
    CommonsCollector,
    norm_title,
    parse_shifra,
    shifra_pattern,
)
from nyshporka.sources.base import SourceError
from nyshporka.sources.commons import CommonsSource
from nyshporka.sources.http import Fetcher


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class _Api:
    """Двійник Commons: збіг за регексом, POST бере участь тілом."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.seen: list[str] = []
        self.posts: list[dict[str, str]] = []

    def _match(self, url: str) -> _Resp:
        for pat, body in self.answers.items():
            if re.search(pat, url):
                return _Resp(body)
        raise AssertionError(f"двійник не знає адреси: {url}")

    def get(self, url: str) -> _Resp:
        self.seen.append(url)
        return self._match(url)

    def post(self, url: str, data: dict[str, str] | None = None,
             json: object = None) -> _Resp:
        # 🔴 Тіло бере участь у збігу. Двійник, який дивиться лише на адресу,
        # не відрізнив би батч метаданих від будь-якого іншого POST — тобто
        # відповідав би не на те, про що спитали.
        self.posts.append(data or {})
        body = "&".join(f"{k}={v}" for k, v in sorted((data or {}).items()))
        return self._match(f"{url}?{body}")


def test_underscore_and_space_are_the_same_page() -> None:
    """🔴 MediaWiki їх ототожнює, а ми ні: без зведення той самий файл
    рахувався двічі, і фонд «мав» 276 сканів замість 138."""
    a = norm_title("ДАХмО_230-1-11._1802._Протоколи.pdf")
    b = norm_title("ДАХмО 230-1-11. 1802. Протоколи.pdf")
    assert a == b


def test_a_letter_after_a_space_is_a_title_not_a_shifra() -> None:
    """🔴 «230-1-2640 Дзічковських» — це справа 2640, а не фантомна «2640д»,
    якої в описі немає. Справжня при цьому лишалась би «без скана»."""
    p = shifra_pattern("ДАХмО", "230")
    m = p.search("ДАХмО 230-1-2640 Дзічковських.pdf")
    assert m and (m.group(1), m.group(2), m.group(3)) == ("1", "2640", "")
    m2 = p.search("ДАХмО 230-1-24а. Опис.pdf")
    assert m2 and m2.group(3) == "а"


def test_hyphen_between_archive_and_fond_is_still_a_shifra() -> None:
    """🔴 Заливач ЦДІАК ф.972 ставив дефіс замість пробілу — «ЦДІАК-972-1-253».
    Половина фонду лягала в «без шифри», і справа з живим сканом на Commons
    виглядала як така, якої онлайн немає."""
    p = shifra_pattern("ЦДІАК", "972")
    m = p.search("ЦДІАК-972-1-253. Справа про призначення Лукаша Полюховича.pdf")
    assert m and (m.group(1), m.group(2)) == ("1", "253")
    m2 = p.search("ЦДІАК 972-2-4. 1800-1838. Сповідальні розписи.pdf")
    assert m2 and (m2.group(1), m2.group(2)) == ("2", "4")


def test_a_glued_title_gives_no_shifra_instead_of_a_phantom_case() -> None:
    """🔴 «ЦДІАК-972-1-261Справа про призначення…» — назва приліпла до номера
    без пробілу. Без запобіжника регекс відступав по цифрах і віддавав
    ФАНТОМНУ справу 26, якої у фонді немає; фантом гірший за пропуск, бо
    виглядає як відкриття. Правильна відповідь — «шифри не видно»."""
    p = shifra_pattern("ЦДІАК", "972")
    assert p.search("ЦДІАК-972-1-261Справа про призначення Теодора.pdf") is None
    # а розділений пробілом номер із літерою лишається шифрою
    ok = shifra_pattern("ДАХмО", "230").search("ДАХмО 230-1-24а. Опис.pdf")
    assert ok and (ok.group(2), ok.group(3)) == ("24", "а")


def test_a_shifra_written_in_words_is_still_a_shifra() -> None:
    """🔴 «ЦДІАК фонд 1040, опис 1, справа 48» — та сама справа, що й
    «ЦДІАК 1040-1-48». У ф.1040 так названо 141 файл із 434, і том на 816
    сторінок вважався відсутнім онлайн."""
    codes = ("ЦДІАК",)
    assert parse_shifra(
        "ЦДІАК фонд 1040, опис 1, справа 48. Акти духовного суду.pdf",
        codes, "1040") == ("1", "48", "")
    assert parse_shifra("ЦДІАК Ф. 53, о. 2, спр. 216 (8 арк.).pdf",
                        codes, "53") == ("2", "216", "")
    assert parse_shifra("ДАВО фонд 407, опис 1, справа 54а. Метрична книга.pdf",
                        ("ДАВО",), "407") == ("1", "54", "а")
    # цифрова форма розбирається, як і раніше
    assert parse_shifra("ЦДІАК 1040-1-2. 1749-1751. Акти.pdf",
                        codes, "1040") == ("1", "2", "")


def test_a_worded_shifra_does_not_borrow_a_longer_fond_or_an_opys_scan() -> None:
    """«фонд 10400» — чужий фонд, а «фонд 1040 опис 1» без справи — скан самого
    опису. Приписати їх справі фонду 1040 означало б фантом у реєстрі."""
    codes = ("ЦДІАК",)
    assert parse_shifra("ЦДІАК фонд 10400, опис 1, справа 5.pdf", codes, "1040") is None
    assert parse_shifra("ЦДІАК фонд 1040 опис 1.pdf", codes, "1040") is None
    assert parse_shifra("ЦДІАК фонд 1040 опис 1 том 2.pdf", codes, "1040") is None


def test_metadata_go_by_POST_because_a_url_would_not_fit(tmp_path: Path) -> None:
    """Півсотні назв кирилицею не влазять у адресу: сервер відповідає 414, і
    виглядає це як «файлів немає»."""
    api = _Api({
        r"list=allimages": json.dumps(
            {"query": {"allimages": [{"name": "ДАХмО_230-1-1._Опис.pdf"}]}}),
        r"list=search": json.dumps({"query": {"search": []}}),
        r"prop=imageinfo": json.dumps({"query": {"pages": [
            {"title": "File:ДАХмО 230-1-1. Опис.pdf",
             "imageinfo": [{"size": 42, "pagecount": 7, "url": "https://х/ф.pdf"}]}]}}),
    })
    coll = CommonsCollector(fetcher=Fetcher(base="https://commons", delay=0.0,
                                            client=api))
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path)

    assert api.posts, "метадані пішли не POST'ом"
    assert res.rows == 1
    _, rows = T.read_tsv(res.out)
    assert rows[0]["size"] == "42" and rows[0]["pagecount"] == "7"


def test_a_file_without_a_shifra_is_marked_not_dropped(tmp_path: Path) -> None:
    """🔴 Скани, названі по-людськи, теж існують. Мовчазне зникнення такого
    файла читалось би як «його немає»."""
    api = _Api({
        r"list=allimages": json.dumps(
            {"query": {"allimages": [{"name": "Метрики Городківки 1802.pdf"}]}}),
        r"list=search": json.dumps({"query": {"search": []}}),
        r"prop=imageinfo": json.dumps({"query": {"pages": []}}),
    })
    coll = CommonsCollector(fetcher=Fetcher(base="https://c", delay=0.0, client=api))
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path)

    _, rows = T.read_tsv(res.out)
    assert len(rows) == 1 and rows[0]["no_shifra"] == "1"
    assert any(b.kind == "no_shifra" for b in res.blind)


def test_worded_names_are_found_and_a_longer_fond_is_filtered_out(tmp_path: Path) -> None:
    """🔴 Файл, названий «ЦДІАК фонд 1040, опис 1, справа 48», не має префікса
    «ЦДІАК 1040-», тож канали за цифровою шифрою його не бачили. Канал за
    словесною формою ширший — він ловить і фонд 10400, який у реєстр 1040
    потрапити не має навіть рядком «без шифри»."""
    worded = quote("ЦДІАК фонд 1040")
    api = _Api({
        rf"list=allimages&aiprefix={re.escape(worded)}": json.dumps({"query": {"allimages": [
            {"name": "ЦДІАК_фонд_1040,_опис_1,_справа_48._Акти.pdf"},
            {"name": "ЦДІАК фонд 10400, опис 1, справа 5.pdf"}]}}),
        r"list=allimages": json.dumps({"query": {"allimages": []}}),
        r"list=search": json.dumps({"query": {"search": []}}),
        r"prop=imageinfo": json.dumps({"query": {"pages": []}}),
    })
    coll = CommonsCollector(fetcher=Fetcher(base="https://c", delay=0.0, client=api))
    res = coll.collect(Target(repo="CDIAK", fond="1040"), dest=tmp_path)

    _, rows = T.read_tsv(res.out)
    assert [(r["opys"], r["spr_int"]) for r in rows] == [("1", "48")]


def test_search_pages_past_the_first_answer(tmp_path: Path) -> None:
    """🔴 Пошук віддає 500 назв за раз. Без гортання хвіст видачі мовчки
    зникав би, і справа з живим сканом виглядала б як відсутня."""
    api = _Api({
        r"list=search.*sroffset=500": json.dumps({"query": {"search": [
            {"title": "File:ДАХмО 230-1-9. Друга сторінка.pdf"}]}}),
        r"list=search": json.dumps({"continue": {"sroffset": 500}, "query": {"search": [
            {"title": "File:ДАХмО 230-1-1. Перша сторінка.pdf"}]}}),
        r"list=allimages": json.dumps({"query": {"allimages": []}}),
        r"prop=imageinfo": json.dumps({"query": {"pages": []}}),
    })
    coll = CommonsCollector(fetcher=Fetcher(base="https://c", delay=0.0, client=api))
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path)

    _, rows = T.read_tsv(res.out)
    assert sorted(r["spr_int"] for r in rows) == ["1", "9"]


def test_recollecting_does_not_duplicate_files_without_a_shifra(tmp_path: Path) -> None:
    """🔴 Рядки без шифри мають порожній опис, і злиття вважало їх «чужим
    описом, який цей запуск не чіпав»: кожен перезбір долучав старі до нових."""
    api = _Api({
        r"list=allimages": json.dumps(
            {"query": {"allimages": [{"name": "Метрики Городківки 1802.pdf"}]}}),
        r"list=search": json.dumps({"query": {"search": []}}),
        r"prop=imageinfo": json.dumps({"query": {"pages": []}}),
    })
    coll = CommonsCollector(fetcher=Fetcher(base="https://c", delay=0.0, client=api))
    coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path)
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path)

    _, rows = T.read_tsv(res.out)
    assert len(rows) == 1


def test_a_file_found_by_hand_survives_a_recollect(tmp_path: Path) -> None:
    """🔴 Частину файлів без шифри колись знайшли ручним запитом, і обхід їх
    не бачить. Перезбір, що їх викидає, ховає живий скан — а дубль того, що
    обхід знайшов сам, лишатись не має."""
    T.write_tsv(tmp_path / "commons.tsv", FIELDS, [
        {"opys": "", "spr_int": "", "spr_letter": "", "no_shifra": "1",
         "file": "Протоколи ревізійної комісії 1842.pdf"},
        {"opys": "", "spr_int": "", "spr_letter": "", "no_shifra": "1",
         "file": "Метрики Городківки 1802.pdf"},
    ])
    api = _Api({
        r"list=allimages": json.dumps(
            {"query": {"allimages": [{"name": "Метрики Городківки 1802.pdf"}]}}),
        r"list=search": json.dumps({"query": {"search": []}}),
        r"prop=imageinfo": json.dumps({"query": {"pages": []}}),
    })
    coll = CommonsCollector(fetcher=Fetcher(base="https://c", delay=0.0, client=api))
    res = coll.collect(Target(repo="DAHMO", fond="230"), dest=tmp_path)

    _, rows = T.read_tsv(res.out)
    assert sorted(r["file"] for r in rows) == [
        "Метрики Городківки 1802.pdf", "Протоколи ревізійної комісії 1842.pdf"]


def test_an_unknown_archive_refuses_instead_of_guessing() -> None:
    """Здогад тут шкідливий: запит про архів, якого на Commons немає, дає нуль,
    а нуль читається як «сканів немає»."""
    plan = CommonsCollector().plan(Target(repo="XXX", fond="1"))
    assert not plan.ready and "codes.commons" in plan.needs


def test_the_columns_are_a_promise() -> None:
    assert FIELDS == ("opys", "spr_int", "spr_letter", "no_shifra", "size",
                      "pagecount", "url", "file")


# ── джерело ──────────────────────────────────────────────────────────────────
def test_partial_download_never_lands_in_the_case_folder(tmp_path: Path) -> None:
    """🔴 Обірвана закачка під правильним іменем лягла б в облік як повна
    справа, і виявилось би це тоді, коли в ній шукають запис, якого немає в
    недовантаженій частині."""
    info = json.dumps({"query": {"pages": [
        {"title": "File:справа.pdf",
         "imageinfo": [{"size": 1000, "pagecount": 5, "url": "https://х/ф.pdf"}]}]}})

    class _Short(_Api):
        def stream(self, method: str, url: str):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                class R:
                    @staticmethod
                    def raise_for_status() -> None:
                        pass

                    @staticmethod
                    def iter_bytes(chunk: int = 0) -> list[bytes]:
                        return [b"x" * 10]      # обірвалось на десятому байті
                yield R()
            return _cm()

    api = _Short({r"prop=imageinfo": info})
    src = CommonsSource(fetcher=Fetcher(base="https://c", delay=0.0, client=api))
    res = src.fetch("file:справа.pdf", tmp_path)

    assert res.errors and "неповний" in res.errors[0]
    assert not list(tmp_path.glob("*.pdf")), "неповний файл лишився в теці справи"


def test_asking_for_frames_is_refused_not_ignored(tmp_path: Path) -> None:
    """Мовчазне ігнорування меж дало б людині повний файл там, де вона просила
    частину, — і вона вважала б, що взяла частину."""
    src = CommonsSource()
    with pytest.raises(SourceError) as exc:
        src.fetch("file:х.pdf", tmp_path, frames=(1, 10))
    assert "одним файлом" in str(exc.value)


def test_the_address_must_name_a_file() -> None:
    with pytest.raises(SourceError):
        CommonsSource().manifest("fond:230")


def test_search_refuses_instead_of_returning_zero() -> None:
    """🔴 Commons знає назви файлів, а не заголовки справ. Порожній список
    звідси читався б як «в архіві такого немає» — найдорожча відповідь у
    генеалогії, бо вона закриває напрям назавжди."""
    with pytest.raises(SourceError) as exc:
        CommonsSource().search("Городківка")
    assert "registry collect commons" in str(exc.value), "відмова не веде далі"
