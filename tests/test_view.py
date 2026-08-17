"""👁 Гортач: вартість перегляду рахується геометрією, а не бажанням.

Правило, на якому тримається весь пошук: **виявити ≠ перевірити**. Машина подає
кандидата, вирішує око — і другий рушій тут не суддя, бо ознака в пікселях.

Тому дефолт — РЯДОК. Ціла сторінка коштує моделі приблизно вчетверо дорожче за
вирізку рядка (а в байтах на реальному скані різниця виходила в десятки разів),
і при десятках звірок за сеанс це вирішує, скільки їх узагалі відбудеться.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.htr import view as V

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.fixture
def run(tmp_path: Path, monkeypatch):
    """Прогін із однією сторінкою, текстом і рамками рядків."""
    # 🔴 Простір оголошується ПЕРШИМ, до імпорту сховища: `htr_store` бере
    # корені на рівні МОДУЛЯ, тож після його імпорту перемикати вже пізно.
    # Це та сама «застигла константа», через яку тест інакше читав би простір
    # розробника — і зеленів би від чужих даних.
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import htr_store as S

    case = tmp_path / "data" / "raw" / "справа"
    out = tmp_path / "reports" / "htr" / "прогін"
    case.mkdir(parents=True)
    out.mkdir(parents=True)

    img = Image.new("RGB", (600, 400), (250, 248, 244))
    img.save(case / "0001.jpg")

    (out / "0001.txt").write_text("перший рядок\nдругий рядок\nтретій рядок\n",
                                  encoding="utf-8")
    (out / "0001.lines.json").write_text(json.dumps({
        "size": [600, 400],
        "boxes": [[40, 30, 560, 80], [40, 120, 560, 170], [40, 210, 560, 260]],
    }), encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "version": 1, "case_dir": str(case), "model": "pysar_cyr_v17.pt",
        "engine": "parseq", "script": "cyrillic",
        "pages": {"0001.jpg": {"orient": 0, "lines": 3, "conf": 0.9}},
    }), encoding="utf-8")

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    monkeypatch.setattr(S, "_case_roots", lambda: [tmp_path / "data" / "raw"])
    return "прогін", "0001.jpg"


def test_line_crop_is_far_lighter_than_the_page(run) -> None:
    """🔴 Головна властивість: рядок дешевий, сторінка дорога."""
    name, page = run
    line = V.shot(name, page, line=1)
    whole = V.shot(name, page, region="page")
    assert line.region == "line" and whole.region == "page"
    assert len(line.png) < len(whole.png)
    assert line.height < whole.height


def test_crop_carries_its_own_line_of_text(run) -> None:
    """Разом із пікселями їде саме той рядок, який оцінюють."""
    name, page = run
    assert V.shot(name, page, line=0).text == "перший рядок"
    assert V.shot(name, page, line=2).text == "третій рядок"


def test_pad_widens_the_crop_because_cursive_has_tails(run) -> None:
    """Виносні елементи скоропису («д», «р», «у») виходять за рамку рядка."""
    name, page = run
    tight = V.shot(name, page, line=1, pad=0, annotate=False)
    loose = V.shot(name, page, line=1, pad=30, annotate=False)
    assert loose.width > tight.width and loose.height > tight.height


def test_annotation_marks_which_line_is_being_judged(run) -> None:
    """🔴 Без рамки модель бачить кілька рядків і оцінює НЕ ТОЙ.

    Саме тому `pad` і `annotate` йдуть парою: щойно взяли із запасом — треба
    сказати, який саме рядок питають.
    """
    name, page = run
    plain = V.shot(name, page, line=1, pad=40, annotate=False)
    marked = V.shot(name, page, line=1, pad=40, annotate=True)
    assert plain.png != marked.png, "рамку не домальовано"


def test_missing_boxes_fall_back_to_the_page_and_say_so(run, tmp_path) -> None:
    """Прогони до 2026-08-09 рамок не писали — це не помилка, але й не мовчання.

    Мовчки віддати сторінку замість рядка не можна: вона коштує інакше.
    """
    name, page = run
    (tmp_path / "reports" / "htr" / "прогін" / "0001.lines.json").unlink()
    s = V.shot(name, page, line=1)
    assert s.region == "page"
    assert "рамок" in s.note


def test_line_out_of_range_is_a_message_not_a_crash(run) -> None:
    name, page = run
    with pytest.raises(V.ViewError, match="рядка 9"):
        V.shot(name, page, line=9)


def test_missing_scan_explains_where_it_was_looked_for(run, tmp_path) -> None:
    """Скан міг переїхати; сказати про це треба прямо, а не порожнім екраном."""
    name, page = run
    (tmp_path / "data" / "raw" / "справа" / "0001.jpg").unlink()
    with pytest.raises(V.ViewError, match="скан"):
        V.shot(name, page, line=0)


def test_view_returns_a_data_url_for_the_browser(run) -> None:
    name, page = run
    s = V.shot(name, page, line=0)
    assert s.data_url.startswith("data:image/png;base64,")
    assert "image" not in s.as_dict(), "картинка не має дублюватись у полях"


def test_mcp_sends_the_image_as_an_image_not_as_text() -> None:
    """🔴 Модель не вміє «подивитись» на base64-рядок.

    Якщо картинка їде текстом, звірка оком перетворюється на ще один переказ
    того, що вже сказала машина.
    """
    from nyshporka.core.envelope import ok
    from nyshporka.mcp.server import _pop_image

    env = ok({"line": 3, "image": "data:image/png;base64,QUJD"})
    got = _pop_image(env)
    assert got == ("QUJD", "image/png")
    assert "image" not in env.data, "картинка лишилась ще й у JSON"


def test_page_text_actually_carries_the_text(run) -> None:
    """🔴 Відповідь була `ok`, а тексту в ній не було зовсім.

    `read_page_text` віддає рядки тексту під ключем `lines`; операція
    накладала туди ж геометрію рамок — і прочитане зникало. Гортач, головний
    екран «подивитись, що прочитала машина», показував порожню сторінку й
    «0 рядків»: не помилку, не попередження, просто нічого. Знайшлось лише
    проходом по реальному прогону, бо на рівні окремої функції все справне.
    """
    from nyshporka import ops as O

    name, page = run
    env = O.call("page.text", {"run": name, "page": page})
    assert env.ok, env.error
    assert env.data["lines"] == ["перший рядок", "другий рядок", "третій рядок"]
    assert "перший рядок" in env.data["text"]
    # Геометрія лишається — під власним іменем, а не замість тексту.
    assert env.data["geometry"]["has"] is True
    assert len(env.data["geometry"]["boxes"]) == 3


def test_the_viewer_reads_the_same_keys_the_op_returns() -> None:
    """Гортач і операція мусять називати ті самі речі однаково.

    Саме розходження імен («text» проти «lines») і давало порожній екран без
    жодної помилки: JS звертався до поля, якого в відповіді не існує, і
    отримував `undefined`, а не збій.
    """
    import re

    js = (Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "daemon"
          / "static" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"'view\.open': async.*?\n  \},", js, re.S)
    assert block, "обробник гортача змінився — перевірку треба переписати"
    used = set(re.findall(r"env\.data\.(\w+)", block.group(0)))
    assert used <= {"lines", "geometry", "text", "page", "orient", "conf",
                    "detector"}, f"гортач читає невідомі поля: {used}"


# ── канал Б: рендер зі справи-PDF ────────────────────────────────────────────
@pytest.fixture
def pdf_run(tmp_path: Path, monkeypatch):
    """Прогін, у якого кадрів на диску НЕМА — лише справа-PDF.

    Це не екзотика, а третина прогонів проєкту: хмара розгортає PDF у кадри на
    орендованому боксі, читає їх і зникає разом із ними. На диску лишається
    текст, рамки — і жодного зображення.

    Сторінка навмисно НЕ біла: чорна смуга стоїть у нижній половині, а рамка
    рядка вказує на неї. Рендер виходить іншої ширини, ніж кадр, який читав
    прогін, — тож якщо рамку не перемасштабувати, кроп поїде у порожній верх.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import htr_store as S

    case = tmp_path / "data" / "raw" / "pdf-справа"
    out = tmp_path / "reports" / "htr" / "pdf-прогін"
    case.mkdir(parents=True)
    out.mkdir(parents=True)

    # Кадр, який «читав» прогін: 1000×1400, смуга на y=900..1000.
    src = Image.new("RGB", (1000, 1400), (255, 255, 255))
    for y in range(900, 1000):
        for x in range(100, 900):
            src.putpixel((x, y), (10, 10, 10))
    # Справа лежить одним PDF на дві сторінки; наш кадр — другий.
    blank = Image.new("RGB", (1000, 1400), (255, 255, 255))
    blank.save(case / "справа.pdf", save_all=True, append_images=[src])

    (out / "0002.txt").write_text("смуга\n", encoding="utf-8")
    (out / "0002.lines.json").write_text(json.dumps({
        "size": [1000, 1400], "boxes": [[100, 900, 900, 1000]],
    }), encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "version": 1, "case_dir": str(case), "frames_total": 2,
        "model": "pysar_cyr_v17.pt", "engine": "parseq", "script": "cyrillic",
        "pages": {"0002.jpg": {"orient": 0, "lines": 1}},
    }), encoding="utf-8")

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    monkeypatch.setattr(S, "_case_roots", lambda: [tmp_path / "data" / "raw"])
    V._RENDER_CACHE.clear()
    return "pdf-прогін", "0002.jpg", case


