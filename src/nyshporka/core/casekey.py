"""Ключ справи: `REPO/фонд/опис/справа` — одна форма для всіх фондів.

`DAHMO/315/1/8433` · `DAVIO/R-6129/24/5` · `DAOO/37/_/1235` (опис невідомий) ·
`ANRM/211/@fuzovka` (збірка: вибірка з різних справ) · `ANRM/211/11/@razeni_goian`
(збірка в межах одного опису — опис названо, коли її оголошували).

Опис — фізично окремий підрозділ фонду, і номери справ у різних описах
повторюються: «ДАДнО 193-1-213» і «193-3-213» — дві різні книги. Ключ без
опису їх зливав, і довкола цього наросли латки: список фондів, де опис «таки
входить» у ключ, реєстр колізій, що давав власний ключ лише другій книзі,
пошук справи кількома формами ключа. Ключ із описом завжди робить їх зайвими.

🔴 Невідомий опис пишеться `_`, а не пропускається. Тоді ключ лишається
чотирискладовим, і за формою видно, що опису не встановлено. Пропуск давав би
трискладовий рядок, тобто ту саму форму, що й старий ключ.

🔴 Старий ключ (до 0.22) — трискладовий без `@`: `DAHMO/315/8433` або
`DAHMO/196-8/712`. Нова форма такого рядка не породжує ніколи, тож старий ключ
розпізнається з першого погляду. Перекладає його лише `cases.rekey`: там
заморожений старий будівник і карта переїзду простору.

Цеглини номерів і нормалізатори живуть тут, а не в `library`, бо ключ — нижчий
шар: його будують і розбирають модулі, яким бібліотека не потрібна.
"""
from __future__ import annotations

import re
from typing import NamedTuple

__all__ = [
    "FOND_TOKEN", "OPYS_TOKEN", "SPR_TOKEN", "UNKNOWN", "CaseKey", "LegacyKeysError",
    "compatible", "is_bundle", "is_legacy", "keys_current", "make", "norm_fond", "norm_part",
    "parse", "parse_legacy", "require_current", "stem",
]

#: Опис не встановлено. Один символ, якого немає в жодному номері.
UNKNOWN = "_"

#: Версія ключів простору (`[workspace] keys` у маркері). 1 — до опису в ключі.
KEYS_VERSION = 2

#: 🔴 ТРИ ЦЕГЛИНИ, з яких складаються всі розбори шифри: як виглядає номер
#: фонду, опису й справи. Відповідь на це питання мусить бути одна, інакше
#: розбори розходяться (бібліотека читала «Р-6129», реєстрація — ні).
FOND_TOKEN = r"(?:[А-ЯЄІЇҐA-Z]{1,2}-)?\d+"      # 315 · Р-6129 · R-6129
OPYS_TOKEN = r"\d+[а-яa-z]?"                     # 1 · 24 · 4б
SPR_TOKEN = r"\d+[а-яa-z]?"                      # 8433 · 2а

#: кирилична літера індексу справи → латинська. Канон латинський — ним названі
#: файли сховища сторінок (`315-1-7029a.json`).
_LETTER_TO_LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e"}
#: кирилична літера префікса фонду → латинська: «Р-6129» і «R-6129» — один фонд.
_FOND_PREFIX_TO_LAT = {"р": "R", "п": "P", "ф": "F", "c": "C", "с": "S"}


def norm_part(s: object) -> str | None:
    """Номер справи чи опису без провідних нулів: `00114`→`114`, `2а`→`2a`.

    Приймає і число: паспорти пишуть `"inv": 1` так само часто, як `"inv": "1"`.
    """
    if s is None or s == "":
        return None
    out = str(s).strip().lower().lstrip("0") or "0"
    # Літерний індекс справи приходить обома письмами: тека `spr-2a`, рендер тієї
    # самої книги — `230-1-2а` кирилицею. Без зведення це дві справи.
    if len(out) > 1 and out[-1] in _LETTER_TO_LAT and out[:-1].isdigit():
        out = out[:-1] + _LETTER_TO_LAT[out[-1]]
    return out


