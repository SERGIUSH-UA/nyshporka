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


# ── 📖 зразкова справа ───────────────────────────────────────────────────────
def test_sample_deploys_a_working_chain(tmp_path: Path, monkeypatch) -> None:
    """🔴 Приймач зразка — не «файли скопіювались», а ЛАНЦЮГ, що на них працює.

    Зразок існує заради одного питання новачка: «чи воно взагалі щось робить».
    Відповідь дає не наявність кадрів, а те, що після розгортання гортач
    показує рядок, а пошук його знаходить. Тому тест іде тим самим шляхом, що
    й людина: розгорнув — подивився — знайшов.
    """
    from nyshporka.core.workspace import Workspace
    from nyshporka.setup import sample as S

    root = wizard.create(tmp_path / "простір", name="проба")
    ws = Workspace(root=root, name="проба")

    assert not S.installed(ws), "на щойно створеному просторі зразка бути не може"
    got = S.install(ws)
    assert S.installed(ws)
    assert got["case_key"] == S.CASE_KEY
    assert len(got["frames"]) >= 3
    assert S.RUN_MAIN in got["runs"] and S.RUN_SIDE in got["runs"]

    # 🔴 Шлях у меті — ВІДНОСНИЙ. Абсолютний пережив би переїзд простору на
    # інший диск лише до першого відкриття гортача; саме на цьому й горять
    # хмарні прогони, у яких лишається тека орендованого боксу.
    meta = json.loads((ws.htr_reports / S.RUN_MAIN / "_htr_meta.json")
                      .read_text(encoding="utf-8"))
    assert meta["case_dir"] == f"data/raw/{S.CASE_DIR}"
    assert not Path(meta["case_dir"]).is_absolute()

    monkeypatch.setenv("NYSHPORKA_WORKSPACE", str(root))
    import nyshporka.htr_store as HS

    monkeypatch.setattr(HS, "ROOT", root)
    monkeypatch.setattr(HS, "HTR_ROOT", ws.htr_reports)
    monkeypatch.setattr(HS, "_case_roots", lambda: [ws.raw])

    # 1. пошук у декоді знаходить прізвище, заради якого справу й брали
    found = HS.search("Долищинский", limit=10)
    assert found["hits"], "декод зразка не шукається"
    hit = next(h for h in found["hits"] if "Долищинскій" in h["line"])

    # 2. гортач показує ЦЕЙ САМЕ рядок — і не сторінку цілком.
    # 🔴 Індекс беремо з хіта (`line_index`), а не константою: номер залежить
    # від сегментації, і прибитий цвяхом «line=1» ламався б від будь-якого
    # перескладання зразка, хоча ланцюг лишався б робочим.
    from nyshporka.htr import view as V

    shot = V.shot(S.RUN_MAIN, hit["page"], line=hit["line_index"])
    assert shot.region == "line", shot.note
    assert shot.png[:4] == b"\x89PNG"
    assert "Долищинскій" in shot.text, shot.text
    # Кроп рядка мусить бути дешевшим за сторінку — на цьому тримається вся
    # економіка перегляду (виміряно: 15 КБ проти 1.1 МБ).
    page = V.shot(S.RUN_MAIN, hit["page"], region="page")
    assert len(shot.png) < len(page.png)


def test_sample_install_is_idempotent(tmp_path: Path) -> None:
    """Двічі розгорнутий зразок не має ні падати, ні дублюватись."""
    from nyshporka.core.workspace import Workspace
    from nyshporka.setup import sample as S

    root = wizard.create(tmp_path / "простір")
    ws = Workspace(root=root, name="проба")
    first = S.install(ws)
    again = S.install(ws)
    assert first["frames"] == again["frames"]
    assert len(list((ws.raw / S.CASE_DIR).glob("*.jpg"))) == len(first["frames"])


def test_search_hit_carries_both_line_numbers(tmp_path: Path, monkeypatch) -> None:
    """🔴 Номер рядка для ЛЮДИНИ і індекс рамки для ГОРТАЧА — різні числа.

    Пошук нумерує рядки з одиниці (так їх читає людина в таблиці хітів), а
    гортач адресує рамку в `.lines.json`, тобто з нуля. Доти, доки поле було
    одне, кнопка 👁 передавала людський номер туди, де ждали індекс, — і око
    бачило СУСІДНІЙ рядок, маючи всі підстави вірити, що бачить знайдений.
    Тест закріплює саме різницю: зійдуться назад в одне число — впаде тут, а не
    в дослідника посеред звірки.
    """
    from nyshporka.core.workspace import Workspace
    from nyshporka.setup import sample as S

    root = wizard.create(tmp_path / "простір")
    ws = Workspace(root=root, name="проба")
    S.install(ws)

    import nyshporka.htr_store as HS

    monkeypatch.setattr(HS, "ROOT", root)
    monkeypatch.setattr(HS, "HTR_ROOT", ws.htr_reports)
    monkeypatch.setattr(HS, "_case_roots", lambda: [ws.raw])

    hit = next(h for h in HS.search("Долищинский", limit=10)["hits"]
               if "Долищинскій" in h["line"])
    assert hit["line_index"] == hit["line_no"] - 1

    # І приймач по суті: рядок, названий індексом, справді той самий.
    text = HS.read_page_text(S.RUN_MAIN, hit["page"])["lines"]
    assert text[hit["line_index"]] == hit["line"]

    # А кнопка 👁 у фронті мусить передавати саме індекс, не людський номер.
    js = (Path(HS.__file__).parent / "daemon" / "static" / "app.js").read_text(
        encoding="utf-8")
    eye = js[js.index('data-act="hit.eye"'):]
    eye = eye[:eye.index("</button>")]
    assert "h.line_index" in eye, "кнопка 👁 знову передає людський номер рядка"
