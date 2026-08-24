"""🎨 Дві теми спільного шару: кожен колір у токені, кожен токен — з парою.

Три речі, кожна з яких ламається ТИХО і ЛИШЕ в одній темі — тобто в тій, у якій
цієї миті не працюють:

1. **Хардкоджений колір поза `tokens.css`.** Він не перемикається взагалі:
   панель довкола посвітлішає, а елемент лишиться темною плямою. У базовій темі
   дефект невидимий, бо там хардкод збігається з нею.
2. **Токен без пари.** Новий `--foo` у `:root` без запису в
   `:root[data-theme="light"]` успадкує ТЕМНЕ значення у світлій — той самий
   ефект, але замаскований під «усе на токенах, значить усе гаразд».
3. **`--accent-fill` у ролі чорнила.** Заливка лишається світло-помаранчевою в
   обох темах (це фірмовий колір активної вкладки), тож як `color:` вона дає
   1.6:1 і текст стає нечитабельним саме на світлому тлі.

🔴 Виняток із пункту 2 оголошується ДАНИМИ — полем `same: true` в `brand.yaml`,
а не списком усередині приймача. Список тут означав би, що «забув пару» і «так
задумано» розрізняє тест, а не автор кольору; а пояснення, чому саме цей токен
не перевертається, лишалось би там, куди не дивляться.

Приймач читає ДЖЕРЕЛА, а не рендер: рендер довелося б відкривати браузером, а
браузера в CI немає.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nyshporka import ui
from nyshporka.brand import active

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ui.static_dir() / "tokens.css"
BASE_CSS = ui.static_dir() / "base.css"
APP_CSS = ROOT / "src" / "nyshporka" / "daemon" / "static" / "app.css"
INDEX = ROOT / "src" / "nyshporka" / "daemon" / "static" / "index.html"
JS = [*sorted(ui.static_dir().glob("*.js")),
      ROOT / "src" / "nyshporka" / "daemon" / "static" / "app.js"]

HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
COLOUR_VALUE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def _code_only(text: str) -> list[tuple[int, str]]:
    """(номер рядка, код без коментарів).

    У коментарях hex — це ІСТОРІЯ правила; заборонити її означало б заборонити
    пояснювати, чому правило саме таке.
    """
    out, in_block = [], False
    for i, ln in enumerate(text.split("\n"), 1):
        s, res = ln, ""
        while s:
            if in_block:
                end = s.find("*/")
                if end < 0:
                    s = ""
                else:
                    s, in_block = s[end + 2:], False
                continue
            start = s.find("/*")
            line_c = s.find("//")
            # `//` всередині рядка-літерала (напр. "https://…") — не коментар
            if line_c >= 0 and (start < 0 or line_c < start) \
                    and ":" not in s[max(0, line_c - 1):line_c + 1]:
                res += s[:line_c]
                s = ""
            elif start >= 0:
                res += s[:start]
                s, in_block = s[start + 2:], True
            else:
                res += s
                s = ""
        out.append((i, res))
    return out


def _hex_hits(path: Path) -> list[str]:
    out = []
    raw = path.read_text(encoding="utf-8").split("\n")
    for i, code in _code_only("\n".join(raw)):
        # `href="#i-search"` — посилання на символ спрайта, не колір
        if HEX.search(re.sub(r"#i-[\w-]+", "", code)):
            out.append(f"{path.name}:{i}: {raw[i - 1].strip()[:120]}")
    return out


@pytest.mark.parametrize("path", [BASE_CSS, APP_CSS], ids=["base.css", "app.css"])
def test_css_has_no_hardcoded_colour(path: Path) -> None:
    """Фарбувати можна ТІЛЬКИ токенами — так вимагає шапка обох файлів."""
    hits = [h for h in _hex_hits(path)
            # ⚠ `stroke='black'` у масці хрестика `type=search` — не колір, а
            # ключове слово: маска бере саму лише альфу фігури, а колір дає
            # `currentColor` у правилі поряд.
            if "stroke='black'" not in h]
    assert not hits, "hex поза токенами:\n" + "\n".join(hits)


def test_index_has_no_hardcoded_colour() -> None:
    """Інлайн `style=` б'є будь-яке правило теми, тож hex тут найдорожчий."""
    hits = [h for h in _hex_hits(INDEX)
            # `theme-color` оновлює `theme.js` із токена `--s-0`; у файлі
            # лишається стартове значення на перший кадр
            if 'name="theme-color"' not in h]
    assert not hits, "hex поза токенами:\n" + "\n".join(hits)


