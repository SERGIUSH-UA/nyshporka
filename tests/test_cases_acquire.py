"""📥 Облік завантаженої справи: паспорт, сторож опису, межа з приватним репо."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.cases import acquire as A


def _meta(case_dir: Path, opys: str) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "meta.json").write_text(
        json.dumps({"inv": opys, "spr": "33"}, ensure_ascii=False), encoding="utf-8")


def test_two_inventories_never_share_one_case_folder(tmp_path: Path) -> None:
    """🔴 Номери справ між описами повторюються: «спр.33» є і в описі 30, і в
    описі 24. Покладені в одну теку, вони виглядали б справною справою — файли
    на місці, паспорт на місці, — а насправді це ДВІ різні справи під однією
    шифрою. Помічають таке не тоді, коли клали, а коли шукають у ній запис.
    """
    case = tmp_path / "spr-33"
    _meta(case, "30")

    with pytest.raises(A.AcquireError) as exc:
        A.guard_inventory(case, "24")
    assert "30" in str(exc.value) and "24" in str(exc.value)

    # Той самий опис — не перешкода: це доповнення тієї ж справи.
    A.guard_inventory(case, "30")


def test_the_passport_is_extended_not_replaced(tmp_path: Path) -> None:
    """⚠ Заміщення стерло б те, що дописала людина, — а дізналась би вона про
    це, лише не знайшовши свого запису."""
    case = tmp_path / "spr-1"
    case.mkdir()
    (case / "meta.json").write_text(
        json.dumps({"inv": "1", "shifra_needs_eye": "звірити оком с.14",
                    "note": "моя нотатка"}, ensure_ascii=False), encoding="utf-8")

    A.write_meta(case, archive="ДАХмО", fond="230", opys="1", spr="1",
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
    assert A.page_count(broken) == 0, "побитий файл видав себе за читаний"
    assert A.page_count(tmp_path / "нема.pdf") == 0


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
