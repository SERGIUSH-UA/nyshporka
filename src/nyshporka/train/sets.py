"""🗃 Набір — одна справа (або добірка сторінок) із кропами, голосами й мітками.

Це те саме, чим для спотера є банк: **розмітка людським оком, яка нічим не
регенерується**. Тому `data/train/sets/<набір>/` лежить у просторі поруч із
каноном, а не в кеші.

Розкладка одного набору:

    data/train/sets/<набір>/
      set.json          опис: звідки нарізано, які голоси, роль (train|holdout)
      lines.jsonl       ручні мітки — append-only, останній запис на (page, idx) виграє
      drafts/<id>/<page>.txt      голос або злиття: рядок на індекс кропа, діри = порожні
      drafts/<id>/_meta.json      {"pages": {"<page>": {"conf": {"31": "high|med|low"}}}}
    data/train/crops/<набір>/<page>/line_NNN.png   + _cut_meta.json

🔴 Голос і злиття — різні речі, хоч і лежать поруч. Голос — те, що прочитав
рушій; злиття (`merge`) — те, що з голосів зробили арбітри. При експорті
завдань для арбітрів злиття голосом НЕ береться ніколи: інакше арбітр другого
заходу читав би власну попередню відповідь як «третій рушій» і підтверджував
сам себе.

🔴 Ім'я теки злиття зафіксоване тут (`MERGE_ID`), і прапорця «покласти під
іншим іменем» немає навмисно. У дослідницькому конвеєрі збірник корпусу шукав
теку за точним іменем, а злиття двічі клали під схожим — і 1033 готові рядки
мовчки не потрапили в трен. Тут це неможливо за побудовою.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, WorkspaceError, workspace
from nyshporka.train import layout as L
from nyshporka.train.text import strip_conflict_marks
from nyshporka.utils.atomic import read_json, write_json

SET_FILE = "set.json"
MARKS_FILE = "lines.jsonl"
DRAFTS_DIR = "drafts"
META_FILE = "_meta.json"
CUT_META_FILE = "_cut_meta.json"

#: Тека злиття арбітрів усередині `drafts/`. Див. докстрінг модуля.
MERGE_ID = "merge"

STATUSES = ("ok", "skip", "unsure")
KINDS = ("hand", "print", "mixed")
ROLES = ("train", "holdout")
CONFS = ("high", "med", "low")

#: `line_007.png`, `line_0123.png` — ширина індексу не фіксується: нарізка
#: різних років писала по-різному, а індекс один і той самий.
_CROP_RE = re.compile(r"^line_(\d+)\.png$")

_LOCK = threading.Lock()


class SetError(ValueError):
    """Набору немає, ім'я неприпустиме або опис не читається."""


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── опис набору ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Draft:
    """Голос або злиття. Рівно одне з `run` / `dir` непорожнє.

    `run` — текст береться прямо з теки прогону (`reports/htr/<run>/<page>.txt`)
    без копіювання: індекс рядка там і є індекс кропа, бо кропи різались із
    цього ж прогону. `dir` — тека всередині набору (`drafts/<id>`).
    """

    id: str
    run: str = ""
    dir: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"id": self.id}
        if self.run:
            out["run"] = self.run
        if self.dir:
            out["dir"] = self.dir
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Draft:
        return cls(id=str(d.get("id") or ""), run=str(d.get("run") or ""),
                   dir=str(d.get("dir") or ""))


@dataclass
class SetSpec:
    name: str
    title: str = ""
    case: str = ""
    script: str = "cyrillic"
    role: str = "train"
    source_run: str = ""
    #: Тека кропів відносно `set.json`; дефолт — `../../crops/<набір>`.
    crops: str = ""
    domain: str = ""
    drafts: list[Draft] = field(default_factory=list)
    glossary: dict[str, Any] = field(default_factory=dict)
    skip_names: list[str] = field(default_factory=list)
    hidden: bool = False
    note: str = ""
    version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "name": self.name, "title": self.title,
            "case": self.case, "script": self.script, "role": self.role,
            "source_run": self.source_run, "crops": self.crops,
            "domain": self.domain,
            "drafts": [d.as_dict() for d in self.drafts],
            "glossary": self.glossary, "skip_names": list(self.skip_names),
            "hidden": self.hidden, "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SetSpec:
        drafts = [Draft.from_dict(x) for x in (d.get("drafts") or [])
                  if isinstance(x, dict)]
        return cls(
            name=str(d.get("name") or ""), title=str(d.get("title") or ""),
            case=str(d.get("case") or ""),
            script=str(d.get("script") or "cyrillic"),
            role=str(d.get("role") or "train"),
            source_run=str(d.get("source_run") or ""),
            crops=str(d.get("crops") or ""), domain=str(d.get("domain") or ""),
            drafts=drafts,
            glossary=dict(d.get("glossary") or {}),
            skip_names=[str(x) for x in (d.get("skip_names") or [])],
            hidden=bool(d.get("hidden", False)), note=str(d.get("note") or ""),
            version=int(d.get("version") or 1),
        )

    def voices(self) -> list[Draft]:
        """Голоси для експорту арбітрам — БЕЗ злиття. Див. докстрінг модуля."""
        return [d for d in self.drafts if d.id != MERGE_ID]

    def merge(self) -> Draft | None:
        return next((d for d in self.drafts if d.id == MERGE_ID), None)


