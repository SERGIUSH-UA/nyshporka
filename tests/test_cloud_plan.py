"""🧮 План хмарного заходу: числа, на яких стоїть рішення «везти чи не везти».

Три речі, кожна з яких ламається БЕЗ помилки — і саме тому перевіряються тут:

* **машина бреше про залізо.** `nproc` показує ядра хоста, а не нашу частку, і
  план, побудований на них, дає вчетверо більше процесів, ніж машина тягне;
* **пам'ять карт складають.** Наївне «сума × запас ÷ на шард» щедріше за
  чесне рівно на один процес — а зайвий процес не сповільнює прогін, а завалює;
* **час передачі мовчить.** Дев'ятнадцять годин заливки виглядають так само,
  як п'ять хвилин, доки їх не назвати числом ДО старту.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.cloud import probe as P
from nyshporka.cloud import sizing as S


# ── проба заліза ─────────────────────────────────────────────────────────────
def test_host_cores_are_not_our_cores() -> None:
    """🔴 Головне про пробу: правду каже cgroup, а не `nproc`.

    Замір, який це купив: контейнер із 48 проданими ядрами показував 192, а
    `free -g` — 251 ГБ при 62.9. Довіра до заявленого числа тут дає не
    повільний прогін, а завалений.
    """
    got = P.parse([
        "nproc=192", "nproc_all=192",
        "cgroup_v2=4800000 100000",          # 48 ядер
        "mem_total_kb=263000000",            # 251 ГБ на хості
        "cgroup_mem=67553994752",            # 62.9 ГБ наші
        "gpu=24576,24000", "disk_free_gb=120.5", "python=Python 3.12.3",
    ])
    assert got.cores == 48.0, "ядра беруться з квоти, а не з `nproc`"
    assert got.cores_seen == 192.0, "видиме число теж лишається — для пояснення"
    assert got.cpu_lied is True
    assert got.ram_gb == pytest.approx(62.9, abs=0.1)


def test_cgroup_v1_quota_is_read_too() -> None:
    """Старше ядро тримає квоту в інших файлах — але бреше так само."""
    got = P.parse(["nproc=64", "cfs_quota=800000", "cfs_period=100000"])
    assert got.cores == 8.0


def test_no_quota_means_believe_what_we_see() -> None:
    """Без квоти видиме число і є правда — вигадувати обмеження не можна."""
    got = P.parse(["nproc=8", "cgroup_v2=max 100000"])
    assert got.cores == 8.0
    assert got.cpu_lied is False


def test_free_vram_is_taken_per_card_not_summed() -> None:
    """🔴 Карти рахуються поодинці, і береться ВІЛЬНА пам'ять, не паспортна.

    Поруч може рахувати чужа задача, і тоді «24 ГБ» до нас не стосуються.
    """
    got = P.parse(["nproc=32", "gpu=24576,24000", "gpu=24576,8000"])
    assert got.gpus == 2
    assert got.vram_gb_min == pytest.approx(7.81, abs=0.01), "мінімум по картах"
    assert got.has_gpu is True


def test_a_machine_without_a_card_is_not_a_failure() -> None:
    """Читання без карти йде — просто повільніше. Це не привід відмовляти."""
    got = P.parse(["nproc=16", "mem_total_kb=33000000"])
    assert got.has_gpu is False
    assert got.cores == 16.0


# ── розбиття ─────────────────────────────────────────────────────────────────
def test_shard_capacity_is_counted_per_card() -> None:
    """🔴 Дві карти по 8 ГБ дають 4 процеси, а не 5.

    Наївне `int(сума × 0.9 / на_шард)` = `int(16 × 0.9 / 2.5)` = 5. Зайвий
    процес не сповільнює прогін — сторінки падають на браку пам'яті, процес
    виходить із нульовим кодом, і підсумок мовчить.
    """
    got = S.plan_sizing(cores=64, vram_gb_min=8, gpus=2)
    assert got.shards == 4
    assert got.shards_per_gpu == 2
    assert "пам'ять карти" in got.capped_by


def test_cores_can_be_the_binding_limit() -> None:
    """Шість ядер — це три процеси, скільки б пам'яті не було на карті."""
    got = S.plan_sizing(cores=6, vram_gb_min=48, gpus=1)
    assert got.shards == 3
    assert got.capped_by == "ядра"


