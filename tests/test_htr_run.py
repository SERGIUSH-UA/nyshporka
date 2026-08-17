"""▶️ Вибір моделі й план прогону: тут помилка коштує ночі й тихого сміття.

Три речі, кожна з яких ламається БЕЗ помилки:

* **не та версія ваг** — читання йде, текст виходить, просто гірший. «Найновіша»
  ≠ «найкраща»: бойовою двічі лишалась не остання версія;
* **не те письмо** — невідповідність рушія письму дає сміття без падіння
  впевненості, і виглядає це як погані скани;
* **тека з підтеками** — раннер не рекурсивний і читає її як порожню.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.htr import run as R


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір із текою ваг і порожнім кешем паків."""
    models = tmp_path / "data" / "spotter" / "models"
    models.mkdir(parents=True)
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return models


def _weights(models: Path, *names: str) -> None:
    for n in names:
        (models / n).write_bytes(b"\0" * 16)


# ── вибір моделі ─────────────────────────────────────────────────────────────
def test_production_file_wins_over_the_newest(space: Path) -> None:
    """🔴 Головне. «Найновіша» ≠ «найкраща», і файл дослідника це вирішує.

    Без нього вибір падає на найбільший номер версії — тобто мовчки на гіршу
    модель там, де пізніша програла на голдовому зрізі.
    """
    _weights(space, "pysar_cyr_v16.pt", "pysar_cyr_v17.pt", "pysar_cyr_v18.pt")
    (space / R.PRODUCTION_NAME).write_text(
        json.dumps({"production": {"cyrillic": {"model": "pysar_cyr_v17.pt"}}}),
        encoding="utf-8")
    main, _ = R.pick_model("cyrillic")
    assert main.name == "pysar_cyr_v17.pt"


def test_without_production_file_the_highest_version_wins(space: Path) -> None:
    """Без вказівки — найвища версія, а не перша за абеткою.

    Абеткою `pysar_cyr_v1.pt` іде поперед `v17`, і саме так виглядала перша
    реалізація: читання йшло найстарішими вагами й нічим про це не казало.
    """
    _weights(space, "pysar_cyr_v1.pt", "pysar_cyr_v9.pt", "pysar_cyr_v17.pt")
    main, _ = R.pick_model("cyrillic")
    assert main.name == "pysar_cyr_v17.pt"


def test_script_comes_from_the_name_prefix_not_the_extension(space: Path) -> None:
    """🔴 `.mlmodel` буває ДВОХ письм: `skryba_*` латинка, `diak_*` кирилиця.

    Вибір «за розширенням» поставив би на латинську справу кириличну модель —
    і це тихе сміття, а не помилка.
    """
    _weights(space, "skryba_f792_v6.mlmodel", "diak_cyr_v4.mlmodel")
    lat, lat_voice = R.pick_model("latin")
    assert lat.name.startswith("skryba")
    assert lat_voice is None, "у латинки другого голосу немає"
    cyr, _ = R.pick_model("cyrillic")
    assert cyr.name.startswith("diak")


def test_second_voice_is_a_different_engine(space: Path) -> None:
    """Другий голос має помилятись ІНАКШЕ, інакше він марний.

    CTC прив'язаний до пікселів і калічить локально, зберігаючи корінь; PARSeq
    має мовну модель і підставляє правдоподібне слово. Два PARSeq'и такої
    користі не дали б.
    """
    _weights(space, "pysar_cyr_v17.pt", "diak_cyr_v4.mlmodel")
    main, voice = R.pick_model("cyrillic", second_voice=True)
    assert main.suffix == ".pt" and voice is not None
    assert voice.suffix == ".mlmodel"
    _, none = R.pick_model("cyrillic", second_voice=False)
    assert none is None


def test_no_weights_is_a_message_not_a_crash(space: Path) -> None:
    with pytest.raises(R.ReadError, match="моделі письма"):
        R.pick_model("cyrillic")


def test_missing_script_names_what_is_available(space: Path) -> None:
    _weights(space, "diak_cyr_v4.mlmodel")
    with pytest.raises(R.ReadError, match="latin"):
        R.pick_model("latin")


