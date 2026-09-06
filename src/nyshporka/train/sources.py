"""🗂 Джерела корпусу: свої мітки, злиття арбітрів, зовнішні корпуси.

Кожен рідер віддає `[(шлях_кропа, текст)]` — форма одна, і на неї спираються
дедуплікація, ім'я кропа в корпусі й запис. Що ще рідер знає про рядок (вага
за впевненістю, чи повертати кроп), він кладе у власні поля звіту, а не міняє
форму кортежу.

🔴 Holdout виключається ОДНАКОВО для ручних міток і злиття: псевдо-мітка не
робить кроп «небаченим» — модель зазубрює саме зображення, і CER на
вимірювачі падає нечесно. Роль набору (`train|holdout`) читається з `set.json`.
"""
from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nyshporka.core.workspace import Workspace, WorkspaceError, workspace
from nyshporka.train import layout as L
from nyshporka.train import sets as S
from nyshporka.train.recipes import PseudoOpts
from nyshporka.train.text import is_babble, strip_conflict_marks, unify_i

BUILTIN = ("gt", "pseudo")


class SourceError(ValueError):
    """Опис джерела не читається або формат невідомий."""


@dataclass
class SourceSpec:
    id: str
    kind: str
    path: Path | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    unify_i: bool = False
    rotate_tall: bool = False
    reject: dict[str, Any] = field(default_factory=dict)


@dataclass
class Items:
    """Результат рідера: рядки, вага, повороти, звіт."""

    rows: list[tuple[Path, str]] = field(default_factory=list)
    weight: dict[str, float] = field(default_factory=dict)      # str(path) → вага
    rotate: set[str] = field(default_factory=set)               # str(path) → +90°
    kept: dict[str, list[list[Any]]] = field(default_factory=dict)  # набір → [[page, idx, text]]
    notes: list[str] = field(default_factory=list)


def _is_cyrillic(t: str) -> bool:
    cyr = sum(1 for c in t if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in t if c.isascii() and c.isalpha())
    return cyr > lat


# ── опис джерел простору ─────────────────────────────────────────────────────
def load_sources(ws: Workspace | None = None) -> dict[str, SourceSpec]:
    """`config/train/sources.yaml` простору; відсутній файл — порожньо, не помилка."""
    try:
        w = ws if ws is not None else workspace()
    except WorkspaceError:
        return {}
    f = L.config_root(w) / "sources.yaml"
    if not f.is_file():
        return {}
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SourceError(f"{f}: {exc}") from None
    out: dict[str, SourceSpec] = {}
    for sid, body in (raw.get("sources") or {}).items():
        if not isinstance(body, dict) or not body.get("kind"):
            raise SourceError(f"{f}: джерело «{sid}» без kind")
        if str(sid) in BUILTIN:
            raise SourceError(f"{f}: ім'я «{sid}» зарезервоване за вбудованим джерелом")
        path = body.get("path")
        p = Path(str(path)).expanduser() if path else None
        if p is not None and not p.is_absolute():
            p = (w.root / p).resolve()
        out[str(sid)] = SourceSpec(
            id=str(sid), kind=str(body["kind"]), path=p,
            files=[x if isinstance(x, dict) else {"file": str(x)} for x in (body.get("files") or [])],
            unify_i=bool(body.get("unify_i", False)),
            rotate_tall=bool(body.get("rotate_tall", False)),
            reject=dict(body.get("reject") or {}))
    return out


def _reject_set(spec: SourceSpec) -> tuple[set[str], str]:
    """Відсіяні рядки з JSON `{"reject": {...}}`; ключ — шлях або ім'я в корпусі."""
    rj = spec.reject
    if not rj or not rj.get("path"):
        return set(), "path"
    p = Path(str(rj["path"]))
    if not p.is_file():
        return set(), str(rj.get("key") or "path")
    try:
        got = json.loads(p.read_text(encoding="utf-8")).get("reject") or {}
    except (OSError, ValueError):
        return set(), "path"
    return {str(k) for k in got}, str(rj.get("key") or "path")