def norm_fond(s: object) -> str | None:
    """Номер фонду; літерний префікс радянських фондів — латинкою.

    `Р-6129` → `R-6129`, `р-06129` → `R-6129`, `R6129` → `R-6129`, `0315` → `315`.
    """
    if s is None or s == "":
        return None
    raw = str(s).strip()
    # дефіс необов'язковий: шифра пише «Р-6129», ID джерела канону — «R6129»
    m = re.match(r"^([А-ЯЄІЇҐA-Za-zа-яєіїґ]{1,2})-?(\d.*)$", raw)
    if not m:
        return norm_part(raw)
    pref, rest = m.group(1).lower(), norm_part(m.group(2))
    if not rest:
        return norm_part(raw)
    return f"{_FOND_PREFIX_TO_LAT.get(pref, pref.upper())}-{rest}"


def _norm_opys(s: object) -> str:
    if s is None or str(s).strip() in ("", UNKNOWN):
        return UNKNOWN
    return norm_part(s) or UNKNOWN


def is_bundle(spr: object) -> bool:
    """Збірка (`@fuzovka`) — вибірка з різних справ; опису не має за побудовою."""
    return str(spr or "").startswith("@")


class CaseKey(NamedTuple):
    """Розібраний ключ. `opys` — `UNKNOWN` або номер; у збірки — номер або `""`."""

    repo: str
    fond: str
    opys: str
    spr: str

    @property
    def bundle(self) -> bool:
        return is_bundle(self.spr)

    @property
    def opys_known(self) -> bool:
        return bool(self.opys) and self.opys != UNKNOWN

    @property
    def key(self) -> str:
        if self.bundle and not self.opys:
            return f"{self.repo}/{self.fond}/{self.spr}"
        return f"{self.repo}/{self.fond}/{self.opys}/{self.spr}"

    def __str__(self) -> str:
        return self.key


def make(repo: object, fond: object, opys: object, spr: object) -> str | None:
    """Ключ справи. `None` — бракує архіву, фонду чи справи.

    Нормалізує кожну частину сам: ключ однаковий незалежно від того, яким
    письмом і з якими нулями номери прийшли. Збірка несе опис, лише коли його
    названо: опис за замовчуванням фонду її не стосується — вона з різних справ.
    """
    ck = make_key(repo, fond, opys, spr)
    return ck.key if ck else None


def make_key(repo: object, fond: object, opys: object, spr: object) -> CaseKey | None:
    """Те саме, що `make`, але розібраним кортежем."""
    r = str(repo or "").strip().upper()
    f = norm_fond(fond)
    if not (r and f and spr not in (None, "")):
        return None
    if is_bundle(spr):
        o = "" if opys is None or str(opys).strip() in ("", UNKNOWN) else norm_part(opys)
        return CaseKey(r, f, o or "", str(spr).strip())
    s = norm_part(spr)
    if not s:
        return None
    return CaseKey(r, f, _norm_opys(opys), s)


_REPO_RE = r"[A-Za-z][A-Za-z0-9_]*"
#: Сегмент опису чи справи в КЛЮЧІ — будь-що без скісної й пробілу. Шифру з
#: тексту розбирають цеглини вище; тут питання лише в будові ключа, а номери
#: бувають і `7864_parish56_1846`, і `3ДОД` (ДАЖО ф.118).
_SEG = r"[^/\s]+"
_NEW_RE = re.compile(
    rf"^(?P<repo>{_REPO_RE})/(?P<fond>{FOND_TOKEN})/(?P<opys>{_SEG})/(?P<spr>{_SEG})$",
    re.IGNORECASE)
_BUNDLE_RE = re.compile(rf"^(?P<repo>{_REPO_RE})/(?P<fond>{FOND_TOKEN})/(?P<spr>@{_SEG})$",
                        re.IGNORECASE)
#: Старий ключ: `REPO/фонд/справа` або `REPO/фонд-опис/справа`; і псевдоключ
#: `?/фонд/справа`, який раннер писав у мету, коли архіву не знав.
_LEGACY_RE = re.compile(
    rf"^(?P<repo>{_REPO_RE}|\?)/(?P<fond>{FOND_TOKEN})(?:-(?P<opys>[^/\s-]+))?"
    rf"/(?P<spr>[^/\s]+)$", re.IGNORECASE)


