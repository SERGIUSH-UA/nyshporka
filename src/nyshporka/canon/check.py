"""🩺 Перевірка канону: чи цілий він після правки.

Канон правлять файлами (агент або людина), тож після кожної правки питання одне:
чи не зламали ми щось поруч. Модель pydantic ловить лише форму однієї картки.
Усе, що лежить МІЖ картками, — зв'язки в обидва боки, хронологія родини,
існування місця й джерела, файл доказу на диску — видно тільки звідси.

Рівні:

* `ERROR` — канон бреше або не читається: неіснуючий ID, картка не за схемою,
  народження після смерті, доказ, якого немає на диску. Код повернення 1.
* `WARN` — підозріло, але буває правдою: однобічний зв'язок, вік батька 72,
  факт `confirmed` без цитати.
* `INFO` — довідка: особа без жодних зв'язків.

🔴 Одна зіпсована картка не валить перевірку: вона стає рядком ERROR, решта
канону перевіряється далі. Інакше перша ж помилка ховала б усі наступні, і
виправлення йшло б по одній за прогін.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from nyshporka.models import Family, GedDate, Hypothesis, Person, Place, Source
from nyshporka.models.hypothesis import MAX_HITS
from nyshporka.storage.files import read_entity

Severity = Literal["ERROR", "WARN", "INFO"]

KINDS: dict[str, type[BaseModel]] = {
    "persons": Person,
    "families": Family,
    "places": Place,
    "sources": Source,
    "hypotheses": Hypothesis,
}

#: Посилання в тексті картки: `[[I1234]]`, `[[S_ARCHIVE_X]]`.
WIKILINK = re.compile(r"\[\[([A-Za-z0-9_]+)\]\]")

#: Шляхи доказів у тексті картки. У бектіках — цілком (там бувають пробіли),
#: голий — до роздільника, YAML-поле — до кінця рядка.
_IN_TICKS = re.compile(r"`(data/source/[^`]+)`")
_BARE = re.compile(r"(?<![`\w])(data/source/[^\s\"'`)\]]+)")
_YAML_FIELD = re.compile(
    r"^\s*(?:raw_path|path|secured_to):\s*['\"]?(data/source/[^'\"]+?)['\"]?\s*$",
    re.MULTILINE)
#: Те, що схоже на шлях, але ним не є: шаблон `<year>`, перелік `{a,b}`,
#: діапазон сторінок `p253-255`.
_TEMPLATE = re.compile(r"[<>{}]")
_RANGE_TAIL = re.compile(r"_p?\d+-\d+(\.\w+)?$")

#: Межі віку батьків при народженні дитини. Нижче 14 — помилка (не буває),
#: вище — попередження (буває, але рідко й варте другого погляду).
MIN_PARENT_AGE = 14
MAX_FATHER_AGE = 70
MAX_MOTHER_AGE = 50
MAX_LIFESPAN = 110

#: Роль і вид факту в реченні для людини (`Issue.say`); у `text` лишаються поля.
_ROLE_UK = {"husband": "Чоловік", "wife": "Дружина",
            "hypothetical_husband": "Гіпотетичний чоловік",
            "hypothetical_wife": "Гіпотетична дружина",
            "батько": "Батько", "мати": "Мати"}
_FACT_UK = {"birth": "народження", "death": "смерті", "marriage": "шлюбу",
            "divorce": "розлучення", "residence": "проживання", "occupation": "заняття",
            "education": "освіти", "baptism": "хрещення", "burial": "поховання",
            "emigration": "еміграції", "military": "служби", "religion": "віри",
            "nationality": "народності", "other": "іншого виду"}

#: Хто без дати смерті й народжений не раніше стількох років тому, імовірно живий.
LIVING_WINDOW = 100

#: Рівні доказу, з якими `confirmed` чесний. Решта — підстава для гіпотези.
STRONG_CONFIDENCE = frozenset({"direct", "indirect"})


@dataclass(frozen=True)
class Issue:
    """Одна знахідка перевірки.

    `text` — для того, хто правитиме картку: назви полів, ID, як у файлі.
    `say` — те саме реченням для людини в консолі, `who` — про кого воно
    (особа, а не родина, де знахідку знайдено). 🔴 Консоль показувала `text`, і
    дослідник читав «parent_family і hypothetical_parent_family», «wife … у
    віці 7», «мав(ла) 51 років» (прохід канону 22.10.2026). `text` не чіпаємо:
    за ним агент знаходить, яке поле правити.
    """

    severity: Severity
    code: str
    where: str
    text: str
    say: str = ""
    who: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"severity": self.severity, "code": self.code,
               "where": self.where, "text": self.text}
        if self.say:
            out["say"] = self.say
        if self.who:
            out["who"] = self.who
        return out


@dataclass
class Canon:
    """Прочитаний канон: сутності за ID і файли, які не прочитались."""

    root: Path
    persons: dict[str, Person] = field(default_factory=dict)
    families: dict[str, Family] = field(default_factory=dict)
    places: dict[str, Place] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    #: ID → файл, звідки його взято (для повідомлень).
    files: dict[str, Path] = field(default_factory=dict)

    @property
    def canonical(self) -> Path:
        return self.root / "data" / "canonical"

    def all_ids(self) -> set[str]:
        return (set(self.persons) | set(self.families) | set(self.places)
                | set(self.sources) | set(self.hypotheses))

    def counts(self) -> dict[str, int]:
        return {"persons": len(self.persons), "families": len(self.families),
                "places": len(self.places), "sources": len(self.sources),
                "hypotheses": len(self.hypotheses)}


@dataclass
class Report:
    canon: Canon
    issues: list[Issue] = field(default_factory=list)
    hashed: bool = False

    def add(self, severity: Severity, code: str, where: str, text: str,
            *, say: str = "", who: str = "") -> None:
        self.issues.append(Issue(severity, code, where, text, say, who))

    def count(self, severity: Severity) -> int:
        return sum(1 for i in self.issues if i.severity == severity)

    @property
    def ok(self) -> bool:
        return self.count("ERROR") == 0

    def as_dict(self) -> dict[str, Any]:
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        return {
            "root": str(self.canon.canonical),
            "loaded": self.canon.counts(),
            "errors": self.count("ERROR"),
            "warnings": self.count("WARN"),
            "info": self.count("INFO"),
            "hashed": self.hashed,
            "issues": [i.as_dict() for i in sorted(
                self.issues, key=lambda i: (order[i.severity], i.code, i.where))],
        }


# ── читання ──────────────────────────────────────────────────────────────────
def load(root: Path, report: Report | None = None) -> Canon:
    """Прочитати весь канон; збій картки — рядок звіту, а не виняток."""
    canon = Canon(root=root)
    for kind, model in KINDS.items():
        folder = canon.canonical / kind
        if not folder.is_dir():
            continue
        bucket: dict[str, Any] = getattr(canon, kind)
        for path in sorted(folder.glob("*.md")):
            rel = _rel(root, path)
            try:
                entity = read_entity(path, model)
            except ValidationError as exc:
                if report is not None:
                    report.add("ERROR", "schema", rel, _short_validation(exc))
                continue
            except Exception as exc:  # битий YAML, кодування
                if report is not None:
                    report.add("ERROR", "unreadable", rel, f"{type(exc).__name__}: {exc}")
                continue
            eid: str = entity.id  # type: ignore[attr-defined]
            if eid in bucket:
                if report is not None:
                    report.add("ERROR", "duplicate_id", rel,
                               f"ID {eid} уже є в {_rel(root, canon.files[eid])}")
                continue
            # 🔴 Ім'я файлу мусить збігатися з ID: за іменем файлу картку
            # шукають і агент, і посилання `[[…]]` на сайті. Розбіжність
            # з'являється, коли картку копіюють як заготовку й забувають id.
            if path.stem != eid and report is not None:
                report.add("ERROR", "file_name", rel,
                           f"у файлі id «{eid}», а ім'я файлу «{path.stem}»")
            bucket[eid] = entity
            canon.files[eid] = path
    return canon


def _short_validation(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors()[:4]:
        loc = ".".join(str(x) for x in e.get("loc", ()))
        parts.append(f"{loc}: {e.get('msg', '')}")
    more = len(exc.errors()) - 4
    return "; ".join(parts) + (f" (і ще {more})" if more > 0 else "")


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def year_of(date: GedDate | None) -> int | None:
    if date is None or not date.value:
        return None
    m = re.match(r"^(\d{4})", date.value)
    return int(m.group(1)) if m else None


# ── перевірка ────────────────────────────────────────────────────────────────
def check(root: Path, *, hash_evidence: bool = False) -> Report:
    report = Report(canon=Canon(root=root), hashed=hash_evidence)
    canon = load(root, report)
    report.canon = canon
    _links(canon, report)
    _chronology(canon, report)
    _refs(canon, report)
    _citations(canon, report)
    _hypotheses(canon, report)
    _evidence(canon, report, hash_evidence)
    _regions(canon, report)
    _orphans(canon, report)
    return report


def _regions(c: Canon, r: Report) -> None:
    """Коди регіонів у покритті джерел — ті, що є в `regions.yml`.

    Без цього індекс падає на першому ж невідомому коді, і людина бачить трасу
    замість рядка «ось яке джерело й який код».
    """
    spans = [(sid, span.region) for sid, s in c.sources.items() for span in s.coverage]
    if not spans:
        return
    path = c.canonical / "regions.yml"
    if not path.is_file():
        r.add("ERROR", "regions", "regions.yml",
              f"{len(spans)} спанів покриття мають коди регіонів, а реєстру "
              f"data/canonical/regions.yml немає")
        return
    from nyshporka.models import load_regions

    try:
        codes = load_regions(c.root).codes()
    except Exception as exc:
        r.add("ERROR", "regions", "regions.yml", f"реєстр не читається: {exc}")
        return
    for sid, code in spans:
        if code not in codes:
            r.add("ERROR", "regions", sid, f"код регіону «{code}» відсутній у regions.yml")


def _links(c: Canon, r: Report) -> None:
    """Зв'язки особа ↔ родина: існування, обидва боки, стать."""
    P, F = c.persons, c.families
    for pid, p in P.items():
        if p.parent_family and p.parent_family not in F:
            r.add("ERROR", "missing_ref", pid, f"parent_family → немає {p.parent_family}")
        if p.hypothetical_parent_family and p.hypothetical_parent_family not in F:
            r.add("ERROR", "missing_ref", pid,
                  f"hypothetical_parent_family → немає {p.hypothetical_parent_family}")
        for fid in p.spouse_families:
            if fid not in F:
                r.add("ERROR", "missing_ref", pid, f"spouse_families → немає {fid}")
        for fid in p.hypothetical_spouse_families:
            if fid not in F:
                r.add("ERROR", "missing_ref", pid, f"hypothetical_spouse_families → немає {fid}")
            if fid in p.spouse_families:
                r.add("WARN", "both_levels", pid,
                      f"{fid} і в spouse_families, і в hypothetical_spouse_families",
                      say="Шлюб записано і як доведений, і як гіпотетичний")
        if p.parent_family and p.parent_family == p.hypothetical_parent_family:
            r.add("WARN", "both_levels", pid,
                  "parent_family і hypothetical_parent_family вказують на одну родину",
                  say="Батьківську родину записано і як доведену, і як гіпотетичну")
        # Зворотний бік: особа каже «я в родині», а родина про неї не знає.
        if p.parent_family in F:
            fam = F[p.parent_family]
            if pid not in fam.children:
                r.add("WARN", "one_sided", pid,
                      f"parent_family = {fam.id}, але в {fam.id}.children її немає",
                      say=f"Батьківська родина {fam.id} не має цієї особи серед дітей")
        for fid in p.spouse_families:
            if fid in F and pid not in (F[fid].husband, F[fid].wife):
                r.add("WARN", "one_sided", pid,
                      f"spouse_families містить {fid}, але там вона не чоловік і не дружина",
                      say=f"У шлюбі {fid} ця особа не записана ні чоловіком, ні дружиною")

    for fid, f in F.items():
        for role, who, bad_sex in (("husband", f.husband, "F"), ("wife", f.wife, "M")):
            if not who:
                continue
            if who not in P:
                r.add("ERROR", "missing_ref", fid, f"{role} → немає {who}")
                continue
            if P[who].sex == bad_sex:
                r.add("ERROR", "sex", fid, f"{role} {who} має sex={bad_sex}")
            if fid not in P[who].spouse_families:
                r.add("WARN", "one_sided", fid,
                      f"{role} {who} не має {fid} у spouse_families",
                      say=f"{_ROLE_UK[role]} у родині, але в картці особи цього шлюбу немає",
                      who=who)
        for cid in f.children:
            if cid not in P:
                r.add("ERROR", "missing_ref", fid, f"children → немає {cid}")
            elif P[cid].parent_family != fid:
                r.add("WARN", "one_sided", fid,
                      f"children містить {cid}, але в нього parent_family = "
                      f"{P[cid].parent_family}",
                      say=f"Дитина в родині {fid}, а в картці дитини батьківська родина інша",
                      who=cid)
        for role, who, bad_sex in (("hypothetical_husband", f.hypothetical_husband, "F"),
                                   ("hypothetical_wife", f.hypothetical_wife, "M")):
            if not who:
                continue
            if who not in P:
                r.add("ERROR", "missing_ref", fid, f"{role} → немає {who}")
                continue
            if P[who].sex == bad_sex:
                r.add("ERROR", "sex", fid, f"{role} {who} має sex={bad_sex}")
            if (fid not in P[who].hypothetical_spouse_families
                    and fid not in P[who].spouse_families):
                r.add("WARN", "one_sided", fid,
                      f"{role} {who} не має {fid} у (hypothetical_)spouse_families",
                      say=f"{_ROLE_UK[role]} у родині, але в картці особи цього шлюбу немає",
                      who=who)
        for cid in f.hypothetical_children:
            if cid not in P:
                r.add("ERROR", "missing_ref", fid, f"hypothetical_children → немає {cid}")
            elif fid not in (P[cid].hypothetical_parent_family, P[cid].parent_family):
                r.add("WARN", "one_sided", fid,
                      f"hypothetical_children містить {cid}, але його "
                      f"(hypothetical_)parent_family вказує деінде",
                      say=f"Гіпотетична дитина родини {fid}, а в картці дитини "
                          f"батьківська родина інша",
                      who=cid)


