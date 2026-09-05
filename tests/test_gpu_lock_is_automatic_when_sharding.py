"""Шарди на одній карті мусять брати лок GPU-фази без нагадування.

Тут стояло попередження в лозі — і воно не працювало: тоне серед решти рядків, а
кожен, хто запускає шарди руками (щоб щось поміряти), іде без лока. Хмарний
раннер передає його завжди, тобто бойовий і ручний шляхи розходяться саме там,
де ручний найлегше зіпсувати.

⚠ Лок купує НЕ швидкість. Замір 05.09.2026 (2 шарди, 8 густих сторінок,
повтори): 21.8 с/стор із локом проти 21.9 без — різниці немає. Сенс у піках
VRAM: без лока forward'и шардів збігаються, і що більший флот, то ймовірніше
карта вичерпується. Саме тому `--gpu-lock` описаний як обов'язковий при
`--shard` на одній карті.

🪤 Перша редакція цього файла посилалась на «зависання без лока — 2868 с на 173 с
рахунку». Це був СОН МАШИНИ, а не вада: ціна сторінки в тому прогоні лишилась
нормальною (21.68 с), роз'їхався лише годинник. Настінний час на локальній
машині не є доказом; на нього спирався один-єдиний висновок, і той виявився
хибним.
"""

from __future__ import annotations

import re
from pathlib import Path

from nyshporka.htr.runner import _device_slug

RUNNER_SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "runner.py"


def test_lock_name_separates_cards() -> None:
    """🔴 Спільний лок на всі карти звів би багатокартковість нанівець: шарди на
    cuda:0 і cuda:1 чекали б одне одного без жодної причини."""
    assert _device_slug("cuda:0") == "cuda0"
    assert _device_slug("cuda:1") == "cuda1"
    assert _device_slug("cuda:0") != _device_slug("cuda:1")
    assert _device_slug("cuda") == "cuda"
    # Ім'я мусить лишатись придатним для файлової системи за будь-якого входу.
    assert re.fullmatch(r"[A-Za-z0-9]+", _device_slug("cuda:0/../etc"))
    assert _device_slug(":::") == "cuda", "порожній слаг дав би прихований файл"


def test_sharded_cuda_run_derives_a_lock_instead_of_only_warning() -> None:
    """Приймач самої заміни: у коді має бути ВИВЕДЕННЯ лока, а не лише рядок
    попередження. Перевірка тримається за структуру гілки, бо запустити тут
    справжній прогін нема на чому — це чужий інтерпретатор і карта."""
    src = RUNNER_SRC.read_text(encoding="utf-8")

    derive = src.index("if not args.gpu_lock and shard_n > 1")
    install = src.index("install_gpu_lock(Path(args.gpu_lock)")
    assert derive < install, "лок мусить виводитись ДО встановлення"

    branch = src[derive:install]
    assert "_device_slug(device)" in branch, "ім'я лока мусить розрізняти карти"
    assert "out_dir" in branch, "лок кладеться в теку прогону — спільну для шардів"

    # Стара гілка «лише попередити» не сміє лишитись живою: доки вона є,
    # шардований прогін може піти без лока.
    assert "⚠ --shard без --gpu-lock" not in src, (
        "попередження лишилось замість запобіжника — шарди знову підуть без лока")


def test_an_explicit_lock_path_still_wins() -> None:
    """Хмарний раннер робить ім'я лока сам (пер-карту, поза текою прогону), і
    перебивати його не можна."""
    src = RUNNER_SRC.read_text(encoding="utf-8")
    derive = src.index("if not args.gpu_lock and shard_n > 1")
    assert "not args.gpu_lock" in src[derive:derive + 120], (
        "виведення мусить спрацьовувати ЛИШЕ коли шлях не заданий явно")