def test_explicit_shards_are_honoured_but_capped() -> None:
    """🔴 Людина може попросити менше — і не може попросити більше, ніж влізе.

    Щільність книги вона знає краще за нас (розворот на дві сторінки бере
    вдвічі більше пам'яті, і жодна проба цього не бачить). Але дозволити
    поставити більше фізичного — це поміняти повільний прогін на завалений.
    """
    fewer = S.plan_sizing(cores=64, vram_gb_min=24, gpus=1, shards=2)
    assert fewer.shards == 2, "менше — можна"

    more = S.plan_sizing(cores=64, vram_gb_min=8, gpus=1, shards=99)
    assert more.shards == 2, "більше за фізичне — ні"
    assert "просили 99" in more.capped_by


def test_shards_are_capped_by_how_much_work_there_is() -> None:
    """🔴 Розбиття, яке не окупається обсягом, — не повільніше, а дорожче.

    Кожен процес платить холодний старт: ваги в пам'ять карти, прогрів. На
    справі з дванадцяти кадрів вісім процесів дістануть по півтори сторінки, і
    весь захід складатиметься з самих накладних.
    """
    tiny = S.plan_sizing(cores=32, vram_gb_min=24, gpus=1, pages=12)
    assert tiny.shards == 1
    assert tiny.capped_by == "обсяг справи"

    big = S.plan_sizing(cores=32, vram_gb_min=24, gpus=1, pages=5000)
    assert big.shards == 8, "на великій справі обсяг уже не обмежує"


def test_speed_names_what_is_pressing() -> None:
    """«Чому так повільно» мусить мати відповідь у самому плані."""
    by_cores = S.plan_sizing(cores=4, vram_gb_min=48, gpus=1)
    assert by_cores.limited_by == "ядра"

    by_shards = S.plan_sizing(cores=256, vram_gb_min=8, gpus=1)
    assert by_shards.limited_by == "шарди"


def test_cold_start_is_always_paid() -> None:
    """🔴 Саме накладні роблять невигідним хмарний прогін маленької справи.

    Вісім хвилин підготовки не залежать від обсягу — і на тридцяти кадрах вони
    і є весь захід.
    """
    sizing = S.plan_sizing(cores=32, vram_gb_min=24, gpus=1)
    small = S.predict_hours(30, sizing)
    assert small > 0.13, "накладні не зникають на дрібній справі"
    assert S.predict_hours(30, sizing, warm=True) < small


def test_cost_is_none_when_the_machine_is_ours() -> None:
    """Своя машина не коштує погодинно — і вигадувати ціну не можна."""
    sizing = S.plan_sizing(cores=8, vram_gb_min=8, gpus=1)
    assert S.predict_cost(100, sizing, None) is None
    assert S.predict_cost(100, sizing, 0.25) is not None


def test_a_machine_without_measured_cores_is_refused() -> None:
    """Нуль ядер — не «повільно», а «плану немає з чого будувати»."""
    with pytest.raises(S.SizingError):
        S.plan_sizing(cores=0, vram_gb_min=24, gpus=1)


# ── канал передачі ───────────────────────────────────────────────────────────
def test_slow_channel_is_reported_with_a_number() -> None:
    """🔴 Порада без числа — смак; із числом — рішення.

    «Візьміть сховище» нічого не важить, доки поруч не стоїть «інакше заливка
    триватиме дев'ять годин».
    """
    from nyshporka.cloud.transfer import Speed, pick_channel

    slow = Speed(mb_per_sec=0.45, how="замір")
    channel, why = pick_channel(nbytes=31 * 10 ** 9, storage=None, sftp=slow)
    assert channel == "sftp"
    assert "год" in why and "⚠" in why


