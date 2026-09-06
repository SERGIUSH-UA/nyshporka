"""🧱 Збірник корпусу: джерела → рецепт → `images/` + `gt_train.txt` + tgz.

Один артефакт на всі шляхи обчислень: локальна карта, свій сервер і gpurunner
годуються тим самим `<корпус>.tgz`, у корені якого `gt_train.txt`,
`gt_val.txt`, `images/<джерело>/<хеш>.jpg` і `corpus.json`.

Три правила, куплені помилками попереднього конвеєра:

* **Ім'я кропа — від хеша шляху джерела**, не від позиції: порядкова нумерація
  ламається при найменшій зміні складу, і докачка мовчки роз'їжджає маніфест
  із картинками.
* **Дробова вага реалізується жеребом по імені**, а не `random`: два прогони з
  тим самим рецептом дають побайтово той самий `gt_train.txt`.
* **val — за квотою СИМВОЛІВ на джерело**, не за часткою: CER корпусний, вагу в
  ньому визначає довжина; спільна частка топить домен у зовнішньому корпусі, і
  модель оптимізується не під ті рукописи, які треба читати.

🔴 У tgz не має бути жодного `*.jsonl`: раннер трену читає будь-який `.jsonl`
під входом як маніфест. Маніфест збірки тому — `corpus.json`.
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
import tarfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import layout as L
from nyshporka.train import sets as S
from nyshporka.train import sources as SRC
from nyshporka.train.recipes import Recipe, resolve_reps
from nyshporka.utils.atomic import write_json

CORPUS_VERSION = 1
HIST = "ъѣѳѵыэiіїєґ"


class CorpusError(ValueError):
    """Немає джерел, рецепт не сходиться або тека зайнята."""


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).split())


def relname(src: str, p: Path) -> str:
    """`images/<джерело>/<blake2b-16>.jpg` — від хеша ШЛЯХУ, не позиції."""
    h = hashlib.blake2b(str(p).encode("utf-8"), digest_size=8).hexdigest()
    return f"images/{src}/{h}.jpg"


def copies(rep: int, weight: float, key: str) -> int:
    """Скільки разів рядок лягає в епоху; дробову частину розігрує жереб по імені."""
    n = rep * weight
    base = int(n)
    frac = n - base
    if frac > 1e-9:
        h = int(hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest(), 16)
        if (h % 1_000_000) / 1_000_000 < frac:
            base += 1
    return max(1, base)


@dataclass
class SourcePlan:
    id: str
    n_unique: int
    rep: int
    rows: int
    share_ordered: str
    share_actual: float
    hist: dict[str, int]
    notes: list[str] = field(default_factory=list)


@dataclass
class CorpusPlan:
    recipe: Recipe
    picked: dict[str, list[tuple[Path, str]]]
    weight: dict[str, float]
    rotate: set[str]
    kept: dict[str, list[list[Any]]]
    reps: dict[str, int]
    per_source: list[SourcePlan]
    total_rows: int
    holdout: list[str]
    sets_used: dict[str, dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"recipe": self.recipe.name, "total_rows": self.total_rows,
                "holdout": self.holdout,
                "sources": [{"id": s.id, "n_unique": s.n_unique, "rep": s.rep, "rows": s.rows,
                             "share_ordered": s.share_ordered,
                             "share_actual": round(s.share_actual, 4), "hist": s.hist,
                             "notes": s.notes} for s in self.per_source],
                "sets": self.sets_used}


def _sets_summary(reg: S.Registry) -> tuple[list[str], dict[str, dict[str, Any]]]:
    holdout: list[str] = []
    used: dict[str, dict[str, Any]] = {}
    for name in reg.names(hidden=True):
        try:
            spec = reg.load(name)
        except S.SetError:
            continue
        if spec.role == "holdout":
            holdout.append(name)
            continue
        marks = reg.marks_path(name)
        sha = hashlib.sha256(marks.read_bytes()).hexdigest() if marks.is_file() else ""
        n_ok = sum(1 for r in reg.marks(name).values() if r.get("status") == "ok")
        used[name] = {"sha256": sha, "n_ok": n_ok, "merge": spec.merge() is not None}
    return holdout, used


def plan(recipe: Recipe, *, only: list[str] | None = None, include_unsure: bool = False,
         seed: int = 42, ws: Workspace | None = None) -> CorpusPlan:
    """Що піде в корпус — без запису на диск. Те саме, що побачить `build`."""
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    ext = SRC.load_sources(w)
    want = set(only or recipe.mix)
    rng = random.Random(seed)
    picked: dict[str, list[tuple[Path, str]]] = {}
    weight: dict[str, float] = {}
    rotate: set[str] = set()
    kept: dict[str, list[list[Any]]] = {}
    notes: dict[str, list[str]] = {}
    warnings: list[str] = []
    manual: set[str] = set()

    for sid in recipe.mix:
        if sid not in want:
            continue
        if sid == "gt":
            it = SRC.read_gt(reg, include_unsure=include_unsure)
            manual = {str(p) for p, _ in SRC.read_gt(reg, include_unsure=True).rows}
        elif sid == "pseudo":
            if not manual:
                manual = {str(p) for p, _ in SRC.read_gt(reg, include_unsure=True).rows}
            it = SRC.read_pseudo(reg, recipe.pseudo, manual=manual)
            kept = it.kept
        else:
            spec = ext.get(sid)
            if spec is None:
                warnings.append(f"[{sid}] не описане в config/train/sources.yaml — пропущено")
                continue
            it = SRC.read_external(spec)
        notes[sid] = it.notes
        if not it.rows:
            warnings.append(f"[{sid}] 0 рядків — джерела нема на диску або воно порожнє")
            continue
        # 🔴 Дедуплікація за шляхом: мітки append-only, і повторна розмітка
        # того самого кропа лишає обидва записи; дублікат потрапляв би і в
        # val, і в train — витік, через який val перестає бути незалежним.
        dedup: dict[str, tuple[Path, str]] = {}
        for p, t in it.rows:
            dedup[str(p)] = (p, t)
        if len(dedup) != len(it.rows):
            notes[sid].append(f"дублікатів прибрано: {len(it.rows) - len(dedup)}")
        items = [(p, t) for p, t in dedup.values() if len(_norm(t)) >= 2]
        rng.shuffle(items)
        cap = recipe.mix[sid].cap
        if cap:
            items = items[:cap]
        picked[sid] = items
        weight.update(it.weight)
        rotate |= it.rotate
    if not picked:
        raise CorpusError("жодного джерела з рядками: перевірте набори (nysh train sets) "
                          "і config/train/sources.yaml")

    counts = {sid: len(items) for sid, items in picked.items()}
    reps, rep_warn = resolve_reps(recipe.mix, counts)
    warnings += rep_warn
    per: list[SourcePlan] = []
    total = 0
    rows_of: dict[str, int] = {}
    for sid, items in picked.items():
        n = 0
        for p, _ in items:
            n += copies(reps[sid], weight.get(str(p), 1.0), relname(sid, p))
        rows_of[sid] = n
        total += n
    for sid, items in picked.items():
        ch = "".join(t for _, t in items)
        hist = {c: ch.count(c) for c in "ъѣѳ"}
        m = recipe.mix[sid]
        per.append(SourcePlan(id=sid, n_unique=len(items), rep=reps[sid], rows=rows_of[sid],
                              share_ordered=m.share or f"×{m.rep}",
                              share_actual=rows_of[sid] / max(1, total), hist=hist,
                              notes=notes.get(sid, [])))
    holdout, used = _sets_summary(reg)
    if "gt" in picked and not holdout:
        warnings.append("жоден набір не має ролі holdout — епоху не буде чим обирати")
    return CorpusPlan(recipe=recipe, picked=picked, weight=weight, rotate=rotate, kept=kept,
                      reps=reps, per_source=per, total_rows=total, holdout=holdout,
                      sets_used=used, warnings=warnings)


@dataclass
class BuildReport:
    name: str
    out: Path
    tgz: Path
    rows_train: int
    rows_val: int
    val_by_source: dict[str, dict[str, int]]
    copied: int
    failed: int
    pruned: int
    sha256: str
    warnings: list[str] = field(default_factory=list)


def build(name: str, cp: CorpusPlan, *, seed: int = 42, prune: bool = False,
          workers: int = 8, ws: Workspace | None = None, force: bool = False) -> BuildReport:
    """Записати корпус за планом: кропи, маніфести, `corpus.json`, tgz."""
    from PIL import Image

    w = ws if ws is not None else workspace()
    if not L.valid_name(name):
        raise CorpusError(f"неприпустиме ім'я корпусу: {name!r}")
    out = L.corpora_root(w) / name
    tgz = L.corpora_root(w) / f"{name}.tgz"
    if tgz.is_file() and not force:
        raise CorpusError(f"корпус «{name}» уже зібраний ({tgz}); --force перезбирає")
    (out / "images").mkdir(parents=True, exist_ok=True)
    rec = cp.recipe
    rng = random.Random(seed)
    rotate = cp.rotate

    def _one(job: tuple[str, Path]) -> Any:
        src, p = job
        dst = out / relname(src, p)
        if dst.exists() and str(p) not in rotate:
            return None
        try:
            with Image.open(p) as raw:
                im = raw.convert("RGB")
                if str(p) in rotate:
                    im = im.rotate(90, expand=True)
                if im.height != rec.crop.height:
                    wdt = max(8, min(rec.crop.max_width,
                                     int(im.width * rec.crop.height / max(im.height, 1))))
                    im = im.resize((wdt, rec.crop.height), Image.Resampling.LANCZOS)
                dst.parent.mkdir(parents=True, exist_ok=True)
                im.save(dst, "JPEG", quality=90)
            return True
        except Exception as exc:
            return f"{p}: {type(exc).__name__}: {exc}"

    jobs = [(src, p) for src, items in cp.picked.items() for p, _ in items]
    copied = failed = 0
    fails: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for res in pool.map(_one, jobs):
            if res is True:
                copied += 1
            elif isinstance(res, str):
                failed += 1
                if len(fails) < 5:
                    fails.append(res)

    copies_of: dict[str, dict[str, int]] = {}
    for src, items in cp.picked.items():
        copies_of[src] = {relname(src, p): copies(cp.reps[src], cp.weight.get(str(p), 1.0),
                                                  relname(src, p)) for p, _ in items}

    # val за квотою символів; текст, який уже лежить у train іншим кропом, у val не йде.
    # 🔴 І не більше п'ятої частини рядків джерела: на малому власному наборі
    # квота в символах з'їдала ВСІ рядки, і train виходив порожнім — трен без
    # жодного прикладу з того письма, заради якого його запускали.
    val_pick: dict[str, set[str]] = {}
    train_texts: set[str] = set()
    val_capped: list[str] = []
    for src, items in cp.picked.items():
        keep: set[str] = set()
        chars = 0
        cap = rec.val.quota_chars.get(src, 0)
        max_rows = max(1, len(items) // 5) if cap else 0
        for p, txt in items:
            if chars >= cap:
                break
            if len(keep) >= max_rows:
                val_capped.append(src)
                break
            rel = relname(src, p)
            t = _norm(txt)
            if len(t) < rec.val.min_len or not (out / rel).is_file():
                continue
            keep.add(rel)
            chars += len(t)
        val_pick[src] = keep
        for p, txt in items:
            if relname(src, p) not in keep:
                train_texts.add(_norm(txt))
    train_rows: list[str] = []
    val_rows: list[str] = []
    for src, items in cp.picked.items():
        for p, txt in items:
            rel = relname(src, p)
            if not (out / rel).is_file():
                continue
            row = f"{rel}\t{_norm(txt)}"
            n = copies_of[src][rel]
            if rel in val_pick.get(src, ()) and _norm(txt) not in train_texts:
                val_rows.append(row)
            else:
                train_rows.extend([row] * n)
    rng.shuffle(train_rows)
    (out / "gt_train.txt").write_text("\n".join(train_rows) + "\n", encoding="utf-8")
    (out / "gt_val.txt").write_text("\n".join(val_rows) + "\n", encoding="utf-8")

    pruned = 0
    if prune:
        used = {r.split("\t", 1)[0] for r in train_rows + val_rows}
        for f in out.rglob("*.jpg"):
            rel = str(f.relative_to(out)).replace("\\", "/")
            if rel not in used:
                f.unlink()
                pruned += 1

    vs: dict[str, dict[str, int]] = {}
    for row in val_rows:
        rel, t = row.split("\t", 1)
        v = vs.setdefault(rel.split("/")[1], {"rows": 0, "chars": 0})
        v["rows"] += 1
        v["chars"] += len(t)
    manifest = {
        "version": CORPUS_VERSION, "name": name, "recipe": rec.model_dump(mode="json"),
        "seed": seed, "built": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": "nyshporka.train.corpus", "plan": cp.as_dict(),
        "rows_train": len(train_rows), "rows_val": len(val_rows), "val": {"by_source": vs},
        "kept": cp.kept,
    }
    write_json(out / "corpus.json", manifest)
    # 🔴 tgz — вміст у корені (так очікує раннер), і без жодного .jsonl усередині.
    with tarfile.open(tgz, "w:gz") as tf:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                if f.suffix == ".jsonl":
                    raise CorpusError(f"у корпусі опинився {f.name} — раннер прочитав би його "
                                      f"як маніфест")
                tf.add(f, arcname=str(f.relative_to(out)).replace("\\", "/"))
    sha = hashlib.sha256(tgz.read_bytes()).hexdigest()
    rep = BuildReport(name=name, out=out, tgz=tgz, rows_train=len(train_rows),
                      rows_val=len(val_rows), val_by_source=vs, copied=copied, failed=failed,
                      pruned=pruned, sha256=sha, warnings=list(cp.warnings))
    rep.warnings += fails
    if val_capped:
        rep.warnings.append(f"val обмежено п'ятою частиною рядків джерела ({', '.join(val_capped)}): "
                            f"квота символів більша за сам набір")
    if not val_rows:
        rep.warnings.append("val порожній — рання зупинка й вибір best у трені будуть сліпі; "
                            "додайте quota_chars для наявних джерел")
    return rep


def charset_of(cp: CorpusPlan) -> collections.Counter[str]:
    """Частоти літер з урахуванням кратності — стільки разів модель їх побачить."""
    allch: collections.Counter[str] = collections.Counter()
    for src, items in cp.picked.items():
        for p, t in items:
            k = copies(cp.reps[src], cp.weight.get(str(p), 1.0), relname(src, p))
            for ch, v in collections.Counter(t).items():
                allch[ch] += v * k
    return allch


def load_manifest(name: str, ws: Workspace | None = None) -> dict[str, Any]:
    w = ws if ws is not None else workspace()
    f = L.corpora_root(w) / name / "corpus.json"
    if not f.is_file():
        raise CorpusError(f"корпусу «{name}» немає: {f}")
    got = json.loads(f.read_text(encoding="utf-8"))
    if not isinstance(got, dict):
        raise CorpusError(f"{f}: не об'єкт")
    return got
