"""База трену з хабу і чекпойнти — не довільний pickle (аудит 29.09.2026).

Раннер трену — гість середовища рушіїв, тож він вантажиться тут файлом, а
мережа підміняється фальшивим `huggingface_hub`: жодного справжнього
завантаження тест не робить.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import tarfile
import types
from pathlib import Path
from typing import Any

import pytest

torch = pytest.importorskip("torch")

RUNNER = (Path(__file__).resolve().parent.parent / "src" / "nyshporka" / "train"
          / "guest" / "parseq_train_runner.py")
REPO = "Hukyl/parseq-s-cyrillic-handwritten"


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    spec = importlib.util.spec_from_file_location("_ptrain_under_test", RUNNER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Лог раннера пишеться в KAGGLE_WORKING — не в корінь диска.
    monkeypatch.setattr(mod, "KAGGLE_WORKING", tmp_path / "out")
    mod._LOG_LINES.clear()
    yield mod
    if mod._LOG_FH[0] is not None:
        mod._LOG_FH[0].close()


def _weights(dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model_state": {"w": torch.zeros(2)}, "charset": "аб",
                "config": {"img_height": 32}}, dest)
    return hashlib.sha256(dest.read_bytes()).hexdigest()


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Фальшивий хаб: віддає файл зі «снапшота» і записує, що в нього просили."""
    best = tmp_path / "hub" / "snapshots" / "c0ffee" / "best.pt"
    got: dict[str, Any] = {"sha": _weights(best), "calls": []}

    def hf_hub_download(repo_id: str, filename: str, revision: Any = None) -> str:
        got["calls"].append((repo_id, filename, revision))
        return str(best)

    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(hf_hub_download=hf_hub_download))
    return got


def test_pin_zbihsia_vahy_vantazhatsia_z_reviziieiu(runner: Any, hub: dict[str, Any]) -> None:
    state, charset, _ = runner._load_pretrained(
        {"pretrained": f"{REPO}@c0ffee#{hub['sha'].upper()}"}, [])
    assert charset == "аб" and "w" in state
    assert hub["calls"] == [(REPO, "best.pt", "c0ffee")]


def test_pin_ne_zbihsia_vidmova_do_torch_load(runner: Any, hub: dict[str, Any],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*_: Any, **__: Any) -> None:
        raise AssertionError("torch.load до звірки sha256")

    monkeypatch.setattr(torch, "load", never)
    with pytest.raises(RuntimeError, match="sha256"):
        runner._load_pretrained({"pretrained": f"{REPO}#{'0' * 64}"}, [])


def test_bez_pina_hromke_poperedzhennia_z_sha(runner: Any, hub: dict[str, Any]) -> None:
    runner._load_pretrained({"pretrained": REPO}, [])
    assert hub["calls"] == [(REPO, "best.pt", None)]
    warn = [x for x in runner._LOG_LINES if "НЕ запіновано" in x]
    assert warn and hub["sha"] in warn[0] and f"{REPO}@c0ffee#" in warn[0]


def test_kryvyi_pin_vidmova(runner: Any, hub: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError, match="64"):
        runner._load_pretrained({"pretrained": f"{REPO}#abc"}, [])
    assert not hub["calls"]


class _Gadget:
    """Не тензор і не словник — такого в чекпойнті раннера не буває."""


def test_resume_ne_vykonuie_dovilnyi_pickle(runner: Any, tmp_path: Path) -> None:
    root = tmp_path / "in"
    root.mkdir()
    torch.save({"epoch": 1, "evil": _Gadget()}, root / runner.RESUME_NAME)
    with pytest.raises(RuntimeError, match="не чистий чекпойнт"):
        runner._load_resume({"resume": True}, [root])


def test_resume_povnyi_stan_vantazhytsia(runner: Any, tmp_path: Path) -> None:
    """Те, що пише сам раннер (оптимізатор, OneCycle, скейлер), — вантажиться."""
    m = torch.nn.Linear(3, 2)
    opt = torch.optim.AdamW(m.parameters(), lr=3e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-4, total_steps=10,
                                                cycle_momentum=False)
    m(torch.randn(1, 3)).sum().backward()
    opt.step()
    sched.step()
    root = tmp_path / "in"
    root.mkdir()
    torch.save({"model_state": m.state_dict(), "optimizer": opt.state_dict(),
                "scheduler": sched.state_dict(), "scaler": None, "epoch": 2,
                "best_cer": 0.1, "ref_cer": 0.1, "stale": 0, "charset": "аб",
                "config": {"img_height": 32}, "history": [{"val_cer": 0.1}],
                "baseline": None, "fingerprint": {"n_train": 5}},
               root / runner.RESUME_NAME)
    got = runner._load_resume({"resume": True}, [root])
    assert got["epoch"] == 2 and "state" in got["optimizer"]


def test_zapasne_rozpakuvannia_ne_vypuskaie_za_teku(runner: Any, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    with tarfile.open(inp / "corpus.tgz", "w:gz") as tar:
        blob = b"evil"
        info = tarfile.TarInfo("../../evil.txt")
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))
    monkeypatch.setattr(runner, "KAGGLE_INPUT", inp)
    monkeypatch.setattr(runner, "EXTRACT", tmp_path / "x" / "y" / "extract")

    def no_tar(*_: Any, **__: Any) -> None:
        raise FileNotFoundError("tar")

    monkeypatch.setattr(runner.subprocess, "run", no_tar)
    with pytest.raises(tarfile.FilterError):
        runner._extract_inputs()
    assert not (tmp_path / "x" / "evil.txt").exists()


# ── рецепт: форма піна перевіряється в плані ─────────────────────────────────

def test_recept_pryimaie_pin_i_vidmovliaie_kryvyi() -> None:
    from nyshporka.train.recipes import TrainParams

    sha = "AB" * 32
    got = TrainParams(pretrained=f"{REPO}@c0ffee#{sha}")
    assert got.pretrained == f"{REPO}@c0ffee#{sha.lower()}"
    assert TrainParams(pretrained=REPO).pretrained == REPO
    with pytest.raises(ValueError, match="sha256"):
        TrainParams(pretrained=f"{REPO}#123")


def test_gpurunner_ne_prypuskaie_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.train.compute import TrainJob
    from nyshporka.train.compute import gpurunner as G
    from nyshporka.train.recipes import TrainParams

    monkeypatch.setattr(G, "which", lambda: "gpurunner")
    def plan_for(base: str) -> Any:
        params = {**TrainParams(pretrained=base).as_params(), "modal_volume": "vol"}
        job = TrainJob(run_id="r", corpus_name="c", corpus_tgz=Path("c.tgz"),
                       params=params, backend="modal")
        return G.GpurunnerTrainer().plan(job)

    assert plan_for(REPO).ok
    pinned = plan_for(f"{REPO}@c0ffee#{'a' * 64}")
    assert not pinned.ok and any("пін бази" in w for w in pinned.warnings)
