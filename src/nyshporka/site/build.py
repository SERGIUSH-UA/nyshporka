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

import io
import json
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from nyshporka.site import config as CFG
from nyshporka.site import i18n as I18N
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
    languages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"out": str(self.out), "public": self.public, "counts": self.counts,
                "hidden": self.hidden, "withheld_sources": self.withheld_sources,
                "dropped_lines": self.dropped_lines, "overlaid": self.overlaid,
                "ambiguous": self.ambiguous, "leaks": self.leaks, "skipped": self.skipped,
                "html": str(self.html) if self.html else None,
                "canon_warnings": self.warnings, "languages": self.languages}


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
    # Сирці кожної мови — свої (`docs`, `docs-en`, …): прибираються всі, бо
    # мову могли прибрати з `site.yml`, а її старі сторінки лишились би.
    for old in [docs, *out.glob("docs-*")]:
        if old.is_dir():
            shutil.rmtree(old)
    for old in out.glob("mkdocs.*.yml"):
        old.unlink()
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


def install_assets(docs: Path, lang: str = I18N.DEFAULT) -> None:
    """Стилі, скрипти й бібліотеки сайту → `<docs>/assets` (поверх наявного),
    і рядки скриптів мовою збірки (`assets/js/strings.js`)."""
    shutil.copytree(ASSETS, docs / "assets", dirs_exist_ok=True)
    (docs / "assets" / "js" / "strings.js").write_text(I18N.js_module(lang), encoding="utf-8")


