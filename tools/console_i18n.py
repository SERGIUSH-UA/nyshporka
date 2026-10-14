"""Переклад консолі (`nysh serve`): вивантажити недостачу, прийняти переклад.

Словники лежать у `src/nyshporka/daemon/static/core/strings/<мова>.js`, по
одному файлу на мову; ключі — ті самі, що в `uk.js`.

    python tools/console_i18n.py export pl todo.json [--portal ../nyshporka-online]
    python tools/console_i18n.py import pl done.json
    python tools/console_i18n.py check

`export` кладе в JSON лише ключі, яких мові бракує: `{ключ: {"uk": …, "en": …}}`.
З `--portal` спершу бере готові переклади порталу — у його каталогах `.po`
ключ (msgid) і є українським текстом, тож напис, однаковий у консолі й на
порталі, перекладається однаково й не перекладається вдруге.

`import` приймає `{ключ: переклад}` і переписує файл мови в порядку ключів
`uk.js`. Ключ, якого немає в `uk.js`, відкидається з попередженням.

Словники читає node (той самий, що перевіряє фронт у тестах): значення в них —
рядки JS зі склейками `+`, і розбирати їх регексом означало б другий парсер.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DICTS = ROOT / "src" / "nyshporka" / "daemon" / "static" / "core" / "strings"

# Ім'я в шапці файла мови.
NAMES = {"uk": "українська", "en": "English", "pl": "polski", "ro": "română",
         "fr": "français", "de": "Deutsch", "ru": "русский"}

PLACEHOLDER = re.compile(r"\{\w+\}")
# Лише справжні теги: «<that number>» у тексті — це не розмітка.
TAG = re.compile(r"</?(a|b|i|em|strong|code|kbd|br|p|span|small)\b")


def load(lang: str) -> dict[str, str]:
    """Словник мови як dict. Файла немає — порожній словник."""
    path = DICTS / f"{lang}.js"
    if not path.exists():
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        twin = Path(tmp) / "d.mjs"
        twin.write_bytes(path.read_bytes())
        res = subprocess.run(
            ["node", "--input-type=module", "-e",
             f"import d from {json.dumps(twin.as_uri())};"
             "process.stdout.write(JSON.stringify(d));"],
            capture_output=True)
    if res.returncode != 0:
        raise SystemExit(f"{path.name} не розбирається:\n"
                         f"{res.stderr.decode('utf-8', 'replace')[:800]}")
    return json.loads(res.stdout.decode("utf-8"))


def portal(root: Path, lang: str) -> dict[str, str]:
    """Переклади порталу: український текст → текст мовою `lang`."""
    from babel.messages.pofile import read_po

    po = root / "app" / "locale" / lang / "LC_MESSAGES" / "messages.po"
    if not po.exists():
        return {}
    with po.open("rb") as fh:
        cat = read_po(fh)
    out: dict[str, str] = {}
    for m in cat:
        # Множину й контекст не беремо: у консолі таких записів немає, а збіг
        # однини з пасмом множини дав би хибну форму.
        if not m.id or m.context or isinstance(m.id, tuple) or m.fuzzy:
            continue
        if isinstance(m.string, str) and m.string:
            out[m.id] = m.string
    return out


def faults(src: str, dst: str) -> list[str]:
    """Чим переклад розходиться з оригіналом за формою (не за змістом)."""
    bad = []
    if sorted(PLACEHOLDER.findall(src)) != sorted(PLACEHOLDER.findall(dst)):
        bad.append(f"підстановки {sorted(PLACEHOLDER.findall(src))} → "
                   f"{sorted(PLACEHOLDER.findall(dst))}")
    if sorted(TAG.findall(src)) != sorted(TAG.findall(dst)):
        bad.append("теги HTML не збігаються")
    return bad


def js_str(s: str) -> str:
    return "'" + (s.replace("\\", "\\\\").replace("'", "\\'")
                  .replace("\n", "\\n").replace("\r", "")) + "'"


def write(lang: str, d: dict[str, str]) -> None:
    order = list(load("uk"))
    lines = [f"/** Словник: {NAMES.get(lang, lang)}. Порядок ключів — як в `uk.js`;",
             " *  файл пише `tools/console_i18n.py import`. */",
             "export default {"]
    lines += [f"    {js_str(k)}: {js_str(d[k])}," for k in order if k in d]
    lines.append("};")
    (DICTS / f"{lang}.js").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_export(a: argparse.Namespace) -> None:
    uk, en, have = load("uk"), load("en"), load(a.lang)
    found = portal(Path(a.portal), a.lang) if a.portal else {}
    reused = {k: found[v] for k, v in uk.items()
              if k not in have and v in found and not faults(v, found[v])}
    if reused:
        write(a.lang, {**have, **reused})
        have = {**have, **reused}
    todo = {k: {"uk": v, "en": en.get(k, "")} for k, v in uk.items() if k not in have}
    Path(a.out).write_text(json.dumps(todo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.lang}: з порталу {len(reused)}, до перекладу {len(todo)} → {a.out}")


def cmd_import(a: argparse.Namespace) -> None:
    uk, have = load("uk"), load(a.lang)
    got = json.loads(Path(a.src).read_text(encoding="utf-8"))
    stray = sorted(set(got) - set(uk))
    bad = {k: faults(uk[k], v) for k, v in got.items() if k in uk and faults(uk[k], v)}
    for k, why in bad.items():
        print(f"⚠ {k}: {'; '.join(why)}", file=sys.stderr)
    if stray:
        print(f"⚠ немає в uk.js, відкинуто: {stray}", file=sys.stderr)
    write(a.lang, {**have, **{k: v for k, v in got.items() if k in uk}})
    left = len(set(uk) - set(have) - set(got))
    print(f"{a.lang}: прийнято {len(got) - len(stray)}, бракує ще {left}")
    if bad:
        raise SystemExit(1)


def cmd_check(_a: argparse.Namespace) -> None:
    uk = load("uk")
    rc = 0
    for lang in NAMES:
        if lang == "uk":
            continue
        d = load(lang)
        miss, extra = set(uk) - set(d), set(d) - set(uk)
        bad = [k for k in d if k in uk and faults(uk[k], d[k])]
        print(f"{lang}: {len(d)}/{len(uk)}, бракує {len(miss)}, зайвих {len(extra)}, "
              f"з вадою форми {len(bad)}")
        rc |= bool(miss or extra or bad)
    raise SystemExit(rc)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("lang")
    e.add_argument("out")
    e.add_argument("--portal", help="корінь репо nyshporka-online")
    e.set_defaults(fn=cmd_export)
    i = sub.add_parser("import")
    i.add_argument("lang")
    i.add_argument("src")
    i.set_defaults(fn=cmd_import)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
