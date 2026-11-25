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

    def _chytaty(pages: Path, run: Path, script: str, whole_line: bool = False) -> int:
        run.mkdir(parents=True, exist_ok=True)
        if whole_line:
            for k in pages.glob("*.jpg"):
                (run / f"{k.stem}.txt").write_text("", encoding="utf-8")
            return 0
        vyklyky.append(pages)
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


def _read_z_meta(d: Path, **kw: Any) -> Any:
    """Перший `read` зупиняється по метадані опису (агент глянув сторінки), другий — читає далі."""
    env = _read(d, **kw)
    if env.ok and env.data.get("meta_potribni"):
        assert env.data["hlianuty"] and env.data["zrobleno"] == ["паспорт", "сторінки"]
        m = OO.opysy_meta(OO.MetaArgs(dir=str(d), forma="hand_ruled", kolonky="nomer,nazva,kinets",
                                      sprav=0))
        assert m.ok, m
        env = _read(d, **{k: v for k, v in kw.items() if k in ("language", "script")})
    return env


def test_read_i_push_dvoma_komandamy(tmp_path: Path, server: dict[str, Any],
                                     chytannia: list[Path]) -> None:
    d = tmp_path / "opys"
    env = _read_z_meta(d, pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9", url=URL,
                       language="ru")
    assert env.ok, env
    assert env.data["zrobleno"][0] == "читання" and env.data["zrobleno"][-1] == "таблиця"
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
    monkeypatch.setattr(OO, "_chytaty", lambda pages, run, script, whole_line=False: 1)
    env = _read_z_meta(tmp_path / "o", pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9",
                       url=URL)
    assert not env.ok and "0 з 2" in env.error and "продовжить" in env.error
    assert W.load(tmp_path / "o")  # паспорт і сторінки лишились — повтор продовжить


def test_mova_z_tekstu_doreformena_i_ukrainska() -> None:
    from nyshporka.opysy import pack_dir as PD

    ru = [{"voices": {"p": "Дѣло по обвиненію офицера Григорія Мотеева въ изнасилованіи дѣвочки "
                           "Тоже крестьянина Ивана Выбрановскаго въ избіеніи служителя"}}]
    uk = [{"voices": {"p": "Костьол с. Білогородка. Метрична книга запису народження, шлюбу та "
                           "смерті за 1895 рік; Її, єпархія, Ґорґани"}}]
    assert PD.language(ru, "") == "ru" and PD.language(uk, "") == "uk"


