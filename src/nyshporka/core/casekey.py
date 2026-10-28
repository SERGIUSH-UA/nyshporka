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
    "FIELD_LABEL_WORD",
    "FOND_LABEL",
    "FOND_TOKEN",
    "LETTERS",
    "LETTER_TO_LAT",
    "OPYS_LABEL",
    "OPYS_TOKEN",
    "SPR_LABEL",
    "SPR_TOKEN",
    "UNKNOWN",
    "CaseKey",
    "LegacyKeysError",
    "compatible",
    "fond_variants",
    "is_bundle",
    "is_legacy",
    "keys_current",
    "make",
    "norm_fond",
    "norm_letter",
    "norm_part",
    "parse",
    "parse_legacy",
    "require_current",
    "show_part",
    "stem",
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

#: Позначки полів перед номером: «ф.315 оп.1 спр.8433», «Ф. 211 Оп. 3 Д. 140»,
#: румунське «inv.». Ті самі для всіх розборів — інакше `nysh case` приймав
#: «ф.315 оп.1 спр.8433», а резолвер справи (і сервер Супряги за ним) — ні.
#: Регістр — на `re.IGNORECASE` розбору.
FOND_LABEL = r"ф\.?\s*"
OPYS_LABEL = r"(?:оп|inv)\.?\s*"
SPR_LABEL = r"(?:спр|д|d)\.?\s*"
#: Будь-яка з позначок як окреме слово — щоб її не взяли за назву архіву.
FIELD_LABEL_WORD = r"(?:ф|оп|спр|д|inv|d)"

#: 🔴 ЄДИНА таблиця письма літер у шифрі (індекс опису й справи: `1д`, `5доп`,
#: `355а`). Канон — ЛАТИНКА: ним названі файли сховища сторінок
#: (`315-1-7029a.json`), теки прогонів (`118-3d-38`) і ключі в `overrides`.
#: Кирилиця лишається лише у «показі» (`show_part`): так опис друкує архів, так
#: названі теки (`op1д-spr-406`) і колонки реєстрів опису.
#: Звукова пара: а→a б→b в→v г→g д→d е→e.
LETTER_TO_LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e"}
#: Решта літер (`о`→`o`, `п`→`p`, `р`→`r`, `с`→`s`…) — нижче, тією ж транслітерацією.
#: Літери поза таблицею (`ч`, `ж`, `з`…) не зводяться: токен лишається як є.
#: Клас літер, з яких складається індекс опису/справи, — для регексів розборів.
LETTERS = "а-яіїєґa-z"
_TAIL_RE = re.compile(r"^(\d+)([^\W\d_]+)$")
#: кирилична літера префікса фонду → латинська: «Р-6129» і «R-6129» — один фонд.
_FOND_PREFIX_TO_LAT = {"р": "R", "п": "P", "ф": "F", "c": "C", "с": "S"}
#: латинська літера префікса → кирилична, ОДНАКОВА НА ВИГЛЯД. Для пошуку, не для
#: канону: канон лишається звуковим (вище), бо ним названі всі наявні записи.
#: 🔴 Дві таблиці тому, що звукова породжує двозначність: «Р» за звуком дає «R»,
#: «П» дає «P», а виглядає «Р» як латинська «P». Набрана латинська «P» — це або
#: канон фонду «П», або одруківка замість «Р», і розрізнити їх може лише
#: бібліотека (відгук №5 з порталу, 28.10.2026). Те саме чекає на H (Г/Н),
#: B (Б/В) і Y (И/У), щойно ці літери потраплять у звукову таблицю.
_FOND_PREFIX_LOOKALIKE = {
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "i": "і", "k": "к",
    "m": "м", "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
}
_FOND_PREFIX_LOOKALIKE_BACK = {v: k for k, v in _FOND_PREFIX_LOOKALIKE.items()}
# Решта літер індексу — теж ТРАНСЛІТЕРАЦІЄЮ, одним принципом із таблицею вище.
# Таблиця ін'єктивна: дві різні кириличні літери ніколи не дають одну латинську
# (було `р` і `п` → `p`, тож `дор` = `доп`; у ЦДІАЛ ф.201 спр.3346 є літери і
# `п`, і `р`). Латинська `p` читається як `п` (`dop` → `доп`), `r` — як `р`.
# Латинські `c`, `h`, `y` у таблиці немає: вони лишаються собою.
_TRANSLIT_EXTRA = {"і": "i", "к": "k", "м": "m", "н": "n", "о": "o", "п": "p",
                   "р": "r", "с": "s", "т": "t", "у": "u", "х": "x"}
