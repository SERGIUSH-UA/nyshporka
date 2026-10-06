"""Читання/запис сховища сторінок: `data/pages/<REPO>/<fond>-<opys>-<spr>.json`.

Ідіоми ті самі, що в library/decode_hits: atomic tmp+replace, людська праця
переживає повторний запис (union-merge, статус лише підвищується), ключ справи —
`REPO/фонд/опис/справа` (`core.casekey`). Плюс lockfile — бо основний сценарій
це паралельні агентні сесії, що пишуть в одну справу.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from nyshporka import vydannia
from nyshporka.archives.pack import active as _pack_active
from nyshporka.cases.walk import frame_names
from nyshporka.core import casekey
from nyshporka.core import legacy_key as legacy
from nyshporka.core.workspace import workspace
from nyshporka.library import (
    _REPO_LABEL,
    Address,
    _mk_key,
    _norm_spr,
    default_opys,
    find_by_address,
    library_lookup,
    load_library,
    parse_address,
    parse_case_code,
    parse_source_id,
)
from nyshporka.pagestore.models import CaseFile, CaseNote, PageNote, Record
from nyshporka.utils.atomic import atomic_write_text

ROOT = workspace().root
PAGES_ROOT = workspace().pages

#: Формат файла справи. 2 — з нотатником (`notes`). Файл без нотаток пишеться
#: як 1: його без змін читає й пакет, що нотатника ще не знає.
FILE_VERSION = 2

# порядок підвищення статусу: понизити повний прохід частковим не можна
_STATUS_RANK = {"unreadable": 0, "skipped": 0, "partial": 1, "full": 2}

# «архів 123-1-456» / «dahmo 315-1-8433» / «315-1-8433» (без архіву — помилка)
_SHIFRA_RE = re.compile(r"^(?:(\S+)\s+)?(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\w+)$")
#: 🔴 Зводиться до канонічного коду, а не до першого-ліпшого. Один архів
#: буває підписаний двома кодами (`DAVO` і `DAVIO` — це ДАВіО), і без зведення
#: те, під яким кодом опиниться сторінка, вирішував би порядок словника: та
#: сама книга лягала б то в один архів, то в сусідній.
#: 🔴 Функція, а не словник на рівні модуля — з тієї самої причини, що й у
#: `library._repo_alias`: заморожений при імпорті знімок не бачить архіву,
#: доданого в цій же сесії, і сховище сторінок відмовляє словами «невідомий
#: архів» одразу після «✅ додано».
def _label2repo() -> dict[str, str]:
    pk = _pack_active()
    return {w: pk.canon_repo(c) for w, c in pk.word_index().items()}

#: 🔴 Правило СЛОВАМИ, приклад — ілюстрацією. Доти тут стояли самі приклади, з
#: яких правило треба було вивести, порівнявши два з них між собою: «архів
#: 123-1-456» через дефіси й «ANRM/211-3/140» через скісну з дефісом усередині.
#: Людина набирала «CDIAK/127/781/534» — найприроднішу форму, бо шифра в усьому
#: світі пишеться в один ряд, — і діставала «не розпізнав справу» без жодного
#: натяку, що саме не так. Тепер порядок і роздільники названі; форма, яка тоді
#: відмовлялась, приймається.
_ACCEPTED_FORMATS = (
    "шифру «ЦДІАК 127-781-534» — архів, потім фонд, опис і справа саме в цьому "
    "порядку, розділені дефісом або скісною (тож «ЦДІАК/127/781/534» — те саме); "
    "ключ «DAHMO/315/1/8433» (опис невідомий — «_»); source-id "
    "«S_<архів>_F<фонд>_D<справа>»; "
    "шлях теки «data/raw/архів_123/spr-456»"
)


@dataclass
class CaseRef:
    """Розв'язана справа + збагачення з бібліотеки."""

    key: str
    repo: str
    fond: str
    spr: str
    opys: str | None = None
    shifra: str = ""
    title: str = ""
    path: str = ""          # rel-шлях теки сканів (або .pdf) — для status
    frames: int | None = None


@dataclass
class MergeReport:
    """Що сталося при annotate_pages/add_records."""

    path: str
    added: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "added": self.added, "merged": self.merged,
                "replaced": self.replaced, "errors": self.errors}