# ── реєстр ───────────────────────────────────────────────────────────────────
class Registry:
    """Набори одного простору. Створюється на `data/train`, а не на простір
    цілком, щоб тести й міграція могли підставити будь-яку теку."""

    def __init__(self, root: Path, *, htr_reports: Path | None = None) -> None:
        self.root = root
        self.sets_dir = root / L.SETS
        self.crops_dir = root / L.CROPS
        self._htr = htr_reports

    # -- шляхи --
    def set_dir(self, name: str) -> Path:
        if not L.valid_name(name):
            raise SetError(f"неприпустиме ім'я набору: {name!r}")
        return self.sets_dir / name

    def spec_path(self, name: str) -> Path:
        return self.set_dir(name) / SET_FILE

    def marks_path(self, name: str) -> Path:
        return self.set_dir(name) / MARKS_FILE

    def crops_of(self, spec: SetSpec) -> Path:
        if spec.crops:
            return (self.set_dir(spec.name) / spec.crops).resolve()
        return (self.crops_dir / spec.name).resolve()

    def draft_dir(self, spec: SetSpec, draft: Draft) -> Path | None:
        """Тека, з якої читати текст голосу. `None` — голос живе у прогоні."""
        if draft.dir:
            return (self.set_dir(spec.name) / draft.dir).resolve()
        return None

    def merge_dir(self, spec: SetSpec) -> Path:
        return self.set_dir(spec.name) / DRAFTS_DIR / MERGE_ID

    def run_dir(self, run: str) -> Path | None:
        """Тека прогону — той самий гард, що в `htr_store._case_dir`."""
        base = self._htr
        if base is None:
            try:
                base = workspace().htr_reports
            except WorkspaceError:
                return None
        if not run or "/" in run or "\\" in run or run.startswith("."):
            return None
        d = (base / run).resolve()
        if d.parent != base.resolve() or not d.is_dir():
            return None
        return d

    # -- опис --
    def names(self, *, hidden: bool = False) -> list[str]:
        if not self.sets_dir.is_dir():
            return []
        out = []
        for d in sorted(self.sets_dir.iterdir()):
            if d.is_dir() and (d / SET_FILE).is_file():
                if hidden:
                    out.append(d.name)
                else:
                    try:
                        if not self.load(d.name).hidden:
                            out.append(d.name)
                    except SetError:
                        out.append(d.name)  # зіпсований опис має бути видно
        return out

    def exists(self, name: str) -> bool:
        return L.valid_name(name) and self.spec_path(name).is_file()

    def load(self, name: str) -> SetSpec:
        p = self.spec_path(name)
        if not p.is_file():
            raise SetError(f"набору «{name}» немає: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SetError(f"опис набору «{name}» не читається: {exc}") from None
        if not isinstance(raw, dict):
            raise SetError(f"опис набору «{name}» — не об'єкт")
        spec = SetSpec.from_dict(raw)
        spec.name = name  # ім'я — це тека, а не поле всередині
        return spec

    def save(self, spec: SetSpec) -> Path:
        if not L.valid_name(spec.name):
            raise SetError(f"неприпустиме ім'я набору: {spec.name!r}")
        if spec.role not in ROLES:
            raise SetError(f"role має бути одним з {ROLES}, дано {spec.role!r}")
        p = self.spec_path(spec.name)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json(p, spec.as_dict())
        return p

    # -- кропи --
    def cut_meta(self, spec: SetSpec) -> dict[str, Any]:
        got = read_json(self.crops_of(spec) / CUT_META_FILE, default={})
        return got if isinstance(got, dict) else {}

    def crop_pages(self, spec: SetSpec) -> dict[str, int]:
        """{сторінка: скільки кропів на диску} — знаменник, а не самозвіт."""
        root = self.crops_of(spec)
        if not root.is_dir():
            return {}
        out: dict[str, int] = {}
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            n = sum(1 for p in d.iterdir() if _CROP_RE.match(p.name))
            if n:
                out[d.name] = n
        return out

    def crop_path(self, spec: SetSpec, page: str, idx: int) -> Path | None:
        """Файл кропа або `None`. Ширина індексу в імені не вгадується —
        шукається будь-яка."""
        d = self.crops_of(spec) / page
        if not d.is_dir() or "/" in page or "\\" in page or page.startswith("."):
            return None
        for width in (3, 4, 2, 5, 1):
            p = d / f"line_{idx:0{width}d}.png"
            if p.is_file():
                return p
        return None

    # -- голоси --
    def draft_lines(self, spec: SetSpec, draft: Draft, page: str) -> list[str] | None:
        """Рядки голосу для сторінки; `None` — файла немає."""
        if draft.dir:
            f = self.set_dir(spec.name) / draft.dir / f"{page}.txt"
        else:
            rd = self.run_dir(draft.run)
            if rd is None:
                return None
            f = rd / f"{page}.txt"
        if not f.is_file():
            return None
        return f.read_text(encoding="utf-8", errors="replace").splitlines()

    def draft_meta(self, spec: SetSpec, draft: Draft) -> dict[str, Any]:
        if not draft.dir:
            return {}
        got = read_json(self.set_dir(spec.name) / draft.dir / META_FILE, default={})
        return got if isinstance(got, dict) else {}

    def merge_conf(self, spec: SetSpec) -> dict[str, dict[str, str]]:
        """{сторінка: {idx: conf}} зі злиття; порожньо — злиття немає."""
        m = spec.merge()
        if m is None:
            return {}
        pages = self.draft_meta(spec, m).get("pages") or {}
        out: dict[str, dict[str, str]] = {}
        for pg, info in pages.items():
            conf = (info or {}).get("conf") or {}
            out[str(pg)] = {str(k): str(v) for k, v in conf.items()}
        return out

    # -- мітки --
    def marks(self, name: str) -> dict[tuple[str, int], dict[str, Any]]:
        """{(page, idx): запис} — останній запис на ключ перемагає."""
        path = self.marks_path(name)
        out: dict[tuple[str, int], dict[str, Any]] = {}
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and "page" in rec and "idx" in rec:
                out[(str(rec["page"]), int(rec["idx"]))] = rec
        return out

    def append_mark(self, name: str, page: str, idx: int, text: str, status: str,
                    *, kind: str = "hand", draft: str = "", secs: float = 0.0,
                    by: str = "eye") -> dict[str, Any]:
        """Дописати мітку. Append-only: історія правок зберігається."""
        if status not in STATUSES:
            raise SetError(f"status має бути одним з {STATUSES}, дано {status!r}")
        if kind not in KINDS:
            raise SetError(f"kind має бути одним з {KINDS}, дано {kind!r}")
        # 🔴 Гейт саме тут, а не «перед треном»: `lines.jsonl` — джерело правди,
        # і маркер, прийнятий одним Enter, лишився б у ньому назавжди.
        text = strip_conflict_marks(text).strip()
        rec = {"page": str(page), "idx": int(idx), "text": text, "status": status,
               "kind": kind, "draft": draft, "secs": round(float(secs), 1),
               "ts": _utc(), "by": by}
        path = self.marks_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    # -- зведення --
    def stats(self, name: str) -> dict[str, Any]:
        """Знаменники набору: сторінки, кропи, мітки за статусом, покриття злиття."""
        spec = self.load(name)
        pages = self.crop_pages(spec)
        n_crops = sum(pages.values())
        marks = self.marks(name)
        by_status = dict.fromkeys(STATUSES, 0)
        by_kind = dict.fromkeys(KINDS, 0)
        for rec in marks.values():
            by_status[str(rec.get("status"))] = by_status.get(str(rec.get("status")), 0) + 1
            by_kind[str(rec.get("kind") or "hand")] = by_kind.get(
                str(rec.get("kind") or "hand"), 0) + 1
        conf = self.merge_conf(spec)
        merge = dict.fromkeys(CONFS, 0)
        for per_page in conf.values():
            for c in per_page.values():
                merge[c] = merge.get(c, 0) + 1
        crops_dir = self.crops_of(spec)
        return {
            "name": name, "title": spec.title, "case": spec.case, "role": spec.role,
            "script": spec.script, "source_run": spec.source_run,
            "domain": spec.domain, "hidden": spec.hidden,
            "crops_dir": str(crops_dir), "crops_present": crops_dir.is_dir(),
            "n_pages": len(pages), "n_crops": n_crops,
            "n_marked": len(marks), "by_status": by_status, "by_kind": by_kind,
            "voices": [d.id for d in spec.voices()],
            "merge": merge if conf else None,
            "n_merged": sum(merge.values()) if conf else 0,
            "glossary_n": len(spec.glossary),
        }


def registry(ws: Workspace | None = None) -> Registry:
    """Реєстр наборів цього простору."""
    w = ws if ws is not None else workspace()
    return Registry(L.train_root(w), htr_reports=w.htr_reports)
