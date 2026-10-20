"""🧪 Лінт скілів: кожна команда, яку скіл радить, існує — разом із прапорцями.

Скіл агент виконує буквально. Застарілий рядок у ньому — це не «неточність у
документації», а вигаданий прапорець у справжньому запуску (`--pack-dir`,
`--target-pph` з грепу замість скіла — дві зірвані оренди). Тому команди в
скілах перевіряються проти живого дерева CLI, а не проти знімка: знімок
старіє так само, як скіл.

Модуль не знає про конкретну програму: дерево click і ім'я програми
передаються ззовні. Так той самий розбір перевіряє `nysh …` у скілах пакета і
команди власної програми в скілах проєкту, що стоїть на пакеті.

Що вважається командою: текст у коді — інлайн-спани в бектиках і огороджені
блоки. Голий текст не розбирається: у прозі «nysh» буває назвою, а не
викликом, і хибна тривога там дорожча за пропуск.

Навмисний негатив («команди `nysh cases stats` не існує») пропускається, якщо
поруч стоїть маркер `NEGATIVE`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

#: Тверда межа тіла `SKILL.md` у знаках. Довгий скіл агент не дочитує, і
#: саме кінець — ворота, перевірка, що записати — губиться першим.
BODY_MAX = 15_000

#: Маркери навмисного негативу поруч із командою.
NEGATIVE = ("не існує", "немає такої", "does not exist")

_FENCE = re.compile(r"^\s*(```|~~~)")
_SPAN = re.compile(r"`([^`\n]+)`")
_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
_WORD = re.compile(r"[a-z][a-z0-9-]*$")
_OP = re.compile(r"[a-z_]+\.[a-z_]+")
_STOP = frozenset({"|", "||", "&&", ";", ">", ">>", "2>&1", "&", ")", "»", "→"})


@dataclass(frozen=True)
class Problem:
    """Одна вада: де, що саме написано і чому це не працює."""

    where: str
    text: str
    why: str

    def __str__(self) -> str:
        return f"{self.where}: `{self.text}` — {self.why}"


def body_chars(text: str) -> int:
    """Довжина в знаках без `\\r`: CRLF не має робити скіл «довшим»."""
    return len(text.replace("\r", ""))


def code_lines(text: str) -> list[tuple[int, str]]:
    """Шматки коду з номерами рядків: рядки огороджених блоків і інлайн-спани.

    Рядки, перенесені в межах абзацу, склеюються перед пошуком спанів —
    інакше `nysh train` в кінці одного рядка й `from-pool` на початку
    наступного розійшлися б у дві «команди». У блоках коду склеюються
    продовження з `\\` чи PowerShell-бектиком у кінці рядка.
    """
    out: list[tuple[int, str]] = []
    lines = text.replace("\r", "").split("\n")
    fenced = False
    para: list[tuple[int, str]] = []
    cont: tuple[int, str] | None = None

    def flush() -> None:
        if not para:
            return
        joined = " ".join(s.strip() for _, s in para)
        out.extend((para[0][0], m.group(1)) for m in _SPAN.finditer(joined))
        para.clear()

    for i, line in enumerate(lines, 1):
        if _FENCE.match(line):
            flush()
            fenced = not fenced
            continue
        if fenced:
            body = line.rstrip()
            if cont is not None:
                body = f"{cont[1]} {body.strip()}"
                i = cont[0]
            if body.endswith(("\\", "`")) and not body.endswith("``"):
                cont = (i, body[:-1].rstrip())
                continue
            cont = None
            out.append((i, body))
        elif line.strip():
            para.append((i, line))
        else:
            flush()
    flush()
    return out


def _negated(code: str, para: str) -> bool:
    """Маркер негативу в тому самому реченні, а не будь-де в абзаці."""
    at = para.find(code)
    window = para if at < 0 else para[max(0, at - 100):at + len(code) + 100]
    return any(n in window.lower() for n in NEGATIVE)


def _opts(cmd: Any) -> dict[str, Any]:
    """Прапорці команди з другими половинами пар («--json/--human»).

    ⚠ Typer несе власну копію click (`typer._click`), тож класи click тут не
    порівнюються через `isinstance` — лише за атрибутами.
    """
    got: dict[str, Any] = {"--help": None}
    for p in cmd.params:
        for o in (*p.opts, *getattr(p, "secondary_opts", ())):
            if o.startswith("-"):
                got[o] = p
    return got


def resolve(root: Any, tokens: list[str],
            known_ops: set[str] | None = None) -> str | None:
    """Пройти дерево за токенами після імені програми. `None` — усе існує.

    Опції груп (`nysh --project Y text find`, `nysh ops --map`) приймаються
    там, де їх оголошено. Позиційні аргументи листка не перевіряються: там
    стоять `<справа>`, `…` і справжні шифри.
    """
    node = root
    path: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _STOP or tok.startswith("#"):
            break
        if tok.startswith("-") and len(tok) > 1 and not tok[1:2].isdigit():
            flag = tok.split("=", 1)[0]
            opts = _opts(node)
            if flag not in opts:
                where = " ".join(path) or "(корінь)"
                return f"у `{where}` немає прапорця {flag}"
            p = opts[flag]
            takes_value = (p is not None and p.param_type_name == "option"
                           and not p.is_flag and not getattr(p, "count", False)
                           and "=" not in tok)
            i += 2 if takes_value else 1
            continue
        subs = getattr(node, "commands", None)
        if subs is not None:
            sub = subs.get(tok)
            if sub is not None:
                node, path = sub, [*path, tok]
                i += 1
                continue
            if _WORD.match(tok) and not getattr(node, "invoke_without_command", False):
                where = " ".join(path) or "(корінь)"
                return f"у `{where}` немає команди «{tok}»"
            break
        # Листок: решта — аргументи, крім прапорців.
        if (path == ["op"] and known_ops is not None and _OP.fullmatch(tok)
                and tok not in known_ops):
            return f"немає операції «{tok}»"
        i += 1
    return None


def check(text: str, prog: str, root: Any, *, where: str = "",
          known_ops: set[str] | None = None) -> list[Problem]:
    """Усі вади в одному тексті для програми `prog` (`nysh` чи програми проєкту)."""
    head = re.compile(rf"(?<![\w-]){re.escape(prog)}(?:\.exe)?(?=\s)")
    problems: list[Problem] = []
    for lineno, code in code_lines(text):
        for m in head.finditer(code):
            tail = code[m.end():]
            tokens = _TOKEN.findall(tail)
            # Плейсхолдер на місці команди («nysh <група>») — не порада.
            if not tokens or tokens[0].startswith(("<", "…", "$", "{")):
                continue
            why = resolve(root, tokens, known_ops)
            if why is None:
                continue
            shown = f"{prog} {' '.join(tokens[:6])}"
            if _negated(code, _source_line(text, lineno)):
                continue
            problems.append(Problem(f"{where}:{lineno}", shown, why))
    return problems


def _source_line(text: str, lineno: int) -> str:
    """Абзац, з якого взято шматок коду, — для маркера негативу поруч."""
    lines = text.replace("\r", "").split("\n")
    lo = hi = lineno - 1
    while lo > 0 and lines[lo - 1].strip():
        lo -= 1
    while hi + 1 < len(lines) and lines[hi + 1].strip():
        hi += 1
    return " ".join(lines[lo:hi + 1])


def check_files(paths: Iterable[tuple[str, str]], prog: str, root: Any,
                known_ops: set[str] | None = None) -> list[Problem]:
    """Пари (ім'я для звіту, текст) — щоб тест не залежав від розкладки тек."""
    out: list[Problem] = []
    for name, text in paths:
        out.extend(check(text, prog, root, where=name, known_ops=known_ops))
    return out
