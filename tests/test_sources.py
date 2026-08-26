"""📥 Джерела: розпізнавання входу, реєстр плагінів, канал прогресу.

Найважливіше тут — форма «тека з підтеками». Вона виглядає як порожня справа, і
прийняти її за справу означає прогін на нуль сторінок, який завершується
«успішно», лишаючи людину без тексту й без пояснення.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from nyshporka.core import progress as P
from nyshporka.sources import base, load, registry
from nyshporka.sources.local import LocalSource, inspect


def _touch(path, name: str, size: int = 8):
    f = path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * size)
    return f


# ── розпізнавання входу ──────────────────────────────────────────────────────
def test_folder_of_images_is_a_case(tmp_path):
    for i in range(3):
        _touch(tmp_path, f"{i:04d}.jpg")
    sh = inspect(tmp_path)
    assert sh.kind == "images" and sh.images == 3 and sh.usable
    assert "3 кадр" in sh.explain()


def test_folder_of_subfolders_is_MANY_cases_not_an_empty_one(tmp_path):
    """🔴 Найдорожча плутанина цього шару.

    Тека, всередині якої лежать теки-справи, зображень не містить — тобто
    виглядає порожньою. Прийняти її за справу означає прогін на нуль сторінок,
    який завершується успішно: ні помилки, ні тексту, ні пояснення.
    """
    for name in ("22", "131", "7"):
        _touch(tmp_path / name, "0001.jpg")
    sh = inspect(tmp_path)
    assert sh.kind == "cases" and not sh.usable
    assert len(sh.cases) == 3
    assert "не одна справа" in sh.explain()


def test_numeric_case_folders_sort_as_numbers(tmp_path):
    """22 перед 131 — інакше перелік нечитабельний саме там, де його читають."""
    for name in ("22", "131", "7"):
        _touch(tmp_path / name, "0001.jpg")
    sh = inspect(tmp_path)
    assert [c.label for c in sh.cases] == ["7", "22", "131"]


def test_single_image_is_treated_as_its_folder(tmp_path):
    """«Справа з одного кадру» не має ставати окремим випадком усюди."""
    img = _touch(tmp_path, "0001.jpg")
    _touch(tmp_path, "0002.jpg")
    assert inspect(img).kind == "images"
    assert inspect(img).images == 2


def test_empty_folder_explains_itself(tmp_path):
    sh = inspect(tmp_path)
    assert sh.kind == "empty" and not sh.usable
    assert "немає ні зображень, ні PDF" in sh.explain()


def test_missing_path_is_an_answer_not_a_crash(tmp_path):
    sh = inspect(tmp_path / "нема")
    assert sh.kind == "missing"
    assert "нічого немає" in sh.explain()


def test_pdf_without_reader_reports_unknown_page_count(tmp_path, monkeypatch):
    """🔴 `None` — це чесне «не знаю», і воно краще за вигадане число.

    Оцінку часу без нього просто не показують; вигадана зіпсувала б планування
    на кілька годин уперед.
    """
    pdf = _touch(tmp_path, "справа.pdf", size=100)
    monkeypatch.setitem(__import__("sys").modules, "pypdfium2", None)
    monkeypatch.setitem(__import__("sys").modules, "fitz", None)
    sh = inspect(pdf)
    assert sh.kind == "pdf" and sh.pages is None
    assert "один PDF" in sh.explain()


def test_folder_with_images_and_pdfs_prefers_images(tmp_path):
    """Скани важать більше за супровідний PDF-опис, який часто лежить поруч."""
    _touch(tmp_path, "0001.jpg")
    _touch(tmp_path, "опис.pdf")
    sh = inspect(tmp_path)
    assert sh.kind == "images" and sh.pdfs == 1


# ── локальне джерело ─────────────────────────────────────────────────────────
def test_local_manifest_counts_frames_and_size(tmp_path):
    for i in range(4):
        _touch(tmp_path, f"{i:04d}.jpg", size=1000)
    m = LocalSource().manifest(str(tmp_path))
    assert m.frames == 4 and m.bytes_estimate >= 4000
    assert m.source == "local" and m.title == tmp_path.name


def test_local_manifest_refuses_a_folder_of_cases_with_a_reason(tmp_path):
    _touch(tmp_path / "22", "0001.jpg")
    with pytest.raises(base.SourceError, match="не одна справа"):
        LocalSource().manifest(str(tmp_path))


def test_local_browse_lists_subcases(tmp_path):
    for name in ("a", "b"):
        _touch(tmp_path / name, "0001.jpg")
    nodes = LocalSource().browse(str(tmp_path))
    assert {n.label for n in nodes} == {"a", "b"}
    assert all(n.kind == "case" for n in nodes)


def test_local_browse_without_ref_does_not_walk_the_disk(tmp_path):
    assert LocalSource().browse(None) == []


def test_local_fetch_refuses_to_copy_gigabytes(tmp_path):
    """Друга копія архівної справи з'їла б диск заради нічого."""
    with pytest.raises(base.SourceError, match="уже на диску"):
        LocalSource().fetch("x", tmp_path)