def _repo_for_write(addr: Address, raw: str) -> str:
    """Код архіву з адреси — або відмова.

    🔴 Одна політика замість двох, які тут були. Сховище сторінок ПИШЕ, і
    мовчки взятий перший-ліпший архів означає аркуші, дописані в чужу справу.
    Тому безархівна шифра — відмова, хоч у пошуку та сама форма є законним
    питанням: пошук нічого не змінює, і неоднозначність для нього — відповідь.

    ⚠ Латинське невідоме слово лишається як є (`.upper()`): латинський код —
    наш простір імен, туди попадають архіви, яких пак іще не знає. Кириличне
    невідоме — відмова: це людське написання, і мовчки зробити з нього код
    означало б завести архів на одруківку.
    """
    if addr.repo:
        return addr.repo
    if not addr.repo_word:
        raise ValueError(
            f"шифра «{raw}» без архіву неоднозначна — додай архів "
            f"(«ДАХмО {raw}») або дай ключ/шлях.{_near_miss(addr)} "
            f"Приймаю: {_ACCEPTED_FORMATS}")
    if addr.repo_word.isascii():
        return addr.repo_word.upper()
    raise ValueError(
        f"невідомий архів «{addr.repo_word}» "
        f"(знаю: {', '.join(sorted(_REPO_LABEL.values()))})")


#: Два числа замість трьох — найчастіша форма «майже влучив».
_TWO_NUMS_RE = re.compile(r"^\s*(\d+)\s*[-–/]\s*(\d+[а-яa-z]?)\s*$", re.IGNORECASE)


def _two_numbers_hint(v: str) -> str:
    """Підказка на два числа: неоднозначність тут у самому записі, а не в даних.

    «127-534» однаково правдоподібно читається як «фонд 127, справа 534» і як
    «фонд 127, опис 534» з нествореною справою. Здогадуватись за людину не
    можна, а назвати обидва прочитання — можна.
    """
    m = _TWO_NUMS_RE.match(v)
    if not m:
        return ""
    a, b = m.group(1), m.group(2)
    # Серію пошук приймає лише там, де область — опис (`htr_store.runs_for_scope`);
    # підказка її називає, бо «фонд і опис» найчастіше й означає «усі справи опису».
    return (f" Два числа неоднозначні: якщо це фонд і справа — «АРХІВ/{a}/{b}»; "
            f"якщо фонд і опис — дай ще й справу, а для пошуку по всіх прочитаних "
            f"справах опису — серію з архівом: «АРХІВ {a}-{b}».")


def _near_miss(addr: Address) -> str:
    """«Мабуть, ти мав на увазі X» — але лише коли X справді лежить на диску.

    🔴 Підказка спирається на бібліотеку, а не на перелік форм. Порада назвати
    архів коштує рядка завжди; порада назвати САМЕ ЦЕЙ архів варта його лише
    тоді, коли така справа в просторі одна — інакше це здогад, поданий тоном
    відповіді.
    """
    try:
        found = find_by_address(addr)
    except Exception:      # бібліотека не зібрана — підказка не критична
        return ""
    if len(found) != 1:
        return ""
    shifra = found[0].get("shifra") or ""
    return f" Схоже, це «{shifra}» — тоді набирай так." if shifra else ""


