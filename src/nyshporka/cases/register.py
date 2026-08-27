"""🗂 Завести справу руками: «ця тека — ДАХмО 315-1-8433, метрична книга, 1858».

Досі опис справи міг з'явитись лише двома шляхами: з каталогу архіву або з
сайдкара, який писали скрипти дослідницького конвеєра. Для людини зі сканами на
диску це означало, що її тека лишається безіменною назавжди — бібліотека бачить
кадри, але не знає ні шифри, ні назви, ні років. А без шифри справа не має
ключа, тобто не має ні обліку прочитаного, ні місця в реєстрі, ні можливості
процитувати знахідку.

🔴 Опис пишеться В теку справи (`_source.json`), а не в окрему базу. Причина
конкретна: тека переїжджає між дисками, копіюється на резервний носій і
приїжджає до колеги — і опис мусить їхати з нею. Зовнішня база лишила б після
такого переїзду теку без імені, а базу з посиланням у нікуди.

🔴 Своє не затирається. Сайдкар, написаний завантажувачем архіву, несе
провенанс (звідки качали, коли, яким запитом); правка людини має його доповнити,
а не стерти — інакше перший же ручний коментар знищив би доказ походження.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka import library as L

SIDECAR = "_source.json"

#: «315-1-8433», «ДАХмО 315-1-8433», «ф.315 оп.1 спр.8433», «Ф. 211 Оп. 3 Д. 140»,
#: «ДАВіО Р-6129-24-5» (радянський фонд), «ЦДІАЛ 201-4б-15» (літера в описі).
#:
#: 🔴 Номер фонду й опису описують ЦЕГЛИНИ З `library`, а не власні шаблони. Цей
#: розбір і той, що шукає шифру в тексті, різні за призначенням — тут людський
#: запис із «ф./оп./спр.», там пошук у прозі, — і зводити їх в один не можна. А
#: от відповідь на питання «що таке номер фонду» мусить бути одна: доти кожен
#: ніс власну, і вони розійшлись — бібліотека навчилась читати «Р-6129», а
#: `nysh case` на тій самій шифрі казав «не розібрав».
#:
#: ⚠ Літерний префікс фонду захоплюється лише разом із ДЕФІСОМ, інакше хвіст
#: назви архіву («ДАВіО ») поїхав би в номер фонду.
_SHIFRA_RE = re.compile(
    r"(?:(?P<repo>[A-Za-zА-Яа-яІЇЄҐіїєґ']+)\s+)?"
    rf"(?:ф\.?\s*)?(?P<fond>{L.FOND_TOKEN})\s*[-–/\s]\s*"
    rf"(?:оп\.?\s*|inv\.?\s*)?(?P<opys>{L.OPYS_TOKEN})\s*[-–/\s]\s*"
    r"(?:спр\.?\s*|д\.?\s*|d\.?\s*)?(?P<spr>[\w@]+)",
    re.IGNORECASE)

#: Людські назви архівів → код репозиторію. Свідомо короткий: розширюється
#: паком архівів, а не цим файлом.
_REPO_WORDS = {
    "дахмо": "DAHMO", "dahmo": "DAHMO",
    "даво": "DAVO", "давіо": "DAVO", "davo": "DAVO",
    "цдіак": "CDIAK", "cdiak": "CDIAK",
    "anrm": "ANRM", "анрм": "ANRM", "нам": "ANRM",
    "даоо": "DAOO", "daoo": "DAOO",
    "дажо": "DAZHO", "dazho": "DAZHO",
}


class RegisterError(RuntimeError):
    """Справу не завести — з поясненням, чого бракує."""


@dataclass(frozen=True)
class Shifra:
    repo: str
    fond: str
    opys: str
    spr: str

    def as_text(self) -> str:
        return f"{self.repo} {self.fond}-{self.opys}-{self.spr}"

    # ⚠ Тут була властивість `key`, і вона складала ключ сама: `repo/fond/spr`,
    # без опису й завжди. Для фондів, де опис входить у ключ, це схлопувало
    # «211-1-140» (с. Парково) і «211-3-140» (Кишинівський собор) в одну
    # адресу — тобто аркуші однієї книги мовчки дописувались би в іншу.
    # Викликачів вона не мала жодного, тож була зарядженою міною, а не вадою:
    # ключ у пакеті складає лише `library._mk_key`, який знає про описи.
    # Форматні ворота (`tests/test_case_key_builder.py`) її не бачили — `self.`
    # у f-рядку не підпадав під їхню регулярку.


def parse_shifra(text: str, *, repo_hint: str = "") -> Shifra:
    """Людський запис шифри → розібрана шифра, або зрозуміла відмова.

    Приймає всі форми, якими люди справді пишуть: «315-1-8433»,
    «ДАХмО 315-1-8433», «ф.315 оп.1 спр.8433», «Ф. 211 Оп. 3 Д. 140».
    """
    raw = (text or "").strip()
    if not raw:
        raise RegisterError(
            "шифра порожня. Це не формальність: без неї справа не має ключа, "
            "тобто ні обліку прочитаного, ні місця в реєстрі, ні можливості "
            "послатись на знахідку. Приклад: «ДАХмО 315-1-8433».")
    m = _SHIFRA_RE.search(raw)
    if not m:
        raise RegisterError(
            f"не розібрав шифру «{raw}». Приймаю: «ДАХмО 315-1-8433», "
            f"«315-1-8433», «ф.315 оп.1 спр.8433», «Ф. 211 Оп. 3 Д. 140».")
    word = (m.group("repo") or "").strip().lower().rstrip(".")
    repo = _REPO_WORDS.get(word, "") or (repo_hint or "").upper()
    if not repo:
        raise RegisterError(
            f"з «{raw}» не видно архіву. Додайте його назву («ДАХмО 315-1-8433») "
            f"або вкажіть окремо — інакше та сама шифра в двох архівах злиється "
            f"в одну справу.")
    # 🔴 Фонд зводиться до канону ТІЄЮ САМОЮ функцією, що й у бібліотеці:
    # «Р-6129» кирилицею і «R-6129» латинкою — один фонд. Інакше та сама справа
    # заходила б у облік двома ключами залежно від того, яким письмом її набрали.
    return Shifra(repo=repo, fond=str(L._norm_fond(m.group("fond"))),
                  opys=m.group("opys"), spr=str(m.group("spr")).lstrip("0") or "0")


def read_sidecar(case_dir: Path) -> dict[str, Any]:
    """Наявний опис теки — або порожньо. Помилка читання = порожньо, не виняток."""
    for name in (SIDECAR, "meta.json"):
        f = Path(case_dir) / name
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def case_path(case_dir: str | Path) -> Path:
    """Тека справи як абсолютний шлях.

    🔴 Реєстр справ зберігає шляхи відносними до простору — щоб простір можна
    було перенести на інший диск чи віддати колезі. Через це `Path(...)` від
    такого рядка резолвиться від поточної теки процесу, а вона в демона й у
    командному рядку різна: та сама справа, натиснута кнопкою, «зникала» б, а
    з-під `cd` у корені простору знаходилась. Тому відносний шлях завжди
    добудовується коренем простору, і лише абсолютний береться як є.
    """
    p = Path(case_dir).expanduser()
    if not p.is_absolute():
        from nyshporka.core.workspace import workspace

        p = workspace().root / p
    return p.resolve()


def reachable(case_dir: Path) -> bool:
    """Чи побачить цю теку збірка бібліотеки.

    🔴 Сканується лише `<простір>/data/raw` (та оголошені корені справ). Тека
    на робочому столі чи на флешці лишається невидимою — а саме туди й показує
    людина, яка щойно поставила застосунок.

    Питання не косметичне: без нього заведення справи проходило з ✅, опис
    писався в теку — і на цьому все закінчувалось. Реєстр лишався порожній,
    облік прочитаного не мав куди лягти, пошук нічого не знаходив, вивантаження
    відмовляло. Кожен наступний крок падав з окремої причини, і жодна з них не
    називала справжню.
    """
    from nyshporka.core.workspace import workspace

    for root in workspace().case_roots():
        try:
            case_dir.relative_to(root.resolve())
        except ValueError:
            continue
        return True
    return False


def describe(case_dir: str | Path, *, shifra: str = "", title: str = "",
             doc_type: str = "", year_from: int | None = None,
             year_to: int | None = None, place: str = "", note: str = "",
             repo_hint: str = "") -> dict[str, Any]:
    """Записати або доповнити опис справи в її теці. Повертає готовий сайдкар.

    Порожнє поле не затирає наявне: правка одного заголовка не має стирати
    роки, які хтось уже уточнив.
    """
    d = case_path(case_dir)
    if not d.is_dir():
        raise RegisterError(f"теки немає: {d}")

    old = read_sidecar(d)
    sh: Shifra | None = None
    if shifra:
        sh = parse_shifra(shifra, repo_hint=repo_hint)
    elif old.get("shifra"):
        sh = parse_shifra(str(old["shifra"]), repo_hint=repo_hint)
    if sh is None:
        raise RegisterError(
            "у теці ще немає опису, тож шифра обов'язкова: саме вона робить "
            "теку справою, а не купою файлів.")

    out: dict[str, Any] = dict(old)
    out["shifra"] = sh.as_text()
    out["repo"] = sh.repo
    out["fond"] = sh.fond
    out["opys"] = sh.opys
    out["spr"] = sh.spr
    for key, val in (("title", title), ("doc_type", doc_type), ("place", place)):
        if val:
            out[key] = val
    if year_from is not None:
        out["year_from"] = year_from
    if year_to is not None:
        out["year_to"] = year_to
    if note:
        out["note"] = note
    # 🔴 Слід ручної правки лишається назавжди. Опис, узятий із каталогу архіву,
    # і опис, набраний людиною, мають різну вагу — і не розрізнити їх пізніше
    # означає не знати, чому назва саме така.
    out["desc_source"] = "hand" if not old else out.get("desc_source", "hand")
    out["edited_by_hand"] = True

    tmp = d / (SIDECAR + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / SIDECAR)
    return out


def forget(case_dir: str | Path) -> bool:
    """Прибрати ручний опис. Повертає True, якщо було що прибирати.

    ⚠ Прибирає рівно сайдкар, нічого більше: скани й прочитане лишаються. Без
    опису тека просто повертається в стан «матеріал без шифри».
    """
    f = case_path(case_dir) / SIDECAR
    if not f.is_file():
        return False
    f.unlink()
    return True
