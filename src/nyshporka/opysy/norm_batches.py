"""Нормалізація назв справ: таблиця опису → пачки запитів → прийом відповідей.

Нормалізує агент учасника (підагент) або Batch API за шаблоном `normalize` — пакет у мережу не
ходить, тож тут лише пачки й прийом:

- `export` — `<тека>/batch_NNN.json`: повний запит (`request`), сирі назви (`titles`), ключі рядків
  (`page`, `part`, `row`), скільки назв (`n`);
- відповідь моделі кладеться поруч як `batch_NNN.out.txt` (сирий текст відповіді: JSON-масив);
- `collect` — розбір кожної відповіді строго (`normalize.parse`: та сама довжина й порядок, інакше
  пачка не приймається) → TSV з `title_norm`.

🔴 Пачка з іншою довжиною відповіді не «підрізається»: зсув на одну назву пришиває нормалізацію до
чужої справи. Така пачка лишається без нормалізації й переробляється.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from nyshporka.opysy.normalize import Orthography

#: Мова опису → (як назвати її в шаблоні, правопис виходу). Українська — як в оригіналі: правило
#: `ru_modern` (ѣ→е, «-аго»→«-ого») на українському тексті русифікувало б назви.
MOVY: dict[str, tuple[str, Orthography]] = {"ru": ("російською, часто дореформеною орфографією", "ru_modern"),
        "uk": ("українською", "keep")}


def key(page: str, part: object, title: str) -> tuple[str, str, str]:
    """Ключ нормалізації: сторінка, половина, сира назва (а не номер рядка — він зсувається)."""
    return (str(page), str(part), " ".join(str(title).split()))


def known(tsv: Path) -> dict[tuple[str, str, str], str]:
    """Уже прийняті нормалізації (TSV `collect`) за `key`."""
    p = Path(tsv)
    out: dict[tuple[str, str, str], str] = {}
    if p.exists():
        with p.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                out[key(r["page"], r["part"], r["title"])] = r.get("title_norm") or ""
    return out


def describe_source(repo: str, fond: str, title: str = "", years: str = "", mova: str = "ru") -> str:
    """Одне речення про джерело для шаблону: архів, фонд, установа, роки, мова."""
    from nyshporka.fonds.registry import REPO_LABEL

    bits = [REPO_LABEL.get(repo, repo), f"фонд {fond}"]
    if title:
        bits.append(title)
    if years:
        bits.append(years)
    bits.append(MOVY[mova][0])
    return ", ".join(bits)


def narizani(out_dir: Path) -> set[tuple[str, str, str]]:
    """Ключі назв, уже нарізаних у пачки теки (з відповіддю чи без)."""
    out: set[tuple[str, str, str]] = set()
    for p in sorted(Path(out_dir).glob("batch_*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        for k, title in zip(b.get("keys") or [], b.get("titles") or [], strict=False):
            out.add(key(k["page"], k["part"], title))
    return out


def bez_vidpovidi(out_dir: Path) -> list[Path]:
    """Пачки, на які ще немає відповіді (`batch_NNN.out.txt`)."""
    d = Path(out_dir)
    return [p for p in sorted(d.glob("batch_*.json")) if not p.with_name(p.stem + ".out.txt").exists()]


def export(table: Path, out_dir: Path, *, source: str, mova: str = "ru",
           have: dict[tuple[str, str, str], str] | None = None) -> list[Path]:
    """Пачки запитів для назв таблиці, яких ще не нормалізовано (`have`); нові пачки — з
    наступного номера (старі лишаються)."""
    from nyshporka.opysy import normalize as NZ

    with Path(table).open(encoding="utf-8", newline="") as fh:
        recs = [r for r in csv.DictReader(fh, delimiter="\t") if (r.get("title") or "").strip()
                and (r.get("y") or "").strip()]
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    have = have or {}
    # Уже нарізане, але ще не прийняте, теж не нарізається вдруге: повтор `nysh opys read` до
    # `push` інакше клав би ще один повний набір пачок, і агент платив би двічі.
    narizano = narizani(d)
    recs = [r for r in recs if (kl := key(r["page"], r["part"], r["title"])) not in have
            and kl not in narizano]
    start = len(list(d.glob("batch_*.json")))
    out = []
    titles = [r["title"].strip() for r in recs]
    for k0, (off, batch) in enumerate(NZ.batches(titles)):
        k = start + k0
        keys = [{"page": r["page"], "part": r["part"], "row": r["row"]}
                for r in recs[off:off + len(batch)]]
        p = d / f"batch_{k:03d}.json"
        p.write_text(json.dumps({"request": NZ.request(source, batch, MOVY[mova][1]), "titles": batch,
                                 "keys": keys, "n": len(batch)}, ensure_ascii=False, indent=1),
                     encoding="utf-8", newline="\n")
        out.append(p)
    return out


def collect(out_dir: Path, out_tsv: Path) -> dict[str, Any]:
    """Відповіді → TSV (`page`, `part`, `row`, `title`, `title_norm`). Пачки без відповіді чи з
    битою — у звіті."""
    from nyshporka.opysy import normalize as NZ

    d = Path(out_dir)
    rows, missing, bad = [], [], []
    for p in sorted(d.glob("batch_*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        ans = p.with_name(p.stem + ".out.txt")
        if not ans.exists():
            missing.append(p.name)
            continue
        try:
            got = NZ.parse(ans.read_text(encoding="utf-8"), int(b["n"]))
        except NZ.NormError as exc:
            bad.append(f"{p.name}: {exc}")
            continue
        for k, title, norm in zip(b["keys"], b["titles"], got, strict=True):
            rows.append({**k, "title": title, "title_norm": norm})
    out = Path(out_tsv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["page", "part", "row", "title", "title_norm"], delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    return {"rows": len(rows), "missing": missing, "bad": bad, "file": str(out)}