_FOLD = {**_TRANSLIT_EXTRA, **LETTER_TO_LAT}
_FOLD_TR = str.maketrans(_FOLD)
#: Зворотне зведення для показу: латинка → кирилиця.
_UNFOLD_TR = str.maketrans({v: k for k, v in _FOLD.items()})
_FOND_PREFIX_RE = re.compile(r"^([A-Za-zА-ЯЄІЇҐа-яєіїґ]{1,2})-(\d.*)$")


def _fold_letters(letters: str) -> str | None:
    """Літери індексу → канон, або `None`, коли хоч одна не зводиться (`ч`)."""
    low = letters.lower()
    if all(c in _FOLD or ("a" <= c <= "z") for c in low):
        return low.translate(_FOLD_TR)
    return None


def norm_letter(s: object) -> str:
    """Літера (чи літери) індексу справи в каноні: `А`, `a`, `а` → `a`."""
    low = str(s or "").strip().lower()
    return _fold_letters(low) or low


def norm_part(s: object) -> str | None:
    """Номер справи чи опису для ПОРІВНЯННЯ і ключа: `00114`→`114`, `2а`→`2a`.

    Регістр, провідні нулі й письмо літер зведені: `1Д`, `1д`, `1d` → `1d`;
    `5доп` = `5dop`; `355a` = `355а`. Літери зводяться, лише коли ВСІ вони в
    таблиці (`LETTER_TO_LAT` + `_TRANSLIT_EXTRA`): `7049ч` лишається як є.

    Приймає і число: паспорти пишуть `"inv": 1` так само часто, як `"inv": "1"`.
    """
    if s is None or s == "":
        return None
    out = str(s).strip().lower().lstrip("0") or "0"
    m = _TAIL_RE.match(out)
    if m:
        folded = _fold_letters(m.group(2))
        if folded:
            out = m.group(1) + folded
    return out


def show_part(s: object) -> str:
    """Номер опису для ПОКАЗУ й імені теки: латинський суфікс → кирилиця.

    `1d` → `1д`, `5dop` → `5доп`, `1д` → `1д`. Токен без цифр+латинки
    (`GP35`, `@збірка`) лишається, як є, лише в нижньому регістрі.
    """
    low = str(s or "").strip().lower()
    m = re.match(r"^(\d+)([a-z]+)$", low)
    return m.group(1) + m.group(2).translate(_UNFOLD_TR) if m else low


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


def fond_variants(s: object) -> list[str]:
    """Написання того самого фонду: канонічне перше, далі — чим його підміняють.

    `R-7720` → `R-7720`, `7720`; `P-1989` → `P-1989`, `R-1989`, `1989`;
    `7720` → `7720`, `R-7720`, `P-7720`, `F-7720`, `C-7720`, `S-7720`.

    🔴 Перше значення — канон, решта — ПРИПУЩЕННЯ, яке мусить підтвердити
    бібліотека: латинську «P» набирають і замість «Р», і як канон фонду «П», а
    «Р-7720» і «7720» в архівах бувають різними фондами. Підставляти з цього
    переліку наосліп не можна.
    """
    canon = norm_fond(s)
    if not canon:
        return []
    out = [canon]

    def add(value: str) -> None:
        v = norm_fond(value)
        if v and v not in out:
            out.append(v)

    m = _FOND_PREFIX_RE.match(canon)
    if m:
        pref, rest = m.group(1).lower(), m.group(2)
        for table in (_FOND_PREFIX_LOOKALIKE, _FOND_PREFIX_LOOKALIKE_BACK):
            swapped = "".join(table.get(c, c) for c in pref)
            if swapped != pref:
                add(f"{swapped}-{rest}")
        add(rest)
    else:
        for pref in dict.fromkeys(_FOND_PREFIX_TO_LAT.values()):
            add(f"{pref}-{canon}")
    return out


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

    Збірка з названим описом — `211-11-@ispovidi`: збірки з однаковою назвою в
    різних описах — різні справи, і файл у них теж свій.

    Лише для запису. Читаючи, файл ідентифікують за полем `key` усередині, а не
    за іменем: фонд `R-6129` уже має дефіс, і ім'я на частини не розкладається.
    """
    if ck.bundle and not ck.opys_known:
        return f"{ck.fond}-{ck.spr}"
    return f"{ck.fond}-{ck.opys}-{ck.spr}"


# ── версія ключів простору ───────────────────────────────────────────────────
class LegacyKeysError(RuntimeError):
    """Простір ще на старих ключах: запис відкладено до `nysh cases rekey`."""


def keys_current() -> bool:
    """Чи простір уже на ключах з описом. Без простору — так (нічого переносити).

    Версія читається з маркера на диску (`workspace.keys_now`), а не з кешу
    процесу: перенос чи відкат у сусідньому терміналі мусить бути видно
    застосунку й демону без перезапуску.
    """
    try:
        from nyshporka.core.workspace import keys_now

        return keys_now() >= KEYS_VERSION
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
