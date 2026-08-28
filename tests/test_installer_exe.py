"""🪟 Майстер `.exe`: те, що ламається тихо й помічається вже в користувача.

Три скарги з першого дня публічного доступу були про установлення, і жодна —
про застосунок. Третя не мала вади взагалі: «користувач має скачати файл,
натиснути встановити і отримати застосунок». `install/nyshporka.iss` — відповідь
на неї, і саме тому він накритий приймачами: помилка тут не падає в CI, вона
доходить до людини у вигляді майстра, який щось не те зробив.

🔴 Головне правило файла: **`.iss` не дублює логіку встановлення.** Усе, що
справді ставить Нишпорку, живе у `windows.ps1` — оплачене трьома скаргами й
накрите приймачами в `test_sections.py`. Друга копія на Pascal розійшлася б із
першою на найближчому виправленні, і розійшлася б мовчки.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "install" / "nyshporka.iss"
PS1 = ROOT / "install" / "windows.ps1"


def iss_text() -> str:
    return ISS.read_text(encoding="utf-8")


def test_iss_offers_only_presets_that_exist() -> None:
    """🔴 Друкарська помилка в назві набору спрацьовує на ОСТАННЬОМУ кроці.

    Майстер передає вибір у `-Preset`, а розбирає його вже `nysh init` — після
    того, як завантажено інтерпретатор і пакети. «resercher» замість
    «researcher» дасть відмову через двадцять хвилин чекання, коли все вже на
    диску, і виглядатиме вона як зламане встановлення.

    ⚠ Чому `.iss` НЕ додано в `test_installer_extras_match_the_sections`: той
    приймач вимагає, щоб згадувався КОЖЕН набір, а майстер навмисно пропонує
    два з чотирьох — чотири радіокнопки з майже однаковими підписами це рівно
    те «розбирання», по яке прийшла скарга. `amateur` і `lab` лишаються
    доступні через `-Preset` у самому скрипті.
    """
    from nyshporka.core import sections as S

    known = set(S.preset_names())
    text = iss_text()
    # Два місця, де набір названий рядком: що майстер ПОВЕРТАЄ і що він
    # ПРИЙМАЄ у тихому режимі (`/PRESET=`). Друге не менш важливе: білий
    # список, який розійшовся з `core.sections`, або відкине правильне ім'я,
    # або пропустить неправильне далі — у `nysh init`, на останній крок.
    used = set(re.findall(r"Result\s*:=\s*'([a-z]+)'", text))
    used |= set(re.findall(r"Quiet\s*<>\s*'([a-z]+)'", text))
    assert used, "у майстрі не знайдено жодного набору — розбір зламався"
    assert used <= known, (
        f"майстер пропонує набір, якого немає в `core.sections`: {used - known}")


def test_iss_passes_only_flags_the_script_declares() -> None:
    """🔴 Перейменований параметр скрипта лишає майстер зі старим іменем.

    PowerShell тоді каже «A parameter cannot be found that matches parameter
    name 'Preset'» — у вікні, яке людина сприймає як технічний шум, після чого
    установлення падає з ненульовим кодом. Тут це ловиться текстом.
    """
    declared = set(re.findall(r"\[string\]\$(\w+)|\[switch\]\$(\w+)",
                              PS1.read_text(encoding="utf-8-sig")))
    names = {a or b for a, b in declared}
    assert names, "не вдалось розібрати param() у windows.ps1"

    # Прапорці, які майстер справді передає: беремо з рядка складання Params.
    passed = set(re.findall(r"' -(\w+)|\s-(\w+) '", iss_text()))
    used = {a or b for a, b in passed} & (names | {"NoProfile", "ExecutionPolicy", "File"})
    ours = used - {"NoProfile", "ExecutionPolicy", "File"}
    assert ours, "майстер не передає жодного параметра скрипта — розбір зламався"
    assert ours <= names, (
        f"майстер передає те, чого `windows.ps1` не оголошує: {ours - names}")


def test_the_installer_pins_the_version_it_is_named_after() -> None:
    """🔴 Файл, названий однією версією, ставив іншу.

    `nyshporka-0.6.0-setup.exe` показує 0.6.0 у «Програмах і засобах» — і доти
    ставив те, що лежало на PyPI того дня. Це рівно та вада, проти якої в
    релізному воркфлоу вже стоїть приймач «версія колеса == тег» із докстрінгом
    «реліз v0.2.0, всередині якого 0.1.0: pip поставить друге, а людина
    шукатиме перше й вирішить, що зламався pip». `.exe` відтворював її на
    поверхню вище, де людина навіть не має чим перевірити.

    Перевірено наскрізно: зібраний із `/DAppVersion=0.6.0` інсталятор ставить
    саме 0.6.0, хоча на PyPI вже 0.6.2.

    ⚠ Пін чіпляється лише до ОБЧИСЛЕНОГО складу. Хто задав `-Source` руками,
    уже сказав, що саме ставить; дописати туди `==` означало б зіпсувати чужу
    специфікацію.
    """
    assert "-Version {#AppVersion}" in iss_text(), (
        "майстер не передає свою версію — `.exe` знову ставитиме «останню»")
    ps1 = PS1.read_text(encoding="utf-8-sig")
    assert '$Source = "$Source==$Version"' in ps1, (
        "`windows.ps1` більше не застосовує пін")
    head = ps1[:ps1.index("$Source = \"$Source==$Version\"")]
    assert head.rstrip().endswith("else { 'nyshporka[app,archives,htr]' }") or         "if (-not $Source)" in head[-400:], (
        "пін виїхав за межі гілки обчисленого складу — він зіпсує явний -Source")


def test_iss_never_makes_a_second_desktop_shortcut() -> None:
    """🔴 Без `-NoLauncher` на столі опиняються ДВА ярлики.

    `windows.ps1` кладе свій `Нишпорка.lnk` сам; майстер кладе власний, бо
    інакше не зміг би прибрати його при деінсталяції. Обидва разом дають
    другий ярлик, який після видалення застосунку лишається вести в нікуди.
    """
    assert "-NoLauncher" in iss_text(), (
        "майстер не глушить ярлик, який кладе сам скрипт")


def test_iss_uninstall_never_touches_the_research() -> None:
    """🔴🔴 У робочому просторі лежить робота людини, а не дані застосунку.

    Скани, прочитане, транскрибовані описи — і середовище рушіїв на кілька
    гігабайтів, яке `setup/doctor.py` створює ПРЯМО В ПРОСТОРІ. Деінсталятор
    знімає рівно те, що поставив; усе інше лишається, навіть якщо виглядає як
    сміття.

    Окремо забороняється рекурсивне видалення `{app}`: тека встановлення
    сусідить із `user_data_dir`, і одна необережна `filesandordirs` змила б
    довідники з вагами.
    """
    text = iss_text()
    for trap in ("{userdocs}", "{localappdata}\\Nyshporka\"",
                 "filesandordirs; Name: \"{app}\""):
        assert trap not in text, (
            f"деінсталятор дотягується до чужого: «{trap}»")


def test_iss_is_utf8_without_bom() -> None:
    """⚠ Дзеркало `test_windows_installer_is_utf8_with_bom`, і навмисно НАВПАКИ.

    У `windows.ps1` BOM обов'язковий: без нього PowerShell 5.1 читає файл як
    ANSI. Тут — протилежне: Inno Setup з 6.3 читає `.iss` у UTF-8 без BOM, і
    саме без BOM файл лежить. Два сусідні файли з протилежною вимогою — рівно
    те місце, де наступний агент «вирівняє» їх і зламає один із двох, тож
    вимога записана приймачем, а не лише коментарем.
    """
    raw = ISS.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        "у `.iss` з'явився BOM — на Inno < 6.3 це кракозябри в усьому майстрі")
    raw.decode("utf-8")  # кине UnicodeDecodeError, якщо кодування зіпсували


def test_iss_names_the_minimum_inno_version() -> None:
    """⚠ Стара збірка Inno ламає МОВУ, а не збірку.

    До 6.3 `.iss` без BOM читається як ANSI, до 6.5 немає `Ukrainian.isl` —
    і те, і те помітно лише тому, хто завантажив готовий `.exe`. Тому версія
    вимагається директивою `#if VER`, яка падає на компіляції.
    """
    assert "EncodeVer(6,5,0)" in iss_text(), (
        "з `.iss` зникла вимога мінімальної версії Inno Setup")


def test_iss_compiles() -> None:
    """🔴 Головний приймач: `.iss` мусить збиратись.

    Лінтера для Inno Setup не існує, тож єдиний спосіб дізнатись, що файл
    працездатний, — покликати компілятор. Він ловить цілий клас вад, який
    текстові перевірки не бачать: невідома директива, поламана секція, помилка
    Pascal у `[Code]`, посилання на `{code:X}` неоголошеної функції.

    ⚠ Пак довідників при цьому не потрібен: `skipifsourcedoesntexist` у `.iss`
    навмисно дозволяє збірку без нього, інакше приймач не міг би працювати в
    того, хто не має `gh auth`.
    """
    if os.name != "nt":
        pytest.skip("Inno Setup — інструмент Windows")
    iscc = None
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                 str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")):
        if not base:
            continue
        candidate = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if candidate.exists():
            iscc = candidate
            break
    if iscc is None:
        iscc = shutil.which("ISCC")
    if iscc is None:
        pytest.skip("Inno Setup недоступний")

    out = Path(os.environ.get("TEMP", ".")) / "nysh-iss-check"
    out.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [str(iscc), "/DAppVersion=0.0.0", f"/O{out}", str(ISS)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"`.iss` не збирається:\n{r.stdout}\n{r.stderr}"
    finally:
        shutil.rmtree(out, ignore_errors=True)
