"""📚 Commons: перелік сканів фонду й завантаження справи."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.base import Target
from nyshporka.fonds.collect.commons import (
    FIELDS,
    CommonsCollector,
    norm_title,
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