def _chronology(c: Canon, r: Report) -> None:
    births: dict[str, int | None] = {}
    deaths: dict[str, int | None] = {}
    for pid, p in c.persons.items():
        for kind, store in (("birth", births), ("death", deaths)):
            facts = [f for f in p.facts if f.type == kind]
            years = sorted(y for y in {year_of(f.date) for f in facts} if y is not None)
            if len(years) > 1:
                r.add("ERROR", "conflict", pid, f"кілька {kind} з різними роками {years}",
                      say=f"Роки {_FACT_UK[kind]} розходяться: "
                          f"{', '.join(str(y) for y in years)}")
            elif len(facts) > 1:
                r.add("WARN", "duplicate_fact", pid, f"{len(facts)} фактів {kind} (дубль?)",
                      say=f"Фактів {_FACT_UK[kind]}: {len(facts)} — можливо, дубль")
            store[pid] = year_of(facts[0].date) if facts else None
        by, dy = births[pid], deaths[pid]
        # Приватна збірка сайту ховає живих лише за позначкою `private`, тож
        # імовірно живий без неї — це дати й нотатки живої людини на сторінці.
        if (by and not dy and not p.private
                and by >= date.today().year - LIVING_WINDOW
                and not any(f.type == "burial" for f in p.facts)):
            r.add("WARN", "maybe_living", pid,
                  f"народжений {by}, смерті немає, а private: false — якщо живий, "
                  f"позначити private: true",
                  say=f"Народження {by}, смерті немає — можливо, живий, а на сайті "
                      f"не прихований")
        if by and dy and by > dy:
            r.add("ERROR", "chronology", pid, f"народження {by} пізніше за смерть {dy}",
                  say=f"Народження {by} пізніше за смерть {dy}")
        elif by and dy and dy - by > MAX_LIFESPAN:
            r.add("WARN", "chronology", pid, f"прожив {dy - by} років",
                  say=f"Тривалість життя {dy - by} (роки {by}–{dy})")

    for fid, f in c.families.items():
        married = [y for y in (year_of(m.date) for m in f.facts if m.type == "marriage") if y]
        my = min(married) if married else None
        if my:
            for role, who in (("husband", f.husband), ("wife", f.wife)):
                by = births.get(who) if who else None
                dy = deaths.get(who) if who else None
                if by and my < by:
                    r.add("ERROR", "chronology", fid,
                          f"шлюб {my} раніше за народження {role} {who} ({by})",
                          say=f"Шлюб {my} раніше за народження ({by})", who=who)
                elif by and my - by < MIN_PARENT_AGE:
                    r.add("WARN", "chronology", fid,
                          f"{role} {who} у шлюбі у віці {my - by}",
                          say=f"{_ROLE_UK[role]} у шлюбі у віці {my - by} "
                              f"(народж. {by}, шлюб {my})",
                          who=who)
                if dy and my > dy:
                    r.add("ERROR", "chronology", fid,
                          f"шлюб {my} після смерті {role} {who} ({dy})",
                          say=f"Шлюб {my} після смерті ({dy})", who=who)
        for cid in f.children:
            cy = births.get(cid)
            if not cy:
                continue
            for role, who, top in (("батько", f.husband, MAX_FATHER_AGE),
                                   ("мати", f.wife, MAX_MOTHER_AGE)):
                by = births.get(who) if who else None
                dy = deaths.get(who) if who else None
                if by:
                    age = cy - by
                    # Дитина в реченні — іменем у називному: ID підміняє консоль.
                    said = f"{_ROLE_UK[role]} у віці {age}, дитина {cid} народжена {cy}"
                    if age < MIN_PARENT_AGE:
                        r.add("ERROR", "chronology", fid,
                              f"{role} {who} мав(ла) {age} років при народженні {cid}",
                              say=said, who=who)
                    elif age > top:
                        r.add("WARN", "chronology", fid,
                              f"{role} {who} мав(ла) {age} років при народженні {cid}",
                              say=said, who=who)
                # +1 рік на посмертне народження; для матері це неможливо.
                if dy and cy > dy + 1:
                    sev: Severity = "ERROR" if role == "мати" else "WARN"
                    died = "помер" if role == "батько" else "померла"
                    r.add(sev, "chronology", fid,
                          f"{role} {who} помер(ла) {dy}, а {cid} народився {cy}",
                          say=f"{_ROLE_UK[role]} {died} {dy}, а дитина {cid} народжена {cy}",
                          who=who)


