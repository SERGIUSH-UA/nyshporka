#!/usr/bin/env python3
"""🔒 Ворота проти приватних даних у публічному репозиторії.

Цей пакет виділяється з приватного дослідницького репо однієї родини. Небезпека
тут не в тому, що хтось свідомо закомітить канон живих осіб, а в тому, що це
станеться ВИПАДКОВО: один `git add -A` у розгоні, скопійований для прикладу
шматок коду з реальним ID особи, шлях `E:\\Projects\\MeGen\\...` у докстрінгу.

🔴 Головне: git не забуває. Файл, закомічений і видалений наступним комітом,
лишається в історії назавжди, і «прибрати» його означає переписати історію вже
опублікованого репозиторію. Тому перевірка мусить стояти ДО коміту, а не після.

    python tools/scan_private.py                # робоче дерево
    python tools/scan_private.py --staged       # те, що зараз у git add (pre-commit)
    python tools/scan_private.py --history      # УСЯ історія (перед першим push)

Вихід 0 — чисто, 1 — знайдено, 2 — помилка запуску.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Розширення, які взагалі має сенс читати як текст.
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
    ".html", ".css", ".js", ".ts", ".sh", ".ps1", ".jsonl", ".tsv", ".csv", "",
}
#: Каталоги, у які не заходимо ніколи.
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
             ".ruff_cache", ".pytest_cache", "dist", "build", ".idea", ".vscode"}
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Rule:
    id: str
    why: str
    pattern: re.Pattern[str]


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


RULES: tuple[Rule, ...] = (
    # ── ідентифікатори канону ────────────────────────────────────────────────
    # Особи/родини/місця приватного дослідження. Саме вони найлегше приїжджають
    # разом зі скопійованим прикладом чи тестовою фікстурою.
    Rule("canon-person", "ID особи з приватного канону (I0123)",
         re.compile(r"\bI0\d{3}\b")),
    Rule("canon-family", "ID родини з приватного канону (F0123)",
         re.compile(r"\bF0\d{3}\b")),
    Rule("canon-place", "ID місця з приватного канону (PL0123)",
         re.compile(r"\bPL0\d{3}\b")),
    Rule("canon-source", "ID джерела з приватного канону (S_DAHMO_F315_...)",
         re.compile(r"\bS_[A-Z]{2,}_F\d+")),

    # ── прізвище роду в усіх написаннях ──────────────────────────────────────
    # 🔴 Не одна форма, а корінь із варіантами: декод і транслітерація дають
    # десяток написань, і фільтр на єдине «Долищинський» пропустив би більшість.
    # ⚠ Перша редакція вимагала `c`/`s` після кореня (`doli[sș][cs]`) і через це
    # не бачила голого румунського `doliş` — тобто саме тієї форми, заради якої
    # варіанти й перелічуються.
    Rule("clan-surname", "прізвище роду з приватного дослідження",
         _rx(r"д[оаі]л[иіы]щ[иі]н|d[oa]li[sșş]")),

    # ── локальні шляхи ───────────────────────────────────────────────────────
    # Абсолютний шлях машини автора — не секрет, але він робить код непереносним
    # і видає структуру приватного архіву.
    Rule("abs-path-win", "абсолютний шлях Windows із машини автора",
         _rx(r"[A-Z]:[\\/](?:Projects|Users|Temp|megen_archive)[\\/]")),
    Rule("abs-path-nix", "абсолютний шлях із чужої машини/VPS",
         re.compile(r"(?:^|[\"'\s=])/(?:root|home)/[a-z0-9_.-]+/")),
    Rule("private-repo", "ім'я приватного репозиторію дослідження",
         _rx(r"\bmegen\b|megen_archive|SERGIUSH-UA/domus")),

    # ── секрети ──────────────────────────────────────────────────────────────
    Rule("aws-presigned", "presigned-URL з креденшелом (X-Amz-...)",
         _rx(r"X-Amz-(?:Credential|Signature|Security-Token)")),
    Rule("bearer", "захардкоджений токен/ключ",
         _rx(r"(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}")),
    Rule("private-host", "приватний хост/тунель автора",
         _rx(r"easykey-backup|itdeo\.tech")),
)

#: Свідомі винятки: файл (glob) → які правила там дозволені.
#: 🔴 Виняток завжди ТОЧКОВИЙ — правило × шлях. Глобальне «ігнорувати цей файл»
#: перетворює ворота на декорацію: наступна людина допише туди що завгодно.
ALLOW: tuple[tuple[str, str], ...] = (
    # Сам сканер містить усі патерни за визначенням.
    ("tools/scan_private.py", "*"),
    # README пояснює, звідки походить проєкт, і називає приватний репо.
    ("README.md", "private-repo"),
    # Тест воріт мусить містити зразки того, що вони ловлять.
    ("tests/test_scan_private.py", "*"),
    # 🔴 Атрибуція автора — НЕ приватні дані, хоч і збігається з прізвищем, яке
    # шукає дослідження. Межа тут проходить не по слову, а по ролі: ім'я автора
    # у метаданих пакета публічне за призначенням, а те саме прізвище всередині
    # КОДУ (у списку форм пошуку, у фікстурі, у тестових даних) — ознака, що
    # сюди приїхав шматок приватного конвеєра. Виняток точковий саме тому.
    ("pyproject.toml", "clan-surname"),
)


def _allowed(rel: str, rule_id: str) -> bool:
    rel = rel.replace("\\", "/")
    for pat, allowed in ALLOW:
        if (rel == pat or Path(rel).match(pat)) and allowed in ("*", rule_id):
            return True
    return False


@dataclass
class Finding:
    path: str
    line_no: int
    rule: Rule
    excerpt: str


def scan_text(rel: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        for rule in RULES:
            if _allowed(rel, rule.id):
                continue
            m = rule.pattern.search(line)
            if m:
                frag = line.strip()
                if len(frag) > 120:
                    lo = max(0, m.start() - 50)
                    frag = ("…" if lo else "") + line[lo:lo + 120].strip() + "…"
                out.append(Finding(rel, i, rule, frag))
    return out


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


def iter_worktree() -> list[tuple[str, str]]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > MAX_BYTES:
            continue
        rel = p.relative_to(ROOT).as_posix()
        out.append((rel, p.read_text(encoding="utf-8", errors="replace")))
    return out


def iter_staged() -> list[tuple[str, str]]:
    """Вміст, який ЗАРАЗ у індексі — саме він потрапить у коміт.

    Читаємо з `git show :file`, а не з диска: інакше перевірка дивилась би на
    робоче дерево, тоді як закомітиться індекс, і `git add -p` пройшов би повз.
    """
    names = [n for n in _git("diff", "--cached", "--name-only", "-z").split("\0") if n]
    out = []
    for rel in names:
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            out.append((rel, _git("show", f":{rel}")))
        except RuntimeError:
            continue  # видалений файл
    return out


def iter_history() -> list[tuple[str, str]]:
    """Усі версії всіх текстових файлів в історії.

    Дорого, але потрібно рівно один раз — перед першим `git push`. Після нього
    прибрати знахідку означає переписати опубліковану історію.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    lines = _git("rev-list", "--objects", "--all").splitlines()
    for line in lines:
        sha, _, name = line.partition(" ")
        if not name or Path(name).suffix.lower() not in TEXT_SUFFIXES or sha in seen:
            continue
        seen.add(sha)
        try:
            size = int(_git("cat-file", "-s", sha).strip())
        except (RuntimeError, ValueError):
            continue
        if size > MAX_BYTES:
            continue
        try:
            out.append((f"{name} @{sha[:8]}", _git("cat-file", "-p", sha)))
        except RuntimeError:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="лише те, що в git add")
    g.add_argument("--history", action="store_true", help="уся історія (перед першим push)")
    ap.add_argument("--list-rules", action="store_true", help="показати правила й вийти")
    a = ap.parse_args()

    if a.list_rules:
        for r in RULES:
            print(f"  {r.id:16s} {r.why}")
        return 0

    try:
        if a.staged:
            items, what = iter_staged(), "індекс"
        elif a.history:
            items, what = iter_history(), "історія"
        else:
            items, what = iter_worktree(), "робоче дерево"
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for rel, text in items:
        findings += scan_text(rel, text)

    if not findings:
        print(f"✅ приватних даних не знайдено ({what}: {len(items)} файлів, "
              f"{len(RULES)} правил)")
        return 0

    print(f"🔴 ЗНАЙДЕНО ПРИВАТНІ ДАНІ ({what}) — {len(findings)} збігів:\n")
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule.id, []).append(f)
    for rid, group in sorted(by_rule.items()):
        print(f"  ▸ {rid} — {group[0].rule.why}  ({len(group)})")
        for f in group[:8]:
            print(f"      {f.path}:{f.line_no}  {f.excerpt}")
        if len(group) > 8:
            print(f"      … ще {len(group) - 8}")
    print("\nЩо робити: прибрати дані або, якщо це свідомий приклад, додати "
          "ТОЧКОВИЙ виняток у `ALLOW` (правило × шлях, не «ігнорувати файл»).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
