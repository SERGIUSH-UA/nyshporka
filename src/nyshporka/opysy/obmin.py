"""Обмін нормалізацією описів — сторона учасника (рішення дослідника 25.11.2026).

Автор без ресурсів віддає рукописний опис ненормалізованим (`nysh opys push <тека> --na-obmin`),
а нормалізацію бере будь-хто з учасників:

    nysh opys obmin                 що чекає
    nysh opys vziaty <тека>         узяти опис (оренда 48 год) — тека з пачками запитів
       … агент відповідає на пачки так само, як після `nysh opys read` …
    nysh opys viddaty <тека> --model <модель>   віддати відповіді (можна по ходу, кілька разів)

Пачки — того самого формату, що `norm_batches.export` (`batch_NNN.json`: `request`, `titles`, `n`;
відповідь — JSON-масив тієї самої довжини в `batch_NNN.out.txt`), лише ключ рядка — `rk` опису в
Супрязі. Приймає сервер своїми воротами (вигадані власні назви, чужі рядки).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nyshporka.opysy import norm_batches as NB
from nyshporka.opysy import normalize as NZ

ZAVDANNIA = "obmin.json"
VIDDANO = "viddano.json"


def zapysaty(d: Path, zavdannia: dict[str, Any]) -> list[Path]:
    """Відповідь `take` → тека: завдання й пачки запитів (уже нарізані не дублюються)."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / ZAVDANNIA).write_text(json.dumps(zavdannia, ensure_ascii=False, indent=1),
                               encoding="utf-8", newline="\n")
    mova = zavdannia.get("language") or "ru"
    styl = NB.MOVY.get(mova, NB.MOVY["ru"])[1]
    source = NB.describe_source(zavdannia["repo"], zavdannia["fond"], zavdannia.get("title", ""),
                                zavdannia.get("years", ""), mova if mova in NB.MOVY else "ru")
    vzhe = {k["rk"] for p in d.glob("batch_*.json")
            for k in json.loads(p.read_text(encoding="utf-8")).get("keys", [])}
    riadky = [r for r in zavdannia.get("riadky") or [] if r["rk"] not in vzhe]
    start = len(list(d.glob("batch_*.json")))
    out = []
    titles = [str(r["title_raw"]).strip() for r in riadky]
    for k0, (off, batch) in enumerate(NZ.batches(titles)):
        p = d / f"batch_{start + k0:03d}.json"
        keys = [{"rk": r["rk"], "page": r.get("page"), "posylannia": r.get("posylannia", "")}
                for r in riadky[off:off + len(batch)]]
        p.write_text(json.dumps({"request": NZ.request(source, batch, styl), "titles": batch,
                                 "keys": keys, "n": len(batch),
                                 "dzherelo": zavdannia.get("dzherelo", "")},
                                ensure_ascii=False, indent=1),
                     encoding="utf-8", newline="\n")
        out.append(p)
    return out


def vidpovidi(d: Path) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """Ще не віддані відповіді теки: ([{rk, title_norm}], пачки з відповіддю, биті пачки)."""
    d = Path(d)
    viddano = set(json.loads((d / VIDDANO).read_text(encoding="utf-8"))) \
        if (d / VIDDANO).exists() else set()
    out: list[dict[str, str]] = []
    gotovi, bad = [], []
    for p in sorted(d.glob("batch_*.json")):
        ans = p.with_name(p.stem + ".out.txt")
        if p.name in viddano or not ans.exists():
            continue
        b = json.loads(p.read_text(encoding="utf-8"))
        try:
            got = NZ.parse(ans.read_text(encoding="utf-8"), int(b["n"]))
        except NZ.NormError as exc:
            bad.append(f"{p.name}: {exc}")
            continue
        out += [{"rk": k["rk"], "title_norm": n} for k, n in zip(b["keys"], got, strict=True)]
        gotovi.append(p.name)
    return out, gotovi, bad


def poznachyty(d: Path, pachky: list[str]) -> None:
    d = Path(d)
    bulo = json.loads((d / VIDDANO).read_text(encoding="utf-8")) if (d / VIDDANO).exists() else []
    (d / VIDDANO).write_text(json.dumps(sorted(set(bulo) | set(pachky)), ensure_ascii=False),
                             encoding="utf-8")


def bez_vidpovidi(d: Path) -> int:
    return sum(1 for p in Path(d).glob("batch_*.json")
               if not p.with_name(p.stem + ".out.txt").exists())