# ── резолюція справи ─────────────────────────────────────────────────────────
def resolve_case(value: str) -> CaseRef:
    """Будь-який людський ідентифікатор справи → CaseRef. ValueError якщо не вийшло.

    Ключ (`DAHMO/315/1/8433`), старий ключ до 0.22 (`DAHMO/315/8433` — через
    карту переїзду простору), адреса, шифра, ID джерела канону, шлях теки.
    """
    v = (value or "").strip()
    pub = vydannia.parse(v)
    if pub is not None:
        # Друковане видання: шифри архіву немає, і бібліотека справ про нього
        # нічого не знає, тож ключ і є шифра (`nyshporka.vydannia`).
        code, year = pub
        k = vydannia.key(code, year)
        return CaseRef(key=k, repo=vydannia.REPO, fond=code, spr=str(year), shifra=k)
    parsed: tuple[str, str, str | None, str] | None = None
    # Старий ключ — за картою переїзду: вона знає, якій справі він належав.
    # Лише ключ, якого карта не знає, розбирається на частини.
    ck = casekey.parse(v)
    if ck is None and casekey.is_legacy(v):
        moved = legacy.translate(v)
        old = casekey.parse_legacy(v)
        if moved:
            ck = casekey.parse(moved)
        elif old and old[0] != "?":
            ck = casekey.CaseKey(old[0], old[1], old[2] or casekey.UNKNOWN, old[3])
    if ck is not None and not ck.opys_known:
        # Ключ без опису (`_`, збірка без опису), якому перенос обліку вже
        # знайшов опис: облік лежить під тим ключем.
        ck = casekey.parse(legacy.current_key(ck.key)) or ck
    if ck is not None:
        # 🔴 Код зводиться до канонічного, як і в сусідній гілці шифри. Голий
        # `.upper()` означав, що ключ `DAVIO/…` шукав файл у `data/pages/DAVIO/`,
        # тоді як 109 уже записаних аркушів лежать у `data/pages/DAVO/`. Агент,
        # який чесно питає сховище перед тим, як відкривати скани, діставав
        # порожньо — і передивлявся переглянуте.
        parsed = (_label2repo().get(ck.repo.casefold(), ck.repo), ck.fond,
                  ck.opys if ck.opys_known else None, ck.spr)
    if parsed is None:
        # Канал адреси — того, що людина набирає, коли називає книгу. Розбір
        # спільний (`library.parse_address`), тож форми, які вже приймав реєстр
        # опису, більше не відмовляються тут.
        addr = parse_address(v)
        if addr:
            parsed = (_repo_for_write(addr, v), addr.fond, addr.opys, addr.spr)
    if parsed is None:
        ms = _SHIFRA_RE.match(v)
        if ms:
            label, fond, opys, spr = ms.groups()
            if not label:
                raise ValueError(
                    f"шифра «{v}» без архіву неоднозначна — додай архів "
                    f"(«ДАХмО {v}») або дай ключ/шлях. Приймаю: {_ACCEPTED_FORMATS}")
            repo = _label2repo().get(label.casefold())
            if not repo:
                raise ValueError(
                    f"невідомий архів «{label}» (знаю: {', '.join(sorted(_REPO_LABEL.values()))})")
            parsed = (repo, str(_norm_spr(fond)), _norm_spr(opys), str(_norm_spr(spr)))
    if parsed is None and v.startswith("S_"):
        parsed = parse_source_id(v)
    if parsed is None:
        parsed = parse_case_code(v)
    if parsed is None:
        raise ValueError(
            f"не розпізнав справу «{value}».{_two_numbers_hint(v)} "
            f"Приймаю: {_ACCEPTED_FORMATS}")

    repo, fond, opys, spr = parsed
    # Індекс, а не список: резолвер кличуть на кожен прогін простору
    # (`htr_store.runs_for_scope`), і читання бібліотеки на кожен виклик
    # коштувало 45 с на команду (`library.library_lookup`).
    lib = library_lookup(load_library)
    label = _REPO_LABEL.get(repo, repo)
    entry = lib.by_key.get(_mk_key(repo, fond, spr, opys) or "") \
        if casekey.is_bundle(spr) else lib.find(repo, fond, opys, spr)
    if entry is None and not opys and not casekey.is_bundle(spr):
        # 🔴 Опису не названо, а справ цього номера в архіві кілька — це різні
        # книги («ANRM 211-1-140» с. Парково і «211-3-140» Кишинівський собор).
        # Мовчки взяти першу-ліпшу = дописати аркуші в чужу справу, тому —
        # помилка з переліком того, що є.
        cands = sorted({str(e["opys"]) for e in lib.same_fond_spr(fond, spr)
                        if e.get("repo") == repo and e.get("opys")})
        if len(cands) > 1:
            seen = ", ".join(f"«{label} {fond}-{o}-{spr}»" for o in cands)
            raise ValueError(
                f"справ {label} {fond}-?-{spr} кілька, у різних описах, а «{value}» "
                f"опису не несе. Уточни опис (напр. «{label} {fond}-{cands[0]}-{spr}» "
                f"або «{repo}/{fond}/{cands[0]}/{spr}»). Є: {seen}")
    if entry is None:
        # ДАВО/ДАВіО-плутанина: лейбл шифри каже одне, тека диска — інше.
        # Якщо по (fond, spr) у бібліотеці рівно один запис — його ключ канонічний,
        # інакше нотатки тієї самої справи розповзуться по двох файлах.
        # 🔴 Лише в межах ТОГО САМОГО архіву (`same_as`). Номери фондів і справ
        # повторюються між архівами, і без цього обмеження запис іншого архіву
        # з тим самим фондом і справою мовчки підміняв архів, названий людиною
        # (звіт користувача 29.09.2026: «ДАХмО 315-1-8345» → `DAVIO/315/8345`).
        # Названий опис мусить збігтися або бути невідомим у записі.
        # Суперечливі записи бібліотеки показує `library_conflicts`.
        pk = _pack_active()
        # Опису не названо — тоді це опис за замовчуванням фонду, і книга
        # іншого опису під нього не підходить (ДАХмО 230: оп.3 спр.13 — не оп.1).
        want = _norm_spr(opys or (default_opys(repo, fond) if not casekey.is_bundle(spr)
                                  else ""))
        same = [e for e in lib.same_fond_spr(fond, spr)
                if pk.same_archive(e.get("repo"), repo)
                and not (want and e.get("opys") and _norm_spr(e["opys"]) != want)]
        if len(same) == 1:
            entry = same[0]
            repo = str(entry["repo"])
            label = _REPO_LABEL.get(repo, repo)
    entry = entry or {}
    # Збірка — з різних справ: опис за замовчуванням фонду її не стосується.
    opys = entry.get("opys") or opys or (
        None if casekey.is_bundle(spr) else default_opys(repo, fond))
    key = str(entry.get("key") or "") or _mk_key(repo, fond, spr, opys)
    if not key:
        raise ValueError(f"не зібрав ключ зі «{value}» (repo={repo} fond={fond} spr={spr})")
    shifra = entry.get("shifra") or f"{label} {fond}-{opys or '?'}-{spr}"
    return CaseRef(
        key=key, repo=repo, fond=fond, spr=spr, opys=opys, shifra=shifra,
        title=entry.get("title") or "",
        path=entry.get("path") or entry.get("raw_path") or "",
        frames=entry.get("frames"),
    )