def parse(value: object) -> CaseKey | None:
    """Ключ нової форми → `CaseKey`; будь-що інше (і старий ключ) → `None`."""
    s = str(value or "").strip()
    m = _NEW_RE.match(s)
    if m:
        return make_key(m.group("repo"), m.group("fond"), m.group("opys"), m.group("spr"))
    m = _BUNDLE_RE.match(s)
    if m:
        return make_key(m.group("repo"), m.group("fond"), "", m.group("spr"))
    return None


def is_legacy(value: object) -> bool:
    """Чи це ключ старої форми (до опису в ключі).

    Збірка без опису (`ANRM/211/@fuzovka`) має ту саму форму, що й до 0.22, і
    старою не вважається; збірка з описом у фонді (`ANRM/211-11/@…`) — стара.
    """
    m = _LEGACY_RE.match(str(value or "").strip())
    return m is not None and not (is_bundle(m.group("spr")) and not m.group("opys"))


def parse_legacy(value: object) -> tuple[str, str, str | None, str] | None:
    """Старий ключ → (repo, fond, opys|None, spr). Опис є лише у формі `фонд-опис`.

    🔴 Літерний фонд — один сегмент: `DAVIO/R-6129-24/5` → фонд `R-6129`, опис `24`.
    `?` в архіві лишається `?`: архіву той, хто писав ключ, не знав.
    """
    m = _LEGACY_RE.match(str(value or "").strip())
    if not m or not is_legacy(value):
        return None
    repo = m.group("repo").upper()
    fond = norm_fond(m.group("fond")) or ""
    opys = norm_part(m.group("opys")) if m.group("opys") else None
    raw = m.group("spr")
    spr = raw.strip() if is_bundle(raw) else (norm_part(raw) or "")
    return repo, fond, opys, spr


def compatible(a: object, b: object) -> bool:
    """Чи можуть два ключі означати одну справу.

    Той самий архів, фонд і справа, а описи — однакові або один із них
    невідомий (`_`). 🔴 Невідомий опис — незнання, а не доказ іншої книги:
    шифра паспорта «ЦДІАК 2-1-169» і ключ мети, що опису не знав, — та сама
    справа. Різні НАЗВАНІ описи — різні книги завжди. Рядок, що ключем не
    розбирається, порівнюється як є.
    """
    ka, kb = parse(a), parse(b)
    if ka is None or kb is None:
        return str(a or "").strip().casefold() == str(b or "").strip().casefold()
    if (ka.repo, ka.fond, ka.spr.casefold()) != (kb.repo, kb.fond, kb.spr.casefold()):
        return False
    return ka.opys == kb.opys or not (ka.opys_known and kb.opys_known)


def stem(ck: CaseKey) -> str:
    """Ім'я файла справи в сховищі сторінок: `315-1-8433` · `37-_-1235` · `211-@fuzovka`.

    Лише для запису. Читаючи, файл ідентифікують за полем `key` усередині, а не
    за іменем: фонд `R-6129` уже має дефіс, і ім'я на частини не розкладається.
    """
    if ck.bundle:
        return f"{ck.fond}-{ck.spr}"
    return f"{ck.fond}-{ck.opys}-{ck.spr}"


# ── версія ключів простору ───────────────────────────────────────────────────
class LegacyKeysError(RuntimeError):
    """Простір ще на старих ключах: запис відкладено до `nysh cases rekey`."""


def keys_current() -> bool:
    """Чи простір уже на ключах з описом. Без простору — так (нічого переносити)."""
    try:
        from nyshporka.core.workspace import workspace

        return workspace().keys >= KEYS_VERSION
    except Exception:       # простору немає — і старих ключів у ньому теж
        return True


def require_current(what: str) -> None:
    """Відмовити в записі, доки простір не переїхав на ключі з описом.

    🔴 Запис нового ключа поруч зі старими дав би ту саму справу двома файлами
    (`315-8433.json` і `315-1-8433.json`), і половина роботи не знаходилась би.
    Читання при цьому працює: старі ключі перекладає `cases.rekey`.
    """
    if keys_current():
        return
    raise LegacyKeysError(
        f"{what}: простір ще на старих ключах справ (без опису). Спершу перенесіть "
        f"облік: `nysh cases rekey` покаже, що зміниться, `nysh cases rekey --apply` "
        f"перенесе з архівом для відкату.")