def write_pages(docs: Path, cfg: CFG.SiteConfig, rendered: Any, shown: list[Any],
                places: list[Any], *, public: bool, templates_dirs: list[Path] | None = None,
                pages: tuple[str, ...] = PAGES, lang: str = I18N.DEFAULT) -> dict[str, int]:
    """Оглядові сторінки (головна, дерево, граф, мапа) і `assets/stats.json`.

    `rendered` — звіт `render.build`, `shown` — опубліковані особи. Повертає
    лічильники сайту: їх же бере головна, рукописна в тому числі (через
    `stats.json`)."""
    facts = [f for p in shown for f in p.facts]
    placed = [pl for pl in places if pl.coords is not None]
    counts = {"persons": rendered.persons, "families": rendered.families,
              "places": rendered.places, "sources": rendered.sources,
              "hypotheses": rendered.hypotheses,
              "places_with_coords": len(placed), "facts": len(facts),
              "facts_cited": sum(1 for f in facts if f.citations)}
    y_min, y_max = _years(shown)
    (docs / "assets").mkdir(parents=True, exist_ok=True)
    (docs / "assets" / "stats.json").write_text(
        json.dumps({**counts, "year_min": y_min, "year_max": y_max}), encoding="utf-8")
    env = environment(templates_dirs or [], lang)
    ctx = {
        "title": cfg.title, "description": cfg.description, "public": public,
        "counts": counts, "built": date.today().isoformat(),
        "year_min": y_min, "year_max": y_max,
        "place_groups_json": json.dumps(
            [{"id": g.id, "label": g.label, "color": g.color, "match": g.match}
             for g in cfg.place_groups], ensure_ascii=False),
        "eras_json": json.dumps(cfg.eras, ensure_ascii=False),
        "nav_extra": [*cfg.nav_before, *cfg.nav_after],
    }
    for page in pages:
        (docs / page).write_text(env.get_template(f"pages/{page}.j2").render(**ctx),
                                 encoding="utf-8")
    return counts


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

    # 1. Хто прихований (відкрита версія) — до рендеру, бо рендер їх пропускає.
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
    templates_dirs = [root / cfg.templates] if cfg.templates else []
    shown = [p for p in persons if p.id not in hidden]

    # 2. Кожна мова — окрема збірка тієї самої структури: основна в корені
    # `html`, решта в `html/<мова>`. Перемикач у шапці веде на ту саму сторінку.
    langs = I18N.languages(cfg.languages, cfg.language)
    rep.languages = langs
    configs: list[Path] = []
    withheld: set[str] = set()
    for i, lang in enumerate(langs):
        ldocs = docs if i == 0 else out / f"docs-{lang}"
        ldocs.mkdir(parents=True, exist_ok=True)
        install_assets(ldocs, lang)
        rendered = render_build(
            root, docs_dir=ldocs, cfg=cfg, templates_dirs=templates_dirs,
            hidden=hidden, drop_source_types=set(cfg.drop_source_types) if public else set(),
            source_filter=(lambda s: title_guard.hits(s.title)) if public else None,
            public=public, lang=lang)
        counts = write_pages(ldocs, cfg, rendered, shown, list(canon.places.values()),
                             public=public, templates_dirs=templates_dirs, lang=lang)
        if i == 0:
            rep.hidden = len(hidden)
            rep.withheld_sources = len(rendered.withheld_sources)
            rep.counts = counts
            withheld = set(rendered.withheld_sources)

        # Власні сторінки людини — поверх згенерованого, у кожну мову як є.
        overlay = root / CFG.OVERLAY
        if overlay.is_dir():
            for f in sorted(overlay.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(overlay)
                    # 🔴 У відкриту версію — лише сторінки: текст у них чиститься
                    # від прихованих, а PDF, фото чи таблицю перевірити нічим.
                    if public and f.suffix.lower() != ".md":
                        if i == 0:
                            rep.skipped.append(rel.as_posix())
                        continue
                    (ldocs / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, ldocs / rel)
                    if i == 0:
                        rep.overlaid.append(rel.as_posix())

        # Відкрита версія: прибрати прихованих із тексту й подій.
        if public:
            aliases: dict[str, str] = {}
            for md in sorted(ldocs.rglob("*.md")):
                text = md.read_text(encoding="utf-8")
                new, n = PUB.scrub_markdown(text, hidden, withheld, guard, aliases)
                if new != text:
                    md.write_text(new, encoding="utf-8")
                if i == 0:
                    rep.dropped_lines += n
            for name in ("tree.json", "graph.json"):
                n = PUB.scrub_events(ldocs / "assets" / name, hidden | withheld, guard)
                if i == 0:
                    rep.dropped_lines += n
            for name in ("tree.full.json", "graph.full.json"):
                (ldocs / "assets" / name).unlink(missing_ok=True)

        # Конфіг MkDocs цієї мови.
        tpl = environment([], lang).get_template("mkdocs.yml.j2")
        cfg_path = out / ("mkdocs.yml" if i == 0 else f"mkdocs.{lang}.yml")
        cfg_path.write_text(tpl.render(
            title=cfg.title, description=cfg.description, language=lang,
            search_langs=cfg.search_langs, hooks_path=str(HOOKS),
            extra_css=cfg.extra_css, nav_before=cfg.nav_before, nav_after=cfg.nav_after,
            docs_dir=ldocs.name, site_dir="html" if i == 0 else f"html/{lang}",
            alternate=_alternate(langs, lang)), encoding="utf-8")
        configs.append(cfg_path)
    if not html:
        return rep

    # 3. HTML (основна мова першою: `--clean` у корені стер би решту) і сторож.
    site = out / "html"
    for cfg_path in configs:
        _mkdocs(cfg_path)
    rep.html = site
    if public:
        # Сторож іде по ВСІХ мовах одразу: `html/<мова>` лежить усередині.
        rep.leaks = PUB.guard_site(site, hidden, withheld, guard)
        if rep.leaks:
            shutil.rmtree(site)
            rep.html = None
    return rep


def _mkdocs(cfg_path: Path) -> None:
    """`mkdocs build --clean -q` однієї мови — у цьому ж процесі.

    🔴 Не підпроцес: кожен заново вантажив Python, MkDocs і Material, і сайт
    сімома мовами збирався 14,5 с проти 5,6 с у процесі (замір 19.10.2026).
    Повторна збірка в тому самому процесі — звичайний режим MkDocs: так
    перезбирає `mkdocs serve`.
    """
    import logging

    from mkdocs.commands.build import build as mk_build
    from mkdocs.config import load_config
    from mkdocs.exceptions import MkDocsException

    log = logging.getLogger("mkdocs")
    level = log.level
    # `-q` командного рядка: попередження MkDocs не мають сипатись у вивід nysh.
    log.setLevel(logging.ERROR)
    errors = io.StringIO()
    handler = logging.StreamHandler(errors)
    handler.setLevel(logging.ERROR)
    log.addHandler(handler)
    try:
        mk_build(load_config(str(cfg_path)), dirty=False)
    except (MkDocsException, OSError, ValueError) as exc:
        raise SiteError(f"mkdocs build не зібрав сайт:\n{exc}\n{errors.getvalue()[-2000:]}"
                        ) from exc
    finally:
        log.removeHandler(handler)
        log.setLevel(level)


def _alternate(langs: list[str], current: str) -> list[dict[str, str]]:
    """Посилання перемикача мов відносно кореня поточної збірки."""
    main = langs[0]
    out = []
    for lang in langs:
        if current == main:
            link = "./" if lang == main else f"{lang}/"
        else:
            link = "./" if lang == current else ("../" if lang == main else f"../{lang}/")
        out.append({"name": I18N.NAMES[lang], "link": link, "lang": lang})
    return out


__all__ = ["PAGES", "TEMPLATES", "SiteError", "SiteReport", "build", "default_out",
           "install_assets", "mkdocs_available", "write_pages"]