def library_conflicts(lib: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Записи бібліотеки, чий архів суперечить архіву їхньої ж шифри.

    Такий запис резолвер більше не підставляє замість названого архіву, але
    й сам він не лікується: облік, уже записаний під його ключем, лежить у
    файлі чужого архіву. Показуються, щоб їх виправили (`nysh doctor`).
    Шифра без архіву чи з невідомим архівом — не суперечність, а незнання.
    """
    pk = _pack_active()
    labels = _label2repo()
    out: list[dict[str, str]] = []
    for e in load_library() if lib is None else lib:
        ms = _SHIFRA_RE.match(str(e.get("shifra") or "").strip())
        z_shyfry = labels.get(ms.group(1).casefold()) if ms and ms.group(1) else None
        repo = str(e.get("repo") or "")
        if z_shyfry and repo and not pk.same_archive(z_shyfry, repo):
            out.append({"key": str(e.get("key") or ""), "repo": repo,
                        "shifra": str(e.get("shifra") or ""), "shifra_repo": z_shyfry,
                        "path": str(e.get("path") or e.get("raw_path") or "")})
    return out


def case_path(ref: CaseRef) -> Path:
    """Шлях JSON-файлу справи: `DAHMO/315/1/8433` → `DAHMO/315-1-8433.json`.

    Ім'я — з ключа (`casekey.stem`), архів — тека; збірка — фонд і назва збірки.
    """
    ck = casekey.parse(ref.key)
    if ck is None:
        raise ValueError(f"ключ справи «{ref.key}» не нової форми — облік під ним не пишеться")
    return PAGES_ROOT / ref.repo / f"{casekey.stem(ck)}.json"


def _legacy_path(ref: CaseRef) -> Path | None:
    """Файл, яким справа звалась до переносу обліку; лише поки простір не переїхав."""
    if casekey.keys_current():
        return None
    reg = legacy.registry_set(ROOT)
    old = legacy.legacy_key(ref.repo, ref.fond, ref.spr, ref.opys, reg)
    for k, new in legacy.moves().items():
        if new == ref.key:
            old = k
            break
    parsed = casekey.parse_legacy(old or "")
    if not parsed:
        return None
    _, fond, opys, spr = parsed
    name = f"{fond}-{opys}-{spr}" if opys else f"{fond}-{spr}"
    return PAGES_ROOT / ref.repo / f"{name}.json"


# ── читання ──────────────────────────────────────────────────────────────────
def load_case(ref: CaseRef) -> CaseFile | None:
    p = case_path(ref)
    if not p.is_file():
        # До переносу облік лежить під старим іменем — читаємо його, а не «порожньо».
        old = _legacy_path(ref)
        if old is None or not old.is_file():
            return None
        p = old
    raw = p.read_text(encoding="utf-8")
    ver = re.search(r'"version"\s*:\s*(\d+)', raw[:200])
    if ver and int(ver.group(1)) > FILE_VERSION:
        raise ValueError(
            f"{_rel(p)} записано новішою версією nyshporka (формат {ver.group(1)}, "
            f"ця версія знає до {FILE_VERSION}) — онови пакет: nysh update")
    return CaseFile.model_validate_json(raw)


def _empty_case(ref: CaseRef) -> CaseFile:
    return CaseFile(key=ref.key, repo=ref.repo, fond=ref.fond, spr=ref.spr,
                    opys=ref.opys, shifra=ref.shifra, title=ref.title, path=ref.path)


# ── lockfile: паралельні агенти пишуть в одну справу ─────────────────────────
def _steal_stale(lockp: Path, stale: float) -> bool:
    """Зняти протухлий лок — лише під сторожем і з повторною перевіркою.

    🔴 Аудит 29.09.2026: було «побачив старий mtime → `unlink`». Двоє чекачів
    бачать той самий протухлий лок; A знімає його й ставить свій, а B, який
    свою перевірку вже зробив, знімає СВІЖИЙ лок A — і обидва пишуть справу,
    тобто read-modify-write одного губить нотатки іншого. Тепер знімати може
    лише той, хто тримає сторож `<lock>.steal` (`O_EXCL`), і він перевіряє вік
    лока ще раз уже під сторожем: чужий свіжий лок там видно як свіжий.
    Сторож живе мікросекунди; якщо його лишив мертвий процес — знімається за
    тим самим віком, що й лок.
    """
    guard = lockp.with_name(lockp.name + ".steal")
    try:
        g = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - guard.stat().st_mtime > stale:
                guard.unlink(missing_ok=True)
        except OSError:
            pass
        return False                          # знімає інший — чекаємо далі
    try:
        if time.time() - lockp.stat().st_mtime > stale:
            lockp.unlink(missing_ok=True)
            return True
        return False                          # лок уже чийсь свіжий — не чіпаємо
    except OSError:
        return True                           # лок уже зник — розсудить O_EXCL
    finally:
        os.close(g)
        guard.unlink(missing_ok=True)


@contextmanager
def _lock(path: Path, timeout: float = 5.0,
          stale: float = 30.0) -> Iterator[None]:
    lockp = path.with_name(path.name + ".lock")
    lockp.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lockp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                # власник помер — забираємо лок; не вдалось (знімає інший або
                # лок уже свіжий) — чекаємо далі з паузою й дедлайном
                if (time.time() - lockp.stat().st_mtime > stale
                        and _steal_stale(lockp, stale)):
                    continue
            except OSError:
                # 🔴 Лок щойно зник — або `stat()` стійко відмовляє (на Windows
                # файл у стані pending-delete, антивірус, індексатор). Було
                # голе `continue`: ні паузи, ні перевірки дедлайну, тож вихід
                # лишався єдиний — успішний `os.open`. У парі зі стійким
                # `FileExistsError` це давало вічний цикл на 100% ядра там, де
                # мав спрацювати `timeout`.
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"лок {lockp} зайнятий довше {timeout:.0f}с") from None
            time.sleep(0.1)
    # PID пишеться до `yield`: інакше власник лока невідомий рівно в той
    # проміжок, коли лок і тримають.
    os.write(fd, str(os.getpid()).encode())
    try:
        yield
    finally:
        os.close(fd)
        # ⚠ Знімаємо лише свій лок: за час роботи його могли забрати як
        # протухлий (30 с), і тоді `unlink` без перевірки зняв би чужий.
        try:
            if lockp.read_text(encoding="utf-8", errors="replace").strip() \
                    == str(os.getpid()):
                lockp.unlink(missing_ok=True)
        except OSError:
            pass


def _rel(path: Path) -> str:
    """Rel-шлях від кореня для звітів; абсолютний, якщо PAGES_ROOT винесено (тести)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _write(path: Path, cf: CaseFile) -> None:
    casekey.require_current("запис у сховище сторінок")
    cf.pages = dict(sorted(cf.pages.items()))
    cf.records.sort(key=lambda r: (r.scans[0] if r.scans else "", r.rid))
    cf.version = FILE_VERSION if cf.notes else 1
    payload = cf.model_dump(mode="json", exclude=None if cf.notes else {"notes"})
    if cf.notes:
        # Запис нотатника несе десяток полів, із яких заповнено два-три; порожні
        # у файлі лише роздували б діф у git. Ідентичність і час — завжди: їхні
        # «типові» значення фабричні, і зрівняння з ними нічого не каже.
        payload["notes"] = [
            {"uid": n.uid, "kind": n.kind, "created": n.created,
             **n.model_dump(mode="json", exclude_defaults=True,
                            exclude={"uid", "kind", "created"})}
            for n in cf.notes]
    # 🔴 Аудит 29.09.2026: тут стояв голий `tmp.replace(path)` зі спільним
    # `.json.tmp`. На Windows заміна падає з PermissionError, поки файл справи
    # тримає читач (збірка реєстру, підсумки, в'ювер), — і запис обривався,
    # лишаючи `.json.tmp` поруч. Спільний писар пакета перечікує зайняту ціль
    # і кладе tmp під pid, тож дві сесії не пишуть в один проміжний файл.
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


# ── merge ────────────────────────────────────────────────────────────────────
def _union(a: list[str], b: list[str]) -> list[str]:
    """Об'єднання зі збереженням порядку першої появи; dedup casefold по сирому рядку."""
    seen: dict[str, str] = {}
    for s in [*a, *b]:
        k = s.casefold()
        if k not in seen:
            seen[k] = s
    return list(seen.values())


def _merge_note(old: PageNote, new: PageNote) -> PageNote:
    merged = new.model_copy(deep=True)
    merged.surnames = _union(old.surnames, new.surnames)
    merged.places = _union(old.places, new.places)
    merged.years = list(dict.fromkeys([*old.years, *new.years]))
    if _STATUS_RANK[new.status] < _STATUS_RANK[old.status]:
        merged.status = old.status          # повний прохід не понижується частковим
    for f in ("sheet", "agent"):
        if not getattr(new, f):
            setattr(merged, f, getattr(old, f))
    # коментарі різних агентів не затирають одне одного (інцидент 00898,
    # 2026-07-21: паралельна сесія стерла попередження про фальш-друга) —
    # конкатенуємо відмінні ЦІЛИМИ. Зріз на 600 символах, що стояв тут,
    # мовчки з'їдав хвіст нової нотатки й старий коментар цілком: нотатка
    # суцільної вичитки розвороту має 1–5 тис. символів (інцидент 2026-09-13,
    # 116 обрізаних записів у сховищі одного дослідника).
    if not new.comment:
        merged.comment = old.comment
    elif old.comment and old.comment not in new.comment \
            and new.comment not in old.comment:
        merged.comment = f"{new.comment} ⟂ {old.comment}"
    return merged


def annotate_pages(ref: CaseRef, notes: list[PageNote], replace: bool = False) -> MergeReport:
    """Внести/домержити анотації сторінок. Пише атомарно під локом."""
    path = case_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = MergeReport(path=_rel(path))
    with _lock(path):
        cf = load_case(ref) or _empty_case(ref)
        # збагачення бібліотеки могло оновитись — освіжаємо, не чіпаючи дані
        cf.key = ref.key
        cf.shifra, cf.title = ref.shifra or cf.shifra, ref.title or cf.title
        cf.path, cf.opys = ref.path or cf.path, ref.opys or cf.opys
        for note in notes:
            old = cf.pages.get(note.scan)
            if old is None:
                cf.pages[note.scan] = note
                report.added.append(note.scan)
            elif replace:
                cf.pages[note.scan] = note
                report.replaced.append(note.scan)
            else:
                cf.pages[note.scan] = _merge_note(old, note)
                report.merged.append(note.scan)
        _write(path, cf)
    return report


def add_records(ref: CaseRef, records: list[Record], replace: bool = False) -> MergeReport:
    """Внести записи (upsert по rid). `replace=True` стирає всі записи справи спершу."""
    path = case_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = MergeReport(path=_rel(path))
    with _lock(path):
        cf = load_case(ref) or _empty_case(ref)
        if replace and cf.records:
            report.replaced = [r.rid for r in cf.records]
            cf.records = []
        by_rid = {r.rid: i for i, r in enumerate(cf.records)}
        for rec in records:
            i = by_rid.get(rec.rid)
            if i is None:
                by_rid[rec.rid] = len(cf.records)
                cf.records.append(rec)
                report.added.append(rec.rid)
            else:
                cf.records[i] = rec
                report.merged.append(rec.rid)
        _write(path, cf)
    return report


def add_notes(ref: CaseRef, notes: list[CaseNote]) -> MergeReport:
    """Дописати записи в нотатник справи.

    🔴 Лише дописування: наявний запис не змінюється й не видаляється.
    Повторний запис того самого `uid` (повтор `pull`, двічі імпортована тека)
    — не дубль, а пропуск: він іде в `merged`, і вміст лишається першим.
    """
    path = case_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = MergeReport(path=_rel(path))
    with _lock(path):
        cf = load_case(ref) or _empty_case(ref)
        have = {n.uid for n in cf.notes}
        known = have | {n.uid for n in notes}
        for n in notes:
            target = n.supersedes or n.retracts
            if target and target not in known:
                report.errors.append({"uid": n.uid, "error":
                                      f"запису {target} у нотатнику справи немає"})
                continue
            if n.uid in have:
                report.merged.append(n.uid)
                continue
            cf.notes.append(n)
            have.add(n.uid)
            report.added.append(n.uid)
        if report.added:
            _write(path, cf)
    return report


def move_pages(src: CaseRef, dst: CaseRef, scans: list[str]) -> dict[str, int]:
    """Перенести нотатки й записи названих кадрів з однієї справи в іншу.

    Потрібне розбивці збірної теки: нотатки всіх її справ лежали у файлі
    першої. 🔴 Спершу запис у нову справу, потім прибирання зі старої — обрив
    між ними лишає дубль, який повтор зведе, а не втрату.

    Запис переходить, лише коли ВСІ його кадри названо: запис через межу
    справ лишається, де був, і це видно у звіті розбивки числом.
    """
    want = {str(s).casefold() for s in scans}
    sp, dp = case_path(src), case_path(dst)
    if not want or not sp.is_file() or sp == dp:
        return {"pages": 0, "records": 0}
    cf = load_case(src)
    if cf is None:
        return {"pages": 0, "records": 0}
    notes = [n for k, n in cf.pages.items() if k.casefold() in want]
    recs = [r for r in cf.records
            if r.scans and all(s.casefold() in want for s in r.scans)]
    # Читання рядка прив'язане до кадру, тож їде разом із ним. Ключ — стем:
    # у прогоні сторінка зветься «0031», у сховищі — «0031.JPG».
    stems = {Path(s).stem.casefold() for s in want}
    reads, kept = _notes_to_move(cf.notes, stems)
    if not notes and not recs and not reads:
        return {"pages": 0, "records": 0, "notes": 0, "notes_kept": kept}
    if notes:
        annotate_pages(dst, notes)
    if recs:
        add_records(dst, recs)
    moved: set[str] = set()
    if reads:
        rep = add_notes(dst, reads)
        # 🔴 Зі старої справи прибирається лише те, що в новій справді лягло:
        # відмовлений запис, прибраний «про всяк випадок», зникав з обох файлів.
        moved = set(rep.added) | set(rep.merged)
    rids = {r.rid for r in recs}
    uids = moved
    with _lock(sp):
        cf = load_case(src) or cf
        cf.pages = {k: n for k, n in cf.pages.items() if k.casefold() not in want}
        cf.records = [r for r in cf.records if r.rid not in rids]
        cf.notes = [n for n in cf.notes if n.uid not in uids]
        _write(sp, cf)
    return {"pages": len(notes), "records": len(recs), "notes": len(uids),
            "notes_kept": kept}


def _notes_to_move(notes: list[CaseNote], stems: set[str]) -> tuple[list[CaseNote], int]:
    """Записи нотатника, що їдуть разом із названими кадрами, — ЛАНЦЮЖКАМИ.

    🔴 Ланцюжок (запис, його заміни й відкликання) переїжджає цілим або лишається
    цілим. Порізаний по межі справ він ламався: відкликання без сторінки
    лишалось у старій справі, і відкликане читання оживало в новій; заміна, чий
    попередник лишився, не лягала в нову справу зовсім (перевірка випуску 0.26.0).
    Ланцюжок, що зачіпає сторінки обох справ, лишається, де був, — і це число
    повертається, а не губиться.
    """
    parent = {n.uid: n.uid for n in notes}

    def root(u: str) -> str:
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for n in notes:
        for link in (n.supersedes, n.retracts):
            if link and link in parent:
                parent[root(n.uid)] = root(link)
    groups: dict[str, list[CaseNote]] = {}
    for n in notes:
        groups.setdefault(root(n.uid), []).append(n)
    out: list[CaseNote] = []
    kept = 0
    for members in groups.values():
        pages = [Path(m.page).stem.casefold() for m in members if m.page]
        if not pages or not any(p in stems for p in pages):
            continue
        if all(p in stems for p in pages):
            out += members
        else:
            kept += 1
    order = {n.uid: i for i, n in enumerate(notes)}
    return sorted(out, key=lambda n: order[n.uid]), kept


# ── статус: «чи рендерити цю сторінку?» ──────────────────────────────────────
def _disk_scans(ref: CaseRef) -> list[str]:
    if not ref.path:
        return []
    d = (ROOT / ref.path)
    if not d.is_dir():
        return []
    # Знаменник — за тим самим правилом, що в реєстрі й раннері (`frame_names`):
    # свій набір розширень тут давав справі інше число кадрів (аудит 29.09.2026).
    return sorted(frame_names(p.name for p in d.iterdir() if p.is_file()))


_NUM_NAME_RE = re.compile(r"^(.*?)(\d+)(\D*)$")


def _compress(names: list[str]) -> list[str]:
    """Послідовні числові імена → діапазони: «0031.JPG–0045.JPG (15)»."""
    out: list[str] = []
    run: list[str] = []
    prev: tuple[str, int, str] | None = None
    def flush() -> None:
        if not run:
            return
        out.append(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]} ({len(run)})")
        run.clear()
    for name in names:
        m = _NUM_NAME_RE.match(name)
        cur = (m.group(1), int(m.group(2)), m.group(3)) if m else None
        if not (cur and prev and cur[0] == prev[0] and cur[2] == prev[2]
                and cur[1] == prev[1] + 1):
            flush()
        run.append(name)
        prev = cur
    flush()
    return out