def _mean(im) -> float:
    from PIL import ImageStat

    return float(ImageStat.Stat(im.convert("L")).mean[0])


def test_page_renders_from_the_case_pdf_when_no_scan_exists(pdf_run) -> None:
    """🔴 Без цього гортач сліпий саме на найбільших справах."""
    pytest.importorskip("pypdfium2")
    run, page, _ = pdf_run
    shot = V.shot(run, page, region="page")
    assert shot.region == "page"
    assert shot.png[:4] == b"\x89PNG"


def test_line_box_is_rescaled_to_the_rendered_page(pdf_run) -> None:
    """🔴🔴 Рамка лежить у координатах кадру, а показуємо РЕНДЕР іншої ширини.

    Приймач тут не «кроп повернувся», а те, що в ньому справді ТЕМНО: рамка
    вказує на чорну смугу. Без перемасштабування ті самі числа на ширшому
    рендері вказали б у порожній верх сторінки — кроп був би білим, і людина
    дивилась би на чистий папір, вважаючи, що бачить свій рядок.
    """
    pytest.importorskip("pypdfium2")
    run, page, _ = pdf_run
    shot = V.shot(run, page, line=0, pad=0, annotate=False)
    assert shot.region == "line", shot.note
    got = Image.open(__import__("io").BytesIO(shot.png))
    assert _mean(got) < 100, (
        f"кроп світлий (середнє {_mean(got):.0f}) — рамку не перемасштабували, "
        f"тож він поїхав з чорної смуги в порожнє поле")


