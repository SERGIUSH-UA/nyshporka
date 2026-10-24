"""Бік власника: спакувати набори в `.zvid` і прийняти `.answer.zvid` назад.

Книга пакетів — `data/train/zvid/<id>.json`: яке безлике ім'я (`zv-03`) якому
набору відповідає, яка сторінка контрольна, з яких рамок пакувалось. Вона не
їде в пакет: помічник не має знати, де контрольна сторінка, інакше вона нічого
не міряє.
"""
from __future__ import annotations

import io
import json
import random
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import layout as L
from nyshporka.train import sets as S
from nyshporka.train import tasks as T
from nyshporka.utils.atomic import read_json, write_json
from nyshporka.zvid import common as C

#: Якість JPEG у пакеті. Кроп у наборі — PNG, 6 МБ на сторінку; сірий JPEG 92
#: оку арбітра не відрізнити, а пакет на 13 сторінок стає з ~80 МБ ~15 МБ.
#: Ворота й ширина чорнила рахуються на боці власника з його PNG.
CROP_Q = 92
PAGE_Q = 85


def ledger_dir(ws: Workspace | None = None) -> Path:
    return L.train_root(ws) / "zvid"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jpeg(im: Any, q: int) -> bytes:
    buf = io.BytesIO()
    im.convert("L").save(buf, "JPEG", quality=q, optimize=True)
    return buf.getvalue()


@dataclass
class PackReport:
    id: str
    file: Path
    ledger: Path
    sets: dict[str, str] = field(default_factory=dict)
    control: list[str] = field(default_factory=list)
    pages: int = 0
    crops: int = 0
    bytes: int = 0
    warnings: list[str] = field(default_factory=list)


def _page_image(spec: S.SetSpec, cut_page: dict[str, Any], page: str) -> Any:
    from nyshporka.htr import view as V
    from nyshporka.train.cut import page_image

    return page_image(spec.source_run, cut_page, page, V._page_image)


