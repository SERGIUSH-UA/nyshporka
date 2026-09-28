"""🔓 Відкрита версія сайту: роду без живих.

Приватна збірка показує живих із датами до десятиліття. Відкрита — окрема,
де прихованих немає взагалі:

* їхніх сторінок, рядків у покажчиках, імен у дереві й на мапі немає
  (`render.build(hidden=…)`);
* посилання на них у чужих сторінках стають «_приватна особа_»;
* рядок, що й далі називає прихованого (ID у тексті, повне ім'я), викидається
  цілком: у рукописних текстах пишуть «[[ID]] **Ім'я**», і заміна одного
  посилання лишила б ім'я поруч.

🔴 Приймач — не лічильник викинутих рядків, а `guard_site()` по ГОТОВОМУ сайту.

Хто прихований: `private: true`, помер від `died_after`, без дати смерті й
народився від `born_after`, без жодного року — за родиною, плюс поіменно
`extra_hide`; `extra_show` повертає історичних осіб без дат.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from nyshporka.models import Family, Person
from nyshporka.site.config import SiteConfig

#: «Приватна», а не «жива»: прихованим буває й той, про кого нічого не відомо.
LIVING = "_приватна особа_"

#: Межа слова для кирилиці й латинки (`\b` у Python не знає кириличних літер
#: у всіх режимах однаково).
BOUNDARY = r"(?<![0-9A-Za-zА-Яа-яЇїІіЄєҐґЀ-ӿ])"


class Scrubber:
    """Чи згадує текст когось із прихованих — за дослівними формами імен."""

    def __init__(self, probes: dict[str, list[str]] | None = None) -> None:
        parts = [re.escape(text) for values in (probes or {}).values()
                 for text in values if text]
        self._re = (re.compile(BOUNDARY + "(?:" + "|".join(parts) + ")", re.IGNORECASE)
                    if parts else None)

    def hits(self, text: str | None) -> bool:
        return bool(text and self._re and self._re.search(text))

    def first(self, text: str | None) -> str | None:
        m = self._re.search(text) if (text and self._re) else None
        return m.group(0) if m else None


class NameGuard:
    """Дослівні форми плюс основи «ім'я … прізвище».

    🪤 Дослівна форма не бачить відмінка: «…і Марію Коваль» при формі «Марія
    Коваль». Тому ще й основа імені + основа прізвища (між ними дозволене по
    батькові). Основа, під яку підпадає ім'я ОПУБЛІКОВАНОЇ особи, пробою не
    стає — це тезка, такі видно в `ambiguous`.
    """

    def __init__(self, literal: dict[str, list[str]], stems: re.Pattern[str] | None) -> None:
        self._literal = Scrubber(literal)
        self._stems = stems

    def first(self, text: str | None) -> str | None:
        if not text:
            return None
        hit = self._literal.first(text)
        if hit:
            return hit
        m = self._stems.search(text) if self._stems else None
        return m.group(0) if m else None

    def hits(self, text: str | None) -> bool:
        return self.first(text) is not None


def _stem(word: str) -> str:
    word = word.strip()
    return word[:-1] if len(word) <= 5 else word[:-2]


def stem_probes(persons: list[Person], hidden: set[str]) -> tuple[re.Pattern[str] | None, list[str]]:
    """Одна скомпільована альтернатива основ «ім'я … прізвище» + перелік тезок."""
    shown_forms = [n.form for p in persons if p.id not in hidden for n in p.names if n.form]
    parts: list[str] = []
    ambiguous: list[str] = []
    for p in persons:
        if p.id not in hidden:
            continue
        for n in p.names:
            if not (n.given and n.surname) or len(n.given.strip()) < 3 or len(n.surname.strip()) < 4:
                continue
            part = re.escape(_stem(n.given)) + r"\w*\s+(?:\w+\s+)?" + re.escape(_stem(n.surname)) + r"\w*"
            one = re.compile(BOUNDARY + part, re.IGNORECASE)
            if any(one.search(f) for f in shown_forms):
                ambiguous.append(f"{n.given} {n.surname}")
                continue
            parts.append(part)
    rx = (re.compile(BOUNDARY + "(?:" + "|".join(dict.fromkeys(parts)) + ")", re.IGNORECASE)
          if parts else None)
    return rx, sorted(set(ambiguous))