def test_partial_run_still_renders_thanks_to_frames_total(pdf_run) -> None:
    """🔴 Частковий прогін мав право на аркуш, а отримував відмову.

    Прочитано лише другий кадр із двох; щільність `1..N` не сходиться, і без
    знаменника доказ не будувався. `frames_total` його дає — доказ лишається
    таким самим строгим, але вже не вимагає, щоб прогін дійшов до кінця.
    """
    pytest.importorskip("pypdfium2")
    run, page, _ = pdf_run
    assert V.shot(run, page, region="page").png[:4] == b"\x89PNG"


def test_without_frames_total_a_partial_run_is_refused(pdf_run) -> None:
    """І це не регресія, а межа знання: вгадувати знаменник тут не можна."""
    pytest.importorskip("pypdfium2")
    run, page, case = pdf_run
    meta_path = case.parent.parent.parent / "reports" / "htr" / run / "_htr_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["frames_total"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    V._RENDER_CACHE.clear()
    with pytest.raises(V.ViewError) as exc:
        V.shot(run, page, region="page")
    # 🔴 Причина мусить бути НАЗВАНА: за кожною стоїть інша дія.
    assert "щільна" in str(exc.value) or "не записав" in str(exc.value), exc.value


def test_render_cache_does_not_confuse_two_folders(pdf_run, tmp_path) -> None:
    """🔴 Тека — частина ключа кешу, інакше друга спроба дістає ЧУЖИЙ аркуш."""
    pytest.importorskip("pypdfium2")
    run, page, _ = pdf_run
    first = V.shot(run, page, region="page").png
    assert len(V._RENDER_CACHE) == 1
    key = next(iter(V._RENDER_CACHE))
    assert len(key) == 3 and key[2], "у ключі кешу немає теки справи"
    assert first == V.shot(run, page, region="page").png


