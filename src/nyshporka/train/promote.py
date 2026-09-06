"""🏆 Просування ваг у бойові: копія, картка, `PRODUCTION.json`.

Бойову модель називає дослідник, а не «найновіша за іменем»: у дослідницькому
конвеєрі бойовою двічі лишалась не остання версія, бо пізніші програвали на
holdout. Тому просування вимагає `select.json` (нуль без знаменника — не
результат) і `why` з цифрами, а виняток — лише явний `--force`.

Ваги лягають у ту саму теку, яку читає `htr/run.model_dirs`
(`data/spotter/models`), ім'я — за глобом рушія (`pysar_*.pt`) і з хвостом
`_vN`; поруч — картка `<ім'я>.json` з походженням і ліцензією: базові ваги
йдуть на умовах ShareAlike, і похідні поширюються на тих самих умовах.
"""
from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import corpus as C
from nyshporka.train import layout as L
from nyshporka.train import select as SEL
from nyshporka.train import state as ST
from nyshporka.utils.atomic import read_json, write_json

NAME_RE = re.compile(r"^pysar_[\w\-]*_v(\d+)[a-z]*\.pt$")
LICENSE = "CC BY-SA 4.0"


class PromoteError(ValueError):
    """Немає заміру, імені або чекпойнта."""


def _ckpt_for(st: ST.RunState, epoch: int | None, label: str, ws: Workspace) -> tuple[str, Path]:
    out = st.out_dir(ws)
    if epoch is not None:
        p = out / f"parseq_ep{epoch:02d}.pt"
        return f"ep{epoch:02d}", p
    if label == "best" or not label:
        return "best", out / "parseq_best.pt"
    m = re.match(r"^ep(\d+)$", label)
    if m:
        return label, out / f"parseq_ep{int(m.group(1)):02d}.pt"
    return label, out / label


def promote(run_id: str, *, as_name: str, why: str, epoch: int | None = None,
            label: str = "", force: bool = False, script: str = "cyrillic",
            ws: Workspace | None = None) -> dict[str, Any]:
    w = ws if ws is not None else workspace()
    if not NAME_RE.match(as_name):
        raise PromoteError(f"ім'я «{as_name}» не пройде вибір моделі: потрібно "
                           f"`pysar_<що>_v<N>.pt`, напр. pysar_cyr_v18.pt")
    if not why.strip():
        raise PromoteError("--why обов'язковий: чим ця модель краща і на чому це виміряно")
    st = ST.load(run_id, w)
    sel = SEL.load_select(run_id, w)
    if sel is None and not force:
        raise PromoteError("для цього прогону немає select.json — спершу `nysh train eval`, "
                           "або --force, якщо просуваєте свідомо без заміру")
    lbl, ckpt = _ckpt_for(st, epoch, label or (sel or {}).get("winner_recall", ""), w)
    if not ckpt.is_file():
        raise PromoteError(f"чекпойнта немає: {ckpt}")
    dest_dir = L.models_root(w)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / as_name
    if dest.exists() and not force:
        raise PromoteError(f"{dest} уже існує — інше ім'я або --force")
    shutil.copy2(ckpt, dest)

    corpus_name = str(st.corpus.get("name") or "")
    try:
        man = C.load_manifest(corpus_name, w) if corpus_name else {}
    except C.CorpusError:
        man = {}
    base = str(((man.get("recipe") or {}).get("train") or {}).get("pretrained")
               or st.compute.get("pretrained") or "")
    card = {
        "name": as_name, "engine": "parseq", "script": script, "run_id": run_id,
        "checkpoint": lbl, "corpus": {"name": corpus_name, "sha256": st.corpus.get("sha256", "")},
        "recipe": st.recipe, "base": base, "derived_from": base,
        "eval": None if sel is None else {
            "sets": sel.get("sets"), "micro": (sel.get("micro") or {}).get(lbl),
            "macro": (sel.get("macro") or {}).get(lbl), "thresh": sel.get("thresh"),
            "winner_recall": sel.get("winner_recall")},
        "why": why.strip(), "license": LICENSE, "forced": bool(force and sel is None),
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_json(dest_dir / (as_name[:-3] + ".json"), card)

    prod_path = dest_dir / "PRODUCTION.json"
    prod = read_json(prod_path, default=None)
    if not isinstance(prod, dict):
        prod = {"_comment": "Бойові ваги за письмом; читає nyshporka.htr.run.production_choice",
                "production": {}}
    prod.setdefault("production", {})
    row = prod["production"].get(script)
    prev: list[dict[str, Any]] = []
    if isinstance(row, dict):
        prev = list(row.get("_previous") or [])
        if row.get("model") and row["model"] != as_name:
            prev.insert(0, {"model": row["model"], "why": row.get("why", ""),
                            "until": card["created"]})
    elif isinstance(row, str) and row and row != as_name:
        prev.insert(0, {"model": row, "until": card["created"]})
    prod["production"][script] = {"model": as_name, "why": why.strip(), "since": card["created"],
                                  "run_id": run_id, "checkpoint": lbl, "_previous": prev[:10]}
    write_json(prod_path, prod)
    st.set_phase("promoted", f"{as_name} ← {lbl}").save(w)
    return {"model": str(dest), "card": card, "production": str(prod_path),
            "previous": prev[:1]}
