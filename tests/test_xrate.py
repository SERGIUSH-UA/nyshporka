"""🚦 Крос-процесний ліміт запитів.

Цей модуль існує тому, що пауза в коді нічого не доводить: сервер міряє темп по
клієнту, а `sleep` рахує потік одного процесу. Тому й перевірки тут — не про
те, що ми «поставили паузу», а про журнал фактичних відправок і про поведінку
на межах: побитий файл, стрибок годинника, кілька процесів разом.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from nyshporka.core import xrate as X


def _limiter(tmp_path: Path, **kw: object) -> X.CrossProcessLimiter:
    kw.setdefault("max_events", 3)
    kw.setdefault("window", 0.4)
    kw.setdefault("safety", 1.0)
    return X.CrossProcessLimiter("тест", state_dir=tmp_path, **kw)  # type: ignore[arg-type]


def test_window_invariant_holds_within_one_process(tmp_path: Path) -> None:
    """Базовий інваріант: у будь-якому вікні не більше за ліміт."""
    lim = _limiter(tmp_path)
    for _ in range(7):
        lim.acquire("t")
    res = X.verify(lim.audit_path, 3, 0.4)
    assert res["events"] == 7
    assert res["ok"], res


def test_a_broken_state_file_is_the_worst_case_not_a_clean_slate(tmp_path: Path) -> None:
    """🔴 Побитий стан ≠ порожній.

    Порожній дозволив би пачку запитів одразу, тобто збій файлу став би обходом
    ліміту — рівно та вада, від якої модуль і рятує. Тому нечитабельний стан
    трактується як «вікно щойно заповнене вщент».
    """
    lim = _limiter(tmp_path)
    lim.state_path.write_text("{не json", encoding="utf-8")

    waited = lim.acquire("t")
    assert waited > 0, "після побитого стану запит пішов негайно"


def test_a_clock_jump_forward_does_not_freeze_the_queue(tmp_path: Path) -> None:
    """Гранти з далекого майбутнього — слід NTP чи виходу з гібернації.
    Лишити їх означає зупинити роботу на невизначений час."""
    lim = _limiter(tmp_path)
    far = time.time() + 3600
    lim.state_path.write_text(
        json.dumps({"grants": [far] * 3, "max": 3, "window": lim.window}),
        encoding="utf-8")

    assert lim.acquire("t") < 1.0, "черга застрягла на грантах із майбутнього"


def test_the_journal_is_the_acceptance_not_the_intention(tmp_path: Path) -> None:
    """`verify()` читає фактичні відправки, тож ловить і перевищення."""
    audit = tmp_path / "к.audit.jsonl"
    now = time.time()
    audit.write_text("".join(
        json.dumps({"t": now + i * 0.01, "pid": 1, "tag": ""}) + "\n"
        for i in range(6)), encoding="utf-8")

    res = X.verify(audit, 5, 10.0)
    assert res["worst"] == 6
    assert not res["ok"], "шість запитів у вікні при ліміті п'ять визнано нормою"


def test_the_state_directory_follows_the_variable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(X.ENV_STATE_DIR, str(tmp_path / "своя"))
    assert X.default_state_dir() == tmp_path / "своя"


def test_the_legacy_directory_is_used_while_it_is_the_only_one(
        tmp_path: Path, monkeypatch) -> None:
    """🔴 Доки поруч працюють і пакет, і скрипти дослідницького репозиторію,
    різні теки стану означають дві черги на один IP — тобто подвоєний темп
    рівно тим механізмом, який мав його стримати."""
    legacy = tmp_path / "стара"
    legacy.mkdir()
    monkeypatch.setattr(X, "_legacy_state_dir", lambda: legacy)
    monkeypatch.setattr("platformdirs.user_cache_dir",
                        lambda *a, **k: str(tmp_path / "нова-якої-немає"))

    assert X.default_state_dir() == legacy

    # А щойно з'явилась своя — беремо свою: перехід завершено.
    (tmp_path / "нова-якої-немає" / "xrate").mkdir(parents=True)
    assert X.default_state_dir() == tmp_path / "нова-якої-немає" / "xrate"


def test_the_limit_holds_across_PROCESSES_not_just_threads(tmp_path: Path) -> None:
    """🔴 Головне твердження модуля, і довести його можна лише процесами:
    потоки одного процесу поділили б пам'ять і не перевірили б міжпроцесну
    межу — саме ту, що ламається насправді."""
    import os
    import subprocess

    # Тека стану — через змінну середовища: шлях, переданий у рядку коду,
    # приїхав би в конструктор рядком, а не шляхом.
    env = dict(os.environ, **{X.ENV_STATE_DIR: str(tmp_path)})
    code = ("from nyshporka.core.xrate import CrossProcessLimiter as L;"
            "l=L('гурт',max_events=2,window=0.5,safety=1.0);"
            "[l.acquire('p') for _ in range(3)]")
    kids = [subprocess.Popen([sys.executable, "-c", code], env=env)
            for _ in range(3)]
    assert all(k.wait() == 0 for k in kids)

    res = X.verify(tmp_path / "гурт.audit.jsonl", 2, 0.5)
    assert res["events"] == 9, res
    assert res["pids"] == 3, "процеси не розрізнились — перевірка втратила сенс"
    assert res["ok"], f"ліміт перевищено: {res['worst']} у вікні"