# ── зовнішні рідери ──────────────────────────────────────────────────────────
def read_manifest(spec: SourceSpec) -> Items:
    it = Items()
    if spec.path is None or not spec.path.is_dir():
        return it
    names = [str(f.get("file")) for f in spec.files] or ["gt_train.txt", "gt_val.txt"]
    rej, key = _reject_set(spec)
    dropped = 0
    for name in names:
        f = spec.path / name
        if not f.is_file():
            continue
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if "\t" not in ln:
                continue
            rel, txt = ln.split("\t", 1)
            p = spec.path / rel
            if not (p.is_file() and txt.strip()):
                continue
            if key == "path" and str(p) in rej:
                dropped += 1
                continue
            it.rows.append((p, txt))
    if dropped:
        it.notes.append(f"відсіяно за списком: {dropped}")
    return it


def read_tsv(spec: SourceSpec) -> Items:
    it = Items()
    if spec.path is None or not spec.path.is_dir():
        return it
    for f in spec.files:
        tsv = spec.path / str(f.get("file"))
        if not tsv.is_file():
            continue
        imgdir = spec.path / str(f.get("image_dir") or "")
        header = bool(f.get("header", False))
        for i, ln in enumerate(tsv.read_text(encoding="utf-8", errors="replace").splitlines()):
            if (header and i == 0) or "\t" not in ln:
                continue
            name, txt = ln.split("\t", 1)
            p = imgdir / name
            if p.is_file() and txt.strip():
                it.rows.append((p, txt))
    return it


def read_peter(spec: SourceSpec) -> Items:
    """Розкладка Digital Peter: `<розділ>/images/*.jpg` + `<розділ>/words/*.txt`.

    🔴 Частина кропів лежить боком (висота > ширини); збірник ресайзить до
    висоти зі збереженням пропорцій, і такий кроп стає смужкою у 2–8 пікселів
    при мітці на 46 символів — градієнт іде в нікуди на кожному кадрі.
    Лікується поворотом на +90°, і це виміряно (CER 1.00 → 0.03–0.27).
    """
    it = Items()
    if spec.path is None or not spec.path.is_dir():
        return it
    rotated = 0
    for imgdir in sorted(spec.path.rglob("images")):
        worddir = imgdir.parent / "words"
        if not worddir.is_dir():
            continue
        for img in sorted(imgdir.iterdir()):
            if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            w = worddir / f"{img.stem}.txt"
            if not w.is_file():
                continue
            txt = w.read_text(encoding="utf-8", errors="replace")
            if not txt.strip():
                continue
            if spec.rotate_tall:
                try:
                    from PIL import Image

                    with Image.open(img) as im:
                        tall = im.height > im.width
                except Exception:
                    tall = False
                if tall:
                    rotated += 1
                    it.rotate.add(str(img))
            it.rows.append((img, txt))
    if rotated:
        it.notes.append(f"кропів на боці повернуто на +90°: {rotated}")
    return it


# ── вбудовані джерела простору ───────────────────────────────────────────────
def read_gt(reg: S.Registry, *, include_unsure: bool = False,
            script: str = "cyrillic") -> Items:
    """Ручні мітки наборів із роллю `train`, статус `ok` (і `unsure` за бажанням)."""
    it = Items()
    missing: collections.Counter[str] = collections.Counter()
    for name in reg.names(hidden=True):
        try:
            spec = reg.load(name)
        except S.SetError as exc:
            it.notes.append(f"{name}: {exc}")
            continue
        if spec.role != "train" or (script and spec.script != script):
            continue
        for (page, idx), rec in reg.marks(name).items():
            status = str(rec.get("status") or "")
            text = str(rec.get("text") or "").strip()
            if status == "skip" or not text:
                continue
            if status != "ok" and not include_unsure:
                continue
            if script == "cyrillic" and not _is_cyrillic(text):
                continue
            p = reg.crop_path(spec, page, idx)
            if p is None:
                missing[name] += 1
                continue
            it.rows.append((p, text))
    if missing:
        it.notes.append("кропів немає на диску: "
                        + ", ".join(f"{k}×{v}" for k, v in sorted(missing.items()))
                        + " — перерізати з прогону (nysh train cut)")
    return it


