"""Перед заливкою: чи названо той опис. Лише попередження — заливку це не зупиняє.

27.09.2026 сімнадцять книг Нікополя поїхали в Супрягу під оп. 1 замість
оп. 3. Під тими номерами в оп. 1 лежать інші села (193-1-201 — Волоське 1866),
тож текст ліг би в каталог під чужою книгою. Ворота це не ловлять і не мусять:
шифра розбирається, опис у ній є — просто не той.

Дві підказки, які людина бачить до заливки:

* **пул** — та сама справа вже є в Супрязі під іншим описом. Це законно (інший
  опис — інша книга), але варто переконатись, що опис названо саме той.
  Перевірка офлайнова (зріз пулу), тож іде на кожному пакуванні;
* **покажчик** (Качиний Інспектор, `sources.duck`) — що за описом фонду лежить
  під цією шифрою: назва й роки поруч із назвою з паспорта. Мережевий запит,
  тому лише в пробному пакуванні й лише коли мережа дозволена.

🔴 Нових відмов тут немає: ворота `share.gates` імпортує сервер, і відмова
вдарила б по всіх клієнтах одразу. А рішення «це та книга» — за людиною.
"""
from __future__ import annotations

from typing import Any

__all__ = ["check"]


def _pool_neighbours(repo: str, fond: str, opys: str, spr: str) -> list[str]:
    """Описи, під якими ця сама справа вже лежить у пулі (крім нашого)."""
    from nyshporka.share import pool

    try:
        cells = pool.by_fond(repo, fond)
    except Exception:       # зріз пулу — підказка, не умова пакування
        return []
    if not cells:
        return []
    i = len(spr)
    while i and not spr[i - 1].isdigit():
        i -= 1
    num, letter = spr[:i], spr[i:]
    return sorted({o for (o, s, lt) in cells
                   if s == num and lt == letter and o and o != opys})


def _duck_card(label: str, fond: str, opys: str, spr: str) -> dict[str, Any] | None:
    """Картка справи з покажчика або `None` (мережа заборонена, справи немає, збій)."""
    from nyshporka.sources.http import offline

    if offline():
        return None
    try:
        from nyshporka.sources.duck import DuckSource

        return DuckSource().case_card(f"{label}-{fond}-{opys}-{spr}")
    except Exception:       # покажчик волонтерський: мовчить — значить не знаємо
        return None


def check(case: dict[str, Any], *, network: bool) -> list[dict[str, str]]:
    """Підказки про опис для блоку `case` маніфесту: `[{code, text}]`."""
    repo = str(case.get("repo") or "")
    fond = str(case.get("fond") or "")
    opys = str(case.get("opys") or "")
    spr = str(case.get("spr") or "")
    shifra = str(case.get("shifra") or "")
    if not (repo and fond and opys and spr):
        return []
    out: list[dict[str, str]] = []

    others = _pool_neighbours(repo, fond, opys, spr)
    if others:
        from nyshporka.library import _REPO_LABEL

        label = _REPO_LABEL.get(repo, repo)
        names = ", ".join(f"«{label} {fond}-{o}-{spr}»" for o in others)
        out.append({"code": "pool_other_opys", "text": (
            f"у Супрязі вже є {names} — справа того самого номера в іншому "
            f"описі. Це інша книга; переконайтесь, що для «{shifra}» опис "
            f"названо саме той")})

    if network:
        from nyshporka.library import _REPO_LABEL

        card = _duck_card(_REPO_LABEL.get(repo, repo), fond, opys, spr)
        if card and card.get("title"):
            years = f", {card['years']}" if card.get("years") else ""
            mine = str(case.get("title") or "").strip()
            mine_years = case.get("years") or []
            mine_txt = (f" У картці — «{mine}»"
                        + (f", {mine_years[0]}–{mine_years[-1]}" if mine_years else "")
                        if mine else "")
            out.append({"code": "pokazhchyk", "text": (
                f"за Качиним Інспектором «{shifra}» — «{card['title']}»{years}."
                f"{mine_txt}. Якщо це різні книги, опис чи номер справи названо "
                f"не той")})
    return out