def test_local_declares_only_what_it_can(tmp_path):
    src = LocalSource()
    assert base.supports(src, "manifest") and base.supports(src, "browse")
    assert not base.supports(src, "fetch") and not base.supports(src, "search")


# ── покажчик ─────────────────────────────────────────────────────────────────
def test_manifest_finds_frames_by_index_label():
    """🔴 Покажчик відповідає «де метрики мого села» без завантаження."""
    m = base.Manifest(source="x", ref="r", sheets=(
        base.Sheet(1, 5, "лідер плівки"),
        base.Sheet(11, 13, "Жаврени"),
        base.Sheet(132, 223, "Резина"),
    ))
    assert m.frames_for("резина") == (132, 223)
    assert m.frames_for("ЖАВРЕНИ") == (11, 13)
    assert m.frames_for("Кишинів") is None


# ── реєстр ───────────────────────────────────────────────────────────────────
def test_registry_has_local_out_of_the_box():
    reg = load()
    assert reg.get("local") is not None
    assert "local" in {s.id for s in reg.with_cap("manifest")}


def test_broken_plugin_does_not_take_down_the_rest(monkeypatch):
    """🔴 Один зламаний сторонній архів не має гасити локальну теку."""
    class FakeEP:
        name = "поганий"

        def load(self):
            raise ImportError("немає модуля")

    monkeypatch.setattr(registry, "_from_entry_points",
                        lambda: ([], [(FakeEP.name, "ImportError: немає модуля")]))
    reg = load()
    assert reg.get("local") is not None
    assert reg.broken and reg.broken[0][0] == "поганий"


def test_plugin_cannot_shadow_a_builtin(monkeypatch):
    """Сторонній пакет не має підміняти шлях, яким користувач кладе свої скани."""
    class Impostor:
        id = "local"
        label = "підробка"
        caps = frozenset({"fetch"})

    monkeypatch.setattr(registry, "_from_entry_points", lambda: ([Impostor()], []))
    reg = load()
    assert reg.get("local").label == LocalSource().label
    assert any(name == "local" for name, _ in reg.broken)


def test_plugin_without_id_is_rejected_by_name(monkeypatch):
    """Джерело без `id` не має потрапити в реєстр і не має валити збірку.

    Перевіряється через справжній шлях завантаження (підміняється лише
    `entry_points`), інакше тест доводив би працездатність підміни, а не коду.
    """
    import importlib.metadata as meta

    class NoId:
        id = ""
        caps = frozenset()

    class FakeEP:
        name = "безіменний"

        def load(self):
            return lambda: NoId()

    class GoodEP:
        name = "добрий"

        def load(self):
            def factory():
                src = NoId()
                src.id = "чужий_архів"
                return src
            return factory

    monkeypatch.setattr(meta, "entry_points", lambda **_: [FakeEP(), GoodEP()])
    srcs, broken = registry._from_entry_points()
    assert [s.id for s in srcs] == ["чужий_архів"], "справний плагін мав пройти"
    assert [n for n, _ in broken] == ["безіменний"]
    assert "id" in broken[0][1]