def test_small_case_over_sftp_needs_no_warning() -> None:
    """Дрібна справа їде напряму без жодних порад — інакше вони знеціняться."""
    from nyshporka.cloud.transfer import Speed, pick_channel

    _, why = pick_channel(nbytes=200 * 10 ** 6, storage=None,
                          sftp=Speed(mb_per_sec=5.0, how="замір"))
    assert "⚠" not in why


def test_presigned_name_drops_the_query() -> None:
    """🔴 Підпис у посиланні не має ставати частиною імені файла.

    Інакше на машині з'являється `case.tar?…`, і розпакування падає з помилкою
    ЗАПИСУ — діагнозом, який веде розслідування зовсім не туди.
    """
    from nyshporka.cloud.transfer import name_from_url

    got = name_from_url("https://s3.example/bucket/nysh/run/case.tar"
                        "?X-Amz-Algorithm=AWS4&X-Amz-Expires=3600")
    assert got == "case.tar"


# ── план цілком ──────────────────────────────────────────────────────────────
@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    (tmp_path / "data" / "spotter" / "models").mkdir(parents=True)
    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return tmp_path


def test_plan_refuses_a_folder_with_frames_in_subfolders(space: Path,
                                                         monkeypatch) -> None:
    """🔴 Тека з підтеками читається як ПОРОЖНЯ — і мовчки.

    Раннер не рекурсивний, тож справа, розкладена по підтеках, дала б нуль
    сторінок без жодної помилки. Ціна помилки на чужій машині вища за локальну:
    туди вже поїхали гігабайти.
    """
    from nyshporka.cloud import plan as PL

    case = space / "case"
    (case / "part1").mkdir(parents=True)
    (case / "part1" / "0001.jpg").write_bytes(b"\0")
    with pytest.raises(PL.PlanError, match="підтек"):
        PL.build(case)


def _wire_case(space: Path, monkeypatch, name: str = "case") -> Path:
    """Тека з кадрами, вагами напоготові й без шифри."""
    from nyshporka.htr import run as R

    case = space / name
    case.mkdir()
    for i in range(3):
        (case / f"{i:04d}.jpg").write_bytes(b"\0" * 100)
    monkeypatch.setattr(R, "pick_model",
                        lambda script, second_voice=True: (space / "m.pt", None))
    monkeypatch.setattr(R, "case_key_for", lambda d: ("", ""))
    return case


def test_plan_says_when_the_case_key_is_missing(space: Path, monkeypatch) -> None:
    """🔴 Прогін без шифри лягає «нічиїм»: текст є, а до якої справи — невідомо."""
    from nyshporka.cloud import plan as PL

    case = _wire_case(space, monkeypatch)
    got = PL.build(case, script="cyrillic")
    assert got.frames == 3
    assert any("нічиїм" in w for w in got.warnings)


def test_plan_refuses_when_the_script_is_unknown(space: Path, monkeypatch) -> None:
    """🔴 «Не знаю, яке письмо» — відмова, а не мовчазна кирилиця.

    Невідповідність рушія письму не дає збою: текст виходить, впевненість не
    падає, і виглядає це як погані скани. Локально ціна помилки — ніч прогону;
    у хмарі до неї додається заливка гігабайтів і час чужої машини.
    """
    from nyshporka.cloud import plan as PL

    case = _wire_case(space, monkeypatch, name="spr-90")
    with pytest.raises(PL.PlanError, match="не визначається"):
        PL.build(case)


def test_a_guessed_script_is_said_out_loud(space: Path, monkeypatch) -> None:
    """Здогад лишається здогадом — і про це мусить бути сказано в плані."""
    from nyshporka.cloud import plan as PL

    case = _wire_case(space, monkeypatch, name="kostel_1820")
    got = PL.build(case)
    assert got.script == "latin"
    assert any("ВГАДАНО" in w for w in got.warnings)
