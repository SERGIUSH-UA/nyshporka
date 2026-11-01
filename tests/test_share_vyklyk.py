"""`nysh share vyklyky / vyklyk / vyklyk-stan / vyklyk-skasuvaty / dovidka`.

Клієнт нічого не вирішує: перелік, підписи й причини відмов приходять від
сервера. Тест перевіряє транспорт: що йде на сервер, що друкується людині,
і що 404 та відмова стають коротким текстом, а не трасою.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka import ops as O
from nyshporka.share import catalog, vyklyky, zabir
from nyshporka.share.cli import app
from nyshporka.sources.http import HttpError

PERELIK: dict[str, Any] = {
    "tekst": "Готовий текст від сервера",
    "operatsii": [
        {"kod": "a.b", "nazva": "Перша", "opys": "Опис першої", "dozvoleno": True,
         "povidomlennia": "Можна"},
        {"kod": "c.d", "nazva": "Друга", "opys": "Опис другої", "dozvoleno": False,
         "povidomlennia": "Зараз не можна"},
    ],
}


class Pul:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.get: dict[str, Any] = {}
        self.post: dict[str, Any] = {}
        self.zapyty: list[tuple[str, str, Any]] = []
        monkeypatch.setattr(vyklyky, "_get", self._get)
        monkeypatch.setattr(vyklyky, "_post", self._post)

    def _vidpovid(self, tablytsia: dict[str, Any], url: str) -> Any:
        for kinets, v in tablytsia.items():
            if url.endswith(kinets):
                if isinstance(v, Exception):
                    raise v
                return v
        raise AssertionError(url)

    def _get(self, url: str) -> Any:
        self.zapyty.append(("GET", url, None))
        return self._vidpovid(self.get, url)

    def _post(self, url: str, body: dict[str, Any]) -> Any:
        self.zapyty.append(("POST", url, body))
        return self._vidpovid(self.post, url)


@pytest.fixture
def pul(monkeypatch: pytest.MonkeyPatch) -> Pul:
    return Pul(monkeypatch)


def _cli(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def test_perelik_yak_ye(pul: Pul) -> None:
    pul.get["/m/perelik"] = PERELIK
    env = O.call("share.vyklyky", {})
    assert env.ok and env.data == PERELIK
    assert pul.zapyty == [("GET", f"{catalog.DEFAULT_BASE}/m/perelik", None)]


def test_perelik_druk(pul: Pul) -> None:
    pul.get["/m/perelik"] = PERELIK
    r = _cli("vyklyky")
    assert r.exit_code == 0, r.output
    for slovo in ("Готовий текст від сервера", "a.b", "Перша", "Опис першої", "Можна",
                  "c.d", "Зараз не можна"):
        assert slovo in r.output


def test_dovidka(pul: Pul) -> None:
    pul.get["/m/dovidka"] = {"tekst": "Інструкція для агента"}
    r = _cli("dovidka")
    assert r.exit_code == 0 and "Інструкція для агента" in r.output
    assert json.loads(_cli("dovidka", "--json").output)["data"]["tekst"] == "Інструкція для агента"


def test_zapusk_z_parametrami_i_svoim_kliuchem(pul: Pul) -> None:
    pul.post["/m/vyklyky"] = {"id": 12, "stan": "chekaie"}
    r = _cli("vyklyk", "a.b", "--param", "x=1", "--param", "y=a=b")
    assert r.exit_code == 0, r.output
    assert "12" in r.output and "chekaie" in r.output
    _, url, tilo = pul.zapyty[0]
    assert url.endswith("/m/vyklyky")
    assert tilo["operatsiia"] == "a.b" and tilo["parametry"] == {"x": "1", "y": "a=b"}
    assert len(tilo["kliuch"]) >= 16

    # два запуски без --kliuch — два різні ключі; явний ключ іде як є
    _cli("vyklyk", "a.b")
    assert pul.zapyty[1][2]["kliuch"] != tilo["kliuch"]
    _cli("vyklyk", "a.b", "--kliuch", "moi-kliuch")
    assert pul.zapyty[2][2]["kliuch"] == "moi-kliuch"


def test_parametr_bez_rivnosti_vidmova(pul: Pul) -> None:
    env = O.call("share.vyklyk", {"operatsiia": "a.b", "param": ["bezrivnosti"]})
    assert not env.ok and "ключ=значення" in env.error
    assert pul.zapyty == []


def test_stan_i_skasuvannia(pul: Pul) -> None:
    pul.get["/m/vyklyky/5"] = {"id": 5, "stan": "v_roboti"}
    pul.post["/m/vyklyky/5/skasuvaty"] = {"id": 5, "stan": "skasovano"}
    r = _cli("vyklyk-stan", "5")
    assert r.exit_code == 0 and "v_roboti" in r.output
    r = _cli("vyklyk-skasuvaty", "5")
    assert r.exit_code == 0 and "skasovano" in r.output
    assert pul.zapyty[-1][0] == "POST"


@pytest.mark.parametrize(("op", "args", "metod"), [
    ("share.vyklyky", {}, "get"),
    ("share.dovidka", {}, "get"),
    ("share.vyklyk", {"operatsiia": "a.b"}, "post"),
    ("share.vyklyk_stan", {"vyklyk": 5}, "get"),
    ("share.vyklyk_skasuvaty", {"vyklyk": 5}, "post"),
])
def test_404_korotko_bez_natyakiv(pul: Pul, op: str, args: dict[str, Any], metod: str) -> None:
    pomylka = vyklyky.Vidmova("HTTP 404", status=404)
    for t in (pul.get, pul.post):
        t["/m/perelik"] = t["/m/dovidka"] = t["/m/vyklyky"] = pomylka
        t["/m/vyklyky/5"] = t["/m/vyklyky/5/skasuvaty"] = pomylka
    env = O.call(op, args)
    assert not env.ok and env.error == "у цього пулу такої операції немає"
    assert not env.warnings


def test_vidmova_servera_z_pauzoiu(pul: Pul) -> None:
    pul.post["/m/vyklyky"] = vyklyky.Vidmova("Зараз забагато викликів", status=429, retry_after=30)
    r = _cli("vyklyk", "a.b")
    assert r.exit_code != 0
    assert "Зараз забагато викликів" in r.output and "30" in r.output


def test_vidmova_z_tila_vidpovidi() -> None:
    class Exc(HttpError):
        pass

    exc = Exc("HTTP 429", status=429)
    exc.body = json.dumps({"detail": {"povidomlennia": "Текст сервера", "retry_after": 15}})
    v = vyklyky._vidmova(exc)
    assert str(v) == "Текст сервера" and v.retry_after == 15 and v.status == 429


def test_bez_kliucha_prosyt_pidiednaty(pul: Pul) -> None:
    pul.get["/m/perelik"] = catalog.PotribenKliuch(catalog.KLIUCH_TEXT, status=401)
    env = O.call("share.vyklyky", {})
    assert not env.ok and "nysh share login" in env.error


def test_stezhyty_zapuskaie_i_zabyraie(
    pul: Pul, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pul.post["/m/vyklyky"] = {"id": 9, "stan": "chekaie"}
    vyklyky_zabrano: list[tuple[int, Path, bool]] = []

    def _zabraty(vid: int, teka: Path, *, base: str = "", stezhyty: bool = False,
                 **kw: Any) -> dict[str, Any]:
        vyklyky_zabrano.append((vid, teka, stezhyty))
        return {"teka": str(teka), "arkhiviv": 1, "novykh": 2, "fayliv": 2, "ne_zbihlos": [],
                "konflikty": [], "stan": "hotovo",
                "pasport": {"pidkazka": "Підказка від сервера", "inshe": {"z": 1}}}

    monkeypatch.setattr(zabir, "zabraty", _zabraty)
    teka = tmp_path / "t"
    r = _cli("vyklyk", "a.b", "--stezhyty", "--do", str(teka))
    assert r.exit_code == 0, r.output
    assert vyklyky_zabrano == [(9, teka, True)]
    assert "9" in r.output and "забрано архівів" in r.output
    assert "Підказка від сервера" in r.output and "inshe" not in r.output


def test_stezhyty_zabrano_ne_vse_ne_uspikh(pul: Pul, monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    pul.post["/m/vyklyky"] = {"id": 9, "stan": "chekaie"}
    monkeypatch.setattr(zabir, "zabraty", lambda *a, **k: {
        "teka": "t", "arkhiviv": 0, "novykh": 0, "fayliv": 0, "ne_zbihlos": ["f"],
        "konflikty": [], "stan": "hotovo", "pasport": None})
    r = _cli("vyklyk", "a.b", "--stezhyty", "--do", str(tmp_path / "t"))
    assert r.exit_code != 0


def test_zabraty_404_korotko(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _get(url: str, **kw: Any) -> Any:
        raise catalog.PoolError("HTTP 404", status=404)

    monkeypatch.setattr(catalog, "_get", _get)
    env = O.call("share.zabraty", {"vyklyk": 7, "do": str(tmp_path / "s")})
    assert not env.ok and env.error == "у цього пулу такої операції немає"
