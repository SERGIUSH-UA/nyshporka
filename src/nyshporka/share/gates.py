"""🚦 Ворота пакета: що не пускаємо в обмін і чому саме.

Ворота стоять на ОБОХ кінцях і це навмисно. Пакувальник не збирає брак —
так він не доїжджає до пулу взагалі; приймач проганяє ті самі перевірки ще
раз — бо пакет міг зібрати не той пакувальник, і чужому «все гаразд» вірити
підстав немає.

🔴 Що саме вони бережуть: не охайність, а ЗНАМЕННИК. Декод на три сторінки,
розданий як прочитана справа на три тисячі, не просто марний — він виробляє
хибні нулі оптом. Людина грепне його, не знайде прізвища й закриє напрям,
зробивши все правильно й отримавши неправду. Усі інші ворота другорядні щодо
цього одного.

🔴 Причина відмови завжди НАЗВАНА поштучно. Спільне «пакет не пройшов
перевірку» змушує вгадувати, що виправляти, і найчастіше закінчується тим, що
людина здається — а декод у неї насправді добрий.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from nyshporka.share.bundle import Manifest, as_count

#: Нижче цієї частки прочитаних кадрів пакет вважається уривком, і йому
#: потрібне явне пояснення (`--partial`), інакше знаменник бреше.
MIN_COVERAGE = 0.20

#: Понад стільки порожніх рядків — прогін радше не прочитався, ніж прочитав
#: порожні аркуші. Заміряно на справах, де рушій не взяв письмо взагалі.
MAX_BLANK_FRAC = 0.80

#: Коротший рядок за це — не текст, а сміття сегментації.
MIN_LINE_CHARS = 5

#: Номер правил воріт. Піднімається, коли змінюється те, що ворота ПУСКАЮТЬ
#: (нова відмова, інший поріг, знята відмова), — не на правку тексту.
#:
#: 🔴 Пул зберігає відмову разом із цим номером і пересуджує пакет, коли номер
#: відтоді змінився. Без нього пакет, відхилений через ваду воріт, лишався
#: відхиленим і після її виправлення: вердикт по тих самих байтах вважався
#: остаточним (звіт користувача 29.09.2026, три справи ДАЖО).
POLICY = 1


@dataclass
class Verdict:
    """Підсумок воріт: пускати чи ні, і що саме сказати людині."""

    refusals: list[str] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    #: Ті самі відмови з кодом правила й полем маніфесту — для агента й
    #: сценарію. `refusals` лишається списком рядків: його читають старі
    #: клієнти пулу.
    refusal_details: list[dict[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.refusals

    def refuse(self, why: str, *, rule: str, field: str = "") -> None:
        self.refusals.append(why)
        self.refusal_details.append({"rule": rule, "field": field, "text": why})

    def warn(self, code: str, why: str) -> None:
        self.warnings.append((code, why))

    def extend(self, other: Verdict) -> None:
        """Долити чужий вердикт: відмови разом із їхніми кодами."""
        self.refusals += other.refusals
        self.refusal_details += other.refusal_details
        self.warnings += other.warnings

    def as_json(self) -> dict[str, Any]:
        return {"passed": self.passed, "refusals": list(self.refusals),
                "refusal_details": [dict(d) for d in self.refusal_details],
                "policy": POLICY,
                "warnings": [{"code": c, "text": t} for c, t in self.warnings]}


def check(manifest: Manifest, *, partial_why: str = "") -> Verdict:
    """Проганяє пакет крізь усі ворота. `partial_why` знімає ворота знаменника.

    🔴 Без явного `partial_why` причина береться з маніфесту
    (`extra["partial"]`, туди її кладе `pack --partial`). Сервер кличе ворота
    саме так — без аргументу, покладаючись на маніфест, — і ворота цього поля
    не читали: пакет, який клієнт з `--partial` пропустив, сервер відхиляв
    тим самим «уривком». Часткову справу не було як залити взагалі.
    """
    partial_why = partial_why or str((manifest.extra or {}).get("partial") or "")
    v = Verdict()
    _gate_denominator(manifest, v, partial_why=partial_why)
    _gate_model(manifest, v)
    _gate_emptiness(manifest, v)
    _gate_identity(manifest, v)
    _gate_license(manifest, v)
    _gate_payload(manifest, v)
    return v


def _gate_denominator(m: Manifest, v: Verdict, *, partial_why: str) -> None:
    """Скільки кадрів має справа й скільки з них прочитано."""
    if not m.decode:
        v.refuse("у маніфесті немає блоку `decode` — пакет не називає, скільки "
                 "прочитано; без цього чужий нуль нічого не означає",
                 rule="no_decode", field="decode")
        return
    pages = m.pages
    if pages <= 0:
        v.refuse("у пакеті нуль прочитаних сторінок — нема чого передавати",
                 rule="no_pages", field="decode.pages")
        return
    frames = m.frames_total
    if frames <= 0:
        v.warn("frames_unknown",
               "кадрів справи не названо, тож покриття не порахувати: "
               "отримувач не зможе відрізнити повний декод від уривка. "
               "Кадрів на диску немає (PDF, прибрані після читання) — назвіть "
               "число з каталогу чи опису: nysh share card <справа> --frames N")
        return
    frac = pages / frames
    if frac < MIN_COVERAGE and not partial_why:
        v.refuse(
            f"прочитано {pages} сторінок із {frames} кадрів ({frac:.0%}) — це "
            f"уривок, а розданий без застереження він читається як прочитана "
            f"справа. Пояснити й пустити: --partial \"чому саме стільки\"",
            rule="partial_unexplained", field="extra.partial")
    elif frac < 1.0:
        v.warn("partial",
               f"прочитано {pages} з {frames} кадрів ({frac:.0%})"
               + (f"; причина: {partial_why}" if partial_why else ""))


def _gate_model(m: Manifest, v: Verdict) -> None:
    """Чим читали. Без цього декод неможливо ні відтворити, ні оцінити."""
    voices = m.voices
    if not voices:
        v.refuse("у маніфесті немає жодного голосу — невідомо, що саме в пакеті",
                 rule="no_voices", field="voices")
        return
    unnamed = [x.get("run") or "?" for x in voices if not str(x.get("model") or "").strip()]
    if unnamed:
        v.refuse(f"прогін без назви моделі: {', '.join(unnamed)}. Модель — це не "
                 f"підпис, а єдиний спосіб зрозуміти, чому текст саме такий",
                 rule="model_unnamed", field="voices.model")
    if not str(m.case.get("shifra") or "").strip():
        v.refuse("пакет без шифри справи — його нема куди покласти в отримувача",
                 rule="no_shifra", field="case.shifra")


def _gate_emptiness(m: Manifest, v: Verdict) -> None:
    """Чи є в пакеті власне текст."""
    lines = as_count(m.decode.get("lines"))
    chars = as_count(m.decode.get("chars"))
    if lines <= 0:
        v.refuse("у пакеті нуль рядків тексту", rule="no_lines", field="decode.lines")
        return
    if chars / lines < MIN_LINE_CHARS:
        v.refuse(f"середній рядок — {chars / lines:.1f} символа: це не текст, а "
                 f"сміття сегментації. Перечитати справу перед тим, як ділитись",
                 rule="short_lines", field="decode.chars")
    blank = as_count(m.decode.get("blank_pages"))
    if m.pages and blank / m.pages > MAX_BLANK_FRAC:
        v.refuse(f"порожніх сторінок {blank} із {m.pages} — рушій радше не взяв "
                 f"письмо, ніж прочитав порожні аркуші",
                 rule="blank_pages", field="decode.blank_pages")


def _gate_identity(m: Manifest, v: Verdict) -> None:
    """Чи впізнає отримувач цю справу."""
    if not m.refs:
        v.warn("no_refs", _no_refs_text(m))
    if not m.frames.get("total"):
        v.warn("no_frames",
               "переліку кадрів немає, тож прив'язати текст до чужої зйомки "
               "не вийде: сторінки лишаться номерами")
    repo = str(m.case.get("repo") or "")
    if repo and not str(m.case.get("repo_name") or "").strip() and not _known_archive(repo):
        v.warn("unknown_archive",
               f"архіву «{repo}» немає в довіднику Нишпорки: у каталозі справа "
               "стоятиме під голим кодом. Назвіть архів повністю: "
               "--archive-name \"Державний архів …\"")


def _no_refs_text(m: Manifest) -> str:
    """Порада, яку можна виконати, — залежно від того, що в пакеті вже є.

    🔴 `--link` радиться лише тоді, коли посилань немає зовсім. Пакет із
    посиланням і порожнім `refs` отримував ту саму пораду, і виконана вона
    попередження не прибирала (звіт користувача 29.09.2026, 24 пакети).
    """
    from nyshporka.share.publish import _ref_z_adresy

    urls = [str(x.get("url") or "") for x in m.links or [] if isinstance(x, dict)]
    urls = [u for u in urls if u]
    lead = ("пакет не називає джерела сканів. Шифра лишається, але звірити "
            "знахідку з зображенням отримувачу буде нікуди піти")
    if not urls:
        return f"{lead} — варто додати: --link \"звідки скани=<адреса>\""
    known = [u for u in urls if _ref_z_adresy(u)]
    if known:
        return (f"{lead}: посилання {known[0]} у пакеті є, але як джерело сканів "
                "не записане (посилання з реєстру опису кажуть лише «справа там "
                "є»). Якщо скани саме звідти — перепакуйте: nysh share pack "
                f"<справа> --link \"{known[0]}\", і воно стане джерелом")
    return (f"{lead}: посилання {urls[0]} у пакеті є, але цей хост не входить до "
            "відомих джерел сканів (FamilySearch, Wikimedia Commons, ARCHIUM, Skanoteka ПТГ, "
            "Szukaj w Archiwach). "
            "Адреса лишиться в пакеті, а в каталозі пулу скани не покажуться; "
            "інше посилання на той самий хост цього не змінить")


def _known_archive(repo: str) -> bool:
    """Чи знає довідник архівів цей код. Довідника немає — не заважати."""
    try:
        from nyshporka.archives import active

        return repo in active().repositories
    except Exception:
        return True


def _gate_license(m: Manifest, v: Verdict) -> None:
    if not str(m.license.get("text") or "").strip():
        v.refuse("не вказано ліцензію тексту. Без неї отримувач не знає, що з "
                 "цим можна робити: --license CC0-1.0",
                 rule="no_license", field="license.text")


def _gate_payload(m: Manifest, v: Verdict) -> None:
    """Сліди чужої машини, які не мали пережити пакування."""
    from nyshporka.share.bundle import META_STRIPPED

    leaked = [k for k in META_STRIPPED if k in m.decode or k in m.case]
    if leaked:
        v.refuse(f"у маніфесті лишились поля машини, на якій читали: "
                 f"{', '.join(leaked)}", rule="machine_fields", field="case")
    private = sorted(_private_keys(m.case))
    if private:
        v.refuse(f"в описі справи робочі нотатки дослідника: {', '.join(private)}. "
                 "Опис збирається білим списком полів (`share.opys`)",
                 rule="private_keys", field="case")
    if "[[" in json.dumps(m.case, ensure_ascii=False):
        v.refuse("в описі справи посилання на особу дерева (`[[…]]`) — "
                 "це нотатка дослідження, а не опис справи",
                 rule="tree_links", field="case")


#: Поля паспорта й сховища сторінок, де лежать нотатки про рід.
PRIVATE_KEYS = frozenset({"note", "clan_relevance", "comment", "agent", "records"})


def _private_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {str(k) for k in node if k in PRIVATE_KEYS}
        for val in node.values():
            found |= _private_keys(val)
        return found
    if isinstance(node, list):
        found = set()
        for val in node:
            found |= _private_keys(val)
        return found
    return set()


# ── нотатник справи ──────────────────────────────────────────────────────────
#: Типи записів нотатника, які взагалі можуть їхати. `note` — особисте.
NOTE_KINDS_SHARED = frozenset({"about", "catalog-error", "copy", "reading"})

#: Текстові поля запису нотатника, які читає людина в пулі.
NOTE_TEXT_FIELDS = ("text", "archive_says", "actually", "other")

#: Назви родичів, які разом із присвійним займенником роблять запис особистим.
_KIN = (r"(?:пра)*(?:дід\w{0,3}|діду\w*|баб\w{0,4}|бабус\w*|батьк\w*|батьков\w*|"
        r"тато|тата|татом|татові|мама|мами|мамі|маму|мамою|мати|матір\w*|матері|"
        r"предк\w*|предок|пращур\w*|рід|роду|родом|родин\w*|сім'\w+|сімʼ\w+|"
        r"дядьк\w*|дядь\w*|тітк\w*|тіт\w{0,2}|сестр\w*|брат\w{0,3}|"
        r"дед\w{0,3}|бабушк\w*|отец|отца|мать|матери)")
_MY = (r"(?:мій|моя|моє|мої|мого|моєї|моїй|моєму|моїх|моїм|"
       r"наш|наша|наше|наші|нашого|нашої|наших|нашим|нашому|"
       r"мой|моё|мои|моего|моей|моих)")
#: 🔴 Займенник і родич — у будь-якому порядку й через одне слово: «мій дід»,
#: «прабаба моя», «мого прадіда». Самий родич без займенника — опис джерела
#: («дід записаний у ревізії»), і його ворота пропускають. Виняток —
#: «прадід»/«прабаба» і далі вгору: в описі справи цих слів не буває, а в
#: родинній нотатці вони стоять і без займенника («це прабаба Миколи»).
_PERSONAL_RE = re.compile(
    rf"(?<!\w){_MY}(?:\s+\S+)?\s+{_KIN}(?!\w)|(?<!\w){_KIN}\s+(?:\S+\s+)?{_MY}(?!\w)"
    r"|(?<!\w)пра(?:пра)*(?:дід|діду|баб|дед|бабушк|онук|внук)\w*",
    re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
#: 🔴 Лише форма телефону, а не «десять цифр підряд»: роки й шифри через
#: дефіс («1850-1860 1870», «904-24-54») дали б хибну відмову.
_PHONE_RE = re.compile(
    r"(?<![\w-])(?:\+\d{1,3}[\s-]?\(?\d{2,3}\)?|\(?0\d{2}\)?)"
    r"[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?![\w-])")


def check_note(entry: dict[str, Any]) -> Verdict:
    """Ворота одного запису нотатника перед пулом — на обох кінцях.

    🔴 Причина відмови названа поштучно, з підказкою, куди перенести
    особисте: загальне знання про справу людина хоче віддати, і голе «не
    пройшло» змусило б її або здатись, або вгадувати.
    """
    v = Verdict()
    if entry.get("retracts"):
        return v                            # відкликання змісту не несе
    kind = str(entry.get("kind") or "")
    if kind not in NOTE_KINDS_SHARED:
        v.refuse(f"запис типу «{kind or '?'}» у пул не віддається: особисте "
                 "лишається вдома", rule="note_private_kind", field="kind")
        return v
    private = sorted(_private_keys(entry))
    if private:
        v.refuse(f"у записі робочі поля дослідника: {', '.join(private)}",
                 rule="private_keys", field="entry")
    text = " ".join(str(entry.get(f) or "") for f in NOTE_TEXT_FIELDS)
    was = entry.get("was")
    if isinstance(was, dict):
        text += " " + str(was.get("text") or "")
    if "[[" in text:
        v.refuse("у записі посилання на особу дерева (`[[…]]`) — це нотатка "
                 "дослідження, а не знання про справу", rule="tree_links", field="text")
    if m := _PERSONAL_RE.search(text):
        v.refuse(f"«{m.group(0)}» — це про вашу родину, а не про справу. Таке "
                 "пишіть окремим домашнім записом (`--kind note`), а в пул — лише "
                 "те, що корисне кожному, хто відкриє цю справу",
                 rule="personal", field="text")
    if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        v.refuse("у записі адреса пошти чи телефон", rule="contact", field="text")
    return v


def describe(v: Verdict) -> str:
    """Вердикт одним абзацом — для командного рядка."""
    if v.passed and not v.warnings:
        return "ворота пройдено"
    rows = [f"✗ {r}" for r in v.refusals] + [f"⚠ {t}" for _, t in v.warnings]
    return "\n".join(rows)