# ── план ─────────────────────────────────────────────────────────────────────
def test_nested_folders_are_explained_not_reported_as_empty(space: Path,
                                                            tmp_path: Path) -> None:
    """🔴 `--case-dir` НЕ рекурсивний.

    Тека з підтеками читається як порожня — «у теці немає сторінок». Це
    коштувало прогонів, тож пояснення мусить називати причину, а не наслідок.
    """
    case = tmp_path / "справа"
    (case / "плівка_01").mkdir(parents=True)
    (case / "плівка_01" / "0001.jpg").write_bytes(b"\0")
    with pytest.raises(R.ReadError, match="підтек"):
        R.plan(case)


def test_empty_folder_says_so(tmp_path: Path) -> None:
    case = tmp_path / "порожня"
    case.mkdir()
    with pytest.raises(R.ReadError, match="немає зображень"):
        R.plan(case)


def test_frames_are_counted_flat_like_the_runner_sees_them(tmp_path: Path) -> None:
    case = tmp_path / "справа"
    (case / "під").mkdir(parents=True)
    for n in ("0001.jpg", "0002.JPG", "нотатки.txt"):
        (case / n).write_bytes(b"\0")
    (case / "під" / "0003.jpg").write_bytes(b"\0")
    assert R.count_frames(case) == 2, "порахувались підтеки або чужі файли"


def test_command_carries_the_second_voice_and_progress_channel(tmp_path: Path) -> None:
    plan = R.Plan(case_dir=tmp_path, out_dir=tmp_path / "out",
                  model=tmp_path / "pysar_cyr_v17.pt", script="cyrillic",
                  frames=10, python=tmp_path / "python.exe",
                  runner=tmp_path / "runner.py",
                  voice=tmp_path / "diak_cyr_v4.mlmodel")
    cmd = plan.command(case_key="DAHMO/315/8433")
    assert "--models" in cmd and "--progress-json" in cmd
    assert cmd[cmd.index("--case-key") + 1] == "DAHMO/315/8433"
    assert "--script" in cmd and cmd[cmd.index("--script") + 1] == "cyrillic"


# ── важелі ресурсів ──────────────────────────────────────────────────────────
def _plan(tmp_path: Path):
    from nyshporka.htr.run import Plan

    return Plan(case_dir=tmp_path / "справа", out_dir=tmp_path / "out",
                model=tmp_path / "m.pt", script="cyrillic", frames=100,
                python=tmp_path / "py.exe", runner=tmp_path / "runner.py")


def test_resource_levers_reach_the_runner(tmp_path: Path) -> None:
    """🔴 Машина в кожного своя, і без важелів відповіддю на «не тягне»
    лишалось би «купіть іншу карту».

    Раннер має ці ручки від початку, але доступні вони були лише прямим
    викликом — тобто рівно та людина, якій найбільше треба стиснути прогін під
    слабку карту, важелів не мала.
    """
    cmd = _plan(tmp_path).command(shard="1/3", gpu_lock=str(tmp_path / "x.lock"),
                                  gpu_sato=False, seg_height=1440,
                                  pages="1-50", limit=10)
    assert "--shard" in cmd and cmd[cmd.index("--shard") + 1] == "1/3"
    assert "--gpu-lock" in cmd
    assert "--no-gpu-sato" in cmd, "sato лишився на карті — шарди стануть у чергу"
    assert "--seg-height" in cmd and cmd[cmd.index("--seg-height") + 1] == "1440"
    assert "--pages" in cmd and "--limit" in cmd


def test_default_run_carries_no_levers(tmp_path: Path) -> None:
    """Дефолт лишається тим самим: важіль з'являється лише коли його попросили.

    Інакше кожен звичайний прогін мовчки міняв би поведінку — і різницю в
    результаті приписали б моделі, а не прапорцю.
    """
    cmd = _plan(tmp_path).command()
    for flag in ("--shard", "--gpu-lock", "--no-gpu-sato", "--seg-height",
                 "--pages", "--limit"):
        assert flag not in cmd, f"{flag} просочився у звичайний прогін"


def test_sato_flag_is_negative_only(tmp_path: Path) -> None:
    """⚠ `--gpu-sato` за замовчуванням УВІМКНЕНИЙ у раннері, тож передавати
    його ствердно немає сенсу — а от зняття мусить бути явним."""
    assert "--gpu-sato" not in _plan(tmp_path).command(gpu_sato=True)
    assert "--no-gpu-sato" in _plan(tmp_path).command(gpu_sato=False)
