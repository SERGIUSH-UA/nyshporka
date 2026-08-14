"""🛟 Рятувальний відбір: цілі приходять ЗЗОВНІ, і без них прохід падає.

Що тут стережеться. Прохід відбирає рядки, які перечитає другий рушій, — а
решту не перечитає ніхто. Тому дві протилежні відмови однаково дорогі: відібрати
за чужим прізвищем (витрачений час і хибна впевненість) і не відібрати нічого
(мовчазна порожнеча, яку не відрізнити від «нема кого рятувати»).

До винесення цілей у файл у раннері лежали імена конкретного роду, а решта
підтягувалась імпортом сусіднього скрипта — під інтерпретатором середовища
рушіїв цей імпорт падав, і падав ТИХО, бо він лінивий.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RUNNER = (Path(__file__).resolve().parent.parent
          / "src" / "nyshporka" / "htr" / "runner.py")


@pytest.fixture
def runner():
    """Раннер вантажиться ЗА ШЛЯХОМ — так само, як його запускає наглядач."""
    spec = importlib.util.spec_from_file_location("_runner_under_test", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


@pytest.fixture
def spec_file(tmp_path: Path):
    def make(full: list[str], confusers: list[str] | None = None,
             anchors: list[str] | None = None) -> Path:
        p = tmp_path / "rescue.json"
        p.write_text(json.dumps({"full": full,
                                 "confusers": confusers or [],
                                 "anchors": anchors or []},
                                ensure_ascii=False), encoding="utf-8")
        return p
    return make


def _arm(runner, path: Path) -> None:
    runner._RESCUE_SPEC_PATH = path
    runner._RESCUE_SPEC = None


def test_without_spec_it_raises(runner) -> None:
    """Мовчазний нуль тут заборонений: без цілей — виняток."""
    runner._RESCUE_SPEC_PATH = None
    runner._RESCUE_SPEC = None
    with pytest.raises(RuntimeError, match="rescue-spec"):
        runner.rescue_pick(["якийсь рядок"], 78.0, 60.0)


def test_empty_targets_raise(runner, spec_file) -> None:
    """Порожній перелік — теж відмова, а не «нічого не знайшлось»."""
    _arm(runner, spec_file(full=[]))
    with pytest.raises(RuntimeError, match="порожній"):
        runner.rescue_pick(["якийсь рядок"], 78.0, 60.0)


def test_picks_the_grey_band_and_its_neighbours(runner, spec_file) -> None:
    """Сіра смуга плюс сусіди: хвіст переносу не має чим себе видати.

    Прізвище, розірване межею рядка, лишає на другому рядку огризок, схожий на
    будь-що. Тому відбирається ОКІЛ, а не сам рядок.
    """
    _arm(runner, spec_file(full=["kovalskij"]))
    lines = ["зовсім стороннє речення",
             # «Комалсній» — саме те, як рушій калічить прізвище: бал 70.6,
             # тобто нижче порога ока (78) і вище шуму (60).
             "мѣщанинъ Иванъ Комалсній",
             "ще одне стороннє речення",
             "далеке речення без нічого"]
    picks = runner.rescue_pick(lines, 78.0, 60.0)
    assert 1 in picks, "рядок сірої смуги не відібрано"
    assert 0 in picks and 2 in picks, "сусідів не відібрано — перенос загубиться"
    assert 3 not in picks, "відбір розповз далі околу ±1"


def test_clean_hits_are_not_rescued(runner, spec_file) -> None:
    """Рядок, що й так піде на око, другий рушій не перечитує.

    Рятунок коштує часу й місця саме тому, що вузький: він для того, чого не
    видно з першого голосу. Чисте прочитання видно й так.
    """
    _arm(runner, spec_file(full=["kovalskij"]))
    assert not runner.rescue_pick(["мѣщанинъ Иванъ Ковальскій"], 78.0, 60.0)


def test_confusers_veto_the_pick(runner, spec_file) -> None:
    """Слово, СХОЖЕ на ціль, але нею не є, відбір не запускає.

    Це не косметика: у сусідстві живуть прізвища зі спільним коренем, і без
    вето рятунок захлинається в них, а справжній хіт тоне.
    """
    line = "мѣщанинъ Иванъ Ковальчукъ"
    _arm(runner, spec_file(full=["kovalskij"]))
    without = runner.rescue_pick([line], 78.0, 60.0)
    _arm(runner, spec_file(full=["kovalskij"], confusers=["kovalcuk"]))
    with_veto = runner.rescue_pick([line], 78.0, 60.0)
    assert without, "матеріал для перевірки не спрацював — рядок і так не брався"
    assert not with_veto, "конфузер не наклав вето"


def test_anchor_channel_is_independent_of_surname(runner, spec_file) -> None:
    """Другий канал — ім'я й по батькові, і він працює без збігу прізвища.

    Прізвище рушій калічить сильніше за формульне по батькові, тому канал
    якорів ловить те, чого не ловить прізвищний. Обидва потрібні.
    """
    lines = ["Восприемникъ Онуфрій Іосифовъ"]
    _arm(runner, spec_file(full=["kovalskij"]))
    assert not runner.rescue_pick(lines, 78.0, 60.0)
    _arm(runner, spec_file(full=["kovalskij"], anchors=["Іосифовъ"]))
    assert runner.rescue_pick(lines, 78.0, 60.0), "якір не спрацював"


def test_anchors_can_be_overridden_by_caller(runner, spec_file) -> None:
    """Явні якорі перебивають те, що у файлі: викликач знає роки справи."""
    _arm(runner, spec_file(full=["kovalskij"], anchors=["Іосифовъ"]))
    lines = ["Восприемникъ Онуфрій Іосифовъ"]
    assert runner.rescue_pick(lines, 78.0, 60.0)
    assert not runner.rescue_pick(lines, 78.0, 60.0, anchor_keys=["Антоніевъ"])


def test_best_ratio_ignores_partial_for_short_fragments(runner) -> None:
    """Уламок коротший за ціль не отримує ста балів за підрядок.

    Інакше двобуквений огризок сегментації матчився б із будь-чим.
    """
    long_hit, _ = runner.best_ratio("ivankovalskijsyn", ["kovalskij"])
    short, _ = runner.best_ratio("ko", ["kovalskij"])
    assert long_hit == 100.0
    assert short < 50.0
