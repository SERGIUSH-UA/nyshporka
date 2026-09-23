"""Перетворити зібраний сайт на заглушки, що ведуть на nyshporka.online/docs/.

    DOCS_SITE_URL=https://nyshporka.online/docs/ mkdocs build --strict
    python tools/docs_redirect_stubs.py site https://nyshporka.online/docs/

З 2026-09-23 документація живе на nyshporka.online/docs/ — усередині порталу,
бо окремий домен пошуковик рахує окремим сайтом, і портал не дістає її
ваги. Старі адреси на github.io роздані роками: у README, у описах відео, у
release notes, на форумах. Ламати їх не можна.

🔴 GitHub Pages не вміє віддати 301. Тому кожна сторінка стає заглушкою з
`<link rel="canonical">` і `<meta http-equiv="refresh">` на ту саму сторінку
в новій адресі плюс звичайним посиланням для того, хто вимкнув переадресацію.
Пошуковик зводить таку пару до нової адреси, людина потрапляє туди ж, куди
йшла, а не на головну документації.

Не-HTML (картинки, CSS, пошуковий індекс) лишається як є: на них ніхто не
посилається ззовні, і прибирати їх — зайва робота без виграшу.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

SHABLON = """<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Документація Нишпорки переїхала</title>
<link rel="canonical" href="{url}">
<meta http-equiv="refresh" content="0; url={url}">
<meta name="robots" content="noindex, follow">
</head>
<body>
<p>Документація Нишпорки переїхала: <a href="{url}">{url}</a></p>
</body>
</html>
"""


def zahlushky(site: Path, base: str) -> int:
    base = base.rstrip("/") + "/"
    n = 0
    for page in site.rglob("*.html"):
        rel = page.relative_to(site).as_posix()
        # `faq/index.html` → `faq/`: MkDocs роздає сторінки теками, і саме
        # такі адреси розійшлися по світу.
        if rel == "index.html":
            rel = ""
        elif rel.endswith("/index.html"):
            rel = rel[: -len("index.html")]
        page.write_text(SHABLON.format(url=html.escape(base + rel)), encoding="utf-8")
        n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("вжиток: docs_redirect_stubs.py <тека сайту> <нова адреса>")
    print(f"заглушок: {zahlushky(Path(sys.argv[1]), sys.argv[2])}")