def _facts(c: Canon) -> Iterable[tuple[str, Any]]:
    for pid, p in c.persons.items():
        for f in p.facts:
            yield pid, f
    for fid, fam in c.families.items():
        for f in fam.facts:
            yield fid, f


def _refs(c: Canon, r: Report) -> None:
    """Місця, джерела й `[[…]]` вказують на те, що є."""
    for owner, f in _facts(c):
        if f.place_id and f.place_id not in c.places:
            r.add("ERROR", "missing_ref", owner, f"{f.type}: place_id {f.place_id} не існує")
        for cit in f.citations:
            if cit.source_id not in c.sources:
                r.add("ERROR", "missing_ref", owner,
                      f"{f.type}: цитата на джерело {cit.source_id}, якого немає")
    known = c.all_ids()
    for eid, path in c.files.items():
        text = path.read_text(encoding="utf-8")
        for m in sorted(set(WIKILINK.findall(text))):
            if m not in known:
                r.add("WARN", "wikilink", eid, f"[[{m}]] → такого ID немає",
                      say=f"Посилання на {m}, а такої картки немає")


def _citations(c: Canon, r: Report) -> None:
    """Статус факту має спиратись на доказ відповідної сили."""
    for owner, f in _facts(c):
        if f.status != "confirmed":
            continue
        if not f.citations:
            r.add("WARN", "uncited", owner,
                  f"{f.type}: confirmed без жодної цитати — у дереві виглядає як доведений",
                  say=f"Факт {_FACT_UK[f.type]} позначено доведеним, а джерела немає")
        elif not any(ci.confidence in STRONG_CONFIDENCE for ci in f.citations):
            r.add("WARN", "weak_confirmed", owner,
                  f"{f.type}: confirmed, але цитати лише "
                  f"{sorted({ci.confidence for ci in f.citations})}",
                  say=f"Факт {_FACT_UK[f.type]} позначено доведеним, а джерела лише "
                      f"непрямі чи слабкі")


