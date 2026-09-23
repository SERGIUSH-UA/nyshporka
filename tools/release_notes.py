#!/usr/bin/env python
"""Розділ «Що нового» для версії — текст сторінки релізу для людини.

    python tools/release_notes.py 0.16.0          # надрукувати розділ версії
    python tools/release_notes.py 0.16.0 --body   # розділ разом із преамбулою релізу

🔴 Навіщо окремий крок, якщо є CHANGELOG. Журнал змін пише розробник для
розробника: заміри, причини, ламкі поля конверта. Генеалогіст, який відкрив
сторінку релізу, щоб завантажити файл, із нього не дізнається, що тепер можна
зробити. Тому поруч лежить `docs/whats-new.md`, а цей скрипт — єдине місце, яке
його читає: і тест, і ворота релізу, і текст GitHub Release.

🔴 Розділу немає — код виходу 1, а не порожній текст. Нотатку для людини
забувають саме тоді, коли реліз збирають поспіхом; порожня сторінка релізу
виглядала б як «нічого не змінилось», і ніхто б цього не помітив.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHATS_NEW = ROOT / "docs" / "whats-new.md"

#: Преамбула сторінки релізу. Жила в `release.yml`; тут вона поруч із розділом,
#: який іде за нею, і перевіряється тим самим тестом.
#: 🔏 Умови SignPath Foundation вимагають згадки програми саме на сторінці
#: завантаження — рядок у `<sub>` не прибирати.
PREAMBLE = """\
**Завантажити для Windows:** `nyshporka-setup.exe` — інсталятор,
без Python і без прав адміністратора. Поруч лежить `.sha256`, яким
завантажене можна звірити.

<sub>Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).
Заявку подано; доки її не схвалено, випуски не підписані й Windows
показує «Windows захистив ваш ПК» — це очікувано для програми, яку
ще мало хто завантажував.
[Політика підписування](https://nyshporka.online/docs/signing/)
· [Приватність](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md)</sub>
"""


def section(version: str, text: str) -> str:
    """Текст розділу `## <версія> …` без заголовка. Порожньо — розділу немає.

    ⚠ Заголовок звіряється як «`## 0.16.0` і далі пробіл або кінець рядка», а
    не підрядком: інакше `0.16.1` знаходив би розділ `0.16.10`.
    """
    head = f"## {version.strip().removeprefix('v')}"
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line == head or line.startswith(head + " ")
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def body(version: str, text: str) -> str:
    """Повний текст сторінки релізу: преамбула, розділ, посилання на сайт."""
    notes = section(version, text)
    if not notes:
        return ""
    return (f"{PREAMBLE}\n---\n\n## Що нового\n\n{notes}\n\n"
            f"Усі версії простою мовою — "
            f"[«Що нового»](https://nyshporka.online/docs/whats-new/); "
            f"технічні подробиці — "
            f"[журнал змін](https://github.com/SERGIUSH-UA/nyshporka/blob/main/CHANGELOG.md).\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("version", help="версія або тег: 0.16.0 чи v0.16.0")
    ap.add_argument("--body", action="store_true",
                    help="разом із преамбулою сторінки релізу")
    args = ap.parse_args()
    # 🔴 Обидва потоки — UTF-8, і до першого друку. Перемкнутий був лише stdout,
    # тож відмова з кирилицею йшла в stderr кодуванням консолі (cp1252 на
    # раннері Windows), і читач процесу діставав байти, які не розбираються.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    text = WHATS_NEW.read_text(encoding="utf-8")
    got = body(args.version, text) if args.body else section(args.version, text)
    if not got:
        ver = args.version.strip().removeprefix("v")
        print(f"🔴 у {WHATS_NEW.relative_to(ROOT)} немає розділу «## {ver} — <дата>»: "
              f"що тепер можна зробити з цією версією, простою мовою", file=sys.stderr)
        return 1
    print(got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
