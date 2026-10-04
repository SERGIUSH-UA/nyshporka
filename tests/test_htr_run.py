"""▶️ Вибір моделі й план прогону: тут помилка коштує ночі й тихого сміття.

Три речі, кожна з яких ламається без помилки:

* **не та версія ваг** — читання йде, текст виходить, просто гірший. «Найновіша»
  ≠ «найкраща»: бойовою двічі лишалась не остання версія;
* **не те письмо** — невідповідність рушія письму дає сміття без падіння
  впевненості, і виглядає це як погані скани;
* **тека з підтеками** — раннер не рекурсивний і читає її як порожню.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.htr import run as R


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір із текою ваг і порожнім кешем паків."""
    models = tmp_path / "data" / "spotter" / "models"
    models.mkdir(parents=True)
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return models


def _weights(models: Path, *names: str) -> None:
    for n in names:
        (models / n).write_bytes(b"\0" * 16)


# ── вибір моделі ─────────────────────────────────────────────────────────────
def test_production_file_wins_over_the_newest(space: Path) -> None:
    """🔴 Головне. «Найновіша» ≠ «найкраща», і файл дослідника це вирішує.

    Без нього вибір падає на найбільший номер версії — тобто мовчки на гіршу
    модель там, де пізніша програла на голдовому зрізі.
    """
    _weights(space, "pysar_cyr_v16.pt", "pysar_cyr_v17.pt", "pysar_cyr_v18.pt")
    (space / R.PRODUCTION_NAME).write_text(
        json.dumps({"production": {"cyrillic": {"model": "pysar_cyr_v17.pt"}}}),
        encoding="utf-8")
    main, _ = R.pick_model("cyrillic")
    assert main.name == "pysar_cyr_v17.pt"


def test_without_production_file_the_highest_version_wins(space: Path) -> None:
    """Без вказівки — найвища версія, а не перша за абеткою.

    Абеткою `pysar_cyr_v1.pt` іде поперед `v17`, і саме так виглядала перша
    реалізація: читання йшло найстарішими вагами й нічим про це не казало.
    """
    _weights(space, "pysar_cyr_v1.pt", "pysar_cyr_v9.pt", "pysar_cyr_v17.pt")
    main, _ = R.pick_model("cyrillic")
    assert main.name == "pysar_cyr_v17.pt"


def test_script_comes_from_the_name_prefix_not_the_extension(space: Path) -> None:
    """🔴 `.mlmodel` буває двох письм: `skryba_*` латинка, `diak_*` кирилиця.

    Вибір «за розширенням» поставив би на латинську справу кириличну модель —
    і це тихе сміття, а не помилка.
    """
    _weights(space, "skryba_f792_v6.mlmodel", "diak_cyr_v4.mlmodel")
    lat, lat_voice = R.pick_model("latin")
    assert lat.name.startswith("skryba")
    assert lat_voice is None, "у латинки другого голосу немає"
    cyr, _ = R.pick_model("cyrillic")
    assert cyr.name.startswith("diak")


def test_second_voice_is_a_different_engine(space: Path) -> None:
    """Другий голос має помилятись інакше, інакше він марний.

    CTC прив'язаний до пікселів і калічить локально, зберігаючи корінь; PARSeq
    має мовну модель і підставляє правдоподібне слово. Два PARSeq'и такої
    користі не дали б.
    """
    _weights(space, "pysar_cyr_v17.pt", "diak_cyr_v4.mlmodel")
    main, voice = R.pick_model("cyrillic", second_voice=True)
    assert main.suffix == ".pt" and voice is not None
    assert voice.suffix == ".mlmodel"
    _, none = R.pick_model("cyrillic", second_voice=False)
    assert none is None


def test_pp_voice_is_found_and_the_newest_generation_wins(space: Path) -> None:
    """Дяк-Літописець (`.safetensors`, PP-OCRv6) — нове покоління Дяка.

    Доти `local_models` бачив лише `.pt`/`.mlmodel`, тож ваги PP лежали поруч і
    не існували для вибору: читання мовчки йшло старим голосом.
    """
    _weights(space, "pysar_cyr_v18.pt", "diak_cyr_v4.mlmodel", "diak_cyr_v6.safetensors")
    _, voice = R.pick_model("cyrillic", second_voice=True)
    assert voice is not None and voice.name == "diak_cyr_v6.safetensors"


