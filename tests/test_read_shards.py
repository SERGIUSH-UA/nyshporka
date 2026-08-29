"""⚡ Шардинг: найпоширеніша помилка мусить стати невимовною.

Прогін справи — найдовша робота застосунку, і єдиний спосіб її пришвидшити на
машині, що є, — розкласти сторінки між кількома процесами. Але важелів там три,
і працюють вони лише разом:

  `--shard k/n`   цей процес бере кожен n-й кадр;
  `--gpu-lock`    спільний файл-лок на GPU-фазу;
  `--no-gpu-sato` найдорожча фаза рахується на ядрах, а не на карті.

🔴🔴 `--shard` без спільного лока на одній карті не сповільнює прогін — він
його завалює: два одночасні проходи сегментації не влазять у пам'ять типової
карти. А без знятого sato шардинг здебільшого не дає нічого: найдорожча фаза
йде під локом, і процеси стають у чергу замість паралельної роботи.

Доти цю помилку можна було виразити, і командний рядок її лише називав
застереженням. Приймаючи одне число замість трьох прапорців, ми робимо її
невимовною — а цей файл стежить, щоб вона не стала виразною знову.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from nyshporka.htr.run import Plan, shard_env


@pytest.fixture
def plan(tmp_path: Path) -> Plan:
    return Plan(
        case_dir=tmp_path / "case",
        out_dir=tmp_path / "out",
        model=tmp_path / "pysar_cyr_v4.pt",
        script="cyrillic",
        frames=100,
        python=tmp_path / "python.exe",
        runner=tmp_path / "runner.py",
        gpu_lock=tmp_path / "out" / "_gpu.lock",
    )


def _flags(cmd: list[str]) -> set[str]:
    return {a for a in cmd if a.startswith("--")}


@pytest.mark.parametrize("workers", [2, 3, 4, 8])
def test_shard_never_travels_without_its_two_companions(plan: Plan,
                                                        workers: int) -> None:
    """🔴 Три прапорці або є всі троє, або немає жодного."""
    cmds, _ = plan.shards(workers, device="cuda:0")
    assert len(cmds) == workers, "число процесів не збіглося з числом шардів"
    for cmd in cmds:
        f = _flags(cmd)
        assert "--shard" in f, "шард без свого номера"
        assert "--gpu-lock" in f, (
            "🔴 шард без спільного лока — саме та комбінація, що завалює прогін")
        assert "--no-gpu-sato" in f, (
            "шардинг без знятого sato: найдорожча фаза лишиться під локом, і "
            "процеси стануть у чергу замість паралельної роботи")


def test_all_shards_share_one_and_the_same_lock(plan: Plan) -> None:
    """Лок мусить бути один на всіх. Різні локи не боронять нічого."""
    cmds, _ = plan.shards(3, device="cuda:0")
    locks = {cmd[cmd.index("--gpu-lock") + 1] for cmd in cmds}
    assert len(locks) == 1, f"шарди взяли різні локи: {sorted(locks)}"


def test_one_process_does_not_pay_the_sharding_tax(plan: Plan) -> None:
    """Один процес не бере ні `--shard`, ні зняття sato.

    ⚠ Зняти sato з карти в однопроцесному прогоні — чистий податок на процесор:
    вигравати нема в кого, бо в черзі за карткою ніхто не стоїть.
    """
    cmds, _ = plan.shards(1, device="cuda:0")
    assert len(cmds) == 1
    f = _flags(cmds[0])
    assert not ({"--shard", "--no-gpu-sato"} & f), (
        f"однопроцесний прогін тягне важелі шардингу: {sorted(f)}")


def test_one_process_still_takes_the_card_lock(plan: Plan) -> None:
    """🔴 А от лок карти бере — і це НЕ податок шардингу.

    Різниця в тому, з ким змагаються. `--no-gpu-sato` і `--shard` мають сенс
    лише всередині одного прогону, тож одиночному вони справді нічого не дають.
    Лок же захищає від ДРУГОГО ПРОГОНУ — а `workers.ReadArgs.workers` типово
    дорівнює одиниці, тобто саме одиночний прогін і є звичайним випадком.
    Доти ця гілка команду без лока й віддавала, і два `nysh read` з термінала
    (або термінал плюс застосунок) заходили на карту разом — рівно той звіт,
    з якого почалась ця правка. Черга в демоні сюди не дістає: вона не бачить
    прогонів командного рядка, а карта в них спільна.
    ⚠ Уконтендованому випадку лок безкоштовний — це один файл і один `flock`.
    """
    cmds, _ = plan.shards(1, device="cuda:0")
    f = _flags(cmds[0])
    assert "--gpu-lock" in f, "одиночний прогін лишився без лока карти"
    # І лок той САМИЙ, що взяли б шарди, — інакше він нікого не виключає.
    many, _ = plan.shards(3, device="cuda:0")
    one = cmds[0][cmds[0].index("--gpu-lock") + 1]
    rest = {c[c.index("--gpu-lock") + 1] for c in many}
    assert rest == {one}, f"одиночний прогін узяв інший лок: {one} проти {rest}"


def test_shards_collapse_on_a_processor_and_say_so(plan: Plan) -> None:
    """На процесорі шарди не діляться карткою — вони б'ються за ті самі ядра."""
    cmds, notes = plan.shards(4, device="cpu")
    assert len(cmds) == 1, "на CPU шарди мали згорнутись до одного"
    assert notes and any("ядра" in n for n in notes), (
        "згортання мовчазне: людина попросила чотири процеси й не дізналась, "
        "чому їх один")