# ── фолбек через реєстр: коли в меті шлях орендованого боксу ──────────────────
def test_scan_is_found_through_the_registry_when_meta_path_is_foreign(
        tmp_path: Path, monkeypatch) -> None:
    """🔴 Це ПОДВОЮЄ зону видимості гортача, і досі не мало жодного тесту.

    Хмарний прогін пише в мету теку орендованого боксу (`/tmp/htrcase/…`),
    якої на цій машині не існує й не існувало. Текст є, рамки є, а подивитись
    оком нічим — доти, доки прогін не зведено до справи бібліотеки, у якій шлях
    уже справжній. Заміряно на 478 прогонах: 161 → 326 знайдених сканів.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import htr_store as S

    case = tmp_path / "data" / "raw" / "справжня"
    out = tmp_path / "reports" / "htr" / "хмарний"
    case.mkdir(parents=True)
    out.mkdir(parents=True)
    Image.new("RGB", (300, 200), (200, 200, 200)).save(case / "0001.jpg")
    (out / "0001.txt").write_text("рядок\n", encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "version": 1,
        # той самий шлях, що лишається після хмари — його тут немає
        "case_dir": "/tmp/htrcase/pages_dl_14",
        "case_key": "DAHMO/315/159",
        "pages": {"0001.jpg": {"orient": 0, "lines": 1}},
    }), encoding="utf-8")

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    monkeypatch.setattr(S, "_case_roots", lambda: [tmp_path / "data" / "raw"])

    # Без реєстру скан не знаходиться — це і є та третина «нічиїх» прогонів.
    monkeypatch.setattr(S, "_case_dirs_via_registry", lambda run: [])
    assert S.resolve_scan("хмарний", "0001.jpg") is None

    # А з реєстром — знаходиться, і гортач одразу бачить аркуш.
    monkeypatch.setattr(S, "_case_dirs_via_registry", lambda run: [case])
    got = S.resolve_scan("хмарний", "0001.jpg")
    assert got is not None and got[0] == case / "0001.jpg"
    assert V.shot("хмарний", "0001.jpg", region="page").png[:4] == b"\x89PNG"


def test_refusal_names_the_reason_and_the_repair(tmp_path: Path,
                                                 monkeypatch) -> None:
    """🔴 За кожною причиною відмови стоїть ІНША дія.

    «Немає PDF» лікується докладанням файлу, «сторінок не сходиться» —
    перепрогоном, «теки не названо» — прив'язкою прогону до справи. Одне
    узагальнене «або…, або…» не дає зробити нічого з трьох.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import htr_store as S

    out = tmp_path / "reports" / "htr" / "нічий"
    out.mkdir(parents=True)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (out / "0001.txt").write_text("рядок\n", encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "version": 1, "case_dir": "/tmp/htrcase/pages_dl_14",
        "pages": {"0001.jpg": {"orient": 0, "lines": 1}},
    }), encoding="utf-8")
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    monkeypatch.setattr(S, "_case_roots", lambda: [tmp_path / "data" / "raw"])
    monkeypatch.setattr(S, "_case_dirs_via_registry", lambda run: [])

    with pytest.raises(V.ViewError) as exc:
        V.shot("нічий", "0001.jpg")
    msg = str(exc.value)
    assert "cases bind" in msg, f"відмова не називає ремонту: {msg}"


# ── операція page.view: конверт, а не лише `shot()` ──────────────────────────
def test_page_view_op_returns_an_image_and_warns_without_boxes(run) -> None:
    """🔴 `shot()` тестувався, а ОПЕРАЦІЯ — ні: ні `fail`, ні попередження.

    Саме конверт бачать браузер і агент, і саме в ньому їде попередження
    «показано всю сторінку замість рядка» — різниця вчетверо у вартості.
    """
    from nyshporka import ops as O

    name, page = run
    env = O.call("page.view", {"run": name, "page": page, "line": 0})
    assert env.ok, env.error
    assert env.data.get("image", "").startswith("data:image/png;base64,")
    assert env.data["region"] == "line"

    env = O.call("page.view", {"run": name, "page": "немає.jpg", "line": 0})
    assert not env.ok
    assert "немає" in (env.error or "")


def test_page_view_op_warns_when_it_falls_back_to_the_whole_page(
        run, tmp_path: Path) -> None:
    """Мовчазна підміна рядка сторінкою — це вчетверо дорожчий перегляд."""
    from nyshporka import ops as O

    name, page = run
    (tmp_path / "reports" / "htr" / name / "0001.lines.json").unlink()
    env = O.call("page.view", {"run": name, "page": page, "line": 0})
    assert env.ok, env.error
    assert env.data["region"] == "page"
    assert any(w.code == "view_fallback" for w in env.warnings), env.warnings
