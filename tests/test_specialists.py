"""Спеціалісти: вузькі моделі, яких автомат не бере й не качає без прохання.

Номер версії порівнюється між родинами. Логофет v11 як звичайний пак обійшов би Дяка v10
і читав би другим голосом російські книги, яких не вчив, а `nysh models get` качав би
кожному ще 160 МБ вузьких ваг.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.htr import run as R
from nyshporka.setup import packs

MAIN = packs.Pack(id="pysar-cyr-v28", kind="model", filename="pysar_cyr_v28.pt", sha256="a", size=1,
                  release="weights-v3", script="cyrillic", engine="parseq")
VOICE = packs.Pack(id="diak-cyr-v10", kind="model", filename="diak_cyr_v10.safetensors", sha256="b", size=1,
                   release="weights-v3", script="cyrillic", engine="kraken")
LOGOFET = packs.Pack(id="logofet-ro-v11", kind="model", filename="logofet_ro_v11.safetensors", sha256="c",
                     size=1, release="weights-v4", script="cyrillic", engine="kraken", specialist=True,
                     scope="румунська кирилиця", avoid="російські записи", launch="nysh read <справа> --with x")
X18 = packs.Pack(id="pysar-x18-v1", kind="model", filename="pysar_x18_v1.pt", sha256="d", size=1,
                 release="weights-v4", script="cyrillic", engine="parseq", specialist=True)


@pytest.fixture
def downloaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Усі чотири паки лежать на диску, `PRODUCTION.json` немає: чиста установка."""
    monkeypatch.setattr(packs, "catalog", lambda: [MAIN, VOICE, LOGOFET, X18])
    monkeypatch.setattr(packs, "verify", lambda p: True)
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path)
    monkeypatch.setattr(R, "local_models", list)
    monkeypatch.setattr(R, "production_choice", dict)
    monkeypatch.setattr(R, "production_voice", dict)
    return tmp_path


def test_a_downloaded_specialist_does_not_become_the_voice(downloaded: Path) -> None:
    main, voice = R.pick_model("cyrillic", second_voice=True)
    assert (main.name, voice.name if voice else "") == ("pysar_cyr_v28.pt", "diak_cyr_v10.safetensors")


def test_a_local_specialist_file_is_not_picked_either(downloaded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл поруч із дослідженням, якого в `packs.json` немає (Регент): те саме правило."""
    f = downloaded / "regent_v4.safetensors"
    monkeypatch.setattr(packs, "catalog", lambda: [MAIN, VOICE])
    monkeypatch.setattr(R, "local_models", lambda: [f])
    _, voice = R.pick_model("cyrillic", second_voice=True)
    assert voice is not None and voice.name == "diak_cyr_v10.safetensors"


def test_a_researcher_can_name_a_specialist_in_production(downloaded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = downloaded / "regent_v4.safetensors"
    monkeypatch.setattr(packs, "catalog", lambda: [MAIN, VOICE])
    monkeypatch.setattr(R, "local_models", lambda: [f])
    monkeypatch.setattr(R, "production_voice", lambda: {"cyrillic": f.name})
    _, voice = R.pick_model("cyrillic", second_voice=True)
    assert voice == f


def test_missing_does_not_ask_for_specialists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(packs, "catalog", lambda: [MAIN, LOGOFET])
    monkeypatch.setattr(packs, "verify", lambda p: False)
    assert [p.id for p in packs.missing("model")] == [MAIN.id]
    assert [p.id for p in packs.specialists()] == [LOGOFET.id]


def _fetched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    got: list[str] = []

    def fetch(p: packs.Pack) -> Path:
        got.append(p.id)
        return tmp_path / p.filename

    monkeypatch.setattr(packs, "catalog", lambda: [MAIN, LOGOFET])
    monkeypatch.setattr(packs, "verify", lambda p: False)
    monkeypatch.setattr(packs, "fetch", fetch)
    return got


@pytest.mark.parametrize(("args", "want"), [
    ([], ["pysar-cyr-v28"]),
    (["--specialists"], ["pysar-cyr-v28", "logofet-ro-v11"]),
    (["logofet-ro-v11"], ["logofet-ro-v11"]),
])
def test_models_get_takes_specialists_only_on_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                      args: list[str], want: list[str]) -> None:
    got = _fetched(monkeypatch, tmp_path)
    res = CliRunner().invoke(app, ["models", "get", *args])
    assert res.exit_code == 0, res.output
    assert got == want


def test_models_list_describes_a_specialist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(packs, "catalog", lambda: [MAIN, LOGOFET])
    monkeypatch.setattr(packs, "verify", lambda p: False)
    res = CliRunner().invoke(app, ["models", "list"])
    assert res.exit_code == 0, res.output
    for text in ("Спеціалісти", LOGOFET.scope, LOGOFET.avoid, "nysh models get logofet-ro-v11"):
        assert text in res.output


def test_every_specialist_in_the_manifest_is_described() -> None:
    raw = json.loads(packs.manifest_path().read_text(encoding="utf-8"))["packs"]
    rows = [p for p in raw if p.get("specialist")]
    assert rows
    for p in rows:
        assert p["sha256"] and p["size"]
        assert all(p.get(k) for k in ("scope", "avoid", "launch", "license")), p["id"]
        # Основа PARSeq (Hukyl) під CC BY-SA: її ShareAlike переходить на спеціаліста цього рушія.
        want = "CC BY-SA 4.0" if p["engine"] == "parseq" else "CC BY-NC-SA 4.0"
        assert p["license"] == want, p["id"]
        assert packs.is_specialist_file(p["filename"]), p["id"]
        assert p["filename"].split(".")[0] in p["launch"], p["id"]


def test_a_file_named_like_a_specialist_is_marked_in_the_manifest() -> None:
    raw = json.loads(packs.manifest_path().read_text(encoding="utf-8"))["packs"]
    for p in raw:
        assert bool(p.get("specialist")) == packs.is_specialist_file(p["filename"]), p["id"]


def test_pack_defaults_stay_plain() -> None:
    assert replace(MAIN).specialist is False
