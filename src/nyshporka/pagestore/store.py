"""Читання/запис сховища сторінок: `data/pages/<REPO>/<fond>-<spr>.json`.

Ідіоми ті самі, що в library/decode_hits: atomic tmp+replace, людська праця
переживає повторний запис (union-merge, статус лише підвищується), ключ справи —
трійка repo/fond/spr без опису. Плюс lockfile — бо основний сценарій це
паралельні агентні сесії, що пишуть в одну справу.
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
from nyshporka.core.workspace import workspace
from nyshporka.library import (
    _DEFAULT_OPYS,
    _REPO_LABEL,
    FOND_TOKEN,
    OPYS_TOKEN,
    Address,
    _mk_key,
    _norm_fond,
    _norm_spr,
    claim_collision,
    find_by_address,
    library_lookup,
    load_library,
    opys_conflict,
    opys_in_case_key,
    opys_in_key,
    parse_address,
    parse_case_code,
    parse_source_id,
    split_fond_opys,
)
from nyshporka.pagestore.models import CaseFile, PageNote, Record
from nyshporka.utils.atomic import atomic_write_text

ROOT = workspace().root
PAGES_ROOT = workspace().pages

# порядок підвищення статусу: понизити повний прохід частковим не можна
_STATUS_RANK = {"unreadable": 0, "skipped": 0, "partial": 1, "full": 2}

# «DAHMO/315/8433» і «ANRM/211-3/140» — друга форма з описом у фонді (`opys_in_key`)
# 🔴 Підкреслення в класі спр. — для збірок: `@fuzovka` і `@parkovo` проходили,
# а `@klirovi_films` і `@kishinev_ispovedn` — ні, бо `_` у клас не входило.
# Виглядало це не як синтаксична межа, а як «такої справи немає»: команда
# друкувала перелік прийнятних форм, серед яких ключ і був. Спіймано 2026-08-13,
# коли перегляд кадру збірки клірових ANRM не було куди занести.
# 🔴 Фонд — спільна цеглина `FOND_TOKEN`, а не `\d+`: `cases.list` друкує ключ
# `DAHMO/R-100/7` для радянського фонду, і цей регекс відмовляв на ньому —
# рядок, виданий пакетом, не приймався назад (issue #21).
_KEY_RE = re.compile(rf"^([A-Za-z]+)/({FOND_TOKEN}(?:-{OPYS_TOKEN})?)/([0-9A-Za-z@_]+)$",
                     re.IGNORECASE)
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
    "ключ без опису «DAHMO/315/8433»; source-id «S_<архів>_F<фонд>_D<справа>»; "
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
    return (f" Два числа неоднозначні: якщо це фонд і справа — «АРХІВ/{a}/{b}»; "
            f"якщо фонд і опис — дай ще й справу.")


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


def _refuse_legacy_file(repo: str, fond: str, opys: str | None, spr: str,
                        key: str, label: str) -> None:
    """Відмова, якщо облік цієї книги лежить під іменем без опису.

    🔴 Фонд, що потрапив у `_OPYS_IN_KEY`, міняє ім'я файла сховища:
    `196-712.json` → `196-1-712.json`. Старий файл лишається, а шукати його вже
    ніхто не шукає: `pages status` каже «не дивились» про переглянуте, а новий
    запис лягає окремим файлом поруч. Обидва наслідки тихі, тож — відмова з
    назвою файлів. Файл, чиє поле `opys` каже про ІНШУ книгу, не заважає.
    """
    if not (opys and opys_in_key(repo, fond)) or str(spr).startswith("@"):
        return
    legacy = PAGES_ROOT / repo / f"{fond}-{spr}.json"
    if not legacy.is_file():
        return
    try:
        was = _norm_spr(json.loads(legacy.read_text(encoding="utf-8")).get("opys"))
    except (OSError, ValueError, AttributeError):
        was = None
    if was and was != _norm_spr(opys):
        return
    new = PAGES_ROOT / repo / f"{fond}-{opys}-{spr}.json"
    both = (f" Поруч уже є «{_rel(new)}» — зведіть записи в нього вручну."
            if new.is_file() else
            f" Перейменуйте його на «{new.name}» і поставте в ньому "
            f"\"key\": \"{key}\", \"opys\": \"{opys}\".")
    raise ValueError(
        f"облік справи {label} {fond}-{opys}-{spr} лежить у «{_rel(legacy)}» — "
        f"записаний до того, як опис увійшов у ключ фонду {label} {fond}, і під "
        f"новим ключем не видний.{both}")


# ── резолюція справи ─────────────────────────────────────────────────────────
def resolve_case(value: str, *, claim: bool = True) -> CaseRef:
    """Будь-який людський ідентифікатор справи → CaseRef. ValueError якщо не вийшло.

    `claim=False` — лише назвати ключ, не записуючи колізію опису в реєстр
    (`opys_keys.json`). Так нормалізується ключ з мети прогону: там шифра
    паспорта на мить прогону, і після виправлення опису (`nysh case --shifra`)
    стара шифра заводила б у реєстр справу, якої на диску немає.
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
    m = _KEY_RE.match(v)
    if m:
        fond_part, opys_part = split_fond_opys(m.group(2))
        # 🔴 Код зводиться до канонічного, як і в сусідній гілці шифри. Голий
        # `.upper()` означав, що ключ `DAVIO/904/105` шукав файл у
        # `data/pages/DAVIO/`, тоді як 109 уже записаних аркушів лежать у
        # `data/pages/DAVO/`. Агент, який чесно питає сховище перед тим, як
        # відкривати скани, діставав порожньо — і передивлявся переглянуте.
        parsed = (_label2repo().get(m.group(1).casefold(), m.group(1).upper()),
                  str(_norm_fond(fond_part)),
                  _norm_spr(opys_part) if opys_part else None,
                  str(_norm_spr(m.group(3))))
    if parsed is None:
        # Канал адреси — того, що людина набирає, коли називає книгу. Розбір
        # спільний (`library.parse_address`), тож форми, які вже приймав реєстр
        # опису, більше не відмовляються тут.
        # ⚠ Стоїть ПІСЛЯ ключа: тільки `_KEY_RE` знає збірки (`DAHMO/315/@fuzovka`),
        # а `SPR_TOKEN` номера на «@» не приймає.
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
    # Фонди з описом у ключі: без опису запит неоднозначний за побудовою
    # («ANRM 211-1-140» с. Парково vs «ANRM 211-3-140» Кишинівський собор).
    # Мовчки взяти перший-ліпший = дописати аркуші в чужу справу, тому — помилка
    # з переліком того, що реально є на диску.
    if opys_in_key(repo, fond) and not opys and not str(spr).startswith("@"):
        cands = sorted({str(e["opys"]) for e in lib.same_fond_spr(fond, spr)
                        if e.get("repo") == repo and e.get("opys")})
        if len(cands) == 1:
            opys = cands[0]
        else:
            label = _REPO_LABEL.get(repo, repo)
            seen = ", ".join(f"«{label} {fond}-{o}-{spr}»" for o in cands) or "жодного"
            raise ValueError(
                f"у фонді {label} {fond} опис входить у ключ, а «{value}» його не несе. "
                f"Уточни опис (напр. «{label} {fond}-3-{spr}» або «{repo}/{fond}-3/{spr}»). "
                f"На диску знайдено: {seen}")
    key = _mk_key(repo, fond, spr, opys)
    if not key:
        raise ValueError(f"не зібрав ключ зі «{value}» (repo={repo} fond={fond} spr={spr})")

    entry = lib.by_key.get(key)
    if entry is not None and opys_conflict(opys, entry.get("opys")):
        # 🔴 Ключ без опису знайшов справу, але її опис НАЗВАНИЙ і РІЗНИТЬСЯ —
        # це фізично інша книга (напр. «ЦДІАК 224-1-49» набрано, а плаский ключ
        # уже тримає «224-2-49»). Узяти чужий запис за свій означало б показати
        # чужу шифру/обсяг і писати облік у файл чужої книги. Заводимо власний
        # ключ з описом і НЕ успадковуємо нічого від знайденого запису.
        if claim:
            key = claim_collision(
                repo, fond, opys, spr, holder_shifra=str(entry.get("shifra") or ""),
                holder_key=str(entry.get("key") or "")) or key
        else:
            key = f"{repo}/{fond}-{opys}/{spr}"
        entry = None
    if entry is None:
        # ДАВО/ДАВіО-плутанина: лейбл шифри каже одне, тека диска — інше.
        # Якщо по (fond, spr) у бібліотеці рівно один запис — його ключ канонічний,
        # інакше нотатки тієї самої справи розповзуться по двох файлах.
        # 🔴 Лише в межах ТОГО САМОГО архіву (`same_as`). Номери фондів і справ
        # повторюються між архівами, і без цього обмеження запис іншого архіву
        # з тим самим фондом і справою мовчки підміняв архів, названий людиною
        # (звіт користувача 29.09.2026: «ДАХмО 315-1-8345» → `DAVIO/315/8345`).
        # Суперечливі записи бібліотеки показує `library_conflicts`.
        pk = _pack_active()
        same = [e for e in lib.same_fond_spr(fond, spr)
                if pk.same_archive(e.get("repo"), repo)
                and not opys_conflict(opys, e.get("opys"))]
        if len(same) == 1:
            entry = same[0]
            repo, key = entry["repo"], entry["key"]
    entry = entry or {}
    opys = opys or entry.get("opys") or _DEFAULT_OPYS.get((repo, fond))
    label = _REPO_LABEL.get(repo, repo)
    _refuse_legacy_file(repo, fond, opys, spr, key, label)
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
    """Шлях JSON-файлу справи. Ім'я — з ключа: опис у ньому лише там, де він у ключі.

    `DAHMO/315/8433` → `DAHMO/315-8433.json`; `ANRM/211-3/140` → `ANRM/211-3-140.json`.
    """
    if opys_in_case_key(ref.repo, ref.fond, ref.spr, ref.opys):
        return PAGES_ROOT / ref.repo / f"{ref.fond}-{ref.opys}-{ref.spr}.json"
    return PAGES_ROOT / ref.repo / f"{ref.fond}-{ref.spr}.json"


# ── читання ──────────────────────────────────────────────────────────────────
def load_case(ref: CaseRef) -> CaseFile | None:
    p = case_path(ref)
    if not p.is_file():
        return None
    return CaseFile.model_validate_json(p.read_text(encoding="utf-8"))


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
    cf.pages = dict(sorted(cf.pages.items()))
    cf.records.sort(key=lambda r: (r.scans[0] if r.scans else "", r.rid))
    payload = cf.model_dump(mode="json")
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