# ── гіпотези ─────────────────────────────────────────────────────────────────
#: Відкрита гіпотеза, якої не торкались стільки днів, — напевно, забута.
STALE_DAYS = 60


def _hypotheses(c: Canon, r: Report) -> None:
    """Кожна відкрита гіпотеза каже, що її розв'яже; кожен спірний факт — на гіпотезі.

    🔴 Це правила-ERROR навмисно: правило в нотатках агент забуває через десять
    кроків, а git-хук канону не пускає в коміт картку з помилкою. Тож спірний
    факт без гіпотези чи гіпотеза без «що розв'яже» не лягають у канон узагалі.
    """
    from nyshporka.core import casekey

    known = c.all_ids()
    for hid, h in c.hypotheses.items():
        if h.status != "closed" and not h.decides.strip():
            r.add("ERROR", "hyp_no_decides", hid,
                  "відкрита гіпотеза без `decides`: який документ чи рядок її розв'яже")
        if h.status == "closed" and not (h.verdict.strip() and h.reopen_if.strip()):
            r.add("ERROR", "hyp_no_reopen", hid,
                  "закрита гіпотеза без `verdict` (хто й коли вирішив) або `reopen_if` "
                  "(який новий доказ її відкриває)")
        if h.status == "awaiting" and not h.hits:
            r.add("ERROR", "hyp_awaiting_no_hits", hid,
                  "чекає вердикту, але хітів немає — на що тоді дивитись людині")
        if len(h.hits) > MAX_HITS:
            r.add("ERROR", "hyp_too_many_hits", hid,
                  f"{len(h.hits)} хітів, а людина розбирає не більше {MAX_HITS}: решта — "
                  f"у звіті заходу, тут лише ті, від яких щось залежить")
        for ref in (*h.about, *h.versus):
            if ref not in known:
                r.add("ERROR", "missing_ref", hid, f"посилання на {ref}, якого немає")
        for vid in h.versus:
            if vid in c.hypotheses and hid not in c.hypotheses[vid].versus:
                r.add("WARN", "one_sided", hid, f"versus {vid}, а {vid} про {hid} не знає",
                      say=f"Гіпотеза суперечить {vid}, а та про неї не згадує")
        for cit in h.citations:
            if cit.source_id not in c.sources:
                r.add("ERROR", "missing_ref", hid, f"цитата на джерело {cit.source_id}, якого немає")
        for hit in h.hits:
            ck = casekey.parse(hit.case)
            if ck is None:
                r.add("ERROR", "hyp_bad_case", hid,
                      f"хіт «{hit.case}»: не ключ справи (треба REPO/фонд/опис/справа)")
            elif ck.key != hit.case:
                r.add("ERROR", "hyp_bad_case", hid,
                      f"хіт «{hit.case}»: ключ пишеться «{ck.key}» — інакше вердикт "
                      f"із журналу до нього не знайдеться")
        if h.status != "closed" and (date.today() - h.updated).days > STALE_DAYS:
            r.add("WARN", "hyp_stale", hid,
                  f"не оновлювалась з {h.updated} — або рухається, або чесно закривається",
                  say=f"Гіпотеза не оновлювалась з {h.updated:%d.%m.%Y}")

    for owner, f in _facts(c):
        if f.hypothesis and f.hypothesis not in c.hypotheses:
            r.add("ERROR", "missing_ref", owner, f"{f.type}: hypothesis {f.hypothesis} не існує")
        elif f.status == "disputed" and not f.hypothesis:
            r.add("ERROR", "disputed_unlinked", owner,
                  f"{f.type}: disputed без `hypothesis` — спірний факт мусить казати, "
                  f"чим він вирішиться")

    covered = {x for h in c.hypotheses.values() for x in h.about}
    for pid, p in c.persons.items():
        if ((p.hypothetical_parent_family or p.hypothetical_spouse_families)
                and pid not in covered):
            r.add("WARN", "hypothetical_unlinked", pid,
                  "гіпотетичний родинний зв'язок без гіпотези, що має цю особу в `about`",
                  say="Гіпотетичний родинний зв'язок не описано жодною гіпотезою")
    for fid, fam in c.families.items():
        if fam.hypothetical_children and fid not in covered:
            r.add("WARN", "hypothetical_unlinked", fid,
                  "гіпотетичні діти без гіпотези, що має цю родину в `about`",
                  say="Гіпотетичних дітей не описано жодною гіпотезою")

    _verdict_ready(c, r)