# ── канал прогресу ───────────────────────────────────────────────────────────
def test_progress_roundtrip():
    buf = io.StringIO()
    P.emit(phase="fetch", i=12, n=300, item="0012.jpg", stream=buf)
    ev = P.parse(buf.getvalue().strip())
    assert ev and ev.phase == "fetch" and ev.i == 12 and ev.n == 300
    assert ev.item == "0012.jpg" and ev.pct == 4.0


def test_human_lines_are_not_events():
    assert P.parse("[fetch] качаю 0012.jpg") is None
    assert P.parse("") is None


def test_split_routes_each_line_exactly_once():
    buf = io.StringIO()
    P.emit(phase="fetch", i=1, n=2, stream=buf)
    ev, human = P.split(buf.getvalue().strip())
    assert ev is not None and human is None
    ev2, human2 = P.split("звичайний рядок")
    assert ev2 is None and human2 == "звичайний рядок"


def test_foreign_schema_is_ignored_not_misread():
    """🔴 Показник, що бреше, гірший за відсутній.

    Поля прогресу міняються; читач старої версії, який мовчки візьме число
    іншого сенсу, покаже впевнено неправильний відсоток.
    """
    import json
    line = f"{P.PREFIX} {json.dumps({'v': P.SCHEMA + 1, 'i': 5, 'n': 10})}"
    assert P.parse(line) is None


def test_broken_json_does_not_crash_the_reader():
    assert P.parse(f"{P.PREFIX} {{обірваний") is None


def test_event_is_one_line_even_with_cyrillic():
    """Рядок мусить лишитись одним рядком: читач розбирає потік по `\\n`."""
    buf = io.StringIO()
    P.emit(phase="читання", item="справа/аркуш 12", message="усе гаразд", stream=buf)
    assert buf.getvalue().count("\n") == 1


def test_zero_total_does_not_divide_by_zero():
    ev = P.Event(i=0, n=0)
    assert ev.pct == 0.0


# ── знаменник завантаження ──────────────────────────────────────────────────
def test_a_manifest_that_does_not_know_says_so(tmp_path: Path) -> None:
    """🔴 «Не знаю скільки» і «нуль кадрів» — різні відповіді.

    Поки `Manifest.frames` був просто `int`, обидві зводились до нуля, і звірка
    завантаженого з обіцяним ставала неможливою: з нулем вона або мовчить
    завжди, або лається завжди. Різницю породжують самі джерела — Commons знає
    `pagecount` лише для багатосторінкових, локальна тека не знає сторінок PDF
    без читача.
    """
    from nyshporka.sources.base import Manifest

    assert Manifest(source="x", ref="y").frames == 0
    assert Manifest(source="x", ref="y", frames=None).frames is None