def read_pseudo(reg: S.Registry, opts: PseudoOpts, *, manual: set[str],
                script: str = "cyrillic") -> Items:
    """Злиття арбітрів як мітки для дистиляції — з чотирма запобіжниками.

    1. Holdout виключається так само, як ручні мітки (роль набору).
    2. `low` не береться: це рядки, які арбітр сам визнав здогадом.
    3. Рядки з РУЧНОЮ міткою виключаються: той самий кроп із двома різними
       мітками вчить модель на суперечності.
    4. Однаковий текст не береться понад стелю — інакше корпус набивається
       ДРУКОВАНИМИ шапками формуляра. Стеля роздільна: друк (текст із
       `print_spread` і більше різних наборів) — `max_repeat`, рука —
       `hand_repeat`: підпис священника рукою — цінна річ, а не повтор.
    Плюс белькіт рушія відсівається ЗАВЖДИ, незалежно від conf: пониження
    до `low` робить людина або ворота, і обидва можна не запустити.
    """
    it = Items()
    specs: list[S.SetSpec] = []
    for name in reg.names(hidden=True):
        try:
            spec = reg.load(name)
        except S.SetError:
            continue
        if spec.role != "train" or (script and spec.script != script) or spec.merge() is None:
            continue
        specs.append(spec)
    # передпрохід: у скількох різних наборах трапляється кожен текст
    spread: dict[str, set[str]] = {}
    for spec in specs:
        m = spec.merge()
        assert m is not None
        for page in reg.crop_pages(spec):
            for line in reg.draft_lines(spec, m, page) or []:
                line = strip_conflict_marks(line).strip()
                if line:
                    spread.setdefault(" ".join(line.lower().split()), set()).add(spec.name)
    repeats: collections.Counter[str] = collections.Counter()
    dropped_rep = dropped_babble = 0
    weighted: collections.Counter[str] = collections.Counter()
    for spec in specs:
        m = spec.merge()
        assert m is not None
        conf_all = reg.merge_conf(spec)
        took = 0
        kept: list[list[Any]] = []
        for page in sorted(reg.crop_pages(spec)):
            conf = conf_all.get(page, {})
            for idx, line in enumerate(reg.draft_lines(spec, m, page) or []):
                line = strip_conflict_marks(line).strip()
                level = conf.get(str(idx), "")
                if not line or level in opts.drop_conf:
                    continue
                if is_babble(line):
                    dropped_babble += 1
                    continue
                p = reg.crop_path(spec, page, idx)
                if p is None or str(p) in manual:
                    continue
                if script == "cyrillic" and not _is_cyrillic(line):
                    continue
                key = " ".join(line.lower().split())
                repeats[key] += 1
                cap = opts.max_repeat if len(spread.get(key, ())) >= opts.print_spread \
                    else opts.hand_repeat
                if cap and repeats[key] > cap:
                    dropped_rep += 1
                    continue
                it.rows.append((p, line))
                w = float(opts.conf_weight.get(level, 1.0))
                if w != 1.0:
                    it.weight[str(p)] = w
                    weighted[level] += 1
                kept.append([page, idx, line])
                took += 1
        if took:
            it.kept[spec.name] = kept
            it.notes.append(f"{spec.name}: {took} рядків злиття")
    if dropped_rep:
        it.notes.append(f"відсіяно повторів: {dropped_rep} (друк понад ×{opts.max_repeat}, "
                        f"рука понад ×{opts.hand_repeat})")
    if dropped_babble:
        it.notes.append(f"відсіяно белькоту рушія: {dropped_babble}")
    for lvl, n in sorted(weighted.items()):
        it.notes.append(f"вага ×{opts.conf_weight[lvl]} на conf={lvl}: {n} рядків")
    return it


READERS = {"manifest": read_manifest, "tsv": read_tsv, "peter": read_peter}


def read_external(spec: SourceSpec) -> Items:
    fn = READERS.get(spec.kind)
    if fn is None:
        raise SourceError(f"джерело «{spec.id}»: невідомий kind «{spec.kind}» "
                          f"(є: {', '.join(sorted(READERS))})")
    it = fn(spec)
    if spec.unify_i:
        it.rows = [(p, unify_i(t)) for p, t in it.rows]
    rej, key = _reject_set(spec)
    if rej and key == "relname":
        it.notes.append("відсів за іменем у корпусі застосує збірник")
    return it
