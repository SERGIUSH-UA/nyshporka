"""📥 Облік завантаженої справи: паспорт, сторож опису, межа з приватним репо."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# 🔴 Імпорт лінивий, і це не стиль. `nyshporka.cases.__init__` тягне модулі, які
# беруть корінь робочого простору на рівні модуля, тож імпорт на рівні файла
# падає там, де простору немає. Локально він проходив лише тому, що на машині
# лишався запам'ятований простір від живих прогонів, — тобто тест перевіряв
# машину, а не програму, і виявив це аж CI.


@pytest.fixture(autouse=True)
def _space(tmp_path_factory):
    """Простір потрібен уже для імпорту.

    Ланцюг `cases.__init__ → collect → resolve → library` бере корінь на рівні
    модуля, тож без простору цей файл не імпортується взагалі. Тут це
    оголошено явно — інакше тест мовчки спирався б на те, що на машині
    лишився простір від попередньої роботи (саме так і сталось: локально
    зелено, на CI червоно).
    """
    from nyshporka.core import workspace as W

    root = tmp_path_factory.mktemp("простір")
    (root / "data" / "raw").mkdir(parents=True)
    W.use(W.Workspace(root=root, name="тест", origin="test"))
    yield
    W.reset()


def _acq():
    from nyshporka.cases import acquire

    return acquire


def _meta(case_dir: Path, opys: str) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "meta.json").write_text(
        json.dumps({"inv": opys, "spr": "33"}, ensure_ascii=False), encoding="utf-8")


def test_two_inventories_never_share_one_case_folder(tmp_path: Path) -> None:
    """🔴 Номери справ між описами повторюються: «спр.33» є і в описі 30, і в
    описі 24. Покладені в одну теку, вони виглядали б справною справою — файли
    на місці, паспорт на місці, — а насправді це дві різні справи під однією
    шифрою. Помічають таке не тоді, коли клали, а коли шукають у ній запис.
    """
    case = tmp_path / "spr-33"
    _meta(case, "30")

    with pytest.raises(_acq().AcquireError) as exc:
        _acq().guard_inventory(case, "24")
    assert "30" in str(exc.value) and "24" in str(exc.value)

    # Той самий опис — не перешкода: це доповнення тієї ж справи.
    _acq().guard_inventory(case, "30")


def test_the_passport_is_extended_not_replaced(tmp_path: Path) -> None:
    """⚠ Заміщення стерло б те, що дописала людина, — а дізналась би вона про
    це, лише не знайшовши свого запису."""
    case = tmp_path / "spr-1"
    case.mkdir()
    (case / "meta.json").write_text(
        json.dumps({"inv": "1", "shifra_needs_eye": "звірити оком с.14",
                    "note": "моя нотатка"}, ensure_ascii=False), encoding="utf-8")

    _acq().write_meta(case, archive="ДАХмО", fond="230", opys="1", spr="1",
                 files=[{"file": "х.pdf"}], source="Wikimedia Commons")

    got = json.loads((case / "meta.json").read_text(encoding="utf-8"))
    assert got["note"] == "моя нотатка"
    assert got["shifra_needs_eye"] == "звірити оком с.14"
    assert got["archive"] == "ДАХмО" and got["files"][0]["file"] == "х.pdf"


def test_the_page_count_comes_from_the_file_not_from_the_promise(tmp_path: Path) -> None:
    """Обіцянка каталогу не доказ: обірвана закачка під правильним іменем
    лягла б в облік як повна справа."""
    broken = tmp_path / "не-pdf.pdf"
    broken.write_bytes("це не PDF".encode())
    assert _acq().page_count(broken) == 0, "побитий файл видав себе за читаний"
    assert _acq().page_count(tmp_path / "нема.pdf") == 0


def test_the_package_never_runs_scripts_of_the_private_repository() -> None:
    """🔴 Головна межа цього релізу.

    Публічний пакет запускав підпроцесом файл із дослідницького репозиторію за
    шляхом усередині робочого простору. На чужій машині тієї теки немає, і
    команда падала з «файл не знайдено» — тобто виглядала поламаною, а не
    відсутньою. Ворота стережуть, щоб цей шлях не повернувся.
    """
    import nyshporka

    src = Path(nyshporka.__file__).parent
    guilty = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if 'root / "scripts"' in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert not guilty, f"пакет знову кличе скрипт із чужого репозиторію: {guilty}"
