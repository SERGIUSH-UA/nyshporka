"""🧭 Міграція агента: коли пакет міняє парадигму, застаріває не код, а знання.

Оновлення пакета дотягується до коду й до встановлених скілів (`skills sync`),
але не до того, що агент уже ЗНАЄ: його пам'яті, нотаток, CLAUDE.md проєкту,
правлених руками скілів, конфігу MCP. Там теза «канону в пакеті немає» живе й
після того, як канон з'явився, — і агент чесно діє за нею.

Тому на кожну версію, що міняє поведінку агента, є файл міграції
`migrate/data/<версія>.md`:

* **застарілі тези** — регекси, за якими їх видно в тексті, і що правда тепер;
  `nysh migrate --scan` шукає їх у пам'яті агента й нотатках;
* **кроки** в просторі й на машині — кожен із живою перевіркою (не «позначено
  виконаним», а «зараз зелене»);
* **що вирішує людина.**

Пройдену міграцію запам'ятовує МАШИНА для кожного простору (стан користувача,
поле `agent_migrations`), а не сам простір: частина кроків — про цю машину
(конфіг агента, скіли, пам'ять), і копія простору на новій машині мусить
нагадати про них знову. Поки не позначено, нагадують `workspace.info`,
дашборд і кожна команда `nysh`. Новий простір позначається пройденим одразу:
переходити йому нема з чого.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter

DATA = Path(__file__).resolve().parent / "data"
#: Поле стану користувача: {шлях простору: {"done": [...], "history": [...]}}.
STATE_KEY = "agent_migrations"
#: Вимикач нагадування в CLI — для тестів і скриптів, що розбирають вивід.
ENV_NO_NAG = "NYSHPORKA_NO_MIGRATION_NAG"
#: Файли, довші за це, на застарілі тези не скануються: пам'ять і нотатки —
#: кілобайти, а мегабайти — це дані, не знання агента.
MAX_SCAN_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Stale:
    id: str
    pattern: re.Pattern[str]
    now: str


@dataclass(frozen=True)
class Step:
    id: str
    do: str
    check: str = ""
    human: bool = False


@dataclass
class Migration:
    version: str
    title: str
    body: str
    stale: list[Stale] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    @property
    def key(self) -> tuple[int, ...]:
        return version_key(self.version)


def version_key(v: str) -> tuple[int, ...]:
    """`0.19` і `0.19.0` — одна версія; хвости на кшталт `rc1` ігноруються."""
    parts = [int(m) for m in re.findall(r"\d+", v.split("+")[0])[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def load_all() -> list[Migration]:
    out: list[Migration] = []
    for path in sorted(DATA.glob("*.md")):
        post = frontmatter.load(str(path))
        meta: dict[str, Any] = dict(post.metadata)
        out.append(Migration(
            version=str(meta["version"]),
            title=str(meta.get("title") or ""),
            body=post.content.strip(),
            stale=[Stale(id=s["id"], pattern=re.compile(s["pattern"], re.IGNORECASE),
                         now=s["now"]) for s in meta.get("stale") or []],
            steps=[Step(id=s["id"], do=s["do"], check=s.get("check", ""),
                        human=bool(s.get("human"))) for s in meta.get("steps") or []],
        ))
    return sorted(out, key=lambda m: m.key)


def get(version: str) -> Migration | None:
    want = version_key(version)
    return next((m for m in load_all() if m.key == want), None)


# ── запис про пройдене ───────────────────────────────────────────────────────
def _key(root: Path) -> str:
    return str(root.resolve())


def record(root: Path) -> dict[str, Any]:
    from nyshporka.core.workspace import state_all

    all_ = state_all().get(STATE_KEY)
    got = all_.get(_key(root)) if isinstance(all_, dict) else None
    return got if isinstance(got, dict) else {"done": [], "history": []}


def mark_done(root: Path, versions: Iterable[str], *, how: str = "agent") -> list[str]:
    from nyshporka.core.workspace import state_all, state_set

    data = record(root)
    done = {version_key(v) for v in data.get("done") or []}
    added = []
    for v in versions:
        if version_key(v) not in done:
            data.setdefault("done", []).append(v)
            data.setdefault("history", []).append(
                {"version": v, "at": datetime.now(UTC).isoformat(timespec="seconds"),
                 "how": how})
            done.add(version_key(v))
            added.append(v)
    if added:
        all_ = state_all().get(STATE_KEY)
        all_ = dict(all_) if isinstance(all_, dict) else {}
        all_[_key(root)] = data
        state_set(**{STATE_KEY: all_})
    return added


def pending(root: Path, current: str) -> list[Migration]:
    """Міграції не новіші за пакет, яких цей простір ще не пройшов."""
    done = {version_key(v) for v in record(root).get("done") or []}
    top = version_key(current)
    return [m for m in load_all() if m.key <= top and m.key not in done]


def nag(env: Any, root: Path) -> None:
    """Нагадати в конверті, якщо простір не пройшов міграцію агента.

    Одне попередження й одна порада — у тих відповідях, з яких агент починає
    сесію (`workspace.info`, дашборд). Мовчить, коли все пройдено.
    """
    from nyshporka import __version__

    try:
        todo = pending(root, __version__)
    except Exception:
        return
    if todo:
        last = todo[-1].version
        env.warn("agent_migration",
                 f"пакет оновлено до {__version__}, а простір не пройшов міграцію агента "
                 f"({', '.join(m.version for m in todo)}): частина того, що ти знаєш про "
                 f"Нишпорку, могла застаріти — `nysh migrate`")
        env.suggest("migrate.status", f"що змінилось у {last} і що зробити")


def stamp_new(root: Path, current: str) -> None:
    """Новий простір: переходити йому нема з чого — усе до поточної версії пройдено."""
    top = version_key(current)
    mark_done(root, [m.version for m in load_all() if m.key <= top], how="new-workspace")


# ── живі перевірки кроків ────────────────────────────────────────────────────
@dataclass
class CheckResult:
    state: str          # ok · todo · n/a
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state, "detail": self.detail}


def _mcp_config(root: Path) -> CheckResult:
    """Чи прописаний ще десь сервер Нишпорки (після 0.19 він не підніметься)."""
    found: list[str] = []
    for cfg in dict.fromkeys([Path.cwd() / ".mcp.json", root / ".mcp.json",
                              Path.home() / ".claude.json"]):
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        blocks = [data.get("mcpServers") or {}]
        blocks += [(p or {}).get("mcpServers") or {}
                   for p in (data.get("projects") or {}).values() if isinstance(p, dict)]
        for block in blocks:
            for name, spec in block.items():
                blob = json.dumps(spec, ensure_ascii=False)
                if name == "nyshporka" or ("nysh" in blob and "mcp" in blob):
                    found.append(f"{cfg}: {name}")
    if found:
        return CheckResult("todo", "сервер ще прописаний: " + "; ".join(dict.fromkeys(found)))
    return CheckResult("ok", "сервера Нишпорки в конфігах агента немає")


def _skills_current(root: Path) -> CheckResult:
    from nyshporka import __version__
    from nyshporka import skills as S

    places = S.installed()
    if not places:
        return CheckResult("todo", "скіли пакета ніде не встановлені: nysh skills install --user")
    have = {s.name for s in S.available()}
    problems = []
    for dest, ver in places:
        if version_key(ver) < version_key(__version__):
            problems.append(f"{dest}: скіли з {ver}")
        ledger = S._ledger(dest)
        gone = sorted({rel.split("/", 1)[0] for rel in ledger} - have)
        if gone:
            problems.append(f"{dest}: зняті з пакета {gone}")
    if problems:
        return CheckResult("todo", "; ".join(problems))
    return CheckResult("ok", ", ".join(str(d) for d, _ in places))


def _canon_present(root: Path) -> CheckResult:
    persons = root / "data" / "canonical" / "persons"
    n = len(list(persons.glob("*.md"))) if persons.is_dir() else 0
    if n:
        return CheckResult("ok", f"карток осіб: {n}")
    return CheckResult("todo", "канону ще немає — засівати з людиною")


def _hook_installed(root: Path) -> CheckResult:
    import subprocess

    from nyshporka.canon.hook import hooks_dir

    if not (root / ".git").exists():
        return CheckResult("n/a", "простір не є git-репозиторієм")
    try:
        hook = hooks_dir(root) / "pre-commit"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return CheckResult("n/a", "git недоступний")
    try:
        text = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return CheckResult("todo", "pre-commit не стоїть: nysh canon hook --install")
    if "nyshporka canon precommit" in text:
        return CheckResult("ok", str(hook))
    return CheckResult("todo", f"{hook} є, але без перевірки канону")


def _stale_scan(root: Path) -> CheckResult:
    hits = scan(default_scan_paths(root), load_all())
    if hits:
        files = sorted({h.path for h in hits})
        return CheckResult("todo", f"застарілих тез: {len(hits)} у {len(files)} файлах "
                                   f"(nysh migrate --scan)")
    return CheckResult("ok", "у пам'яті й нотатках застарілих тез не знайдено")


CHECKS: dict[str, Callable[[Path], CheckResult]] = {
    "mcp_config": _mcp_config,
    "skills_current": _skills_current,
    "canon_present": _canon_present,
    "hook_installed": _hook_installed,
    "stale_scan": _stale_scan,
}


def run_check(name: str, root: Path) -> CheckResult:
    fn = CHECKS.get(name)
    if fn is None:
        return CheckResult("n/a", "перевірки немає — лише рішення людини")
    try:
        return fn(root)
    except Exception as exc:  # перевірка не має валити статус міграції
        return CheckResult("todo", f"перевірка не вдалась: {type(exc).__name__}: {exc}")


# ── застарілі тези в тексті ──────────────────────────────────────────────────
@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    stale: str
    text: str
    now: str
    version: str

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "stale": self.stale,
                "text": self.text, "now": self.now, "version": self.version}


def default_scan_paths(root: Path) -> list[Path]:
    """Де живе знання агента: пам'ять цього проєкту, CLAUDE.md/AGENTS.md,
    правлені руками скіли.

    Скіли, покладені пакетом і не правлені, не скануються: їх оновлює
    `nysh skills install`, і застаріле в них лікується оновленням, а не рукою.
    """
    home = Path.home() / ".claude"
    out: list[Path] = []
    # Пам'ять лише ЦЬОГО проєкту: теки Claude Code названі шляхом проєкту, де
    # кожен не-латинський знак став «-». Чужі проєкти — не наша справа.
    for base in dict.fromkeys([Path.cwd(), root]):
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(base.resolve()))
        out.append(home / "projects" / slug / "memory")
    for base in dict.fromkeys([Path.cwd(), root]):
        out += [base / "CLAUDE.md", base / "AGENTS.md", base / ".claude" / "CLAUDE.md"]
    out.append(home / "CLAUDE.md")
    out += _hand_edited_skills(home / "skills")
    out += _hand_edited_skills(root / ".claude" / "skills")
    return [p for p in dict.fromkeys(out) if p.exists()]


def _hand_edited_skills(dest: Path) -> list[Path]:
    from nyshporka import skills as S

    if not dest.is_dir():
        return []
    ledger = S._ledger(dest)
    out = []
    for f in sorted(dest.rglob("*.md")):
        rel = f.relative_to(dest).as_posix()
        if rel in ledger and S.sha256(f) == ledger[rel]:
            continue          # поклав пакет і ніхто не правив — лікується оновленням
        out.append(f)
    return out


def _files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from sorted(x for x in p.rglob("*.md") if x.is_file())


#: Пари лапок, у яких теза ЦИТУЄТЬСЯ, а не стверджується.
#: ASCII-лапки й бектики — ні: непарна `"` глушила б решту рядка, а в
#: бектиках у нотатках стоїть команда, яку агент ВИКОНУЄ, тобто теза.
_QUOTES = (("«", "»"), ("“", "”"))


def _quoted(line: str, pos: int) -> bool:
    """Чи стоїть збіг усередині лапок.

    🪤 Нотатка, що попереджає «не повторювати тезу «канону в пакеті немає»»,
    містить ту саму тезу дослівно. Цитата — не твердження: інакше скан
    вимагав би прибрати саме ті рядки, які застерігають від помилки.
    """
    for opening, closing in _QUOTES:
        depth = 0
        for ch in line[:pos]:
            if opening == closing:
                if ch == opening:
                    depth ^= 1
            elif ch == opening:
                depth += 1
            elif ch == closing and depth:
                depth -= 1
        if depth:
            return True
    return False


def scan(paths: Iterable[Path], migrations: Iterable[Migration]) -> list[Hit]:
    rules = [(m.version, s) for m in migrations for s in m.stale]
    hits: list[Hit] = []
    for f in dict.fromkeys(_files(paths)):
        try:
            if f.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for no, line in enumerate(text.splitlines(), 1):
            for version, rule in rules:
                if any(not _quoted(line, m.start()) for m in rule.pattern.finditer(line)):
                    hits.append(Hit(path=str(f), line=no, stale=rule.id,
                                    text=line.strip()[:200], now=rule.now, version=version))
    return hits