def test_production_names_the_voice_too(space: Path) -> None:
    """Голос — теж рішення дослідника, а не наслідок номера версії."""
    _weights(space, "pysar_cyr_v18.pt", "diak_cyr_v4.mlmodel", "diak_cyr_v6.safetensors")
    (space / R.PRODUCTION_NAME).write_text(json.dumps({"production": {
        "cyrillic": {"model": "pysar_cyr_v18.pt", "voice": "diak_cyr_v4.mlmodel"}}}),
        encoding="utf-8")
    main, voice = R.pick_model("cyrillic", second_voice=True)
    assert main.name == "pysar_cyr_v18.pt"
    assert voice is not None and voice.name == "diak_cyr_v4.mlmodel"


def test_production_picks_a_new_family_over_a_bigger_number(space: Path) -> None:
    """🔴 Номер між родинами не порівнюється: `skryba_pp_v3` — нове покоління,
    а за номером його обійшла б `skryba_f792_v6`."""
    _weights(space, "skryba_f792_v6.mlmodel", "skryba_pp_v3.safetensors")
    (space / R.PRODUCTION_NAME).write_text(json.dumps({"production": {
        "latin": {"model": "skryba_pp_v3.safetensors"}}}), encoding="utf-8")
    main, _ = R.pick_model("latin")
    assert main.name == "skryba_pp_v3.safetensors"


def test_superseded_pack_reads_until_the_new_one_arrives(space: Path, tmp_path: Path,
                                                         monkeypatch) -> None:
    """🔴 Оновлений застосунок читає й без нових ваг — старими, якщо вони вже є.

    Замінений пак не качається за замовчуванням (новий користувач не платить
    за ваги, якими ніхто не читає), але той, у кого він уже лежить, не має
    лишитись «читати нічим», доки нові не довантажені. Щойно новий є — він
    перший, хоч номер у нього менший.
    """
    from nyshporka.setup import packs

    cache = tmp_path / "_cache"
    cache.mkdir()
    old = packs.Pack(id="skryba-f792-v6", kind="model", filename="skryba_f792_v6.mlmodel",
                     sha256="x", size=1, release="weights-v1", script="latin",
                     engine="kraken", superseded=True)
    new = packs.Pack(id="skryba-pp-v3", kind="model", filename="skryba_pp_v3.safetensors",
                     sha256="y", size=1, release="weights-v2", script="latin",
                     engine="kraken")
    present = {"skryba-f792-v6"}
    monkeypatch.setattr(packs, "catalog", lambda: [old, new])
    monkeypatch.setattr(packs, "verify", lambda p: p.id in present)
    monkeypatch.setattr(packs, "path_of", lambda p: cache / p.filename)

    main, _ = R.pick_model("latin")
    assert main.name == "skryba_f792_v6.mlmodel"

    present.add("skryba-pp-v3")
    main, _ = R.pick_model("latin")
    assert main.name == "skryba_pp_v3.safetensors"
    # і за замовчуванням качається лише нове
    assert [p.id for p in packs.missing()] == []
    present.discard("skryba-pp-v3")
    assert [p.id for p in packs.missing()] == ["skryba-pp-v3"]


def test_no_weights_is_a_message_not_a_crash(space: Path) -> None:
    with pytest.raises(R.ReadError, match="моделі письма"):
        R.pick_model("cyrillic")


def test_missing_script_names_what_is_available(space: Path) -> None:
    _weights(space, "diak_cyr_v4.mlmodel")
    with pytest.raises(R.ReadError, match="latin"):
        R.pick_model("latin")


