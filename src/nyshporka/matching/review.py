"""Інтерактивний gate для кандидатів: rich UI з keymap a/r/m/s/n/o/q."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from nyshporka import brand
from nyshporka.models.candidate import Candidate
from nyshporka.storage.files import read_person


def _load_candidates(root: Path) -> list[tuple[Path, Candidate]]:
    cdir = root / "data" / "candidates"
    if not cdir.exists():
        return []
    out: list[tuple[Path, Candidate]] = []
    for path in sorted(cdir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        c = Candidate.model_validate(data)
        if c.status in ("new", "reviewing"):
            out.append((path, c))
    return out


def _format_breakdown(b: dict[str, float]) -> str:
    parts = []
    for key in ("surname", "given", "patronymic", "year", "place"):
        if key in b:
            parts.append(f"{key}={b[key]:.2f}")
    return "  ".join(parts)


def review_loop(
    root: Path,
    *,
    source: str | None = None,
    min_score: float = 0.0,
    console: Console | None = None,
) -> dict[str, int]:
    """Інтерактивно пройти кандидатів. Повертає лічильники по діях."""
    console = console or brand.console()
    all_pairs = _load_candidates(root)
    pairs = [
        (p, c)
        for p, c in all_pairs
        if (source is None or c.source_id == source) and c.score >= min_score
    ]
    counters = {"accepted": 0, "rejected": 0, "skipped": 0, "quit": 0}
    if not pairs:
        console.print("[warn]Немає кандидатів для review.[/warn]")
        return counters

    console.print(f"[bold]До перегляду:[/bold] {len(pairs)} кандидатів")
    for i, (path, candidate) in enumerate(pairs, start=1):
        _render_candidate(console, candidate, root, i, len(pairs))
        action = Prompt.ask(
            "Дія",
            choices=["a", "r", "s", "n", "o", "q"],
            default="s",
            show_choices=False,
        )
        if action == "a":
            candidate.status = "accepted"
            counters["accepted"] += 1
        elif action == "r":
            candidate.status = "rejected"
            counters["rejected"] += 1
        elif action == "n":
            note = Prompt.ask("Нотатка")
            candidate.notes = (candidate.notes + "\n" + note).strip()
            counters["skipped"] += 1
        elif action == "o":
            if os.name == "nt" and Path(candidate.raw_path).exists():
                # 🔴 Подвійна позначка навмисна: `os.startfile` існує лише на
                # Windows, тож на Linux потрібен `attr-defined`, а на Windows
                # той самий рядок робить позначку зайвою. CI ганяє обидві
                # платформи — без `unused-ignore` він червонітиме то тут, то там.
                os.startfile(candidate.raw_path)  # type: ignore[attr-defined, unused-ignore]
            counters["skipped"] += 1
        elif action == "q":
            counters["quit"] += 1
            break
        else:
            counters["skipped"] += 1
        candidate.reviewed_at = datetime.now(tz=UTC)
        path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"\n[ok]Done.[/ok] {counters}")
    return counters


def _render_candidate(
    console: Console, candidate: Candidate, root: Path, idx: int, total: int
) -> None:
    extracted = candidate.extracted
    extr_table = Table(title=f"[{idx}/{total}] Кандидат {candidate.id}", show_header=False)
    extr_table.add_column("ключ", style="muted")
    extr_table.add_column("значення")
    for k in ("surname", "given_name", "patronymic", "birth_year", "birth_place", "father_name"):
        if extracted.get(k):
            extr_table.add_row(k, str(extracted[k]))
    extr_table.add_row("score", f"[bold]{candidate.score:.3f}[/bold]")
    extr_table.add_row("breakdown", _format_breakdown(candidate.score_breakdown))
    extr_table.add_row("source", candidate.source_id)

    panels: list[Panel] = [Panel(extr_table, title="Extracted record")]

    if candidate.proposed_person_id:
        person_path = root / "data" / "canonical" / "persons" / f"{candidate.proposed_person_id}.md"
        if person_path.exists():
            p = read_person(person_path)
            primary = next((n for n in p.names if n.primary), p.names[0])
            t = Table(show_header=False)
            t.add_column("ключ", style="muted")
            t.add_column("значення")
            t.add_row("id", p.id)
            t.add_row("name", primary.form)
            t.add_row("sex", p.sex)
            t.add_row("private", str(p.private))
            for f in p.facts[:5]:
                t.add_row(
                    f.type,
                    f"{f.date.value if f.date else '—'}  ({f.place_id or '—'})",
                )
            panels.append(Panel(t, title="Proposed canonical match"))

    for panel in panels:
        console.print(panel)
    console.print(
        "[muted]Дія: [a]ccept  [r]eject  [s]kip  [n]ote  [o]pen raw  [q]uit[/muted]"
    )
