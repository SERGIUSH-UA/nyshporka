"""📂 Вибір шляху: гортач тек і системне вікно.

🔴 Жоден тест тут не відкриває справжнього вікна. У CI екрана немає, а на машині
розробника такий тест зупинив би прогін до першого людського кліку — тобто
перевірка, яка вимагає людини, не є перевіркою. Тому шви зроблено так, щоб
кожен бік перевірявся окремо: батько ніколи не імпортує tkinter, дитина читає
запит зі stdin (тож її можна підмінити), а логіка самої дитини винесена у
функцію з підставними Tk і діалогами.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from nyshporka.picker import _dialog as D
from nyshporka.picker import browse as B
from nyshporka.picker import native


# ── гортач ───────────────────────────────────────────────────────────────────
def test_a_folder_we_cannot_read_is_listed_not_dropped(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Тека, у яку не пускають, лишається в переліку.

    Перша редакція гортача робила тут `continue`, і тека, на яку немає прав,
    просто зникала зі списку. У провіднику вона є, у застосунку її немає — і
    людина читає це як поламку застосунку, а не як межу прав. Причина невидима
    саме тому, що зникає сам предмет розмови.
    """
    (tmp_path / "видима").mkdir()
    (tmp_path / "замкнена").mkdir()

    real = os.scandir

    class Deny:
        def __init__(self, e: os.DirEntry[str]) -> None:
            self._e = e

        def __getattr__(self, k: str) -> object:
            return getattr(self._e, k)

        def is_dir(self, *a: object, **kw: object) -> bool:
            if self._e.name == "замкнена":
                raise PermissionError(13, "Permission denied")
            return self._e.is_dir()

    def fake(path: object) -> object:
        class It:
            def __enter__(self) -> object:
                self._it = real(path)  # type: ignore[arg-type]
                return [Deny(e) for e in self._it]

            def __exit__(self, *a: object) -> None:
                self._it.close()
        return It()

    monkeypatch.setattr(B.os, "scandir", fake)
    got = B.listing(tmp_path, count_children=False)
    names = {e.name: e for e in got.entries}
    assert "замкнена" in names, "тека без прав зникла зі списку"
    assert names["замкнена"].locked is True
    assert names["замкнена"].why, "замкнену теку показано без причини"


def test_a_huge_folder_says_how_much_it_hid(tmp_path: Path) -> None:
    """Обрізаний список, який виглядає повним, — це нуль без знаменника.

    Людина бачить 200 рядків із 3417 і вважає, що переглянула теку.
    """
    for i in range(250):
        (tmp_path / f"{i:04d}.jpg").write_bytes(b"x")
    got = B.listing(tmp_path, limit=50, count_children=False)
    assert got.shown == 50
    assert got.total == 250, "знаменник загубився"
    assert got.truncated is True


def test_case_folders_sort_the_way_the_archive_numbers_them(tmp_path: Path) -> None:
    """`spr_10` після `spr_2`, а не перед ним.

    Архівні теки нумеровані, і лексикографічний порядок ставить їх у пам'ять
    людини задом наперед. Перша редакція гортача сортувала саме лексикографічно.
    """
    for n in ("spr_10", "spr_2", "spr_1", "spr_12a", "spr_100"):
        (tmp_path / n).mkdir()
    got = B.listing(tmp_path, count_children=False)
    assert [e.name for e in got.entries] == [
        "spr_1", "spr_2", "spr_10", "spr_12a", "spr_100"]


def test_a_case_that_keeps_frames_one_level_down_is_not_shown_as_empty(
        tmp_path: Path) -> None:
    """🔴 Справа з кадрами в підтеці не сміє виглядати порожньою.

    Так лежить половина завантажених справ: `op3-spr-3/pages/00001.jpg`. Сам
    лише лічильник кадрів показав би там «0», і людина пройшла б повз повну
    справу, вирішивши, що тека порожня. Тому коли кадрів немає, рядок каже про
    теки — це дешево (той самий обхід) і не бреше.
    """
    case = tmp_path / "op3-spr-3"
    (case / "pages").mkdir(parents=True)
    for i in range(3):
        (case / "pages" / f"{i:05d}.jpg").write_bytes(b"x")
    got = B.listing(tmp_path)
    row = got.entries[0]
    assert row.frames == 0, "кадри лежать глибше — тут їх справді немає"
    assert row.subdirs == 1, "лічильник тек не заповнено, і рядок мовчить"