def test_js_has_no_hardcoded_colour() -> None:
    """`var(--token)` резолвиться і в інлайн-стилях, які збирає JS."""
    hits: list[str] = []
    for p in JS:
        # `theme.js` має один фолбек на випадок, коли `getComputedStyle` ще порожній
        hits += [h for h in _hex_hits(p) if not h.startswith("theme.js")]
    assert not hits, "hex поза токенами:\n" + "\n".join(hits)


# ── структура самих токенів ───────────────────────────────────────────────────

def _block(theme: str) -> dict[str, str]:
    """Декларації одного блока теми.

    ⚠ Селектор шукається на ПОЧАТКУ рядка. Шапка файлу згадує
    `:root[data-theme="light"]` прозою в коментарі, і проста підрядкова знахідка
    чіплялась саме за неї — зріз базової теми виходив порожнім, а світлої
    вміщав увесь файл разом із темними значеннями.
    """
    css = TOKENS.read_text(encoding="utf-8")
    base = re.search(r"^:root \{", css, re.M)
    other = re.search(r'^:root\[data-theme="\w+"\]', css, re.M)
    assert base and other, "у tokens.css немає одного з блоків тем"
    chunk = css[base.start():other.start()] if theme == "base" else \
        css[other.start():css.index("@media (prefers-reduced-motion")]
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", chunk))


def test_every_colour_token_has_a_pair() -> None:
    """Пропущена пара = елемент лишається темним, і це видно лише у світлій темі.

    🔴 Дозволені винятки беруться з `brand.yaml` (`same: true`), а не з переліку
    тут: інакше приймач ставав би другим джерелом правди про палітру.
    """
    b = active()
    same = {f"--{c.css}" for c in b.palette if c.same}
    # Аліас пари не потребує за побудовою: він посилається на токен (`var(--s-3)`),
    # тож перевертається разом із ним.
    same |= {f"--{a.css}" for a in b.aliases}
    base, other = _block("base"), _block("other")
    missing = sorted(k for k, v in base.items()
                     if COLOUR_VALUE.search(v) and k not in other and k not in same)
    assert not missing, (
        "кольорові токени без пари в другій темі: " + ", ".join(missing)
        + "\n(навмисний виняток оголошується `same: true` у brand.yaml)")


def test_declared_same_tokens_really_are_absent() -> None:
    """Зворотний бік: `same: true` мусить означати, що пари СПРАВДІ немає.

    Інакше запис у даних розходиться з тим, що генератор вивів, — і виняток
    починає прикривати звичайний токен, який хтось потім змінить лише в одній
    темі.
    """
    same = {f"--{c.css}" for c in active().palette if c.same}
    other = _block("other")
    leaked = sorted(same & set(other))
    assert not leaked, f"оголошені `same`, але виведені в обидві теми: {leaked}"


def test_both_themes_declare_color_scheme() -> None:
    """Без `color-scheme` рідні попапи `<select>` лишаються темними на світлому."""
    css = TOKENS.read_text(encoding="utf-8")
    assert "color-scheme: dark" in css and "color-scheme: light" in css


def test_accent_fill_is_never_used_as_ink() -> None:
    """`--accent-fill` світлий в ОБОХ темах; як `color:` він нечитабельний."""
    bad = []
    for p in [BASE_CSS, APP_CSS, INDEX, *JS]:
        for i, ln in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            if re.search(r"(?<!-)\bcolor:\s*var\(--accent-fill\)", ln):
                bad.append(f"{p.name}:{i}")
    assert not bad, "--accent-fill у ролі чорнила: " + ", ".join(bad)


def test_base_css_declares_no_tokens() -> None:
    """Примітиви СПОЖИВАЮТЬ токени, а не заводять свої.

    ⚠ Виняток один і він не колір: маска хрестика `type=search` (`--ctl-x`).
    Вона тримає форму, а не палітру, — усередині неї `stroke='black'` це
    ключове слово, бо маска бере саму лише альфу.
    """
    css = BASE_CSS.read_text(encoding="utf-8")
    declared = {m for m in re.findall(r"^\s*(--[\w-]+)\s*:", css, re.M)}
    assert declared <= {"--ctl-x"}, f"base.css заводить свої токени: {sorted(declared)}"