def _verdict_ready(c: Canon, r: Report) -> None:
    """Вердикт на хіт уже записано гортачем, а гіпотеза досі його чекає."""
    waiting = [(hid, h) for hid, h in c.hypotheses.items() if h.status != "closed" and h.hits]
    if not waiting:
        return
    path = c.root / "data" / "derived" / "verdicts.json"
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(journal, dict):
        return
    from nyshporka.core import legacy_key

    for hid, h in waiting:
        for hit in h.hits:
            rows = legacy_key.get(journal, hit.case)
            if not isinstance(rows, dict):
                continue
            for ck, row in rows.items():
                parts = ck.split("|")
                if len(parts) < 3 or Path(parts[1]).stem.lower() != hit.scan.lower():
                    continue
                if hit.line is not None and parts[2] != str(hit.line):
                    continue
                verdict = row.get("verdict") if isinstance(row, dict) else None
                r.add("WARN", "hyp_verdict_ready", hid,
                      f"на хіт {hit.case} {hit.scan} уже є вердикт «{verdict}» — "
                      f"оновити гіпотезу й вирізати хіт",
                      say=f"На знахідку вже є вердикт «{verdict}» — гіпотезу пора оновити")
                break


# ── докази ───────────────────────────────────────────────────────────────────
def manifest_path(root: Path) -> Path:
    from nyshporka.canon import refs as R

    return R.citations_dir(root) / "MANIFEST_citations.json"