def test_drives_are_found_without_touching_dead_network_letters(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ Перебір 26 літер вішає відкриття гортача на мертвому мережевому диску.

    Кожен `exists` на неіснуючій літері впирається в таймаут SMB — десятки
    секунд без жодного натяку, чому вікно не відкривається.
    """
    if os.name != "nt":
        pytest.skip("літери дисків бувають лише на Windows")
    monkeypatch.delattr(B.os, "listdrives", raising=False)
    monkeypatch.setattr(B.os.path, "exists",
                        lambda p: pytest.fail(f"гортач торкнувся літери {p}"))
    got = B.drives()
    assert got, "диски не знайдено жодним зі способів"


def test_the_listing_never_returns_file_contents() -> None:
    """🔴 Межа модуля, а не стиль: імена — так, вміст — ніколи.

    Наступний автор захоче показати «перші рядки, щоб було видно, що це за
    файл». Саме цей крок перетворює перелік імен на довільне читання будь-якого
    файлу машини по HTTP — і виглядає він як дрібна зручність.
    """
    src = Path(B.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    body = re.sub(r'""".*?"""', "", code, flags=re.S)
    for bad in ("read_bytes", "read_text", "open("):
        assert bad not in body, f"гортач читає вміст файлів: {bad}"


def test_the_browser_starts_where_the_work_is() -> None:
    """Гортач відкривається в робочих місцях, а не в корені диска."""
    kinds = {r.kind for r in B.roots()}
    assert "home" in kinds
    assert "workspace" in kinds or "case_root" in kinds or kinds


def test_a_path_that_no_longer_exists_climbs_to_a_living_parent(tmp_path: Path) -> None:
    """Зниклу теку показуємо з найближчого живого предка, а не з домівки.

    Інакше людина, у якої від'єднався диск, опиняється на іншому кінці дерева й
    мусить проходити весь шлях заново.
    """
    deep = tmp_path / "є" / "немає" / "теж немає"
    (tmp_path / "є").mkdir()
    got = B.listing(deep, count_children=False)
    assert got.path == str(tmp_path / "є")


# ── системне вікно ───────────────────────────────────────────────────────────
def test_the_child_is_addressed_as_a_module_not_a_file() -> None:
    """Шлях до файлу зламався б лише в користувача — у колесі його немає."""
    assert native.CHILD == ("-m", "nyshporka.picker._dialog")


def test_the_kill_switch_isolates_the_machine_from_the_test(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Без вимикача набір тестів перевіряв би машину, а не програму."""
    monkeypatch.setenv(native.KILL_SWITCH, "1")
    assert native.probe().can is False
    got = native.ask("dir", slot="перевірка")
    assert got.state == "unavailable"
    assert got.why, "відмова без причини — це нуль без знаменника"


def test_no_display_is_detected_without_starting_a_process(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Дешева перевірка мусить бути справді дешевою.

    Питання «чи є тут екран» ставиться перед кожним показом кнопки; запускати
    заради нього процес означало б платити за відповідь, яку видно зі змінних
    середовища.
    """
    monkeypatch.delenv(native.KILL_SWITCH, raising=False)
    monkeypatch.setattr(native.sys, "platform", "linux")
    # 🔴 Перевірка на tkinter стоїть у `probe()` ПЕРЕД питанням про екран, і на
    # частині раннерів CI (ubuntu, py3.11 та py3.13) tkinter у складанні Python
    # немає. Без підміни цей тест міряв би збірку інтерпретатора раннера, а не
    # нашу гілку — і падав би рівно там, де перевіряти нічого.
    import importlib.util
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec",
        lambda name, *a, **kw: (real_find_spec("json") if name == "tkinter"
                                else real_find_spec(name, *a, **kw)))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(native.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("запущено процес заради дешевої перевірки"))
    able = native.probe()
    assert able.can is False
    assert "DISPLAY" in able.why


def test_garbage_on_stdout_does_not_eat_the_answer() -> None:
    """⚠ Tk і Gtk на Linux пишуть попередження просто в потік.

    Батько, який бере «останній рядок», дістав би саме їх — і мовчазно вирішив,
    що вікно не відповіло.

    🔴 Серед сміття тут навмисно є валідний JSON-об'єкт. Без мітки розбір
    «останнього рядка, схожого на відповідь» узяв би саме його — і повернув би
    відповідь, якої дитина не давала. Саме тому мітка, а не здогад про формат.
    """
    text = ("Gtk-Message: Failed to load module\n"
            + native.SENTINEL + json.dumps({"state": "picked", "paths": ["E:/архів"]})
            + "\n" + json.dumps({"state": "cancelled", "paths": []})
            + "\nlibEGL warning: DRI2\n")
    got = native._parse(text)
    assert got == {"state": "picked", "paths": ["E:/архів"]}, (
        "розбір узяв чужий рядок замість відповіді дитини")


def test_a_dialog_nobody_closes_is_killed_and_named(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Забуте вікно тримає екран, а людина бачить, що «нічого не працює».

    Найчастіша причина — вікно відкрилось позаду браузера. Тому мовчазного
    очікування без кінця не буває: процес гине, а відповідь називає причину.
    """
    monkeypatch.delenv(native.KILL_SWITCH, raising=False)
    monkeypatch.setattr(native, "probe", lambda **kw: native.Ability(can=True))
    code = "import time; time.sleep(30)"
    monkeypatch.setattr(native, "CHILD", ("-c", code))
    got = native.ask("dir", slot="сон", timeout_s=1.0)
    assert got.state == "timeout"
    assert "позаду" in got.why, "таймаут не назвав найчастішої причини"
    assert not native.live(), "процес лишився в обліку після вбивства"


def test_a_child_that_dies_says_why_instead_of_returning_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Гола відмова мовою системи не є інструкцією — але й мовчання не є."""
    monkeypatch.delenv(native.KILL_SWITCH, raising=False)
    monkeypatch.setattr(native, "probe", lambda **kw: native.Ability(can=True))
    code = ("import sys; sys.stderr.write('ImportError: libtk8.6.so: "
            "cannot open shared object file\\n'); sys.exit(1)")
    monkeypatch.setattr(native, "CHILD", ("-c", code))
    got = native.ask("dir", slot="мертва")
    assert got.state == "error"
    assert "libtk" in got.why


def test_the_title_and_the_path_survive_the_trip_in_cyrillic(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ На Windows дефолтне кодування каліче українські заголовки.

    Урок уже сплачений на прогонах рушія: без явного utf-8 у дитини шлях
    повертався зіпсованим, і шукали це в геть іншому місці.
    """
    monkeypatch.delenv(native.KILL_SWITCH, raising=False)
    monkeypatch.setattr(native, "probe", lambda **kw: native.Ability(can=True))
    code = (
        "import sys, json;"
        "req = json.loads(sys.stdin.read());"
        "sys.stdout.write('@@PICK@@ ' + json.dumps("
        "{'state': 'picked', 'paths': [req['title']]}, ensure_ascii=False))")
    monkeypatch.setattr(native, "CHILD", ("-c", code))
    got = native.ask("dir", title="Оберіть теку ф.230 оп.1 — М'ястківка", slot="мова")
    assert got.path == "Оберіть теку ф.230 оп.1 — М'ястківка"


def test_a_new_ask_in_a_busy_slot_kills_the_old_window(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Двоє вікон одного поля змагаються за «поверх усіх» — і ховають одне одного.

    Це гірше, ніж не відкрити жодного: людина бачить те, що відкрилось першим,
    а відповідає їй те, що відкрилось другим.
    """
    monkeypatch.delenv(native.KILL_SWITCH, raising=False)
    monkeypatch.setattr(native, "probe", lambda **kw: native.Ability(can=True))
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    native._LIVE["зайнятий"] = proc  # type: ignore[assignment]
    monkeypatch.setattr(native, "CHILD",
                        ("-c", "import sys; sys.stdout.write('@@PICK@@ "
                               "{\"state\": \"cancelled\", \"paths\": []}')"))
    native.ask("dir", slot="зайнятий")
    assert proc.poll() is not None, "попереднє вікно лишилось висіти"


# ── дитина ───────────────────────────────────────────────────────────────────
class _FakeRoot:
    def __init__(self) -> None:
        self.dead = False

    def destroy(self) -> None:
        self.dead = True


class _FakeDialogs:
    def __init__(self, answer: object = "") -> None:
        self.answer = answer
        self.kw: dict[str, object] = {}

    def askdirectory(self, **kw: object) -> object:
        self.kw = kw
        return self.answer

    def askopenfilename(self, **kw: object) -> object:
        self.kw = kw
        return self.answer


def test_the_dialog_is_owned_by_a_window_or_it_hides_behind_the_browser() -> None:
    """🔴 Без власника діалог не успадковує «поверх усіх».

    Тобто саме та вада, заради якої стоїть `-topmost`, лишалась би невилікуваною:
    вікно так само ховалось би за браузером, і лікування виглядало б як зроблене.
    """
    dlg = _FakeDialogs("E:/архів/спр 12")
    got = D.answer({"mode": "dir", "start": "E:/"}, lambda: _FakeRoot(), dlg)
    assert got["state"] == "picked"
    assert "parent" in dlg.kw, "діалог відкрито без вікна-власника"


def test_an_empty_choice_is_a_cancel_not_a_silence() -> None:
    """Порожня відповідь означає чотири різні речі — і лікуються вони інакше."""
    dlg = _FakeDialogs("")
    got = D.answer({"mode": "file"}, lambda: _FakeRoot(), dlg)
    assert got["state"] == "cancelled"


def test_the_probe_window_is_never_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Перевірки спроможності не має бути видно.

    Вона ставиться фоном, при кожному показі кнопки. `focus_force` відбирає
    фокус у того, хто зараз працює, і на Windows встигає блимнути в панелі
    задач — тобто застосунок виглядає так, ніби сам відкриває вікна. Один такий
    показ уже спитали.
    """
    raised: list[bool] = []

    def fake_root(*, raise_it: bool = True) -> _FakeRoot:
        raised.append(raise_it)
        return _FakeRoot()

    monkeypatch.setattr(D, "_tk_root", fake_root)
    got = D.answer({"mode": "probe"})
    assert got["state"] == "ready"
    assert raised == [False], "перевірка підняла вікно на екран"


def test_no_test_can_ever_open_a_real_dialog() -> None:
    """🔴🔴 Прогін тестів не сміє відкривати системне вікно.

    `test_triptych_parity` викликає кожну операцію реєстру напряму — і для
    `pick.ask` це означає справжній діалог посеред прогону: вікно, яке чекає на
    людину, поки решта тестів стоїть. Дослідник закривав їх одне за одним, доки
    не сказав про це вголос.

    Приймач стоїть тут, а не в `conftest`, бо ловить він саме зникнення того
    рядка: вимикач легко прибрати як «зайвий», і наслідок побачить не той, хто
    прибрав, а той, хто наступного разу запустить прогін.
    """
    assert os.environ.get(native.KILL_SWITCH), (
        "у тестовому середовищі немає вимикача системного вікна — "
        "перевірте autouse-фікстуру в conftest.py")
    assert native.probe().can is False
    from nyshporka import ops as O

    env = O.call("pick.ask", {"mode": "dir"})
    assert env.ok and env.data["state"] == "unavailable", (
        "виклик операції з реєстру відкриває вікно на екрані людини")


def test_the_cancel_button_can_actually_close_the_window() -> None:
    """🔴 Скасування роботи мусить гасити вікно, а не лише міняти стан у черзі.

    Загальний виконавець довгих робіт крутить тіло операції в потоці й гасителя
    не реєструє: перервати потік нічим, тож «Скасувати» там завжди було
    напівправдою. Для читання справи це прикро, для системного вікна —
    неприйнятно: закрити його зі сторінки неможливо в принципі, тобто без
    власного гасителя людині лишається шукати вікно руками або вбивати процес.

    ⚠ Приймач на форму коду, а не на поведінку: щоб перевірити гасіння живцем,
    треба справжнє вікно — тобто рівно те, чого в тестах не буває.
    """
    from nyshporka.daemon import workers

    src = Path(workers.__file__).read_text(encoding="utf-8")
    # Диспетчер — це тіло `start()` до першої наступної функції: саме там
    # вирішується, чи піде робота у власного виконавця, чи в загального.
    sep = "\nasync def "
    dispatch = src.split("async def start(", 1)[-1].split(sep, 1)[0]
    assert '"pick.ask"' in dispatch, (
        "диспетчер веде системне вікно в загального виконавця, а той гасителя "
        "не реєструє — кнопка «Скасувати» лишиться напівправдою")
    body = src.split("async def _start_pick(", 1)[-1].split(sep, 1)[0]
    assert "on_stop" in body, "виконавець не реєструє, чим закрити вікно"
    assert "native.close" in body, "гаситель не гасить саме вікно"