def case_status(ref: CaseRef, scans: list[str] | None = None) -> dict[str, Any]:
    """Гейт перед рендером: що вже оброблено, що ні."""
    cf = load_case(ref)
    pages = cf.pages if cf else {}
    if scans:
        # Розкладено з тернарного виразу з «моржем» у звичайну функцію. Той
        # вираз працював (умова обчислюється перша, тож `n` встигає звʼязатись),
        # але перевіряч його не доводив — а гілка «сторінку вже дивились» тут
        # головна: саме вона рятує від повторного рендеру всієї справи.
        def _one(scan: str) -> dict[str, Any]:
            note = pages.get(scan)
            if note is None:
                return {"scan": scan, "noted": False}
            return {"scan": scan, "noted": True, "page_type": note.page_type,
                    "status": note.status, "surnames_n": len(note.surnames),
                    "noted_date": note.noted.isoformat()}

        return {"key": ref.key, "shifra": ref.shifra,
                "scans": [_one(s) for s in scans]}
    disk = _disk_scans(ref)
    unnoted = [s for s in disk if s not in pages]
    by_status: dict[str, int] = {}
    for n in pages.values():
        by_status[n.status] = by_status.get(n.status, 0) + 1
    return {
        "key": ref.key, "shifra": ref.shifra, "title": ref.title,
        "total_disk": len(disk) or (ref.frames or 0),
        # 🔴 Нуль сканів і «теки не знайшли» — різні речі, і плутати їх не можна:
        # перше означає «справа порожня», друге — «реєстр про неї ще не знає».
        # Показане як «0 на диску», друге виглядає так, ніби скани зникли.
        "case_dir_known": bool(ref.path),
        "noted": len(pages), "by_status": by_status,
        "records": len(cf.records) if cf else 0,
        "unnoted_count": len(unnoted) if disk else None,
        "unnoted": _compress(unnoted) if disk else None,
    }