def literal_probes(persons: list[Person], hidden: set[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Повні форми імен прихованих (з пробілом) — без тих, що є в опублікованих.

    Саме прізвище пробою не стає: воно стоїть на кожній сторінці роду. Форма,
    ТАК САМО записана в опублікованої особи, — тезка, і пробою бути не може:
    інакше скрабер вирізав би її власну сторінку аж до заголовка.
    """
    shown = {n.form.strip() for p in persons if p.id not in hidden for n in p.names if n.form}
    probes: dict[str, list[str]] = {}
    ambiguous: set[str] = set()
    for p in persons:
        if p.id not in hidden:
            continue
        forms = [n.form for n in p.names if n.form and " " in n.form.strip()]
        ambiguous.update(f for f in forms if f.strip() in shown)
        probes[p.id] = list(dict.fromkeys(f for f in forms if f.strip() not in shown))
    return probes, sorted(ambiguous)


def _year(p: Person, kind: str) -> int | None:
    for f in p.facts:
        if f.type == kind and f.date and f.date.value[:4].isdigit():
            return int(f.date.value[:4])
    return None


def hidden_ids(persons: list[Person], cfg: SiteConfig,
               lived_from: dict[str, int | None] | None = None,
               families: list[Family] | None = None) -> set[str]:
    """Кого на відкритому сайті немає.

    * `private: true`;
    * помер від `died_after` — у нього найближчі живі;
    * без дати смерті й народився від `born_after`;
    * без жодного власного року — вирішує РОДИНА: батько чи мати від
      `born_after − 20`, чоловік/дружина серед прихованих, дитина від
      `born_after + 25` → прихований. 🪤 Оцінка життя з індексу тут бреше на
      десятиліття, тож вона лише останній засіб: коли родина мовчить —
      найраніший факт (доросла роль: мінус 15 років) і оцінка життя; не знає
      ніхто — прихований.
    """
    lived_from = lived_from or {}
    fams = {f.id: f for f in (families or [])}
    by_id = {p.id: p for p in persons}
    show = set(cfg.extra_show)
    out = set(cfg.extra_hide) - show

    def born(p: Person) -> int | None:
        return _year(p, "birth") or _year(p, "baptism")

    undated: list[Person] = []
    for p in persons:
        if p.id in show:
            continue
        if p.private:
            out.add(p.id)
            continue
        died = _year(p, "death")
        if died is not None:
            if died >= cfg.died_after:
                out.add(p.id)
            continue
        if _year(p, "burial") is not None:
            continue
        b = born(p)
        if b is not None:
            if b >= cfg.born_after:
                out.add(p.id)
            continue
        undated.append(p)

    def near_living(p: Person) -> bool:
        fam = fams.get(p.parent_family) if p.parent_family else None
        for par in (fam.husband, fam.wife) if fam else ():
            if par and (par in out or (born(by_id[par]) or 0) >= cfg.born_after - 20
                        if par in by_id else False):
                return True
        for sf in p.spouse_families:
            fm = fams.get(sf)
            for sp in (fm.husband, fm.wife) if fm else ():
                if sp and sp != p.id and (sp in out or (born(by_id[sp]) or 0) >= cfg.born_after - 10
                                          if sp in by_id else False):
                    return True
            for ch in fm.children if fm else ():
                if ch in by_id and (born(by_id[ch]) or 0) >= cfg.born_after + 25:
                    return True
        return False

    changed = True
    while changed:
        changed = False
        for p in undated:
            if p.id not in out and near_living(p):
                out.add(p.id)
                changed = True

    for p in undated:
        if p.id in out:
            continue
        years = [int(f.date.value[:4]) for f in p.facts if f.date and f.date.value[:4].isdigit()]
        if years and min(years) - 15 < cfg.born_after:
            continue
        est = lived_from.get(p.id)
        if est is None or est >= cfg.born_after:
            out.add(p.id)
    return out


def lived_from(root: Path) -> dict[str, int | None]:
    tree = root / "data" / "derived" / "tree.json"
    if not tree.is_file():
        return {}
    nodes = json.loads(tree.read_text(encoding="utf-8")).get("nodes", [])
    return {n["id"]: n.get("lived_from") for n in nodes}


def scrub_markdown(text: str, persons: set[str], sources: set[str] | frozenset[str] = frozenset(),
                   scrubber: Scrubber | NameGuard | None = None,
                   aliases: dict[str, str] | None = None) -> tuple[str, int]:
    """Прибрати прихованих із markdown. Повертає (текст, скільки рядків викинуто).

    1. `[Ім'я](../persons/ID.md)` → «_приватна особа_», `` `ID` `` — геть;
    2. зноска на неопубліковане джерело `[^S_X]` → нейтральний ключ: ключ
       усного свідчення часто сам називає людину;
    3. рядок, де ID прихованої особи чи неопублікованого джерела лишився, або
       є повне ім'я прихованого, — викидається цілком.
    """
    if not persons and not sources:
        return text, 0
    pid = "|".join(sorted(persons)) or "(?!)"
    link = re.compile(r"\[[^\]\n]*\]\((?:\.\./)*(?:persons/)?(?:" + pid + r")\.md(?:#[^)\s]*)?\)")
    tick = re.compile(r"(?:\s+—\s+)?`(?:" + pid + r")`")
    src = "|".join(sorted(sources)) or "(?!)"
    note = re.compile(r"\[\^(" + src + r")\]")
    mention = re.compile(r"(?<!\w)(?:" + "|".join(sorted(persons | set(sources))) + r")(?!\w)")
    aliases = aliases if aliases is not None else {}

    def _alias(m: re.Match[str]) -> str:
        sid = m.group(1)
        if sid not in aliases:
            aliases[sid] = f"nd{len(aliases) + 1}"
        return f"[^{aliases[sid]}]"

    out: list[str] = []
    dropped = 0
    for line in text.splitlines(keepends=True):
        line2 = note.sub(_alias, tick.sub("", link.sub(LIVING, line)))
        if mention.search(line2) or (scrubber is not None and scrubber.hits(line2)):
            dropped += 1
            continue
        out.append(line2)
    return "".join(out), dropped


def scrub_events(path: Path, ids: set[str], scrubber: Scrubber | NameGuard) -> int:
    """Події дерева несуть повний текст факту — викинути ті, що називають прихованих."""
    if not path.is_file() or not ids:
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("events")
    if not isinstance(events, list):
        return 0
    rx = re.compile(r"(?<!\w)(?:" + "|".join(sorted(ids)) + r")(?!\w)")
    kept = [e for e in events
            if not (rx.search(blob := json.dumps(e, ensure_ascii=False)) or scrubber.hits(blob))]
    data["events"] = kept
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return len(events) - len(kept)


def guard_site(site: Path, hidden: set[str], withheld: set[str],
               guard: NameGuard) -> list[str]:
    """Приймач по ГОТОВОМУ сайту: жодного імені прихованого — ніде; жодного ID
    прихованого чи неопублікованого джерела — у сторінках і пошуковому індексі.

    ID у tree.json/graph.json лишаються навмисно: там приховані — вузли без
    імені, і без них дерево розривається.
    """
    ids = hidden | withheld
    rx = re.compile(r"(?<!\w)(?:" + "|".join(sorted(ids)) + r")(?!\w)") if ids else None
    problems: list[str] = []
    for f in sorted(site.rglob("*")):
        if f.suffix not in (".html", ".json", ".geojson", ".xml"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        rel = f.relative_to(site).as_posix()
        name = guard.first(text)
        if name:
            problems.append(f"{rel}: ім'я «{name}»")
        if rx and (f.suffix == ".html" or rel.startswith("search/")):
            m = rx.search(text)
            if m:
                problems.append(f"{rel}: ID {m.group(0)}")
    return problems
