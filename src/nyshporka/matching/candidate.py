"""Створення Candidate'ів із extracted-записів зовнішнього джерела."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.matching.fuzzy import score_record
from nyshporka.models import Person
from nyshporka.models.candidate import Candidate
from nyshporka.storage.files import read_person

_AUTO_THRESHOLD = 0.85
_REVIEW_THRESHOLD = 0.6


@dataclass
class MatchReport:
    total: int
    auto: int           # score ≥ 0.85
    review: int         # 0.6 ≤ score < 0.85
    cold: int           # < 0.6 (без proposed_person_id)
    candidates_path: Path


def _make_candidate_id(source_id: str, record: dict[str, Any]) -> str:
    """Стабільний ID кандидата по дайджесту запису."""
    canon = json.dumps(record, sort_keys=True, ensure_ascii=False)
    h = hashlib.blake2b(canon.encode("utf-8"), digest_size=6).hexdigest()
    return f"{source_id}__{h}"


def match_records(
    records: list[dict[str, Any]],
    persons: list[Person],
    *,
    source_id: str,
    raw_path: str,
) -> list[Candidate]:
    """Для кожного extracted-запису знайти найкращого кандидата серед persons."""
    out: list[Candidate] = []
    for record in records:
        best_person: Person | None = None
        best_score = 0.0
        best_breakdown: dict[str, float] = {}
        for p in persons:
            s = score_record(record, p)
            if s.total > best_score:
                best_score = s.total
                best_person = p
                best_breakdown = s.breakdown

        proposed_id = best_person.id if best_person and best_score >= _REVIEW_THRESHOLD else None
        candidate = Candidate(
            id=_make_candidate_id(source_id, record),
            source_id=source_id,
            raw_path=raw_path,
            extracted=record,
            proposed_person_id=proposed_id,
            score=best_score,
            score_breakdown=best_breakdown,
            status="new" if best_score < _AUTO_THRESHOLD else "reviewing",
        )
        out.append(candidate)
    return out


def save_candidates(candidates: list[Candidate], root: Path) -> MatchReport:
    """Записати кандидатів як JSON у `data/candidates/`. Повернути report."""
    cdir = root / "data" / "candidates"
    cdir.mkdir(parents=True, exist_ok=True)
    auto = review = cold = 0
    for c in candidates:
        path = cdir / f"{c.id}.json"
        path.write_text(c.model_dump_json(indent=2), encoding="utf-8")
        if c.score >= _AUTO_THRESHOLD:
            auto += 1
        elif c.score >= _REVIEW_THRESHOLD:
            review += 1
        else:
            cold += 1
    return MatchReport(
        total=len(candidates),
        auto=auto,
        review=review,
        cold=cold,
        candidates_path=cdir,
    )


def load_persons_index(root: Path) -> list[Person]:
    """Завантажити всі canonical persons для матчингу."""
    persons_dir = root / "data" / "canonical" / "persons"
    return sorted(
        (read_person(p) for p in persons_dir.glob("*.md")),
        key=lambda x: x.id,
    )
