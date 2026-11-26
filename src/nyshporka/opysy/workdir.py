"""Робоча тека опису учасника: паспорт джерела й кроки «скан → таблиця → нормалізація → пакет».

Розкладка теки (`<тека>`):

- `opys.json` — паспорт: архів, фонд, опис, форма, шлях до PDF, джерело (адреса публікації,
  sha256 файлу, сторінок, шаблон посилання на сторінку);
- `pages/NNNN.jpg` — сторінки під читання (`nysh opys pages`);
- `run/` — прочитане цілими сторінками: `nysh read <тека>/pages --out <тека>/run` (другий голос —
  `--with …`, ляже поруч у `run-<тег>`);
- `table.tsv` — таблиця справ (`nysh opys table`);
- `norm/batch_NNN.json` → `batch_NNN.out.txt` (відповідь агента) → `norm.tsv` (`nysh opys norm`);
- `paket/` — робоча тека пакета (`nysh opys build`) → `nysh opys pack <тека>/paket`.

Поки що — лише описи без друкованого бланку, прочитані цілими сторінками (`hand_ruled`).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

PASSPORT = "opys.json"
#: Форми, які вміє цей шлях: рукопис на розграфленому від руки аркуші, читаний цілими сторінками.
FORMS = ("hand_ruled",)


class WorkdirError(ValueError):
    """Вада робочої теки чи паспорта — з причиною для людини."""


def pages_dir(d: Path) -> Path:
    return Path(d) / "pages"


def run_dir(d: Path) -> Path:
    return Path(d) / "run"


def table_path(d: Path) -> Path:
    return Path(d) / "table.tsv"


def norm_dir(d: Path) -> Path:
    return Path(d) / "norm"


def druk_pages_dir(d: Path) -> Path:
    """Сторінки машинописного опису під рушій друку (висота `vl_table.VYSOTA`)."""
    return Path(d) / "pages_druk"


def vl_dir(d: Path) -> Path:
    """Розмітка рушія друку (`NNNN.md`, `NNNN.blocks.json`), забрана з хмари."""
    return Path(d) / "vl"


def dochyt_dir(d: Path) -> Path:
    """Кропи колонки № і плям чорнила з їх читанням (`opysy.dochyt`)."""
    return Path(d) / "dochyt"


def norm_path(d: Path) -> Path:
    return Path(d) / "norm.tsv"


def paket_dir(d: Path) -> Path:
    return Path(d) / "paket"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _source(url: str, kind: str, page_link: str, label: str) -> dict[str, Any]:
    """Джерело за адресою публікації: Commons — сторінка файлу з `?page={page}`."""
    url = url.strip()
    if not kind:
        kind = "commons" if "wikimedia.org" in url else "archive_site"
    if kind == "commons" and "upload.wikimedia.org" in url:
        # пряма адреса файлу → сторінка файлу на Commons (там людина відкриє скан)
        url = "https://commons.wikimedia.org/wiki/File:" + url.rsplit("/", 1)[-1]
    if kind == "commons" and not page_link:
        page_link = url.split("?", 1)[0] + "?page={page}"
    return {"kind": kind, "url": url, "page_link": page_link,
            "label": label or url.rsplit("/", 1)[-1].split("?", 1)[0]}


def _vyd_adresy(url: str, orig: Path) -> None:
    """Адреса веде на файл іншого виду, ніж той, з якого рахується хеш, — відмова: інакше паспорт
    ніс би хеш чужого файлу."""
    if not orig.is_file():
        return
    vyd = Path(unquote(urlparse(url.strip()).path)).suffix.lower()
    if vyd and vyd != orig.suffix.lower():
        raise WorkdirError(f"адреса веде на файл «{vyd}», а хеш рахувався б із «{orig.name}»: "
                           f"дай оригінал, опублікований за адресою (`--published <файл{vyd}>`)")


def init(d: Path, pdf: Path, *, repo: str, fond: str, opys: str, url: str = "", kind: str = "",
         page_link: str = "", form: str = "hand_ruled", title: str = "", years: str = "",
         language: str = "", published: Path | None = None) -> dict[str, Any]:
    """Завести робочу теку: паспорт джерела з локального PDF (сторінки) і адреси, де опис
    опубліковано. Закритий для заливки фонд — відмова до будь-якого прогону.

    Адреса може прийти пізніше (`set_source`): старий PDF, збережений колись із сайту архіву,
    читається одразу, а адресу людина знаходить і перевіряє до `build` (відгук №27, 26.11.2026).
    Вигаданої адреси не ставимо — `build` без неї відмовляє.

    sha256 джерела — того файлу, що лежить за адресою: `published` (оригінал, напр. djvu сайту
    архіву, з якого зроблено PDF), інакше сам PDF."""
    import pypdfium2 as pdfium

    from nyshporka.opysy import gates as G
    from nyshporka.opysy.schema import Source

    if form not in FORMS:
        raise WorkdirError(f"форма «{form}» поки не підтримується; уміємо: {', '.join(FORMS)}")
    why = G.excluded(repo, fond)
    if why:
        raise WorkdirError(f"{repo} ф.{fond}: {why} (подробиці: nysh opys policy {repo} {fond})")
    pdf = Path(pdf).resolve()
    teka = pdf.is_dir()
    if teka:
        from nyshporka.opysy.pages import obrazy

        if not obrazy(pdf):
            raise WorkdirError(f"у теці {pdf} немає кадрів (jpg, png, tif)")
    elif not pdf.is_file():
        raise WorkdirError(f"немає файлу {pdf}")
    orig = Path(published).resolve() if published else pdf
    if not (orig.is_file() or (orig.is_dir() and teka)):
        raise WorkdirError(f"немає файлу {orig}")
    if url.strip():
        _vyd_adresy(url, orig)
    if teka:
        # Архів публікує опис кадрами (тека на сайті чи файлообміннику архіву): сторінки — самі кадри,
        # відбиток джерела — з імен і вмісту кадрів за порядком.
        from nyshporka.opysy.pages import obrazy

        n = len(obrazy(pdf))
        h = hashlib.sha256()
        for k in obrazy(pdf):
            h.update(k.name.encode("utf-8") + b"\0" + _sha256(k).encode("ascii") + b"\n")
        vidbytok = h.hexdigest()
    else:
        doc = pdfium.PdfDocument(str(pdf))
        try:
            n = len(doc)
        finally:
            doc.close()
        vidbytok = _sha256(orig)
    label = orig.name if (published or teka) else ""
    if url.strip():
        src = {**_source(url, kind, page_link, label), "sha256": vidbytok}
        Source(**src, pages=n)  # перевірка схемою: вид, адреса, шаблон посилання
    else:
        # Адресу назвуть пізніше (`set_source`); вид джерела — тоді ж, з адреси.
        src = {"kind": "", "url": "", "page_link": "", "label": label or orig.name,
               "sha256": vidbytok}
    repo_c, fond_c = G.repo_fond(repo, fond)
    pas = {"repo": repo_c, "fond": fond_c, "opys": str(opys).strip(), "form": form, "pdf": str(pdf),
           "pages": n, "source": src, "title": title, "years": years, "language": language}
    if published:
        pas["published"] = str(orig)
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / PASSPORT).write_text(json.dumps(pas, ensure_ascii=False, indent=1), encoding="utf-8",
                              newline="\n")
    return pas


def load(d: Path) -> dict[str, Any]:
    p = Path(d) / PASSPORT
    if not p.exists():
        raise WorkdirError(f"{d}: немає паспорта {PASSPORT} — спершу `nysh opys init`")
    pas: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return pas


def bez_adresy(pas: dict[str, Any]) -> bool:
    """Адресу публікації ще не названо (тека заведена без `--url`)."""
    return not str((pas.get("source") or {}).get("url") or "").strip()


#: Згода людини передати скан власникові Нишпорки для Commons (`nysh opys skan`, лише в терміналі).
SKAN_ZGODA = "skan_zghoda.json"


def skan_fail(pas: dict[str, Any]) -> Path | None:
    """Файл скану, що лежить за адресою джерела: оригінал (`published`) чи сам PDF; тека кадрів —
    None (передати можна лише файл PDF чи DjVu)."""
    f = Path(pas.get("published") or pas["pdf"])
    return f if f.is_file() and f.suffix.lower() in (".pdf", ".djvu") else None


def skan_zghoda(d: Path) -> dict[str, Any] | None:
    """Згода на передачу скану — лише чинна: для того самого файлу (sha256 джерела)."""
    f = Path(d) / SKAN_ZGODA
    try:
        z = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None
    pas = load(d)
    if not isinstance(z, dict) or z.get("sha256") != (pas.get("source") or {}).get("sha256"):
        return None
    return z


def zapysaty_skan_zghodu(d: Path) -> dict[str, Any]:
    """Людина погодилась передати скан (CLI питає її в терміналі; агентові команда відмовляє)."""
    from datetime import UTC, datetime

    pas = load(d)
    f = skan_fail(pas)
    if f is None:
        raise WorkdirError("передати можна лише файл PDF чи DjVu, а опис заведено з "
                           f"{pas.get('published') or pas['pdf']}")
    z = {"sha256": (pas.get("source") or {}).get("sha256"), "fail": f.name,
         "at": datetime.now(UTC).isoformat(timespec="seconds")}
    (Path(d) / SKAN_ZGODA).write_text(json.dumps(z, ensure_ascii=False), encoding="utf-8")
    return z


def set_source(d: Path, *, url: str, kind: str = "", page_link: str = "",
               published: Path | None = None) -> dict[str, Any]:
    """Назвати адресу публікації опису для вже заведеної теки — до `build`.

    Прочитане не чіпається: хеш джерела той самий, якщо не дали оригінал (`published`), з якого
    зроблено PDF. Тоді хеш рахується з оригіналу, бо саме він лежить за адресою."""
    from nyshporka.opysy.schema import Source

    if not url.strip():
        raise WorkdirError("назвіть адресу, де цей файл опубліковано (`--url`): сайт архіву чи Commons")
    pas = load(d)
    pdf = Path(pas["pdf"])
    teka = pdf.is_dir()
    if published is not None:
        if teka:
            raise WorkdirError("опис заведено текою кадрів — оригіналу-файлу (`--published`) тут немає")
        orig = Path(published).resolve()
        if not orig.is_file():
            raise WorkdirError(f"немає файлу {orig}")
        vidbytok = _sha256(orig)
        pas["published"] = str(orig)
    else:
        orig = Path(pas.get("published") or pdf)
        vidbytok = str((pas.get("source") or {}).get("sha256") or "")
    _vyd_adresy(url, orig)
    label = orig.name if (pas.get("published") or teka) else ""
    bulo = str((pas.get("source") or {}).get("url") or "")
    src = {**_source(url, kind, page_link, label), "sha256": vidbytok}
    try:
        Source(**src, pages=int(pas["pages"]))
    except ValueError as exc:
        raise WorkdirError(f"адреса не годиться: {exc}") from exc
    pas["source"] = src
    (Path(d) / PASSPORT).write_text(json.dumps(pas, ensure_ascii=False, indent=1), encoding="utf-8",
                                    newline="\n")
    return {"source": src, "bulo": bulo}


def build(d: Path, *, norm_model: str = "", tool: str = "nysh opys build",
          na_obmin: bool = False) -> dict[str, Any]:
    """Робоча тека пакета `<тека>/paket` з прочитаного, таблиці й нормалізації."""
    from nyshporka.opysy import norm_batches as NB
    from nyshporka.opysy import pack_dir as PD

    pas = load(d)
    source = dict(pas["source"])
    if bez_adresy(pas):
        if skan_zghoda(d) is None:
            raise WorkdirError(
                f"адресу, де опис опубліковано, ще не названо — посилання справ у Засіках ведуть туди, "
                f"щоб кожну справу можна було звірити зі сканом. Три шляхи: (1) знайти цей файл на "
                f"сайті архіву, перевірити, що опис той самий, — `nysh opys dzherelo {d} --url "
                f"<адреса>`; (2) опису онлайн немає — людина сама заливає скан на Wikimedia Commons і "
                f"дає адресу файлу там тією самою командою; (3) не може — людина у своєму терміналі "
                f"погоджується передати скан власникові Нишпорки: `nysh opys skan {d}`, і тоді push "
                f"віддасть опис разом зі сканом (власник заллє його на Commons, посилання допише "
                f"сервер). Скан на Commons стає публічним назавжди — це вирішує людина")
        source = {"kind": "pending_commons", "url": "", "page_link": "",
                  "label": source.get("label") or "", "sha256": source.get("sha256") or ""}
    voices = PD.run_voices(run_dir(d))
    if not voices:
        raise WorkdirError(f"немає прочитаних сторінок у {run_dir(d)} — "
                           f"`nysh read {pages_dir(d)} --out {run_dir(d)}`")
    if not table_path(d).exists():
        raise WorkdirError("немає таблиці справ — `nysh opys table`")
    total = int(pas["pages"])
    main = voices[0][1]
    sizes = {s: sz for i in range(1, total + 1) if (sz := PD.page_size(main, s := f"{i:04d}"))}
    pages = PD.pages_from_voices(voices, total)
    spread = PD.is_spread(sizes)
    rows = PD.rows_from_table(table_path(d), sizes, spread, NB.known(norm_path(d)))
    normalized = any(r["title_norm"] for r in rows)
    if normalized and not norm_model:
        raise WorkdirError("назви нормалізовано — назви модель, що нормалізувала (`--norm-model`)")
    lang = pas.get("language") or PD.language(pages, "other")
    m = PD.manifest(repo=pas["repo"], fond=pas["fond"], opys=pas["opys"], language=lang,
                    source=source, pages=total, spread=spread,
                    engines=[n for n, _ in voices],
                    # рукопис — `low`: нормалізація тоді обов'язкова воротами
                    quality={"klass": "low", "form": pas["form"]}, tool=tool,
                    norm_model=norm_model, normalized=normalized, na_obmin=na_obmin)
    work = PD.write(paket_dir(d), m, pages, rows)
    return {"dir": str(work), "pages": len(pages), "rows": len(rows),
            "normalized": sum(1 for r in rows if r["title_norm"]), "engines": m["engines"]}
