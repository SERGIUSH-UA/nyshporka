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
    args=SiteBuildArgs, mutates=True, agent=False, gui=False, section="research")
def site_build(a: SiteBuildArgs) -> Envelope:
    """Канон → сирці MkDocs → HTML; у відкритій версії — сторож по готовому сайту.

    🔴 Витік у відкритій версії — відмова, а не попередження: тека `html`
    видаляється, щоб її не виклали, а відповідь називає кожен витік.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.site import build as B
    from nyshporka.site.config import ConfigError

    root = workspace().root
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
    if not a.public:
        env.warn("private_build", "приватна версія: живі тут є (з датами до десятиліття). "
                                  "Для публікації — nysh site build --public")
    return env