def evidence_refs(text: str) -> set[str]:
    found = set(_IN_TICKS.findall(text)) | set(_BARE.findall(text)) | set(_YAML_FIELD.findall(text))
    return {p.strip().rstrip(".,;:)»") for p in found}


def _resolves(resolve: Callable[[str], Path], p: str) -> bool:
    """Чи вказує рядок на щось реальне.

    🔴 Спершу диск, потім здогадки: `PPR_1925-1930.pdf` — справжній файл, хоч
    і схожий на діапазон сторінок.
    """
    if resolve(p).exists():
        return True
    # Ім'я з пробілами голий regex обрізав по першому пробілу. Приймаємо лише
    # єдиного кандидата з таким префіксом — кілька означають збіг, а не файл.
    parent, _, stem = p.rpartition("/")
    folder = resolve(parent + "/")
    if stem and folder.is_dir() and len(list(folder.glob(stem + "*"))) == 1:
        return True
    if "," in p:
        parts = [x.strip() for x in p.split(",") if x.strip()]
        base = parts[0].rpartition("/")[0]
        if all(resolve(x if "/" in x else f"{base}/{x}").exists() for x in parts):
            return True
    return False


def _evidence(c: Canon, r: Report, hash_evidence: bool) -> None:
    from nyshporka.canon import refs as R

    root = c.root
    resolve = R.resolver(root)
    for eid, path in c.files.items():
        refs = evidence_refs(path.read_text(encoding="utf-8"))
        for p in sorted(refs):
            if len(p.split("/")) < 4 or _resolves(resolve, p):
                continue
            # Той самий шлях міг потрапити двічі: цілим і обрізаним по пробілу.
            if any(q != p and q.startswith(p) and _resolves(resolve, q) for q in refs):
                continue
            if _TEMPLATE.search(p):
                r.add("WARN", "not_a_path", eid, f"{p}: шаблон або перелік — не шлях",
                      say="Доказ записано шаблоном чи переліком, а не файлом")
            elif _RANGE_TAIL.search(p):
                r.add("WARN", "not_a_path", eid,
                      f"{p}: діапазон сторінок замість файлу — розписати явно",
                      say="Доказ записано діапазоном сторінок, а не файлом")
            else:
                r.add("ERROR", "evidence_missing", eid, f"доказу немає на диску: {p}")

    man = manifest_path(root)
    if not man.is_file():
        return
    try:
        records = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        r.add("ERROR", "manifest", _rel(root, man), f"маніфест не читається: {exc}")
        return
    if isinstance(records, list):
        records = {str(r.get("secured_to") or i): r for i, r in enumerate(records)
                   if isinstance(r, dict)}
    for key, rec in records.items():
        if not isinstance(rec, dict):
            continue
        target = rec.get("secured_to") or key
        f = resolve(target)
        if not f.is_file():
            r.add("ERROR", "manifest_missing", target,
                  f"у маніфесті є, на диску немає (cited_by {rec.get('cited_by') or []})")
            continue
        if hash_evidence and rec.get("sha256"):
            got = hashlib.sha256(f.read_bytes()).hexdigest()
            if got != rec["sha256"]:
                r.add("ERROR", "manifest_hash", target,
                      f"sha256 у маніфесті {rec['sha256'][:12]}…, на диску {got[:12]}…")


def _orphans(c: Canon, r: Report) -> None:
    linked: set[str] = set()
    for f in c.families.values():
        linked.update(f.children, f.hypothetical_children)
        linked.update(x for x in (f.husband, f.wife, f.hypothetical_husband,
                                  f.hypothetical_wife) if x)
    for pid, p in c.persons.items():
        if (p.parent_family or p.spouse_families or p.hypothetical_parent_family
                or p.hypothetical_spouse_families or pid in linked):
            continue
        r.add("INFO", "orphan", pid, f"{p.primary_name}: жодного зв'язку, навіть гіпотетичного",
              say="Жодного родинного зв'язку, навіть гіпотетичного")