def test_no_caller_can_ask_for_a_shard_alone(plan: Plan) -> None:
    """🔴 Головне: подати шард без лока не можна зверху.

    Приймач тримається за поверхню, а не за поведінку: доки `shards()` єдиний
    спосіб отримати кілька процесів, а сам він робить три прапорці разом,
    помилку виразити нічим. Якщо колись з'явиться другий шлях — цей тест
    змусить це помітити.
    """
    sig = inspect.signature(Plan.shards)
    assert "workers" in sig.parameters, "шарди задаються одним числом"
    for banned in ("shard", "gpu_lock", "gpu_sato"):
        assert banned not in sig.parameters, (
            f"«{banned}» знову можна подати повз замок — саме так і виражається "
            f"комбінація, що завалює прогін")


def test_the_lock_belongs_to_the_output_folder(plan: Plan, tmp_path: Path) -> None:
    """Лок — властивість теки виходу, а не аргумент виклику."""
    cmds, _ = plan.shards(2, device="cuda:0")
    lock = cmds[0][cmds[0].index("--gpu-lock") + 1]
    assert Path(lock).parent == tmp_path / "out", (
        "лок ліг не в теку виходу — два прогони однієї справи візьмуть різні")


def test_shard_env_splits_the_cores_and_leaves_one_alone() -> None:
    """Кожен шард бере частку ядер під BLAS, а один процес — нічого не змінює.

    🔴 Без цього кожен шард бачить усі ядра машини й забирає їх під матричні
    операції: три процеси по вісім потоків на восьми ядрах душать одне одного
    рівно там, де прогін і впирається.
    """
    assert shard_env(1) == {}, "однопроцесний прогін не має чого ділити"
    env = shard_env(3)
    assert env, "шарди пішли без обмеження потоків"
    assert set(env) >= {"OMP_NUM_THREADS", "MKL_NUM_THREADS"}
    assert all(int(v) >= 1 for v in env.values()), "нуль потоків не буває"


# ── приймач повноти ──────────────────────────────────────────────────────────
def test_completeness_counts_the_disk_not_the_exit_code(tmp_path: Path) -> None:
    """🔴 Є клас відмов, за якого сторінка вбиває процес: лог обривається,
    перелік збоїв порожній, код повернення успішний. Виміряний випадок — 14
    сторінок із 18. Єдине, що це ловить, — число готових текстів проти кадрів.
    """
    from nyshporka.htr.run import completeness

    case, out = tmp_path / "case", tmp_path / "out"
    case.mkdir()
    out.mkdir()
    for i in range(18):
        (case / f"{i:04d}.jpg").write_bytes(b"x")
    for i in range(14):
        (out / f"{i:04d}.txt").write_text("текст", encoding="utf-8")

    got = completeness(case, out)
    assert got["frames"] == 18 and got["pages"] == 14
    assert got["missing"] == 4, "тиха втрата сторінок пройшла повз приймач"
    assert got["ok"] is False


def test_a_deliberately_partial_run_is_not_called_incomplete(tmp_path: Path) -> None:
    """⚠ При `--limit`/`--pages` прочитано менше навмисно.

    Червоне на здоровому прогоні привчає відмахуватись від приймача — і тоді
    він не спрацює тоді, коли справді треба.
    """
    from nyshporka.htr.run import completeness

    case, out = tmp_path / "case", tmp_path / "out"
    case.mkdir()
    out.mkdir()
    for i in range(50):
        (case / f"{i:04d}.jpg").write_bytes(b"x")
    (out / "0000.txt").write_text("текст", encoding="utf-8")

    got = completeness(case, out, partial=True)
    assert got["missing"] == 0 and got["ok"] is True
    assert got["partial"] is True, "частковість прогону загубилась у відповіді"
