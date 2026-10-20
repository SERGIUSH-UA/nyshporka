"""⚙️🌐 Сайт роду з канону: зібрати теку зі статикою.

🔴 `agent=False` — стартовий перелік агента (`nysh ops --agent`) тримається
коротким; агентові вистачає `nysh site build`. Викладати сайт пакет не вміє й не буде: куди — GitHub Pages,
Cloudflare Pages, власний сервер — вирішує людина.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class SiteBuildArgs(BaseModel):
    public: bool = Field(default=False,
                         description="відкрита версія: без живих і близьких до живих, зі сторожем витоків")
    out: str = Field(default="", description="тека збірки; порожньо — <простір>/site/private|public")
    force: bool = Field(default=False, description="перезаписати непорожню теку, яка не є збіркою сайту")
    html: bool = Field(default=True, description="false — лише сирці MkDocs, без HTML")


@op("site.build", summary="Зібрати сайт роду з канону (приватний або відкритий)",
    args=SiteBuildArgs, mutates=True, gui=False, section="research",
    scope="project", skill="build-site",
    when="зібрати сайт роду з канону")
def site_build(a: SiteBuildArgs) -> Envelope:
    """Канон → сирці MkDocs → HTML; у відкритій версії — сторож по готовому сайту.

    🔴 Витік у відкритій версії — відмова, а не попередження: тека `html`
    видаляється, щоб її не виклали, а відповідь називає кожен витік.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.site import build as B
    from nyshporka.site.config import ConfigError

    root = workspace().proot
    if a.public and not a.html:
        # Сирці відкритої версії без HTML сторож не перевіряє — і саме їх
        # потім збирають і викладають іншим інструментом.
        return fail("відкрита версія збирається лише з HTML: без нього сторож не має "
                    "що перевірити")
    try:
        rep = B.build(root, public=a.public, out=Path(a.out).expanduser() if a.out else None,
                      force=a.force, html=a.html)
    except (B.SiteError, ConfigError) as exc:
        return fail(str(exc))
    if rep.leaks:
        env = fail(f"відкрита версія називає прихованих ({len(rep.leaks)} місць) — HTML "
                   f"видалено, викладати нічого. Перше: {rep.leaks[0]}")
        env.data = rep.as_dict()
        return env
    env = ok(rep.as_dict())
    if rep.warnings:
        env.warn("canon_warnings", f"у каноні {rep.warnings} попереджень (`nysh canon check`) — "
                                   f"сайт зібрано, але їх варто розібрати")
    if rep.ambiguous:
        env.warn("namesakes", f"тезки прихованих і опублікованих ({len(rep.ambiguous)}): "
                              f"їхні імена пробою не стали — перегляньте сторінки оком")
    if rep.skipped:
        env.warn("overlay_skipped", f"у відкриту версію не пішли файли з overlay, крім сторінок "
                                    f".md ({len(rep.skipped)}): {', '.join(rep.skipped[:5])}")
    if rep.private_sources:
        env.warn("private", f"джерела приватних справ у відкриту версію не пішли — ні шифра, "
                            f"ні кропи карток, що їх цитують ({len(rep.private_sources)}): "
                            f"{', '.join(rep.private_sources[:5])}. Відкрити справу: "
                            f"nysh case <тека> --public")
    if not a.public:
        env.warn("private_build", "приватна версія: живі тут є (з датами до десятиліття). "
                                  "Для публікації — nysh site build --public")
    return env


#: Адреса збірки в консолі (`nysh serve`): приватна й відкрита версії.
SITE_URL = {False: "/site/", True: "/site-public/"}


def site_url(public: bool) -> str:
    """Адреса сайту поточного проєкту в консолі.

    Демон один на Майстерню, тож сайт проєкту-підтеки — під префіксом
    `/p/<id>/`: відносні посилання сторінок сайту заголовка проєкту не несуть.
    """
    from urllib.parse import quote

    from nyshporka.core.workspace import workspace

    project = workspace().project
    return (f"/p/{quote(project)}" if project else "") + SITE_URL[public]


class SiteStatusArgs(BaseModel):
    pass


@op("site.status", summary="Що зібрано з сайту роду: коли, скільки осіб, де відкрити",
    args=SiteStatusArgs, mutates=False, section="research",
    scope="project", skill="build-site",
    when="що зібрано з сайту роду: коли, скільки осіб")
def site_status(_a: SiteStatusArgs) -> Envelope:
    """Обидві версії сайту: чи є HTML, коли зібрано, лічильники й адреса в консолі.

    Лічильники — з `assets/stats.json` самої збірки, тобто те, що реально на
    сайті, а не те, що в каноні зараз: різниця й каже, що пора перезібрати.
    """
    import json
    from datetime import UTC, datetime

    from nyshporka.core.workspace import workspace
    from nyshporka.site import build as B

    root = workspace().proot
    canon = root / "data" / "canonical" / "persons"
    in_canon = sum(1 for _ in canon.glob("*.md")) if canon.is_dir() else 0
    out: dict[str, object] = {"canon_persons": in_canon, "mkdocs": B.mkdocs_available()}
    for public in (False, True):
        html = B.default_out(root, public) / "html"
        index = html / "index.html"
        info: dict[str, object] = {"built": index.is_file(), "url": site_url(public),
                                   "path": str(html)}
        if index.is_file():
            info["built_at"] = datetime.fromtimestamp(index.stat().st_mtime, UTC).isoformat(
                timespec="seconds")
            stats = html / "assets" / "stats.json"
            try:
                info["counts"] = json.loads(stats.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info["counts"] = {}
        out["public" if public else "private"] = info
    return ok(out)


class SiteRebuildArgs(BaseModel):
    public: bool = Field(default=False, description="відкрита версія (зі сторожем витоків)")


@op("site.rebuild", summary="Перезібрати сайт роду з консолі — роботою в черзі",
    args=SiteRebuildArgs, mutates=True, long=True, section="research",
    tier="rare", scope="project", skill="build-site")
def site_rebuild(a: SiteRebuildArgs) -> Envelope:
    """Та сама збірка, що `site.build`, але роботою: з поступом у «Роботах» і без
    завислої вкладки — MkDocs на кількасот сторінок іде хвилини.

    `force` тут немає навмисно: кнопка в консолі не перезаписує чужу теку.
    """
    from nyshporka.core.progress import report

    report(0, 1, "збірка сайту")
    env = site_build(SiteBuildArgs(public=a.public))
    report(1, 1, "збірка сайту")
    if env.ok:
        env.data["url"] = site_url(a.public)
    return env
