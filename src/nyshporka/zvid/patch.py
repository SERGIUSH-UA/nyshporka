"""Доповнення пакета Зводу: новий голос чи підказка до вже нарізаного пакета.

Пакет не перепаковується ніколи: кропи, сторінки, рамки, видання лишаються як
були, а нове — текст на кілька КБ на сторінку — їде окремим `<id>.r<N>.zvidpatch`.
Так новий голос моделі доходить і до пакета в черзі, і до пакета, який
помічник уже зводить: зведене не чіпається, бо відповіді лежать окремо від
завдань і прив'язані до id рядка, а не до тексту завдання.

🔴 Доповнення прив'язане до рамок, як і сам пакет: застосовується лише там,
де відбиток рамок набору збігається з тим, з якого пакувалось. Інакше рядок
голосу ліг би під чужий кроп.

🔴 Голос моделі, натренованої на мітках саме цих сторінок, на них не
незалежний (`label-lines`, «Голоси мусять бути співмірні…»): він повторює
власні мітки. Доповнення цього не перевіряє — вирішує власник.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import sets as S
from nyshporka.train import tasks as T
from nyshporka.utils.atomic import read_json, write_json
from nyshporka.zvid import common as C

PATCH_FORMAT = "zvid-patch"
PATCH_SUFFIX = ".zvidpatch"
PATCH_FILE = "patch.json"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PatchReport:
    pack: str
    rev: int
    file: Path
    voices: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    sets: int = 0
    bytes: int = 0
    warnings: list[str] = field(default_factory=list)


# ── власник ─────────────────────────────────────────────────────────────────
def build(pack_id: str, *, voices: list[str], hints: list[str] | None = None,
          out: Path, note: str = "", ws: Workspace | None = None,
          skip_control: bool = False) -> PatchReport:
    """Нові голоси й підказки з наборів власника → доповнення пакета.

    Голос спершу додається до наборів звичайним шляхом (`nysh train voices`
    чи інфер по кропах); тут він лише збирається для пакета.

    `skip_control` — голоси не йдуть на контрольні набори пакета. Потрібно,
    коли модель училась на контрольних сторінках (вони звірені, тож лежать у
    корпусі): її голос там майже дослівно мітка, і CER контрольної перестав би
    міряти помічника. Підказки (`hints`) ідуть усім наборам, як і раніше.
    """
    from nyshporka.zvid import owner

    hints = [h for h in (hints or []) if h]
    voices = [v for v in voices if v]
    if not voices and not hints:
        raise C.ZvidError("нема що доповнювати: назвіть --voices чи --hints")
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    if not C.valid_id(pack_id):
        raise C.ZvidError(f"неприпустимий id пакета: {pack_id!r}")
    ledger_path = owner.ledger_dir(w) / f"{pack_id}.json"
    ledger = read_json(ledger_path, default=None)
    if not isinstance(ledger, dict):
        raise C.ZvidError(f"пакета {pack_id} немає в книзі пакетів цього простору")
    rev = 2 + len(ledger.get("patches") or [])
    control = set(ledger.get("control") or [])
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pack_id}.r{rev}{PATCH_SUFFIX}"
    rep = PatchReport(pack=pack_id, rev=rev, file=path, voices=voices, hints=hints)
    items: list[dict[str, Any]] = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for alias, name in sorted((ledger.get("map") or {}).items()):
            spec = reg.load(name)
            pages = sorted(reg.crop_pages(spec))
            frames = C.frames_sha(reg.cut_meta(spec), pages)
            if frames != (ledger.get("frames") or {}).get(alias):
                raise C.ZvidError(f"{name}: рамки змінились після пакування — доповнення "
                                  "лягло б на чужі кропи; потрібен новий пакет")
            by_id = {d.id: d for d in spec.voices()}
            item: dict[str, Any] = {"set": alias, "frames": frames, "voices": [], "hints": []}
            for vid in ([] if skip_control and alias in control else voices):
                d = by_id.get(vid)
                if d is None:
                    raise C.ZvidError(f"у наборі {name} немає голосу {vid} — спершу додайте "
                                      "його до наборів (nysh train voices / інфер по кропах)")
                for pg in pages:
                    lines = reg.draft_lines(spec, d, pg)
                    if lines is not None:
                        zf.writestr(f"sets/{alias}/{S.DRAFTS_DIR}/{vid}/{pg}.txt",
                                    "\n".join(lines) + "\n")
                item["voices"].append(vid)
            src_by_id = {h.id: h for h in spec.hint_sources}
            for hid in hints:
                src = src_by_id.get(hid)
                if src is None:
                    raise C.ZvidError(f"у наборі {name} немає джерела {hid}")
                data = reg.hint_data(spec, src)
                own = {k: v for k, v in data.items()
                       if (k.rpartition(":")[0] if src.level == "line" else k) in pages}
                fname = f"{S.HINTS_DIR}/{src.id}.json"
                zf.writestr(f"sets/{alias}/{fname}", json.dumps(own, ensure_ascii=False))
                item["hints"].append({**src.as_dict(), "file": fname})
            items.append(item)
        zf.writestr(PATCH_FILE, json.dumps({
            "format": PATCH_FORMAT, "version": 1, "pack": pack_id, "rev": rev,
            "created": _now(), "note": note, "items": items}, ensure_ascii=False, indent=1))
    rep.sets, rep.bytes = len(items), path.stat().st_size
    ledger.setdefault("patches", []).append({"rev": rev, "file": str(path), "voices": voices,
                                             "hints": hints, "at": _now(), "note": note,
                                             **({"skip_control": True} if skip_control else {})})
    write_json(ledger_path, ledger)
    return rep


# ── помічник ────────────────────────────────────────────────────────────────
@dataclass
class ApplyReport:
    pack: str
    rev: int
    skipped: bool = False
    voices: list[str] = field(default_factory=list)
    tasks: list[Path] = field(default_factory=list)


def read_patch(path: Path) -> dict[str, Any]:
    with C.open_zip(path) as zf:
        meta = C.read_json_member(zf, PATCH_FILE)
    if meta.get("format") != PATCH_FORMAT:
        raise C.ZvidError(f"{path.name} — не доповнення Зводу")
    if int(meta.get("version") or 0) > 1:
        raise C.ZvidError("доповнення новішого формату — онови Нишпорку: nysh update")
    if not C.valid_id(str(meta.get("pack") or "")):
        raise C.ZvidError("у доповненні неприпустимий id пакета")
    return meta


def apply(path: Path, *, base: Path | None = None) -> ApplyReport:
    """Доповнення → пісочниця взятого пакета; завдання перебудовуються, відповіді — ні."""
    from nyshporka.zvid import helper

    meta = read_patch(path)
    pack_id, rev = str(meta["pack"]), int(meta.get("rev") or 0)
    root = helper.root_of(pack_id, base)
    state = read_json(root / C.STATE, default=None)
    if not isinstance(state, dict):
        raise C.ZvidError(f"пакет {pack_id} не взято — спершу nysh zvid take")
    rep = ApplyReport(pack=pack_id, rev=rev)
    if rev in (state.get("patches") or []):
        rep.skipped = True
        return rep
    frames = {s["name"]: s["frames"] for s in state.get("sets") or []}
    ws = helper.sandbox(root)
    reg = S.registry(ws)
    for item in meta.get("items") or []:
        a = str(item.get("set") or "")
        if not C.valid_alias(a) or frames.get(a) != item.get("frames"):
            raise C.ZvidError(f"доповнення r{rev}: набір {a} не той, що в пакеті (інші рамки)")
    with C.open_zip(path) as zf:
        for info in zf.infolist():
            p = C.member_path(info.filename)
            if info.is_dir() or p.parts[0] != "sets":
                continue
            if len(p.parts) < 4 or not C.valid_alias(p.parts[1]):
                raise C.ZvidError(f"у доповненні чужий шлях: {info.filename}")
            dst = reg.set_dir(p.parts[1]) / Path(*p.parts[2:])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(zf.read(info))
    for item in meta.get("items") or []:
        spec = reg.load(item["set"])
        have = {d.id for d in spec.drafts}
        for vid in item.get("voices") or []:
            if vid not in have:
                spec.drafts.append(S.Draft(id=vid, dir=f"{S.DRAFTS_DIR}/{vid}"))
                rep.voices.append(vid)
        for h in item.get("hints") or []:
            src = S.HintSource.from_dict(h)
            spec.hint_sources = [x for x in spec.hint_sources if x.id != src.id] + [src]
        reg.save(spec)
    # Завдання — наново тим самим кодом, що й при take: новий голос стає
    # рядком у кожному завданні. Відповіді (`*.answer.json`) лежать окремо й
    # ключовані id рядка — їх перебудова не зачіпає.
    for s in state.get("sets") or []:
        got = T.export_tasks(str(s["name"]), pages_per_file=int(state.get("pages_per_file") or 1),
                             out=root / C.TASKS, ws=ws,
                             procedure=str(state.get("procedure") or "arbiter"),
                             next_cmd=f"nysh zvid give {pack_id} --model <модель>")
        rep.tasks += got.files
    state.setdefault("patches", []).append(rev)
    write_json(root / C.STATE, state)
    rep.voices = sorted(set(rep.voices))
    return rep
