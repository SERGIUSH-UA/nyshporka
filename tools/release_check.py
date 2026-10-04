#!/usr/bin/env python
"""Чи нічого не забуто перед релізом — версія, журнал, нотатка, міграція агента.

    python tools/release_check.py 0.24.0             # перевірити HEAD
    python tools/release_check.py v0.24.0 --ref v0.24.0

Читає файли з КОМІТУ (`--ref`), а не з робочого дерева: у хуку `pre-push` і в
CI перевіряється саме те, що піде в тег. Лише stdlib і git — без середовища
пакета, щоб хук працював на будь-якій машині.

Помилка (код 1) — реліз вийде зламаним або без знання для агента:

* `__version__` не та, що в тегу;
* у CHANGELOG немає розділу `## [<версія>]`, або в `[Unreleased]` лишились
  записи (їх забули перенести);
* у `docs/whats-new.md` немає розділу версії;
* міграція агента новіша за реліз — вона не спрацює, бо `pending` показує
  лише міграції не новіші за пакет (так файл `0.24.md` мовчав би в 0.23.3);
* після попереднього тега дописано в міграцію ВЖЕ ВИПУЩЕНОЇ версії — простір,
  що її пройшов, нової тези не побачить ніколи (04.10.2026: теза про `.part`
  дописана в `0.23.md` після тега v0.23.2).

Попередження — показати людині, рішення за нею:

* змінено скіли, а міграції цієї версії немає (агент не дізнається про зміну);
* правлено розділи журналу вже випущених версій;
* перелік комітів від попереднього тега — пробігти очима.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_notes import section  # один розбір нотатки на всі ворота

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = "src/nyshporka/__init__.py"
CHANGELOG = "CHANGELOG.md"
WHATS_NEW = "docs/whats-new.md"
MIGRATIONS = "src/nyshporka/migrate/data"
SKILLS = ".claude/skills"


def version_key(v: str) -> tuple[int, ...]:
    """`0.24` і `0.24.0` — одна версія (як `nyshporka.migrate.version_key`)."""
    parts = [int(m) for m in re.findall(r"\d+", v.removeprefix("v").split("+")[0])[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


# ── git ──────────────────────────────────────────────────────────────────────
def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def read(ref: str, path: str) -> str:
    try:
        return _git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""


def ls(ref: str, path: str) -> list[str]:
    try:
        return [p for p in _git("ls-tree", "--name-only", f"{ref}:{path}").splitlines() if p]
    except subprocess.CalledProcessError:
        return []


def previous_tag(version: str) -> str:
    """Найновіший тег `v*`, старший за жоден і молодший за реліз."""
    want = version_key(version)
    tags = [t for t in _git("tag", "-l", "v*").split() if version_key(t) < want]
    return max(tags, key=version_key) if tags else ""


# ── розбір тексту ────────────────────────────────────────────────────────────
def declared_version(init_text: str) -> str:
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.M)
    return m.group(1) if m else ""


def changelog_sections(text: str) -> dict[str, str]:
    """`## [0.23.2] — дата` → {"0.23.2": тіло}; `[Unreleased]` — під ключем `Unreleased`."""
    out: dict[str, str] = {}
    name, body = "", []
    for line in text.splitlines():
        m = re.match(r"^## \[([^\]]+)\]", line)
        if m:
            if name:
                out[name] = "\n".join(body).strip()
            name, body = m.group(1), []
        elif name:
            body.append(line)
    if name:
        out[name] = "\n".join(body).strip()
    return out


def migration_version(text: str) -> str:
    m = re.search(r'^version:\s*["\']?([\d.]+)', text, re.M)
    return m.group(1) if m else ""


# ── перевірка ────────────────────────────────────────────────────────────────
@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def check(version: str, ref: str = "HEAD", prev: str | None = None) -> Report:
    version = version.removeprefix("v")
    want = version_key(version)
    rep = Report()
    prev = previous_tag(version) if prev is None else prev

    got = declared_version(read(ref, VERSION_FILE))
    if got != version:
        rep.errors.append(f"`__version__` у {VERSION_FILE} — «{got}», а реліз — {version}")

    sections = changelog_sections(read(ref, CHANGELOG))
    if not sections.get(version):
        rep.errors.append(f"у {CHANGELOG} немає розділу «## [{version}] — <дата>» "
                          f"або він порожній")
    if re.search(r"^\s*[-*] ", sections.get("Unreleased", ""), re.M):
        rep.errors.append(f"у {CHANGELOG} під [Unreleased] лишились записи — "
                          f"перенести в розділ {version}")

    if not section(version, read(ref, WHATS_NEW)):
        rep.errors.append(f"у {WHATS_NEW} немає розділу «## {version} — <дата>»: "
                          f"що змінилось простою мовою")

    migrations = {name: migration_version(read(ref, f"{MIGRATIONS}/{name}"))
                  for name in ls(ref, MIGRATIONS) if name.endswith(".md")}
    for name, mv in sorted(migrations.items()):
        if mv and version_key(mv) > want:
            rep.errors.append(
                f"міграція {name} (версія {mv}) новіша за реліз {version} — агенти її "
                f"не побачать. Перейменувати на версію релізу або відкласти")
    this_release = [n for n, mv in migrations.items()
                    if mv and (not prev or version_key(mv) > version_key(prev))
                    and version_key(mv) <= want]

    if prev:
        changed = [p for p in _git("diff", "--name-only", f"{prev}..{ref}").splitlines() if p]
        for path in changed:
            if path.startswith(MIGRATIONS + "/") and path.endswith(".md"):
                mv = migration_version(read(ref, path))
                if mv and version_key(mv) <= version_key(prev):
                    rep.errors.append(
                        f"{path} змінено після {prev}, а версія {mv} вже випущена: простір, "
                        f"що її пройшов, нових тез не побачить. Перенести в міграцію "
                        f"{version} (`git checkout {prev} -- {path}`)")
        skills = sorted({p.split("/")[2] for p in changed
                         if p.startswith(SKILLS + "/") and p.count("/") >= 3})
        if skills and not this_release:
            rep.warnings.append(
                f"змінено скіли ({', '.join(skills)}), а міграції агента для {version} "
                f"немає. Якщо змінилась поведінка — теза в {MIGRATIONS}/<версія>.md")
        old = changelog_sections(read(prev, CHANGELOG))
        edited = [v for v, body in old.items()
                  if v != "Unreleased" and v in sections and sections[v] != body]
        if edited:
            rep.warnings.append(f"правлено розділи вже випущених версій у {CHANGELOG}: "
                                f"{', '.join(edited)} — нове має йти в {version}")
        log = _git("log", "--no-merges", "--format=%h %s", f"{prev}..{ref}").splitlines()
        rep.info.append(f"комітів від {prev}: {len(log)}")
        rep.info.extend(f"  {line}" for line in log)
    else:
        rep.warnings.append("попереднього тега немає — перевірки «що змінилось» пропущено")
    if this_release:
        rep.info.append(f"міграція агента цієї версії: {', '.join(sorted(this_release))}")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help="версія або тег: 0.24.0 чи v0.24.0")
    ap.add_argument("--ref", default="HEAD", help="коміт, який стане релізом")
    ap.add_argument("--quiet", action="store_true", help="без переліку комітів")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    rep = check(args.version, args.ref)
    if not args.quiet:
        for line in rep.info:
            print(line)
    for w in rep.warnings:
        print(f"⚠ {w}")
    for e in rep.errors:
        print(f"🔴 {e}", file=sys.stderr)
    if rep.errors:
        print(f"\nреліз {args.version} не готовий: {len(rep.errors)} помилок", file=sys.stderr)
        return 1
    print(f"✅ реліз {args.version}: нічого не забуто"
          + (f" ({len(rep.warnings)} попереджень — переглянути)" if rep.warnings else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
