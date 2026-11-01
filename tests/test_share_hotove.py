"""Що чекає на людину на сервері Супряги: список, забір усього й нагадування без мережі."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.core import workspace as W
from nyshporka.share import catalog, zabir
from nyshporka.share import vyklyky as V


@pytest.fixture
def stan_mashyny(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Свій файл стану: тести не пишуть у справжній `state.json` користувача."""
    path = tmp_path / "state.json"
    monkeypatch.setattr(W, "_state_path", lambda: path)
    return path


class Server:
    """Відповіді `/m/hotove` по черзі й журнал забору."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.vidpovidi: list[Any] = []
        self.zabrano: list[tuple[int, str]] = []
        self.provaleni: set[int] = set()
        monkeypatch.setattr(V, "_get", self._get)
        monkeypatch.setattr(zabir, "zabraty", self._zabraty)
        monkeypatch.setattr("time.sleep", lambda _s: None)

    def _get(self, url: str) -> dict[str, Any]:
        assert url.endswith("/m/hotove")
        r = self.vidpovidi.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def _zabraty(self, vid: int, teka: Path, **_kw: Any) -> dict[str, Any]:
        if vid in self.provaleni:
            raise OSError("диск")
        self.zabrano.append((vid, Path(teka).name))
        return {"teka": str(teka), "arkhiviv": 1, "novykh": 2, "fayliv": 2, "ne_zbihlos": [],
                "konflikty": [], "pasport": {"pidkazka": "x"}, "stan": "hotovo"}


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stan_mashyny: Path) -> Server:
    return Server(monkeypatch, tmp_path)


def _r(vid: int, plivka: str = "122385479") -> dict[str, Any]:
    return {"id": vid, "plivka": plivka, "kadriv": 22, "do": "2026-11-08", "kvapno": False}


def test_hotove_syncs_the_local_record_with_the_server(server: Server) -> None:
    V.zapamiataty(5)
    V.zapamiataty(6)
    server.vidpovidi = [{"hotovo": [_r(6)], "zhyvi": [{"id": 7, "operatsiia": "x"}]}]
    env = O.call("share.hotove", {})
    assert env.ok and [r["id"] for r in env.data["hotovo"]] == [6]
    assert V._vidkryti() == [6, 7], "закритий деінде виклик 5 більше не нагадує про себе"


def test_all_ready_goes_each_into_its_own_folder(server: Server, tmp_path: Path) -> None:
    V.zapamiataty(1)
    server.vidpovidi = [{"hotovo": [_r(1, "111"), _r(2, "222")], "zhyvi": []}]
    env = O.call("share.zabraty_usi", {"do": str(tmp_path)})
    assert env.ok, env.error
    assert server.zabrano == [(1, "111"), (2, "222")]
    assert [r["fayliv"] for r in env.data["zabrano"]] == [2, 2]
    assert V._vidkryti() == [], "забране забуто"


def test_one_failure_does_not_stop_the_others_and_is_reported(server: Server, tmp_path: Path) -> None:
    server.provaleni = {1}
    server.vidpovidi = [{"hotovo": [_r(1, "111"), _r(2, "222")], "zhyvi": []}]
    env = O.call("share.zabraty_usi", {"do": str(tmp_path)})
    assert not env.ok and "не все" in (env.error or "")
    assert server.zabrano == [(2, "222")]
    assert [r["id"] for r in env.data["nevdachi"]] == [1]


def test_hostile_name_from_the_server_stays_inside_the_folder(server: Server, tmp_path: Path) -> None:
    server.vidpovidi = [{"hotovo": [_r(9, "../../poza")], "zhyvi": []}]
    env = O.call("share.zabraty_usi", {"do": str(tmp_path)})
    assert env.ok and server.zabrano == [(9, "vyklyk-9")]


def test_watch_waits_for_live_calls_and_takes_each_once(server: Server, tmp_path: Path) -> None:
    server.vidpovidi = [
        {"hotovo": [_r(1, "111")], "zhyvi": [{"id": 2, "operatsiia": "x"}]},
        {"hotovo": [_r(1, "111")], "zhyvi": [{"id": 2, "operatsiia": "x"}]},
        {"hotovo": [_r(2, "222")], "zhyvi": []},
    ]
    env = O.call("share.zabraty_usi", {"do": str(tmp_path), "stezhyty": True})
    assert env.ok and server.zabrano == [(1, "111"), (2, "222")]


def test_without_watch_a_live_call_is_only_named(server: Server, tmp_path: Path) -> None:
    server.vidpovidi = [{"hotovo": [], "zhyvi": [{"id": 2, "operatsiia": "x"}]}]
    env = O.call("share.zabraty_usi", {"do": str(tmp_path)})
    assert env.ok and env.data["zhyvi"] and not server.zabrano and not server.vidpovidi


def test_agent_status_names_open_calls_without_touching_the_network(
    stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bez_merezhi(*_a: Any, **_k: Any) -> None:
        raise AssertionError("хук старту сесії не ходить у мережу")

    monkeypatch.setattr(V, "_get", bez_merezhi)
    monkeypatch.setattr(V, "_post", bez_merezhi)
    assert "Супряга:" not in (O.call("project.status", {"agent": True}).data or {}).get("text", "")
    V.zapamiataty(28)
    text = (O.call("project.status", {"agent": True}).data or {}).get("text", "")
    assert "незакритих викликів 1" in text and "nysh share hotove" in text


def test_agent_of_a_new_session_learns_about_operations_only_after_the_first_guide(
    stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tekst() -> str:
        return (O.call("project.status", {"agent": True}).data or {}).get("text", "")

    assert "nysh share dovidka" not in tekst()
    monkeypatch.setattr(V, "_get", lambda _url: {"tekst": "довідка"})
    assert O.call("share.dovidka", {}).ok
    monkeypatch.setattr(V, "_get", lambda _url: pytest.fail("хук не ходить у мережу"))
    assert "nysh share dovidka" in tekst()


@pytest.fixture
def domivka(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


def test_guide_lays_a_skill_for_the_agent_and_refreshes_it(
    stan_mashyny: Path, domivka: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(V, "_get", lambda _url: {
        "tekst": "довідка", "skil": {"opys": 'Use when: «що про село»\nsecond line', "tekst": "Run it."}})
    env = O.call("share.dovidka", {})
    karta = domivka / ".claude" / "skills" / V.SKIL / "SKILL.md"
    text = karta.read_text(encoding="utf-8")
    assert env.ok and env.data["skil"] == [str(karta.parent)]
    assert text.startswith(f"---\nname: {V.SKIL}\ndescription: \"Use when: «що про село» second line\"\n---")
    assert "Run it." in text
    assert not (domivka / ".agents").exists(), "тек агента, якого немає, не заводимо"
    monkeypatch.setattr(V, "_get", lambda _url: {
        "tekst": "довідка", "skil": {"opys": "нове", "tekst": "Інше."}})
    assert O.call("share.dovidka", {}).ok
    assert "Інше." in karta.read_text(encoding="utf-8")


def test_no_agent_folder_no_skill(
    stan_mashyny: Path, domivka: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (domivka / ".claude").rmdir()
    monkeypatch.setattr(V, "_get", lambda _url: {"tekst": "д", "skil": {"opys": "о", "tekst": "т"}})
    env = O.call("share.dovidka", {})
    assert env.ok and env.data["skil"] == [] and not (domivka / ".claude").exists()


def test_old_server_without_a_skill_still_gives_the_guide(
    stan_mashyny: Path, domivka: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(V, "_get", lambda _url: {"tekst": "довідка"})
    env = O.call("share.dovidka", {})
    assert env.ok and env.data["tekst"] == "довідка" and env.data["skil"] == []


def test_final_refusal_takes_the_skill_away(
    stan_mashyny: Path, domivka: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(V, "_get", lambda _url: {"tekst": "д", "skil": {"opys": "о", "tekst": "т"}})
    assert O.call("share.dovidka", {}).ok
    teka = domivka / ".claude" / "skills" / V.SKIL

    def nema(_url: str) -> dict[str, Any]:
        raise catalog.PoolError("немає", status=404)

    monkeypatch.setattr(V, "_get", nema)
    assert teka.is_dir()
    O.call("share.dovidka", {})
    assert not teka.exists()


def test_guide_refused_for_good_removes_the_reminder(
    stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    W.state_set(**{W.KEY_SUPRIAHA_OPERATSII: True})

    def nema(_url: str) -> dict[str, Any]:
        raise catalog.PoolError("немає", status=404)

    monkeypatch.setattr(V, "_get", nema)
    assert not O.call("share.dovidka", {}).ok
    assert "nysh share dovidka" not in (
        O.call("project.status", {"agent": True}).data or {}).get("text", "")


def test_network_failure_keeps_the_reminder(
    stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    W.state_set(**{W.KEY_SUPRIAHA_OPERATSII: True})

    def zbii(_url: str) -> dict[str, Any]:
        raise OSError("мережа")

    monkeypatch.setattr(V, "_get", zbii)
    assert not O.call("share.dovidka", {}).ok
    assert W.state_all()[W.KEY_SUPRIAHA_OPERATSII] is True


def test_collected_call_is_forgotten_and_a_partial_one_is_not(
    stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    zvit = {"teka": str(tmp_path), "arkhiviv": 1, "novykh": 1, "fayliv": 1, "ne_zbihlos": [],
            "konflikty": [], "pasport": None, "stan": "v_roboti"}
    monkeypatch.setattr(zabir, "zabraty", lambda *_a, **_k: dict(zvit))
    V.zapamiataty(3)
    assert O.call("share.zabraty", {"vyklyk": 3, "do": str(tmp_path)}).ok
    assert V._vidkryti() == [3], "виклик ще йде"
    zvit.update(stan="hotovo", ne_zbihlos=["0001.jpg"])
    O.call("share.zabraty", {"vyklyk": 3, "do": str(tmp_path)})
    assert V._vidkryti() == [3], "не збіглось: лишається на наступний запуск"
    zvit.update(ne_zbihlos=[])
    assert O.call("share.zabraty", {"vyklyk": 3, "do": str(tmp_path)}).ok
    assert V._vidkryti() == []


def test_start_call_is_remembered_only_while_it_lives(
    stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(V, "zapustyty", lambda *_a: {"id": 4, "stan": "hotovo"})
    assert O.call("share.vyklyk", {"operatsiia": "poshuk"}).ok
    assert V._vidkryti() == [], "миттєвий виклик забирати нічого"
    monkeypatch.setattr(V, "zapustyty", lambda *_a: {"id": 5, "stan": "v_roboti"})
    assert O.call("share.vyklyk", {"operatsiia": "kadry"}).ok
    assert V._vidkryti() == [5]


def test_agreement_goes_to_the_server(stan_mashyny: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def post(url: str, _body: dict[str, Any]) -> dict[str, Any]:
        seen.append(url)
        return {"id": 8, "stan": "v_roboti"}

    monkeypatch.setattr(V, "_post", post)
    env = O.call("share.vyklyk_pochaty", {"vyklyk": 8})
    assert env.ok and seen[0].endswith("/m/vyklyky/8/pochaty")