def test_porozhnia_storinka_bez_tekstu_ne_blokuie(tmp_path: Path, server: dict[str, Any],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Сторінка, яку рушій пройшов, але тексту не дав (порожня, титул), — прочитана за метою."""
    def _chytaty(pages: Path, run: Path, script: str, whole_line: bool = False) -> int:
        run.mkdir(parents=True, exist_ok=True)
        if whole_line:
            for k in pages.glob("*.jpg"):
                (run / f"{k.stem}.txt").write_text("", encoding="utf-8")
            return 0
        stem, lines = "0001", STOR["0001"]
        w, h = Image.open(pages / f"{stem}.jpg").size
        (run / f"{stem}.txt").write_text("\n".join(t for *_, t in lines), encoding="utf-8")
        with gzip.open(run / f"{stem}.lines.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"boxes": [list(b[:4]) for b in lines], "size": [w, h]}, fh)
        (run / "_htr_meta.json").write_text(json.dumps(
            {"model": "pysar_cyr_v31.pt", "pages": {"0001.jpg": {"lines": 3},
                                                   "0002.jpg": {"lines": 0}}}), encoding="utf-8")
        return 0

    monkeypatch.setattr(OO, "_chytaty", _chytaty)
    env = _read_z_meta(tmp_path / "p", pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9",
                       url=URL, language="ru")
    assert env.ok, env
    assert "читання" in env.data["zrobleno"] and env.data["sprav"] == 2


def test_push_na_obmin_bez_normalizatsii(tmp_path: Path, server: dict[str, Any],
                                         chytannia: list[Path]) -> None:
    """Автор без ресурсів: рукопис без нормалізації не проходить ворота, з `--na-obmin` —
    проходить із позначкою, і маніфест несе прапорець обміну; підказка `read` називає обидва шляхи."""
    from nyshporka.opysy import bundle as B

    d = tmp_path / "opys"
    env = _read_z_meta(d, pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9", url=URL,
                language="ru")
    assert env.ok and "--na-obmin" in env.data["next"] and "--norm-model" in env.data["next"]
    bez = OO.opysy_push(OO.PushArgs(file=str(d)))
    assert not bez.ok
    assert any(w.code == "norm_missing" and "--na-obmin" in w.text for w in bez.warnings)
    got = OO.opysy_push(OO.PushArgs(file=str(d), na_obmin=True))
    assert got.ok, got
    contents, verdict = B.verify(server["pushed"][-1].read_bytes())
    assert verdict.passed and contents.manifest["normalization_exchange"] is True
    assert any(code == "norm_exchange" for code, _ in verdict.warnings)


def test_vorota_obmin_pryvatne_dzherelo_vidmova() -> None:
    from nyshporka.opysy import gates as G

    rows = [{"regions": [{"page": 1, "y0": 0.1, "y1": 0.2}], "no_raw": "1", "no": 1,
             "no_status": "chain", "title_raw": "Дело о помещике Иванове"}]
    pages = [{"page": 1, "voices": {"pysar": "Дело о помещике Иванове"}}]
    m = {"schema": 2, "repo": "ДАОО", "fond": "445", "opys": "9", "language": "ru",
         "sources": [{"kind": "private", "url": "", "sha256": "0" * 64, "pages": 1,
                      "spread": False, "label": "фото"}],
         "engines": ["pysar_v31"], "license": "CC-BY-NC-SA-4.0",
         "quality": {"klass": "low", "form": "hand_ruled"}, "normalization_exchange": True}
    mm, pp, rr, parsed = G.parse(m, pages, rows)
    assert mm is not None, parsed.refusals
    verdict = G.check(mm, pp, rr)
    assert not verdict.passed
    assert any(d["rule"] == "norm_exchange_private" for d in verdict.refusal_details)


def test_manifest_bez_obminu_bez_polia(tmp_path: Path, server: dict[str, Any],
                                       chytannia: list[Path]) -> None:
    """Пакет без `--na-obmin` не несе `normalization_exchange` (сервер зі старим піном пакета
    відкидав би кожен такий маніфест); з прапорцем — несе."""
    from nyshporka.opysy import bundle as B

    d = tmp_path / "opys"
    _read_z_meta(d, pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9", url=URL, language="ru")
    for b in Path(d / "norm").glob("batch_*.json"):
        titles = json.loads(b.read_text(encoding="utf-8"))["titles"]
        b.with_name(b.stem + ".out.txt").write_text(json.dumps(titles, ensure_ascii=False),
                                                    encoding="utf-8")
    assert OO.opysy_push(OO.PushArgs(file=str(d), norm_model="m")).ok
    contents, _ = B.verify(server["pushed"][-1].read_bytes())
    assert "normalization_exchange" not in contents.manifest


def test_cli_read_zupynka_na_metadanykh_i_povnota(tmp_path: Path, server: dict[str, Any],
                                                   chytannia: list[Path],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """`nysh opys read` людині: зупинка на метаданих каже, що глянути; далі — повнота за метаданими
    й попередження, коли справ у таблиці набагато менше, ніж в описі."""
    from typer.testing import CliRunner

    from nyshporka.opysy.cli import app as opys_app

    monkeypatch.setenv("NYSH_OPYSY", "1")
    monkeypatch.setenv("COLUMNS", "300")
    r = CliRunner()
    d = tmp_path / "opys"
    res = r.invoke(opys_app, ["read", str(d), "--pdf", str(_pdf(tmp_path)), "--repo", "ДАОО", "--fond", "445",
                              "--opys", "9", "--url", URL, "--language", "ru"])
    assert res.exit_code == 0, res.output
    assert "метадані" in res.output and "глянути" in res.output and "nysh opys meta" in res.output
    res = r.invoke(opys_app, ["meta", str(d), "--forma", "blank", "--kolonky", "nomer,nazva",
                              "--sprav", "40", "--dzherelo", "засвідчувальний напис"])
    assert res.exit_code == 0, res.output
    res = r.invoke(opys_app, ["read", str(d), "--language", "ru"])
    assert res.exit_code == 0, res.output
    assert "з 40 за метаданими" in res.output and "частина справ злиплась" in res.output
    # машинопис за метаданими — відмова, як і `--form typed`
    assert r.invoke(opys_app, ["meta", str(d), "--forma", "typed"]).exit_code == 0
    res = r.invoke(opys_app, ["read", str(d), "--language", "ru"])
    assert res.exit_code == 1 and "машинописний" in res.output


def test_krop_bez_tekstu_ne_blokuie_read(tmp_path: Path, server: dict[str, Any],
                                         chytannia: list[Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Рушій пройшов кропи дочиту, а для одного тексту не записав: `read` іде до таблиці, а повтор не
    запускає дочит знову."""
    pidmina = OO._chytaty
    kropy_vyklyky: list[Path] = []

    def _chytaty(pages: Path, run: Path, script: str, whole_line: bool = False) -> int:
        if not whole_line:
            return pidmina(pages, run, script)
        kropy_vyklyky.append(pages)
        run.mkdir(parents=True, exist_ok=True)
        for k in sorted(pages.glob("*.jpg"))[1:]:            # перший кроп — без тексту
            (run / f"{k.stem}.txt").write_text("12", encoding="utf-8")
        return 0

    monkeypatch.setattr(OO, "_chytaty", _chytaty)
    d = tmp_path / "opys"
    env = _read_z_meta(d, pdf=str(_pdf(tmp_path)), repo="ДАОО", fond="445", opys="9", url=URL, language="ru")
    assert env.ok, env
    if not kropy_vyklyky:
        pytest.skip("синтетичні сторінки не дали кропів колонки №")
    assert "дочит №" in env.data["zrobleno"] and len(kropy_vyklyky) == 1
    env2 = _read(d, language="ru")
    assert env2.ok and len(kropy_vyklyky) == 1, "дочит запустився вдруге на тому самому кропі"
