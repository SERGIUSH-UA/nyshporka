"""Простий шлях учасника, як у справ (`nysh read` → `nysh share push`): `nysh opys read <тека> …`
проходить паспорт, сторінки, читання, таблицю й пачки нормалізації одним кроком і продовжує з
місця; агент відповідає на пачки; `nysh opys push <тека> --norm-model …` складає пакет і заливає.
Закритий фонд — відмова одразу, з посиланням сервера."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from nyshporka import ops_opysy as OO
from nyshporka.opysy import remote as R
from nyshporka.opysy import workdir as W

URL = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Opys_9.pdf"
STOR = {"0001": [(200, 300, 1500, 360, "1. Дело о помещике Иванове"),
                 (300, 380, 1500, 440, "и его крестьянах"),
                 (200, 900, 1500, 960, "2. Дело о наследстве")],
        "0002": [(200, 300, 1500, 360, "3. Дело об откупе")]}


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Пул: політика (відкрито, крім ЦДІАК 442) і заливка — без мережі."""
    st: dict[str, Any] = {"pushed": []}

    def _policy(repo: str, fond: str, **kw: Any) -> dict[str, Any]:
        if fond == "442":
            return {"open": False, "why": "Описи веде інший проєкт: https://example.org",
                    "link": "https://example.org"}
        return {"open": True, "why": ""}

    def _push(path: Path, **kw: Any) -> dict[str, Any]:
        st["pushed"].append(Path(path))
        return {"vnesok": 7, "shyfra": "ДАОО 445-9", "duplicate": False, "summary": {"rows": 3},
                "warnings": []}

    monkeypatch.setattr(R, "policy", _policy)
    monkeypatch.setattr(R, "push", _push)
    return st


@pytest.fixture
def chytannia(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Що робить `nysh read <тека>/pages --out <тека>/run`: текст і рамки рядків кожної сторінки."""
    vyklyky: list[Path] = []

    def _chytaty(pages: Path, run: Path, script: str) -> int:
        vyklyky.append(pages)
        run.mkdir(parents=True, exist_ok=True)
        (run / "_htr_meta.json").write_text(json.dumps({"model": "pysar_cyr_v31.pt"}),
                                            encoding="utf-8")
        for stem, lines in STOR.items():
            w, h = Image.open(pages / f"{stem}.jpg").size
            (run / f"{stem}.txt").write_text("\n".join(t for *_, t in lines), encoding="utf-8")
            with gzip.open(run / f"{stem}.lines.json.gz", "wt", encoding="utf-8") as fh:
                json.dump({"boxes": [list(b[:4]) for b in lines], "size": [w, h]}, fh)
        return 0

    monkeypatch.setattr(OO, "_chytaty", _chytaty)
    return vyklyky


def _pdf(tmp: Path) -> Path:
    pdf = tmp / "opys.pdf"
    Image.new("RGB", (1000, 1400), "white").save(
        pdf, save_all=True, append_images=[Image.new("RGB", (1000, 1400), "white")])
    return pdf


def _read(d: Path, **kw: Any) -> Any:
    return OO.opysy_read(OO.ReadOpysArgs(dir=str(d), **kw))


def test_read_i_push_dvoma_komandamy(tmp_path: Path, server: dict[str, Any],
                                     chytannia: list[Path]) -> None:
    d = tmp_path / "opys"
    env = _read(d, pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9", url=URL,
                language="ru")
    assert env.ok, env
    assert env.data["zrobleno"] == ["паспорт", "сторінки", "читання", "таблиця"]
    assert env.data["sprav"] == 3 and env.data["pachok_normalizatsii"] == 1
    assert "nysh opys push" in env.data["next"] and "--norm-model" in env.data["next"]
    # повтор — зроблене не повторюється, читання не запускається вдруге
    env2 = _read(d, language="ru")
    assert env2.ok and "читання" not in env2.data["zrobleno"] and len(chytannia) == 1
    # повтор не нарізає пачок удруге: та сама одна пачка й далі чекає відповіді
    assert env2.data["novykh_pachok"] == 0 and env2.data["pachok_normalizatsii"] == 1
    assert len(list(Path(env.data["norm_dir"]).glob("batch_*.json"))) == 1
    # агент відповідає на пачки
    for b in Path(env.data["norm_dir"]).glob("batch_*.json"):
        titles = json.loads(b.read_text(encoding="utf-8"))["titles"]
        b.with_name(b.stem + ".out.txt").write_text(json.dumps(titles, ensure_ascii=False),
                                                    encoding="utf-8")
    # без моделі нормалізації — відмова з підказкою; з моделлю — пакет і заливка
    bez = OO.opysy_push(OO.PushArgs(file=str(d)))
    assert not bez.ok and "--norm-model" in bez.error
    got = OO.opysy_push(OO.PushArgs(file=str(d), norm_model="agent-model"))
    assert got.ok, got
    assert got.data["vnesok"] == 7 and server["pushed"][-1].suffix == ".nyshopys"
    # той самий пакет удруге не заливається (байти в сховищі лишились би сиротами)
    znov = OO.opysy_push(OO.PushArgs(file=str(d)))
    assert znov.ok and znov.data["duplicate"] and len(server["pushed"]) == 1
    # модель пам'ятається, а `--znovu` заливає все одно
    assert OO.opysy_push(OO.PushArgs(file=str(d), znovu=True)).ok and len(server["pushed"]) == 2
    # після прийняття нормалізації повтор `read` нічого не нарізає й веде одразу до `push`
    env3 = _read(d, language="ru")
    assert env3.ok and env3.data["pachok_normalizatsii"] == 0 and "--norm-model" not in env3.data["next"]


def test_zakrytyi_fond_odrazu_z_posylanniam(tmp_path: Path, server: dict[str, Any],
                                           chytannia: list[Path]) -> None:
    env = _read(tmp_path / "x", pdf=str(_pdf(tmp_path)), repo="ЦДІАК", fond="442", opys="1",
                url=URL)
    assert not env.ok and "https://example.org" in env.error
    assert not (tmp_path / "x").exists() and not chytannia


def test_nova_teka_bez_dzherela_i_mashynopys(tmp_path: Path, server: dict[str, Any]) -> None:
    env = _read(tmp_path / "y", repo="ДАОО", fond="445")
    assert not env.ok and "--pdf" in env.error and "--url" in env.error
    env = _read(tmp_path / "z", form="typed")
    assert not env.ok and "машинопис" in env.error


def test_obirvane_chytannia_kazhe_prodovzhyty(tmp_path: Path, server: dict[str, Any],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OO, "_chytaty", lambda pages, run, script: 1)
    env = _read(tmp_path / "o", pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9",
                url=URL)
    assert not env.ok and "0 з 2" in env.error and "продовжить" in env.error
    assert W.load(tmp_path / "o")  # паспорт і сторінки лишились — повтор продовжить