# ── план ─────────────────────────────────────────────────────────────────────
def test_nested_folders_are_explained_not_reported_as_empty(space: Path,
                                                            tmp_path: Path) -> None:
    """🔴 `--case-dir` не рекурсивний.

    Тека з підтеками читається як порожня — «у теці немає сторінок». Це
    коштувало прогонів, тож пояснення мусить називати причину, а не наслідок.
    """
    case = tmp_path / "справа"
    (case / "плівка_01").mkdir(parents=True)
    (case / "плівка_01" / "0001.jpg").write_bytes(b"\0")
    with pytest.raises(R.ReadError, match="підтек"):
        R.plan(case)


def test_empty_folder_says_so(tmp_path: Path) -> None:
    case = tmp_path / "порожня"
    case.mkdir()
    with pytest.raises(R.ReadError, match="немає зображень"):
        R.plan(case)


def test_frames_are_counted_flat_like_the_runner_sees_them(tmp_path: Path) -> None:
    case = tmp_path / "справа"
    (case / "під").mkdir(parents=True)
    for n in ("0001.jpg", "0002.JPG", "нотатки.txt"):
        (case / n).write_bytes(b"\0")
    (case / "під" / "0003.jpg").write_bytes(b"\0")
    assert R.count_frames(case) == 2, "порахувались підтеки або чужі файли"


def test_command_carries_the_second_voice_and_progress_channel(tmp_path: Path) -> None:
    plan = R.Plan(case_dir=tmp_path, out_dir=tmp_path / "out",
                  model=tmp_path / "pysar_cyr_v17.pt", script="cyrillic",
                  frames=10, python=tmp_path / "python.exe",
                  runner=tmp_path / "runner.py",
                  voice=tmp_path / "diak_cyr_v4.mlmodel")
    cmd = plan.command(case_key="DAHMO/315/8433")
    assert "--models" in cmd and "--progress-json" in cmd
    assert cmd[cmd.index("--case-key") + 1] == "DAHMO/315/8433"
    assert "--script" in cmd and cmd[cmd.index("--script") + 1] == "cyrillic"


# ── важелі ресурсів ──────────────────────────────────────────────────────────
def _plan(tmp_path: Path):
    from nyshporka.htr.run import Plan

    return Plan(case_dir=tmp_path / "справа", out_dir=tmp_path / "out",
                model=tmp_path / "m.pt", script="cyrillic", frames=100,
                python=tmp_path / "py.exe", runner=tmp_path / "runner.py")


def test_resource_levers_reach_the_runner(tmp_path: Path) -> None:
    """🔴 Машина в кожного своя, і без важелів відповіддю на «не тягне»
    лишалось би «купіть іншу карту».

    Раннер має ці ручки від початку, але доступні вони були лише прямим
    викликом — тобто рівно та людина, якій найбільше треба стиснути прогін під
    слабку карту, важелів не мала.
    """
    cmd = _plan(tmp_path).command(shard="1/3", gpu_lock=str(tmp_path / "x.lock"),
                                  gpu_sato=False, seg_height=1440,
                                  pages="1-50", limit=10)
    assert "--shard" in cmd and cmd[cmd.index("--shard") + 1] == "1/3"
    assert "--gpu-lock" in cmd
    assert "--no-gpu-sato" in cmd, "sato лишився на карті — шарди стануть у чергу"
    assert "--seg-height" in cmd and cmd[cmd.index("--seg-height") + 1] == "1440"
    assert "--pages" in cmd and "--limit" in cmd


def test_default_run_carries_no_levers(tmp_path: Path) -> None:
    """Дефолт лишається тим самим: важіль з'являється лише коли його попросили.

    Інакше кожен звичайний прогін мовчки міняв би поведінку — і різницю в
    результаті приписали б моделі, а не прапорцю.
    """
    cmd = _plan(tmp_path).command()
    for flag in ("--shard", "--gpu-lock", "--no-gpu-sato", "--seg-height",
                 "--pages", "--limit", "--voice-batch"):
        assert flag not in cmd, f"{flag} просочився у звичайний прогін"


def test_sato_flag_is_negative_only(tmp_path: Path) -> None:
    """⚠ `--gpu-sato` за замовчуванням увімкнений у раннері, тож передавати
    його ствердно немає сенсу — а от зняття мусить бути явним."""
    assert "--gpu-sato" not in _plan(tmp_path).command(gpu_sato=True)
    assert "--no-gpu-sato" in _plan(tmp_path).command(gpu_sato=False)