def totals() -> dict[str, Any]:
    """Скільки аркушів облік ока тримає по всьому сховищу.

    🔴 Одна глобальна відповідь, і саме тому вона тут, а не в реєстрі справ.
    Реєстр рахує занесені аркуші, розкладені по справах (`cases.collect`), тож
    замітка у файлі, чийого ключа реєстр не впізнав, у його сумі не з'являється
    зовсім. Ця різниця — не похибка, а знахідка: занесені аркуші, які жоден
    екран про справу не покаже. Тому обидва числа лишаються, і в них різні
    імена, а не одне на двох: один графік із двох визначень показав би падіння
    там, де просто змінилось джерело.

    Читає файли, а не моделі: сховище дописується різними версіями застосунку,
    і сувора валідація тут перетворила б зведення на відмову через одну картку.
    """
    out: dict[str, Any] = {"files": 0, "pages": 0, "full": 0,
                           "records": 0, "by_status": {}}
    if not PAGES_ROOT.is_dir():
        return out
    for f in sorted(PAGES_ROOT.glob("*/*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out["files"] += 1
        pages = data.get("pages")
        items = (list(pages.values()) if isinstance(pages, dict)
                 else pages if isinstance(pages, list) else [])
        out["pages"] += len(items)
        for p in items:
            if not isinstance(p, dict):
                continue
            st = str(p.get("status") or "")
            if st:
                out["by_status"][st] = out["by_status"].get(st, 0) + 1
            if st == "full":
                out["full"] += 1
        recs = data.get("records")
        out["records"] += len(recs) if isinstance(recs, list) else 0
    return out