def build(sets: list[str], *, out: Path, procedure: str = "arbiter",
          context: Path | None = None, control: list[str] | None = None,
          pages_per_file: int = 1, note: str = "", ws: Workspace | None = None,
          image_of: Any = None) -> PackReport:
    """Спакувати набори (і контрольні) в один `.zvid`."""
    if procedure not in T.PROCEDURES:
        raise C.ZvidError(f"процедура «{procedure}» невідома: {' | '.join(T.PROCEDURES)}")
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    control = [c for c in (control or []) if c]
    names = [n for n in sets if n]
    if not names:
        raise C.ZvidError("не названо жодного набору")
    if set(names) & set(control):
        raise C.ZvidError(f"набір і робочий, і контрольний: {', '.join(set(names) & set(control))}")
    specs: dict[str, S.SetSpec] = {}
    for n in [*names, *control]:
        spec = reg.load(n)
        if spec.private:
            raise C.ZvidError(f"набір «{n}» позначено private (замовлення, дані клієнта) — "
                              "за межі цієї машини він не йде")
        if len(spec.voices()) < 2:
            raise C.ZvidError(f"набору «{n}» потрібні щонайменше два голоси — "
                              "`nysh train voices`")
        if not reg.crop_pages(spec):
            raise C.ZvidError(f"у наборі «{n}» немає кропів на диску")
        specs[n] = spec
    for n in control:
        if not reg.merge_conf(specs[n]) and not reg.marks(n):
            raise C.ZvidError(f"контрольний «{n}» не має ні злиття, ні ручних міток — "
                              "нема з чим порівнювати")

    pack_id = f"zv{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(3)}"
    # 🔴 Порядок перемішано: контрольна, покладена останньою, впізнавалась би.
    order = [*names, *control]
    random.Random(pack_id).shuffle(order)
    alias = {n: f"zv-{i:02d}" for i, n in enumerate(order, 1)}

    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pack_id}{C.SUFFIX}"
    rep = PackReport(id=pack_id, file=path, ledger=ledger_dir(w) / f"{pack_id}.json",
                     sets={alias[n]: n for n in order},
                     control=sorted(alias[n] for n in control))
    get_image = image_of or _page_image
    m_sets: list[dict[str, Any]] = []
    voices: set[str] = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in order:
            spec, a = specs[n], alias[n]
            pages = sorted(reg.crop_pages(spec))
            cut = reg.cut_meta(spec)
            new_cut = {**cut, "source_run": "", "pages": {}}
            for pg in pages:
                pm = dict((cut.get("pages") or {}).get(pg) or {})
                try:
                    im = get_image(spec, pm, pg)
                    zf.writestr(f"{C.PAGES}/{a}/{pg}.jpg", _jpeg(im, PAGE_Q))
                    pm.update(src=f"{C.PAGES}/{a}/{pg}.jpg", orient=0,
                              size=[im.width, im.height])
                    pm.pop("key", None)
                except Exception as exc:
                    # Без сторінки зведення можливе (кропи є), але без
                    # контексту: це має бачити власник до відправки.
                    rep.warnings.append(f"{n} {pg}: сторінки в пакеті не буде — {exc}")
                new_cut["pages"][pg] = pm
                crop_dir = reg.crops_of(spec) / pg
                for f in sorted(crop_dir.glob("line_*.png")):
                    from PIL import Image

                    with Image.open(f) as im:
                        zf.writestr(f"crops/{a}/{pg}/{f.stem}.jpg", _jpeg(im, CROP_Q))
                    rep.crops += 1
                rep.pages += 1
            zf.writestr(f"crops/{a}/{S.CUT_META_FILE}",
                        json.dumps(new_cut, ensure_ascii=False))
            drafts: list[S.Draft] = []
            for d in spec.voices():
                voices.add(d.id)
                for pg in pages:
                    lines = reg.draft_lines(spec, d, pg)
                    if lines is not None:
                        zf.writestr(f"sets/{a}/{S.DRAFTS_DIR}/{d.id}/{pg}.txt",
                                    "\n".join(lines) + "\n")
                drafts.append(S.Draft(id=d.id, dir=f"{S.DRAFTS_DIR}/{d.id}"))
            sources: list[S.HintSource] = []
            for src in spec.hint_sources:
                data = reg.hint_data(spec, src)
                own = {k: v for k, v in data.items()
                       if (k.rpartition(":")[0] if src.level == "line" else k) in pages}
                fname = f"{S.HINTS_DIR}/{src.id}.json"
                zf.writestr(f"sets/{a}/{fname}", json.dumps(own, ensure_ascii=False, indent=1))
                sources.append(S.HintSource.from_dict({**src.as_dict(), "file": fname}))
            # Безликий опис: ні шифри набору, ні ролі, ні злиття. Справа й
            # назва лишаються — без них агент не знає, що читає.
            packed = S.SetSpec(name=a, title=spec.title, case=spec.case, script=spec.script,
                               domain=spec.domain, drafts=drafts, glossary=dict(spec.glossary),
                               skip_names=list(spec.skip_names), page_hints=spec.page_hints,
                               hint_sources=sources)
            zf.writestr(f"sets/{a}/{S.SET_FILE}",
                        json.dumps(packed.as_dict(), ensure_ascii=False, indent=1))
            m_sets.append({"name": a, "pages": pages,
                           "frames": C.frames_sha(cut, pages)})
        rules = T.CROP_RULES if procedure == "crop-read" else T.RULES
        from nyshporka import __version__

        manifest = {"format": C.FORMAT, "version": C.VERSION, "id": pack_id,
                    "created": _now(), "procedure": procedure,
                    "pages_per_file": max(1, pages_per_file),
                    "min_client": __version__, "rules": C.text_sha(rules),
                    "voices": sorted(voices),
                    "sets": sorted(m_sets, key=lambda s: s["name"]), "note": note}
        zf.writestr(C.MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
        if context is not None:
            zf.writestr(C.CONTEXT, context.read_text(encoding="utf-8"))
        else:
            rep.warnings.append("без context.md: агент не знатиме справи, руки й правопису")
    rep.bytes = path.stat().st_size
    write_json(rep.ledger, {"id": pack_id, "created": manifest["created"],
                            "procedure": procedure, "file": str(path), "map": rep.sets,
                            "control": rep.control,
                            "frames": {s["name"]: s["frames"] for s in m_sets},
                            "note": note, "returns": []})
    return rep


# ── приймання ────────────────────────────────────────────────────────────────
@dataclass
class CollectReport:
    id: str
    model: str = ""
    imported: dict[str, dict[str, Any]] = field(default_factory=dict)
    control: dict[str, dict[str, Any]] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _reference(reg: S.Registry, spec: S.SetSpec) -> dict[str, str]:
    """Еталон контрольної: ручна мітка `ok`, інакше злиття high/med."""
    ref: dict[str, str] = {}
    m = spec.merge()
    if m is not None:
        conf = reg.merge_conf(spec)
        for pg in reg.crop_pages(spec):
            lines = reg.draft_lines(spec, m, pg) or []
            for i, t in enumerate(lines):
                if t.strip() and conf.get(pg, {}).get(str(i)) in ("high", "med"):
                    ref[f"{pg}:{i}"] = t
    for (pg, i), rec in reg.marks(spec.name).items():
        if rec.get("status") == "ok" and str(rec.get("text") or "").strip():
            ref[f"{pg}:{i}"] = str(rec["text"])
    return ref


def collect(path: Path, *, ws: Workspace | None = None) -> CollectReport:
    """Прийняти відповідь помічника: робочі набори — у злиття, контрольні — у замір."""
    from nyshporka.train.metrics import measure

    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    with C.open_zip(path) as zf:
        meta = C.read_json_member(zf, C.META)
        pack_id = str(meta.get("id") or "")
        if not C.valid_id(pack_id):
            raise C.ZvidError(f"у відповіді неприпустимий id пакета: {pack_id!r}")
        ledger_path = ledger_dir(w) / f"{pack_id}.json"
        ledger = read_json(ledger_path, default=None)
        if not isinstance(ledger, dict):
            raise C.ZvidError(f"пакета {pack_id} немає в книзі пакетів цього простору "
                              f"({ledger_path}) — відповідь не на наш пакет")
        answers: dict[str, dict[str, bytes]] = {}
        for info in zf.infolist():
            p = C.member_path(info.filename)
            if len(p.parts) == 2 and p.parts[0] == "answers" and p.name.endswith(".answer.json"):
                a = p.name[: -len(".answer.json")].rsplit("_part", 1)[0]
                answers.setdefault(a, {})[p.name] = zf.read(info)
    rep = CollectReport(id=pack_id, model=str(meta.get("model") or ""))
    amap: dict[str, str] = ledger.get("map") or {}
    control = set(ledger.get("control") or [])
    for a, files in sorted(answers.items()):
        name = amap.get(a)
        if not name:
            rep.refused.append(f"{a}: такого набору в пакеті не було")
            continue
        spec = reg.load(name)
        pages = sorted(reg.crop_pages(spec))
        if C.frames_sha(reg.cut_meta(spec), pages) != (ledger.get("frames") or {}).get(a):
            rep.refused.append(f"{a} → {name}: рамки змінились після пакування — індекси "
                               "відповіді не лягають на кропи")
            continue
        if a in control:
            got: dict[str, str] = {}
            for raw in files.values():
                for k, v in T.parse_answer(raw.decode("utf-8", errors="replace")).items():
                    got[k] = str(v.get("m") or "")
            ref = _reference(reg, spec)
            pairs = [(ref[k], got[k]) for k in sorted(ref) if k in got]
            m = measure(pairs)
            rep.control[name] = {"alias": a, "lines": len(pairs), "of": len(ref),
                                 "cer": round(m.cer, 4), "wer": round(m.wer, 4)}
            continue
        dest = reg.set_dir(name) / T.TASKS_DIR / f"zvid-{pack_id}"
        dest.mkdir(parents=True, exist_ok=True)
        for fname, raw in files.items():
            (dest / fname.replace(a, name, 1)).write_bytes(raw)
        imp = T.import_answers(name, tasks_dir=dest, ws=w)
        rep.imported[name] = {"alias": a, "rows": imp.rows, "conf": imp.conf,
                              "suspects": sum(len(g.suspects) for g in imp.gates),
                              "rejected": len(imp.rejected)}
        rep.warnings += [f"{name}: {x}" for x in imp.warnings]
    ledger.setdefault("returns", []).append({
        "at": _now(), "file": str(path), "model": rep.model,
        "client": meta.get("client"), "agents": meta.get("agents"),
        "imported": {k: v["rows"] for k, v in rep.imported.items()},
        "control": rep.control, "refused": rep.refused})
    write_json(ledger_path, ledger)
    return rep