# ── перечитування іншою моделлю ─────────────────────────────────────────────
@pytest.mark.parametrize(("name", "tag"), [
    ("skryba_f792_v6.mlmodel", "skryba_v6"),
    ("diak_cyr_v4.mlmodel", "diak_v4"),
    ("pysar_cyr_v16.pt", "v16"),
])
def test_model_tag_names_the_folder_like_the_runner_names_voices(name: str, tag: str) -> None:
    assert R.model_tag(name) == tag


def test_an_unknown_model_is_a_message_not_a_crash(space: Path) -> None:
    with pytest.raises(R.ReadError, match="не знайдена"):
        R.resolve_model("nemaie_v1.mlmodel")


def test_rereading_with_a_named_model_goes_to_its_own_folder(space: Path, tmp_path: Path,
                                                             monkeypatch) -> None:
    """🔴 Кирилична справа виявилась наполовину латинкою: Скриба читає її в ОКРЕМУ
    теку (раннер не мішає рушії), письмо — від моделі, сегментація — з кешу."""
    import types

    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    _weights(space, "skryba_f792_v6.mlmodel", "pysar_cyr_v17.pt", "diak_cyr_v4.mlmodel")
    case = tmp_path / "spr-2461"
    case.mkdir()
    (case / "0001.jpg").write_bytes(b"\0")
    monkeypatch.setattr(doc, "engine_venv", lambda: tmp_path / "venv")
    monkeypatch.setattr(E, "inspect", lambda venv: types.SimpleNamespace(
        ok=True, python=tmp_path / "python.exe", problems=[], missing=[]))
    seg = tmp_path / "з-хмари" / "htr_seg" / "pages_dl_01__085f51d2"

    p = R.plan(case, model="skryba_f792_v6.mlmodel", seg_cache=seg)

    assert p.model.name == "skryba_f792_v6.mlmodel"
    assert (p.script, p.voice, p.script_trust) == ("latin", None, "fixed")
    assert p.out_dir.name == "spr-2461-skryba_v6"
    cmd = p.command()
    assert cmd[cmd.index("--seg-cache-dir") + 1] == str(seg)
    assert "--models" not in cmd


# ── гард теки для застосунку (аудит 29.09.2026) ─────────────────────────────
def test_app_reads_only_from_case_roots(space: Path, tmp_path: Path) -> None:
    """Шлях із браузера — лише з коренів справ; термінал гарду не має.

    План не лише читає теку, а й пише в неї (PDF розгортається в кадри), а
    черга демона доти брала будь-яку теку машини.
    """
    from nyshporka import ops as O

    foreign = tmp_path / "чужа"
    foreign.mkdir()
    (foreign / "0001.jpg").write_bytes(b"\0")
    with pytest.raises(R.ReadError, match="Корені справ"):
        R.plan(foreign, zone=True)
    with pytest.raises(R.ReadError, match="Корені справ"):
        R.plan(str(tmp_path / "data" / "raw" / ".." / ".." / "чужа"), zone=True)
    env = O.call("read.plan", {"case_dir": str(foreign)})
    assert not env.ok and "Корені справ" in env.error
    inside = tmp_path / "data" / "raw" / "спр"
    inside.mkdir(parents=True)
    with pytest.raises(R.ReadError, match="немає зображень"):
        R.plan(inside, zone=True)
    with pytest.raises(R.ReadError) as exc:
        R.plan(foreign)                     # термінал: тека людини, гарду нема
    assert "Корені справ" not in str(exc.value)


def test_daemon_queue_asks_for_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from nyshporka.daemon import workers as W

    seen: dict = {}

    class _Stop(Exception):
        pass

    def fake(case_dir, **kw):
        seen.update(kw)
        raise _Stop

    monkeypatch.setattr(R, "plan", fake)
    with pytest.raises(_Stop):
        asyncio.run(W._start_read(None, None, {"case_dir": "x"}))  # type: ignore[arg-type]
    assert seen.get("zone") is True
