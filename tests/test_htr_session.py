"""Спільне читання справи: одна функція для `nysh read` і черги справ.

⚠ Дитина друкує латинкою: її stdout на Windows без UTF-8 — cp1252, і кирилиця
в `print` валила б саму дитину, а не те, що тут перевіряється.

⚠ Раннер підмінено малим справжнім процесом: перевіряється обв'язка — запуск,
реєстр живих прогонів, зупинка на прохання, повнота з диска, — а не рушій.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import workspace as W
from nyshporka.htr import session as S


class _Plan:
    def __init__(self, case: Path, out: Path, code: str) -> None:
        self.case_dir = case
        self.out_dir = out
        self.frames = 3
        self.gpu_lock = out.parent / "gpu.lock"
        self.code = code
        self.asked: list[dict[str, Any]] = []

    def command(self, **kw: Any) -> list[str]:
        self.asked.append(kw)
        return [sys.executable, "-c", self.code, str(self.out_dir)]

    def shards(self, workers: int, **kw: Any) -> tuple[list[list[str]], list[str]]:
        self.asked.append({"workers": workers, **kw})
        return [self.command() for _ in range(workers)], ["шарди"]


@pytest.fixture
def case(tmp_path: Path):
    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "skany"
    d.mkdir()
    for n in (1, 2, 3):
        (d / f"{n:04d}.jpg").write_bytes(b"x")
    yield d, tmp_path / "reports" / "htr" / "skany"
    W.reset()


PYSHE = ("import sys, pathlib\n"
         "out = pathlib.Path(sys.argv[1])\n"
         "for n in (1, 2, 3):\n"
         "    (out / f'{n:04d}.txt').write_text('x', encoding='utf-8')\n"
         "    print('page', n, flush=True)\n")

VYSNE = ("import sys, time, pathlib\n"
         "out = pathlib.Path(sys.argv[1])\n"
         "(out / '0001.txt').write_text('x', encoding='utf-8')\n"
         "print('first', flush=True)\n"
         "time.sleep(120)\n")


def test_dochytane_tse_povno_i_reiestr_chystyi(case) -> None:
    from nyshporka.htr import runs as R

    d, out = case
    seen: list[str] = []
    got = S.read_case(_Plan(d, out, PYSHE), case_key="DAHMO/315/1",
                      on_event=lambda ev, human: seen.append(human or ""))

    assert got.ok and (got.done, got.missing, got.stopped) == (3, 0, False)
    assert "page 3" in seen
    assert R.alive() == []


def test_zupynka_na_prokhannia_lyshaie_prochytane(case, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 «Зупинись» гасить раннер, а не чекає його дві хвилини — і сторінка,
    що вже лягла, лишається: наступний запуск у ту саму теку її пропустить."""
    from nyshporka.htr import runs as R

    monkeypatch.setattr(S, "STOP_POLL_SEC", 0.1)
    import time

    d, out = case
    t0 = time.monotonic()
    got = S.read_case(_Plan(d, out, VYSNE), should_stop=lambda: (out / "0001.txt").exists())

    assert time.monotonic() - t0 < 60, "раннер не погашено: досидів свої дві хвилини"
    assert got.stopped and not got.ok
    assert (got.done, got.missing) == (1, 2)
    assert R.alive() == []


def test_chastkovyi_prohin_povnoty_ne_miriaie(case) -> None:
    d, out = case
    got = S.read_case(_Plan(d, out, "import sys"), limit=1)

    assert got.partial and got.missing == 0


def test_kilka_protsesiv_cherez_shardy_planu(case) -> None:
    """Шард, спільний лок і зняте з карти sato народжуються в плані разом —
    функція читання їх поодинці не складає."""
    d, out = case
    plan = _Plan(d, out, PYSHE)
    got = S.read_case(plan, workers=2, device="cuda", case_key="K")

    assert plan.asked[0] == {"workers": 2, "device": "cuda", "case_key": "K",
                             "limit": 0, "pages": "", "seg_height": 0}
    assert got.ok and got.notes == ("шарди",)


def test_odyn_protses_bere_lok_z_planu(case) -> None:
    d, out = case
    plan = _Plan(d, out, PYSHE)
    S.read_case(plan)

    assert plan.asked[0]["gpu_lock"] == str(plan.gpu_lock)


def test_dytyna_ne_uspadkovuie_chuzhoho_pythonhome(case, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 `uv run` ставить `PYTHONHOME` на свій Python; інтерпретатор рушіїв
    іншої версії з ним падає на `import re`, і назовні це було «середовище
    рушіїв не готове» при повному середовищі (30.09.2026)."""
    from nyshporka.htr.env import foreign_env

    monkeypatch.setenv("PYTHONHOME", "C:/chuzhyi/python")
    monkeypatch.setenv("VIRTUAL_ENV", "C:/chuzhyi/.venv")
    monkeypatch.setenv("NYSH_TEST_KEEP", "1")
    env = foreign_env({"OMP_NUM_THREADS": "2"})
    assert "PYTHONHOME" not in env and "VIRTUAL_ENV" not in env
    assert env["NYSH_TEST_KEEP"] == "1" and env["OMP_NUM_THREADS"] == "2"

    d, out = case
    code = ("import os, sys, pathlib; out = pathlib.Path(sys.argv[1])\n"
            "home = os.environ.get('PYTHONHOME', '')\n"
            "for n in (1, 2, 3):\n"
            "    (out / f'{n:04d}.txt').write_text(home, encoding='utf-8')\n")
    S.read_case(_Plan(d, out, code))
    assert (out / "0001.txt").read_text(encoding="utf-8") == ""


ONUK = ("import subprocess, sys, pathlib\n"
        "out = pathlib.Path(sys.argv[1])\n"
        "(out / '0001.txt').write_text('x', encoding='utf-8')\n"
        "kid = subprocess.Popen([sys.executable, '-c', "
        "'import os, sys, time, pathlib; "
        "pathlib.Path(sys.argv[1], \"onuk.pid\").write_text(str(os.getpid())); "
        "[(print(\"page\", flush=True), time.sleep(0.2)) for _ in range(3000)]', "
        "str(out)])\n"
        "kid.wait()\n")


def test_zupynka_hasyt_i_robochyi_protses_ranera(case, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Раннер читає руками свого робочого процесу. Погасивши лише батька,
    «зупинити зараз» дочитувало справу до кінця: онук тримав канал виводу й
    карту (живий прогін 30.09.2026)."""
    import time

    psutil = pytest.importorskip("psutil")
    monkeypatch.setattr(S, "STOP_POLL_SEC", 0.1)
    d, out = case
    t0 = time.monotonic()
    got = S.read_case(_Plan(d, out, ONUK),
                      should_stop=lambda: (out / "onuk.pid").exists())

    assert got.stopped and time.monotonic() - t0 < 60, "онук читав далі"
    pid = int((out / "onuk.pid").read_text())
    time.sleep(0.5)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == "zombie"

