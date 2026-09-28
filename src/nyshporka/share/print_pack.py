"""📰 Пакет друкованого видання: рік газети чи довідника як книга пулу.

Той самий `.nyshtext`, що й для справи, і ті самі ворота. Відмінності три:

- ідентичність — ключ видання `VYD/<код>/<рік>` (`nyshporka.vydannia`), а не
  шифра архіву;
- голос — не прогін рушія, а текстовий шар джерела (archive.org, PDF
  сайту, власний OCR). Він стоїть на місці моделі, бо ворота вимагають
  назвати, чим отримано текст, і для друку відповідь саме ця;
- номери, сторінки й адреси першоджерела їдуть у `extra.publication`:
  це поле маніфест несе недоторканим, тож ні схема пакета, ні сервер пулу
  заради видань не змінюються.

Сторінки беруться з готової теки `NNNN.txt` у порядку імен. Як їх нарізати з
джерела (маркери сторінок, `_djvu.xml`, переформатування «слово на рядок») —
справа того, хто пакує: у джерел немає спільного формату.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from nyshporka import vydannia
from nyshporka.share import bundle, gates, journal
from nyshporka.share.bundle import Manifest
from nyshporka.share.publish import PublishError

#: Одиниця сторінки пакета: друкована сторінка або цілий номер, коли меж
#: сторінок джерело не зберегло.
PAGE_UNITS = ("page", "issue")


def run_name(code: str, year: int) -> str:
    """Ім'я теки прогону в пакеті й у сторі отримувача: `vyd_pev_1880`."""
    return f"vyd_{code.lower()}_{year}"


def _pages(src: Path) -> list[Path]:
    got = sorted(p for p in Path(src).glob("*.txt") if p.is_file())
    if not got:
        raise PublishError(f"у {src} немає жодної сторінки *.txt")
    return got


def _issues(raw: Any) -> list[dict[str, Any]]:
    """Перелік номерів: лише відомі поля, щоб у пакет не поїхало зайве."""
    keep = ("no", "date", "first_page", "pages", "source_url", "sha256", "note")
    out: list[dict[str, Any]] = []
    for row in raw or []:
        if isinstance(row, dict):
            out.append({k: row[k] for k in keep if row.get(k) not in (None, "")})
    return out


def pack_print(src: Path, code: str, year: int, *, title: str,
               ocr_by: str, ocr_layer: str = "", page_unit: str = "page",
               places: list[str] | None = None, publisher_place: str = "",
               issues: list[dict[str, Any]] | None = None,
               publisher: str = "", contact: str = "", site: str = "",
               note: str = "", links: list[dict[str, str]] | None = None,
               license_text: str = "CC0-1.0", source_terms: str = "",
               dest: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Зібрати пакет одного року видання з теки сторінок."""
    try:
        key = vydannia.key(code, year)
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    code = code.upper()
    if page_unit not in PAGE_UNITS:
        raise PublishError(f"одиниця сторінки — {' або '.join(PAGE_UNITS)}")
    if not title.strip():
        raise PublishError("назва видання обов'язкова: вона стоїть на картці в пулі")
    if not ocr_by.strip():
        raise PublishError("не названо, звідки текстовий шар (--ocr-by): без цього "
                           "отримувач не знає, чому текст саме такий")
    pages = _pages(src)
    rows = _issues(issues)

    with tempfile.TemporaryDirectory(prefix="nysh_vyd_") as tmp:
        run_dir = Path(tmp) / run_name(code, year)
        run_dir.mkdir()
        for i, p in enumerate(pages, 1):
            shutil.copyfile(p, run_dir / f"{i:04d}.txt")
        model = f"OCR · {ocr_by.strip()}" + (f" ({ocr_layer.strip()})" if ocr_layer.strip() else "")
        meta = {"version": 1, "case_key": key, "frames_total": len(pages),
                "model": model, "engine": "print", "done": len(pages)}
        (run_dir / bundle.META_NAME).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        voice = bundle.voice_of(run_dir)
        counted = bundle.tally(
            {run_dir.name: {p.name: p.read_text(encoding="utf-8", errors="replace")
                            for p in sorted(run_dir.glob(bundle.PACKED_TEXT))}},
            {voice.run: voice.model})
        case: dict[str, Any] = {
            "shifra": key, "key_local": key,
            "repo": vydannia.REPO, "fond": code, "spr": str(year),
            "repo_name": vydannia.REPO_NAME,
            "title": f"{title.strip()}, {year}",
            "years": [year, year],
        }
        if places:
            case["places"] = [p for p in places if p.strip()]
        refs = [{"source": "url", "ref": f"{code} {year} №{r['no']}", "url": r["source_url"]}
                for r in rows if r.get("no") and r.get("source_url")]
        publication = {"code": code, "title": title.strip(), "year": year,
                       "place": publisher_place.strip(), "page_unit": page_unit,
                       "ocr": {"by": ocr_by.strip(), "layer": ocr_layer.strip()},
                       "issues": rows}
        pub: dict[str, str] = {}
        if publisher:
            pub["handle"] = publisher
        if contact:
            pub["contact"] = contact
        if site:
            pub["url"] = site
        lic = {"text": license_text, "images": "не входять"}
        if source_terms:
            lic["source_terms"] = source_terms
        m = Manifest(
            case=case, refs=refs,
            frames={"total": len(pages), "listed": 0, "with_sha256": 0, "with_apid": 0},
            decode={**counted, "voices": [voice.as_json()],
                    "content_sha256": voice.content_sha256},
            publisher=pub, note=note, links=list(links or []),
            extra={"publication": publication}, license=lic,
            tool=bundle._tool_version(), created=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

        verdict = gates.check(m)
        sketch = bundle.plan([run_dir])
        out: dict[str, Any] = {"manifest": m.as_json(), "gates": verdict.as_json(),
                               "runs": [run_dir.name], "files": len(sketch["files"]),
                               "bytes_raw": sketch["bytes"], "case_key": key}
        if dry_run:
            out["files_list"] = [f["arc"] for f in sketch["files"]]
            out["dry_run"] = True
            return out
        if not verdict.passed:
            raise PublishError("ворота не пропустили пакет:\n" + gates.describe(verdict))

        name = bundle.suggest_name(m)
        target = Path(dest) if dest else (journal.share_dir() / journal.OUTBOX / name)
        if target.is_dir():
            target = target / name
        wrote = bundle.write(target, m, [run_dir])
    out.update(wrote)
    journal.record(journal.PACKED, shifra=key, case_key=key, pages=m.pages,
                   bytes=wrote["bytes"], sha256=wrote["sha256"], path=wrote["path"],
                   models=model, geom_bytes=0)
    return out
