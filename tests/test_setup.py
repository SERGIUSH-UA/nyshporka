"""🧰 Установлення: доктор, паки, майстер простору.

Кожна перевірка тут стереже ТИХУ поломку. Гучні себе виявляють самі; ці ні —
вони виглядають як «повільно», «нічого не знайшлось» або «модель зламана».
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.setup import doctor, packs, wizard


# ── майстер простору ─────────────────────────────────────────────────────────
def test_plan_does_not_create_anything(tmp_path: Path) -> None:
    """🔴 Простір не з'являється сам.

    Тека, що створилась мовчки, — це дослідження, яке потім не можуть знайти:
    людина шукає скани там, де поклала, а застосунок пише в інше місце.
    """
    target = tmp_path / "простір"
    p = wizard.plan(target)
    assert p.root == target
    assert p.creating
    assert not target.exists()


def test_create_is_idempotent(tmp_path: Path) -> None:
    root = wizard.create(tmp_path / "простір", name="тест")
    marker = root / "nyshporka.toml"
    first = marker.read_text(encoding="utf-8")
    again = wizard.create(root)
    assert again == root
    assert marker.read_text(encoding="utf-8") == first, "маркер переписався"


def test_create_lays_out_the_skeleton(tmp_path: Path) -> None:
    root = wizard.create(tmp_path / "простір")
    for sub in ("data/raw", "data/derived", "data/pages", "reports", "config"):
        assert (root / sub).is_dir(), f"немає {sub}"


def test_cloud_folder_is_flagged_not_refused(tmp_path: Path) -> None:
    """⚠ Тека в хмарі — попередження, а не заборона.

    Заборонити не можна: у частини людей `Documents` перенаправлено в OneDrive
    системно, і відмова лишила б їх без застосунку. Але й змовчати не можна:
    «файли на вимогу» роблять обхід справи мережевим, і 2000 сторінок
    «зависають» без жодної помилки.
    """
    root = tmp_path / "OneDrive" / "Нишпорка"
    root.mkdir(parents=True)
    p = wizard.plan(root)
    assert "хмар" in p.warning.lower()


def test_dangerous_roots_are_refused() -> None:
    from nyshporka.core.workspace import WorkspaceError

    with pytest.raises(WorkspaceError):
        wizard.plan(Path.home())


def test_default_root_avoids_synced_folders(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Documents").mkdir()
    assert not wizard._is_synced(wizard.default_root())


# ── паки ─────────────────────────────────────────────────────────────────────
def test_catalog_lists_the_three_production_models() -> None:
    ids = {p.id for p in packs.catalog()}
    assert {"pysar-cyr-v17", "diak-cyr-v4", "skryba-f792-v6"} <= ids


def test_versions_are_in_the_filenames() -> None:
    """🔴 «Найновіша» не означає «найкраща».

    Бойовими лишаються ті версії, що виграли на голдовому зрізі, а не останні
    натреновані. Пак, який зветься `latest`, це рішення, ухвалене за
    дослідника — і ухвалене неправильно.
    """
    for p in packs.catalog():
        assert "latest" not in p.filename
        assert any(ch.isdigit() for ch in p.filename), p.filename


def test_pack_without_hash_is_never_considered_whole(tmp_path, monkeypatch) -> None:
    """🔴 Головна перевірка цього файлу.

    Обірвана закачка лишає файл, який ВИГЛЯДАЄ як модель. `torch.load` на ньому
    падає десь усередині, повідомленням про формат тензора, — тобто причину
    («не докачалось») доводиться здогадувати. Тому «немає хеша» = «не цілий»,
    а не «пропустимо перевірку».
    """
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path)
    pack = packs.Pack(id="x", kind="model", filename="x.pt", sha256="",
                      size=3, release="r")
    (tmp_path / "x.pt").write_bytes(b"abc")
    assert not packs.verify(pack)
    with pytest.raises(RuntimeError, match="sha256"):
        packs.fetch(pack)


def test_verify_catches_a_truncated_file(tmp_path, monkeypatch) -> None:
    import hashlib

    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path)
    body = "ваги моделі".encode() * 100
    good = packs.Pack(id="x", kind="model", filename="x.pt",
                      sha256=hashlib.sha256(body).hexdigest(), size=len(body),
                      release="r")
    (tmp_path / "x.pt").write_bytes(body)
    assert packs.verify(good)
    (tmp_path / "x.pt").write_bytes(body[:-10])
    assert not packs.verify(good), "обрізаний файл прийнято за цілий"


def test_packs_live_in_cache_not_in_the_research_space(tmp_path) -> None:
    """🔴 Ваги — у кеш, а не в простір.

    У просторі вони і дублювались би на кожен архів, і потрапляли б у резервну
    копію дослідження, де їм не місце: це відтворюваний файл, а не знахідка.
    """
    d = packs.target_dir("model")
    assert "ache" in str(d) or "Cache" in str(d), d


def test_state_separates_absent_from_broken(tmp_path, monkeypatch) -> None:
    """«Немає» лікується завантаженням, «зіпсоване» — повторним; плутати їх
    означає радити не те."""
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path)
    state = packs.as_dict()
    assert {r["state"] for r in state["packs"]} == {"absent"}
    first = packs.catalog()[0]
    (tmp_path / first.filename).write_bytes("недокачано".encode())
    assert any(r["state"] == "broken" for r in packs.as_dict()["packs"])


def test_manifest_is_valid_json_with_sizes() -> None:
    raw = json.loads(packs.manifest_path().read_text(encoding="utf-8"))
    assert raw["schema"] == 1
    assert raw["packs"]


# ── доктор ───────────────────────────────────────────────────────────────────
def test_doctor_never_raises() -> None:
    """Доктора кличуть саме тоді, коли щось зламано — падати він не має права."""
    checks = doctor.run()
    assert checks
    assert all(c.level in ("ok", "warn", "fail") for c in checks)


def test_doctor_checks_the_silent_failures() -> None:
    """Перелік перевірок — це перелік ТИХИХ поломок, і він мусить бути повним."""
    names = {c.name for c in doctor.run()}
    assert {"Прискорення (GPU)", "Хмарна синхронізація", "Місце на диску",
            "Рушії читання", "Моделі письма"} <= names


def test_gpu_check_reports_availability_not_presence() -> None:
    """🔴 CPU-torch не падає — він рахує вп'ятеро довше.

    Тому «torch встановлено» не є відповіддю: перевірка мусить називати
    `is_available()`, інакше різниця між картою й процесором виглядає як
    «сьогодні гальмує».
    """
    src = Path(doctor.__file__).read_text(encoding="utf-8")
    assert "cuda.is_available()" in src


def test_cuda_tag_comes_from_the_manifest() -> None:
    """Матриця sm→cu живе в маніфесті: зашитий тег зробив би застосунок
    непрацездатним на половині заліза, і мовчки."""
    assert doctor.cuda_tag("7.5") == "cu126"
    assert doctor.cuda_tag("9.0") == "cu128"
    assert doctor.cuda_tag("не число") is None
