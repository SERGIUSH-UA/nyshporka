"""🏗 Збірка сайту роду: канон → сирці MkDocs → HTML.

Порядок і чому саме такий:

1. **`canon.check`** — канон із помилками дає сайт, що бреше (биті посилання,
   діти раніше за батьків), тож на ERROR збірка зупиняється.
2. **індекс** — дерево, граф і мапа читають `data/derived/*.json`.
3. **сирці** в `<тека>/docs`: ресурси пакета → сторінки-оглядини → сторінки
   канону → власні сторінки з `data/site/overlay/` (вони перемагають; у
   відкриту версію — лише `.md`).
4. **відкрита версія**: чистка markdown і подій дерева від прихованих.
5. **`mkdocs build`** у `<тека>/html`.
6. **відкрита версія**: `guard_site` по готовому HTML. Знайшов ім'я чи ID
   прихованого — тека `html` видаляється, щоб її не виклали, а збірка
   повертає перелік витоків.

Теки: `<простір>/site/private` і `<простір>/site/public` за замовчуванням.
Чужу непорожню теку (без мітки `.nysh-site`) без `force` не перезаписуємо.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from nyshporka.site import config as CFG
from nyshporka.site import public as PUB
from nyshporka.site.render import TEMPLATES, environment
from nyshporka.site.render import build as render_build

ASSETS = Path(__file__).resolve().parent / "data" / "assets"
HOOKS = Path(__file__).resolve().parent / "hooks.py"
MARK = ".nysh-site"
PAGES = ("index.md", "family-tree.md", "family-graph.md", "places-map.md")


class SiteError(ValueError):
    """Збірку не почато або зупинено — з поясненням, що зробити."""


@dataclass
class SiteReport:
    out: Path
    public: bool
    counts: dict[str, int] = field(default_factory=dict)
    hidden: int = 0
    withheld_sources: int = 0
    dropped_lines: int = 0
    overlaid: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    leaks: list[str] = field(default_factory=list)
    html: Path | None = None
    warnings: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"out": str(self.out), "public": self.public, "counts": self.counts,
                "hidden": self.hidden, "withheld_sources": self.withheld_sources,
                "dropped_lines": self.dropped_lines, "overlaid": self.overlaid,
                "ambiguous": self.ambiguous, "leaks": self.leaks, "skipped": self.skipped,
                "html": str(self.html) if self.html else None,
                "canon_warnings": self.warnings}


def mkdocs_available() -> bool:
    try:
        import material  # noqa: F401
        import mkdocs  # noqa: F401
        import mkdocs_roamlinks_plugin  # noqa: F401
    except ImportError:
        return False
    return True


def default_out(root: Path, public: bool) -> Path:
    return root / "site" / ("public" if public else "private")


def _prepare_out(out: Path, force: bool) -> Path:
    if out.exists() and any(out.iterdir()) and not (out / MARK).is_file() and not force:
        raise SiteError(f"{out} не порожня й не схожа на збірку сайту — інша тека або --force")
    docs = out / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    docs.mkdir(parents=True)
    (out / MARK).write_text("збірка nysh site build — вміст перезаписується\n", encoding="utf-8")
    # Приватна збірка несе повне дерево живих; у git-просторі `git add .` не має
    # її підхопити.
    (out / ".gitignore").write_text("*\n", encoding="utf-8")
    return docs


def _years(persons: list[Any]) -> tuple[int, int]:
    years = [int(f.date.value[:4]) for p in persons for f in p.facts
             if f.date and f.date.value[:4].isdigit()]
    today = date.today().year
    return (min(years) if years else today - 100, max(max(years) if years else today, today))


def build(root: Path, *, public: bool = False, out: Path | None = None,
          force: bool = False, html: bool = True) -> SiteReport:
    from nyshporka.canon import check as C
    from nyshporka.storage.reindex import reindex

    cfg = CFG.load(root)
    if not (root / "data" / "canonical").is_dir():
        raise SiteError("канону в просторі немає — сайт збирати нема з чого (keep-canon)")
    if html and not mkdocs_available():
        raise SiteError("для HTML потрібен MkDocs: pip install nyshporka[site] "
                        "(або --no-html, щоб лише згенерувати сирці)")
    checked = C.check(root)
    if not checked.ok:
        raise SiteError(f"у каноні {checked.count('ERROR')} помилок — сайт брехав би. "
                        f"Спершу nysh canon check")
    reindex(root)

    out = out or default_out(root, public)
    docs = _prepare_out(out, force)
    rep = SiteReport(out=out, public=public, warnings=checked.count("WARN"))

    # 1. Ресурси пакета.
    shutil.copytree(ASSETS, docs / "assets", dirs_exist_ok=True)

    # 2. Хто прихований (відкрита версія) — до рендеру, бо рендер їх пропускає.
    canon = checked.canon
    persons = sorted(canon.persons.values(), key=lambda p: p.id)
    families = sorted(canon.families.values(), key=lambda f: f.id)
    hidden: set[str] = set()
    guard = PUB.NameGuard({}, None)
    stems = None
    if public:
        hidden = PUB.hidden_ids(persons, cfg, PUB.lived_from(root), families)
        stems, stem_amb = PUB.stem_probes(persons, hidden)
        probes, lit_amb = PUB.literal_probes(persons, hidden)
        guard = PUB.NameGuard(probes, stems)
        rep.ambiguous = sorted(set(stem_amb) | set(lit_amb))
    # Назва джерела, що називає прихованого, — не публікується саме джерело:
    # інакше рядок-заголовок вирізало б і сторінка лишилась би без назви.
    title_guard = PUB.NameGuard({}, stems)

    # 3. Сторінки канону.
    templates_dirs = [root / cfg.templates] if cfg.templates else []
    rendered = render_build(
        root, docs_dir=docs, cfg=cfg, templates_dirs=templates_dirs,
        hidden=hidden, drop_source_types=set(cfg.drop_source_types) if public else set(),
        source_filter=(lambda s: title_guard.hits(s.title)) if public else None,
        public=public)
    rep.hidden = len(hidden)
    rep.withheld_sources = len(rendered.withheld_sources)

    # 4. Оглядові сторінки: головна, дерево, граф, мапа.
    shown = [p for p in persons if p.id not in hidden]
    facts = [f for p in shown for f in p.facts]
    placed = [pl for pl in canon.places.values() if pl.coords is not None]
    rep.counts = {"persons": rendered.persons, "families": rendered.families,
                  "places": rendered.places, "sources": rendered.sources,
                  "places_with_coords": len(placed), "facts": len(facts),
                  "facts_cited": sum(1 for f in facts if f.citations)}
    y_min, y_max = _years(shown)
    env = environment(templates_dirs)
    ctx = {
        "title": cfg.title, "description": cfg.description, "public": public,
        "counts": rep.counts, "built": date.today().isoformat(),
        "year_min": y_min, "year_max": y_max,
        "place_groups_json": json.dumps(
            [{"id": g.id, "label": g.label, "color": g.color, "match": g.match}
             for g in cfg.place_groups], ensure_ascii=False),
        "eras_json": json.dumps(cfg.eras, ensure_ascii=False),
    }
    for page in PAGES:
        (docs / page).write_text(env.get_template(f"pages/{page}.j2").render(**ctx),
                                 encoding="utf-8")

    # 5. Власні сторінки людини — поверх згенерованого.
    overlay = root / CFG.OVERLAY
    if overlay.is_dir():
        for f in sorted(overlay.rglob("*")):
            if f.is_file():
                rel = f.relative_to(overlay)
                # 🔴 У відкриту версію — лише сторінки: текст у них чиститься
                # від прихованих, а PDF, фото чи таблицю перевірити нічим.
                if public and f.suffix.lower() != ".md":
                    rep.skipped.append(rel.as_posix())
                    continue
                (docs / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, docs / rel)
                rep.overlaid.append(rel.as_posix())

    # 6. Відкрита версія: прибрати прихованих із тексту й подій.
    withheld = set(rendered.withheld_sources)
    if public:
        aliases: dict[str, str] = {}
        for md in sorted(docs.rglob("*.md")):
            text = md.read_text(encoding="utf-8")
            new, n = PUB.scrub_markdown(text, hidden, withheld, guard, aliases)
            if new != text:
                md.write_text(new, encoding="utf-8")
            rep.dropped_lines += n
        for name in ("tree.json", "graph.json"):
            rep.dropped_lines += PUB.scrub_events(docs / "assets" / name, hidden | withheld, guard)
        for name in ("tree.full.json", "graph.full.json"):
            (docs / "assets" / name).unlink(missing_ok=True)

    # 7. Конфіг MkDocs.
    tpl = environment([]).get_template("mkdocs.yml.j2")
    (out / "mkdocs.yml").write_text(tpl.render(
        title=cfg.title, description=cfg.description, language=cfg.language,
        search_langs=cfg.search_langs, hooks_path=str(HOOKS),
        extra_css=cfg.extra_css, nav_before=cfg.nav_before, nav_after=cfg.nav_after),
        encoding="utf-8")
    if not html:
        return rep

    # 8. HTML і сторож.
    site = out / "html"
    run = subprocess.run([sys.executable, "-m", "mkdocs", "build", "--clean", "-q",
                          "-f", str(out / "mkdocs.yml")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if run.returncode != 0:
        raise SiteError("mkdocs build не зібрав сайт:\n" + (run.stderr or run.stdout)[-2000:])
    rep.html = site
    if public:
        rep.leaks = PUB.guard_site(site, hidden, withheld, guard)
        if rep.leaks:
            shutil.rmtree(site)
            rep.html = None
    return rep


__all__ = ["TEMPLATES", "SiteError", "SiteReport", "build", "default_out", "mkdocs_available"]
