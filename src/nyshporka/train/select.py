"""🎯 Вибір епохи — по ВСЬОМУ holdout, а не за val трену.

`parseq_best.pt` обирається за val_cer, а val збірника — кілька сотень рядків
із ТИХ САМИХ справ, що й train: нової руки й нового фонду він за побудовою не
бачить, а міряє CER, тоді як критерій пошуку — recall власних назв. Тому
раннер кладе ваги кожної епохи, а вибір робиться тут: усі чекпойнти й чинна
бойова модель — одним прогоном по holdout-наборах, у одній таблиці.

Два правила:
1. **Усі моделі міряються одним прогоном.** Абсолютні числа з різних знімків
   holdout не зіставні — він росте, і recall тієї самої моделі повзе.
2. **Малий holdout бреше.** Набір із <60 рядків позначається ⚠, а micro
   (вага набору = його обсяг) показується поруч із macro.

Прогнози кешуються по (відбиток файла чекпойнта, набір): перерахувати
таблицю з іншим порогом — секунди, а не хвилини карти.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import metrics as M
from nyshporka.train import sets as S
from nyshporka.train import state as ST
from nyshporka.train.compute.local import engine_python
from nyshporka.utils.atomic import read_json, write_json

_EP = re.compile(r"parseq_ep(\d+)\.pt$")
INFER = Path(__file__).resolve().parent.parent / "htr" / "pysar_lines_infer.py"
GUEST = Path(__file__).resolve().parent / "guest" / "eval_runner.py"


class SelectError(ValueError):
    """Немає чекпойнтів, holdout або середовища рушіїв."""


def fingerprint(path: Path) -> str:
    st = path.stat()
    return hashlib.blake2b(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode(),
                           digest_size=5).hexdigest()


def collect_ckpts(out_dir: Path, models: list[str], also: list[Path]) -> list[tuple[str, Path]]:
    """[(мітка, шлях)]: епохи за номером, `best`, потім іменовані моделі."""
    out: list[tuple[str, Path]] = []
    if out_dir.is_dir():
        eps = []
        for p in out_dir.rglob("parseq_ep*.pt"):
            mt = _EP.search(p.name)
            if mt:
                eps.append((int(mt.group(1)), p))
        for n, p in sorted(eps):
            out.append((f"ep{n:02d}", p))
        best = next(iter(out_dir.rglob("parseq_best.pt")), None)
        if best is not None:
            out.append(("best", best))
    if models:
        from nyshporka.htr import run as R

        for m in models:
            found = None
            for d in R.model_dirs():
                for cand in (d / m, d / f"{m}.pt", d / f"pysar_cyr_{m}.pt"):
                    if cand.is_file():
                        found = cand
                        break
                if found:
                    break
            if found is None:
                raise SelectError(f"моделі «{m}» немає в теках моделей")
            out.append((found.stem, found))
    for p in also:
        if not p.is_file():
            raise SelectError(f"файла немає: {p}")
        out.append((p.stem, p))
    if not out:
        raise SelectError("жодного чекпойнта: у теці прогону немає parseq_ep*.pt, "
                          "і моделей не названо")
    return out


@dataclass
class HoldoutSet:
    name: str
    skip_names: list[str]
    crops: list[Path]
    texts: list[str]


def holdout_sets(reg: S.Registry, names: list[str] | None = None) -> list[HoldoutSet]:
    out: list[HoldoutSet] = []
    for name in reg.names(hidden=True):
        try:
            spec = reg.load(name)
        except S.SetError:
            continue
        if names:
            if name not in names:
                continue
        elif spec.role != "holdout":
            continue
        crops: list[Path] = []
        texts: list[str] = []
        for (page, idx), rec in sorted(reg.marks(name).items()):
            if rec.get("status") != "ok" or not str(rec.get("text") or "").strip():
                continue
            p = reg.crop_path(spec, page, idx)
            if p is None:
                continue
            crops.append(p)
            texts.append(str(rec["text"]))
        if crops:
            out.append(HoldoutSet(name=name, skip_names=list(spec.skip_names),
                                  crops=crops, texts=texts))
    return out


def _predict(py: Path, ckpt: Path, crops: list[Path], cache: Path, *, device: str,
             batch: int) -> list[str]:
    if cache.is_file():
        got = read_json(cache, default=None)
        if isinstance(got, dict) and len(got.get("preds") or []) == len(crops):
            return [str(x) for x in got["preds"]]
    jobs = cache.with_suffix(".jobs.json")
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text(json.dumps({"crops": [str(p) for p in crops]}, ensure_ascii=False),
                    encoding="utf-8")
    cmd = [str(py), str(GUEST), "--infer", str(INFER), "--ckpt", str(ckpt), "--jobs", str(jobs),
           "--out", str(cache), "--device", device, "--batch", str(batch)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if res.returncode != 0 or not cache.is_file():
        raise SelectError(f"інфер {ckpt.name} упав (rc={res.returncode}): "
                          f"{(res.stderr or res.stdout)[-600:]}")
    got = read_json(cache, default={})
    return [str(x) for x in (got.get("preds") or [])]


@dataclass
class SelectReport:
    run_id: str
    sets: list[str]
    labels: list[str]
    table: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    micro: dict[str, dict[str, float]] = field(default_factory=dict)
    macro: dict[str, dict[str, float]] = field(default_factory=dict)
    winner_recall: str = ""
    winner_cer: str = ""
    winner_macro: str = ""
    denominators: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    thresh: int = M.THRESH
    mode: str = "strip"

    def as_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "sets": self.sets, "labels": self.labels,
                "table": self.table, "micro": self.micro, "macro": self.macro,
                "winner_recall": self.winner_recall, "winner_cer": self.winner_cer,
                "winner_macro": self.winner_macro, "denominators": self.denominators,
                "warnings": self.warnings, "thresh": self.thresh, "mode": self.mode}


def evaluate(run_id: str, *, sets: list[str] | None = None, models: list[str] | None = None,
             also: list[Path] | None = None, thresh: int = M.THRESH, mode: str = "strip",
             device: str = "cuda:0", batch: int = 32, refresh: bool = False,
             ws: Workspace | None = None, predictor: Any = None) -> SelectReport:
    """Таблиця чекпойнти × holdout; `predictor(ckpt, crops)` підставляє тест."""
    w = ws if ws is not None else workspace()
    st = ST.load(run_id, w)
    reg = S.registry(w)
    ckpts = collect_ckpts(st.out_dir(w), models or [], also or [])
    hs = holdout_sets(reg, sets)
    if not hs:
        raise SelectError("немає holdout-наборів із ручними мітками ok і кропами: дайте "
                          "одному-двом наборам роль holdout (set.json) і розмітьте їх")
    py = engine_python()
    if predictor is None and py is None:
        raise SelectError("середовища рушіїв немає — nysh htr install")
    rep = SelectReport(run_id=run_id, sets=[h.name for h in hs], labels=[k for k, _ in ckpts],
                       thresh=thresh, mode=mode)
    cache_dir = st.eval_dir(w) / "preds"
    for label, ckpt in ckpts:
        fp = fingerprint(ckpt)
        rep.table[label] = {}
        rows: dict[str, M.SetMetrics] = {}
        for h in hs:
            cache = cache_dir / f"{label}__{fp}__{h.name}.json"
            if refresh and cache.is_file():
                cache.unlink()
            if predictor is not None:
                preds = list(predictor(ckpt, h.crops))
            else:
                assert py is not None
                preds = _predict(py, ckpt, h.crops, cache, device=device, batch=batch)
            if len(preds) != len(h.crops):
                raise SelectError(f"{label}/{h.name}: прогнозів {len(preds)} на "
                                  f"{len(h.crops)} кропів")
            m = M.measure(list(zip(h.texts, preds, strict=True)), skip_names=h.skip_names,
                          mode=mode, thresh=thresh)
            rows[h.name] = m
            rep.table[label][h.name] = m.as_dict()
        rep.micro[label] = M.micro(rows)
        rep.macro[label] = M.macro(rows)
    rep.denominators = {h.name: {"n_ok": len(h.crops),
                                 "n_names": rep.table[rep.labels[0]][h.name]["n_names"]}
                        for h in hs}
    rank = sorted(rep.labels, key=lambda lb: (rep.micro[lb]["recall"], -rep.micro[lb]["cer"]),
                  reverse=True)
    rep.winner_recall = rank[0]
    rep.winner_cer = min(rep.labels, key=lambda lb: rep.micro[lb]["cer"])
    rep.winner_macro = max(rep.labels, key=lambda lb: rep.macro[lb]["recall"])
    small = [h.name for h in hs if len(h.crops) < M.SMALL_SET]
    if small:
        rep.warnings.append(f"набори з <{M.SMALL_SET} рядків самостійного висновку не витримують: "
                            f"{', '.join(small)}")
    if rep.winner_macro != rep.winner_recall:
        rep.warnings.append(f"macro дає іншого переможця ({rep.winner_macro}) — рейтинг "
                            f"тримається на малому наборі; вірити micro")
    if rep.winner_cer != rep.winner_recall:
        rep.warnings.append(f"за CER виграє {rep.winner_cer}, за recall — {rep.winner_recall}: "
                            f"метрики розійшлися; для пошуку роду важить recall")
    write_json(st.eval_dir(w) / "select.json", rep.as_dict())
    st.set_phase("evaluated", f"переможець за recall: {rep.winner_recall}").save(w)
    return rep


def load_select(run_id: str, ws: Workspace | None = None) -> dict[str, Any] | None:
    w = ws if ws is not None else workspace()
    got = read_json(ST.RunState(run_id=run_id).eval_dir(w) / "select.json", default=None)
    return got if isinstance(got, dict) else None
