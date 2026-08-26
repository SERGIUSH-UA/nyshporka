"""Шифра справи в меті прогону не має права зникнути.

🔴 Чому це тест, а не домовленість. `case_key` — єдина координата, за якою
споживач декоду за межами проєкту (сайт, чужий каталог) знаходить книгу; без
неї лишається розбір імені теки, а нерозібране ім'я дає не помилку, а **тишу**:
справа виглядає непрочитаною. Саме так 2200 сторінок готового тексту стояли
поза обліком (`bershad-678-79`, `davo885_1_1_revizia_1816`), і виявилось це
випадково.

Тут перевіряються рівно ті два місця, де ключ зникав мовчки:

1. **Перезбірка мети шардів.** `merge_meta` бере шапку з білого списку полів
   поточного процесу, а `case_key` у ньому завжди присутній — порожнім рядком,
   коли викликач не дав `--case-key`. Тобто резюм справи без прапорця знімав
   уже проставлену шифру, і прогін знову ставав нічиїм.
2. **Тека побічного голосу.** `<справа>-diak_v4` — окремий прогін для реєстру,
   і його мета писалась без ключа взагалі, тобто половина всього декоду
   лишалась без координати навіть при правильному виклику.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.htr import runner as R

SRC = Path(__file__).resolve().parent.parent / "src" / "nyshporka" / "htr" / "runner.py"


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_merge_keeps_case_key_stamped_after_the_run(tmp_path: Path) -> None:
    """Резюм без `--case-key` не знімає шифру, дописану ремонтом."""
    _write(tmp_path / "_htr_meta.json", {
        "version": 1, "case_dir": "/tmp/htrcase/pages_dl_02",
        "case_key": "DAVO/885/1", "case_dir_cloud": "/tmp/htrcase/pages_dl_02",
        "model": "pysar_cyr_v17.pt", "pages": {"00001.jpg": {"lines": 5}},
        "failed": [], "started": "2026-08-13T12:10:31",
    })
    _write(tmp_path / "_htr_meta.part1.json", {
        "pages": {"00002.jpg": {"lines": 7}}, "failed": [], "done": True,
        "started": "2026-08-19T10:00:00",
    })

    R.merge_meta(tmp_path, {"version": 1, "case_dir": "/tmp/htrcase/pages_dl_02",
                            "case_key": "", "model": "pysar_cyr_v17.pt"})

    merged = json.loads((tmp_path / "_htr_meta.json").read_text(encoding="utf-8"))
    assert merged["case_key"] == "DAVO/885/1"
    # слід походження хмарного прогону — теж дописаний після, теж мусить жити
    assert merged["case_dir_cloud"] == "/tmp/htrcase/pages_dl_02"
    # і сторінки обох шарів на місці — перенос не мав нічого зламати
    assert set(merged["pages"]) == {"00001.jpg", "00002.jpg"}


def test_merge_lets_the_process_override_a_stale_key(tmp_path: Path) -> None:
    """Непорожній ключ цього прогону сильніший за старий у файлі.

    Інакше перенос перетворився б на замок: помилкову шифру не можна було б
    виправити повторним прогоном із правильним `--case-key`.
    """
    _write(tmp_path / "_htr_meta.json",
           {"version": 1, "case_key": "DAVO/678/4", "pages": {}, "failed": []})
    _write(tmp_path / "_htr_meta.part1.json",
           {"pages": {"00001.jpg": {}}, "failed": [], "done": True})

    R.merge_meta(tmp_path, {"version": 1, "case_key": "DAVO/678/64"})

    merged = json.loads((tmp_path / "_htr_meta.json").read_text(encoding="utf-8"))
    assert merged["case_key"] == "DAVO/678/64"


@pytest.mark.parametrize("marker", ['"case_key": meta.get("case_key") or ""'])
def test_side_voice_and_rescue_metas_carry_the_key(marker: str) -> None:
    """Мета побічного голосу й рятунку теж несе шифру.

    Перевіряємо текстом, а не прогоном: обидві гілки живуть глибоко всередині
    `main()` під рушіями, яких у тестовому середовищі немає. Маркер вузький —
    зникне разом із полем, а не разом із рефакторингом.
    """
    src = SRC.read_text(encoding="utf-8")
    assert src.count(marker) == 2, (
        "шифра має стояти у двох метах поза головною: побічний голос "
        "(`<справа>-diak_v4`) і рятувальна тека — обидві реєстр бачить як "
        "окремі прогони"
    )


def test_daemon_passes_resolved_case_key_to_the_runner() -> None:
    """🔴 Третє місце, де ключ зникав: шлях демона.

    `_start_read` резолвить шифру (з payload або з опису в теці) і кладе її в
    `cfg` завдання — а виконавцеві передавав `payload.get("case_key")` наново.
    Форма читання в консолі питає лише теку, тож кожен запуск кнопкою йшов без
    `--case-key`: у черзі шифра видна, у меті прогону — порожньо, і розходження
    непомітне. Тестом покрито не було саме це — виклик `_run_read`.

    Перевіряємо поведінку там, де можна, і текст лише там, де не можна:
    підняти демона з живим раннером у тестах нема чим, а от команду раннера
    зібрати — можна, і саме в ній ключ або є, або немає.
    """
    from nyshporka.htr.run import Plan

    plan = Plan(case_dir=Path("case"), out_dir=Path("out"),
                model=Path("pysar_cyr_v4.pt"), script="cyrillic", frames=1,
                python=Path("python"), runner=Path("runner.py"))
    for workers in (1, 3):
        cmds, _ = plan.shards(workers, device="cuda:0", case_key="DAHMO/315/1")
        for cmd in cmds:
            assert "--case-key" in cmd, (
                "команда раннера пішла без шифри — прогін стане нічиїм")
            assert cmd[cmd.index("--case-key") + 1] == "DAHMO/315/1"

    src = (Path(__file__).resolve().parent.parent / "src" / "nyshporka"
           / "daemon" / "workers.py").read_text(encoding="utf-8")
    # Вирахувана змінна мусить доїхати до збірки команди, а не бути прочитаною
    # з payload удруге: форма читання питає лише теку, тож payload порожній.
    assert "case_key=case_key" in src, (
        "у команду раннера йде не вирахувана змінна `case_key`")
    assert 'payload.get("case_key") or ""))' not in src, (
        "payload перечитується вдруге — шифра з опису теки губиться")