def test_a_pdf_without_a_reader_does_not_pass_files_off_as_pages(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Число файлів замість числа сторінок — знаменник у сотні разів менший.

    Тека з одним PDF на 300 сторінок віддавала `frames=1`, і завантаження
    «сходилось» на першому ж кадрі. Тепер незнання лишається незнанням.
    """
    from nyshporka.sources import local

    case = tmp_path / "справа"
    case.mkdir()
    (case / "книга.pdf").write_bytes(b"%PDF-1.4\n")

    shape = local.inspect(str(case))
    if shape.pages is not None:      # читач PDF стоїть — випадок не той
        pytest.skip("у середовищі є читач PDF, «невідомо» не відтворити")
    man = local.LocalSource().manifest(str(case))
    assert man.frames is None, "число файлів видано за число сторінок"


def test_the_download_is_measured_against_the_manifest(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Приймач — знаменник, а не відсутність помилок.

    Дзеркало, що віддало сорок кадрів із трьохсот і жодного HTTP-збою, давало
    «✓ 40 кадрів» і код 0: обіцянка маніфесту друкувалась рядком вище й ніде
    не звірялась. Той самий клас вади, що обірваний архів, який браузер
    записує як успіх.
    """
    from typer.testing import CliRunner

    from nyshporka import cli as C
    from nyshporka.sources.base import FetchResult, Manifest

    class Половинчасте:
        id, label, caps = "проба", "Проба", frozenset({"manifest", "fetch"})

        def manifest(self, ref: str) -> Manifest:
            return Manifest(source=self.id, ref=ref, title="книга", frames=300)

        def fetch(self, ref, dest, *, frames=None, on_progress=None):
            return FetchResult(dest=Path(dest), frames=40, bytes=1024, skipped=0)

    class Реєстр:
        def get(self, sid: str):
            return Половинчасте()

    monkeypatch.setattr(C, "_sources_registry", lambda: Реєстр())
    res = CliRunner().invoke(C.app, ["get", "проба", "адреса",
                                     "--out", str(tmp_path / "куди")])
    assert res.exit_code == 1, res.stdout
    assert "неповна" in res.stdout, res.stdout


def test_a_download_without_a_denominator_is_not_called_complete(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ Мовчазний «✓» на невідомому знаменнику читається як доведена повнота.

    Нуль без знаменника не є доказом — тож завантаження каже про це вголос,
    але й не оголошує теку неповною: доводити нема чим.
    """
    from typer.testing import CliRunner

    from nyshporka import cli as C
    from nyshporka.sources.base import FetchResult, Manifest

    class Безмовне:
        id, label, caps = "проба", "Проба", frozenset({"manifest", "fetch"})

        def manifest(self, ref: str) -> Manifest:
            return Manifest(source=self.id, ref=ref, title="скан", frames=None)

        def fetch(self, ref, dest, *, frames=None, on_progress=None):
            return FetchResult(dest=Path(dest), frames=7, bytes=99)

    class Реєстр:
        def get(self, sid: str):
            return Безмовне()

    monkeypatch.setattr(C, "_sources_registry", lambda: Реєстр())
    res = CliRunner().invoke(C.app, ["get", "проба", "адреса",
                                     "--out", str(tmp_path / "куди")])
    assert res.exit_code == 0, res.stdout
    assert "повноту я не міряю" in res.stdout, res.stdout


# ── 🦆 зведений покажчик як джерело пошуку ───────────────────────────────────
class _Ответ:
    """Двійник відповіді сервісу. `text`, бо саме його читає джерело."""

    def __init__(self, text: str, code: int = 200) -> None:
        self.text = text
        self.status_code = code

    def raise_for_status(self) -> None:
        pass


class _Покажчик:
    """Двійник HTTP-клієнта: пошук приймає лише тіло, тож POST."""

    def __init__(self, payload: object) -> None:
        import json as _json

        self.body = _json.dumps(payload, ensure_ascii=False)
        self.seen: list[object] = []

    def post(self, url: str, data=None, json=None):
        self.seen.append((url, json))
        return _Ответ(self.body)


def _duck(payload: object):
    from nyshporka.sources.duck import DuckSource
    from nyshporka.sources.http import Fetcher

    api = _Покажчик(payload)
    return DuckSource(fetcher=Fetcher(base="https://п", delay=0.0, client=api)), api


def test_duck_finds_a_case_that_the_bundled_snapshot_never_saw():
    """🔴 Заради цього покажчик і стоїть у пошуку.

    Вкладений зріз ARCHIUM описує виставлене в мережу, і по ф.230 має одну
    позицію з 229 наявних в описі. Запит про справу, якої там немає, віддавав
    нуль — а нуль на екрані каталогів читається як «такого не існує».
    """
    src, api = _duck([{"full_code": "ДАХмО-230-1-2А", "is_online": True,
                       "title": "Іменні списки дворян Подільської губернії. Том 2",
                       "years": [{"start_year": 1844, "end_year": 1844}]}])
    (hit,) = src.search("іменні списки дворян")
    assert hit.shifra == "ДАХмО-230-1-2А"
    assert hit.years == "1844"
    assert hit.url.endswith("/230/1/2%D0%90")
    assert api.seen[0][1] == {"title": "іменні списки дворян"}


def test_duck_promises_no_download_because_it_has_no_files():
    """Кнопка «Завантажити» там, де за нею немає файлу, гірша за її відсутність.

    Покажчик знає про справу все, крім самої справи, — тож знахідка веде на
    його сторінку, а не в чергу завантаження.
    """
    src, _ = _duck([{"full_code": "ЦДІАК-224-1-1112", "title": "Метрична книга"}])
    (hit,) = src.search("метрична")
    assert hit.acquirable is False
    assert hit.url.startswith("https://inspector.duckarchive.com/archives/")


def test_duck_does_not_hide_the_services_ceiling_behind_the_limit():
    """🔴 Рівно 50 — це «обрізано», а не «знайдено 50»: пагінації в пошуку немає.

    Різати видачу рівно по `limit` означало б, що обрізка, зроблена сервісом,
    зникає з очей: перелік виглядає повним, хоч ним не є, — і саме таким його
    беруть за знаменник негативу.
    """
    from nyshporka.sources.duck import CEILING

    src, _ = _duck([{"full_code": f"ДАХмО-230-1-{i}", "title": "Справа"}
                    for i in range(CEILING)])
    assert len(src.search("справа", limit=10)) == CEILING


def test_duck_answers_with_a_reason_not_with_a_silent_zero():
    """Сервіс віддає HTML сторінки там, де шляху немає, — а це не «нічого»."""
    from nyshporka.sources.base import SourceError
    from nyshporka.sources.duck import DuckSource
    from nyshporka.sources.http import Fetcher

    class _HTML:
        def post(self, url: str, data=None, json=None):
            return _Ответ("<!doctype html><html>…")

    src = DuckSource(fetcher=Fetcher(base="https://п", delay=0.0, client=_HTML()))
    with pytest.raises(SourceError):
        src.search("будь-що")


def test_duck_is_in_the_registry_out_of_the_box():
    """Джерело, якого немає в реєстрі, не бере участі в жодному знаменнику."""
    reg = load()
    src = reg.get("duck")
    assert src is not None
    assert "search" in src.caps
    assert src.catalog_source()[0] == "live"


def test_duck_refuses_instead_of_answering_zero_when_the_network_is_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Вимкнена мережа мусить читатись як відмова, а не як «такого немає».

    Порожній перелік від джерела, яке навіть не питали, — найдорожчий вид
    хибного нуля: він додається до знаменника й закриває напрям.
    """
    from nyshporka.sources.base import SourceError
    from nyshporka.sources.duck import DuckSource

    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    with pytest.raises(SourceError):
        DuckSource().search("будь-що")


# ── 🏛 від знахідки до рішення «збирати цей фонд чи ні» ──────────────────────
def test_hits_are_rolled_up_into_fonds_because_the_decision_is_about_a_fond():
    """🔴 Рішення після пошуку приймають про фонд, а не про окрему справу.

    Три томи одного фонду й три випадкові збіги з трьох архівів у плаского
    списку виглядають однаково — і вибір «чий реєстр збирати» доводилось
    робити, вичитуючи шифри очима.
    """
    from nyshporka.ops_builtin import _by_fond

    rows = _by_fond([
        {"repo": "DAHMO", "archive": "ДАХмО", "fond": "230", "source": "duck",
         "years": "1844", "title": "Іменні списки. Том 1"},
        {"repo": "DAHMO", "archive": "ДАХмО", "fond": "230", "source": "archium",
         "years": "1802-1841"},
        {"repo": "CDIAK", "archive": "ЦДІАК", "fond": "224", "source": "duck",
         "years": "1771"},
    ])
    assert [(r["repo"], r["fond"], r["hits"]) for r in rows] == [
        ("DAHMO", "230", 2), ("CDIAK", "224", 1)]
    assert rows[0]["sources"] == ["duck", "archium"]
    # Роки — з того, що знайшлось, і межами фонду не прикидаються.
    assert (rows[0]["year_from"], rows[0]["year_to"]) == (1802, 1844)


def test_a_hit_without_a_fond_is_not_given_one():
    """Дзеркало плівок адресує плівки, а не фонди — вигаданий фонд гірший за брак.

    Такий рядок просто не бере участі в оцінці, і це видно: сума по фондах
    менша за видачу.
    """
    from nyshporka.ops_builtin import _by_fond

    assert _by_fond([{"repo": "", "fond": "", "source": "fsfilm"}]) == []


def test_the_fond_card_puts_the_index_and_our_own_state_side_by_side(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Обидві половини оцінки разом — інакше фонд збирають удруге.

    «Що це за фонд» жило в чужому покажчику, «чи є він у нас» — на іншому
    екрані; поки їх не звели, про вже зібраний фонд дізнавались після збирання.
    """
    from nyshporka import ops_builtin as OB

    class _Двійник:
        id, label, caps = "duck", "Покажчик", frozenset({"search"})

        def fond_card(self, archive: str, fond: str):
            return {"archive": archive, "fond": fond, "title": "Дворянське зібрання",
                    "years": "1800-1914", "opys": [{"opys": "3", "years": "1800-1914",
                                                    "title": "Балтський повіт"}],
                    "url": "https://п/archives/ДАХмО/230"}

    class _Реєстр:
        def get(self, sid: str):
            return _Двійник() if sid == "duck" else None

    monkeypatch.setattr(OB, "_registry", lambda: _Реєстр())
    monkeypatch.setattr(OB, "_our_fond",
                        lambda repo, fond: {"has_registry": False, "rows": 0,
                                            "on_disk": 0})
    op = next(o for o in __import__("nyshporka").ops.all_ops()
              if o.name == "catalog.fond")
    env = op.fn(op.args(repo="DAHMO", fond="230"))
    assert env.ok
    assert env.data["card"]["title"] == "Дворянське зібрання"
    assert [i["opys"] for i in env.data["card"]["opys"]] == ["3"]
    # Фонд, якого в нас немає, мусить вести до наступного кроку, а не в глухий кут.
    assert [n.op for n in env.next] == ["registry.plan"]


def test_the_fond_card_says_why_it_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Порожня картка без причини змішує «фонду немає» і «сервіс не відповів»."""
    from nyshporka import ops_builtin as OB
    from nyshporka.sources.base import SourceError

    class _Мовчун:
        id, label, caps = "duck", "Покажчик", frozenset({"search"})

        def fond_card(self, archive: str, fond: str):
            raise SourceError("покажчик не відповів: таймаут")

    class _Реєстр:
        def get(self, sid: str):
            return _Мовчун()

    monkeypatch.setattr(OB, "_registry", lambda: _Реєстр())
    monkeypatch.setattr(OB, "_our_fond",
                        lambda repo, fond: {"has_registry": True, "rows": 7779,
                                            "on_disk": 39})
    op = next(o for o in __import__("nyshporka").ops.all_ops()
              if o.name == "catalog.fond")
    env = op.fn(op.args(repo="DAHMO", fond="230"))
    assert env.ok and not env.data["card"]
    assert any("таймаут" in w.text for w in env.warnings)
    # Наш стан лишається — картка чужого сервісу не є умовою для власних даних.
    assert env.data["ours"]["rows"] == 7779


def test_an_archive_we_do_not_know_keeps_the_name_the_index_gave_it():
    """🔴 «?» замість «ДАЖО» ховає рівно те, заради чого йдуть у покажчик.

    Наш код лишається порожнім навмисно — підставлений туди чужий завів би
    архів, якого в паку немає. Але назва, яку джерело назвало, мусить долітати
    до екрана: без неї знахідка не адресується й фонд не оцінити.
    """
    from nyshporka.ops_builtin import _by_fond

    (row,) = _by_fond([{"repo": "", "archive": "ДАЖО", "fond": "118",
                        "source": "duck", "years": "1850-1871"}])
    assert row["repo"] == ""
    assert row["label"] == "ДАЖО"


def test_two_unknown_archives_with_the_same_fond_number_stay_apart():
    """Номери фондів між архівами колізують — злиття приписало б чужу вагу."""
    from nyshporka.ops_builtin import _by_fond

    rows = _by_fond([
        {"repo": "", "archive": "ДАЖО", "fond": "118", "source": "duck"},
        {"repo": "", "archive": "ДАРО", "fond": "118", "source": "duck"},
    ])
    assert sorted(r["label"] for r in rows) == ["ДАЖО", "ДАРО"]
