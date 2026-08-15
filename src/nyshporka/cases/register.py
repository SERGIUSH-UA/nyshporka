"""🗂 Завести справу руками: «ця тека — ДАХмО 315-1-8433, метрична книга, 1858».

Досі опис справи міг з'явитись лише двома шляхами: з каталогу архіву або з
сайдкара, який писали скрипти дослідницького конвеєра. Для людини зі сканами на
диску це означало, що її тека лишається безіменною назавжди — бібліотека бачить
кадри, але не знає ні шифри, ні назви, ні років. А без шифри справа не має
ключа, тобто не має ні обліку прочитаного, ні місця в реєстрі, ні можливості
процитувати знахідку.

🔴 Опис пишеться В ТЕКУ СПРАВИ (`_source.json`), а не в окрему базу. Причина
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

SIDECAR = "_source.json"

#: «315-1-8433», «ДАХмО 315-1-8433», «ф.315 оп.1 спр.8433», «Ф. 211 Оп. 3 Д. 140».
_SHIFRA_RE = re.compile(
    r"(?:(?P<repo>[A-Za-zА-Яа-яІЇЄҐіїєґ']+)\s+)?"
    r"(?:ф\.?\s*)?(?P<fond>\d+)\s*[-–/\s]\s*"
    r"(?:оп\.?\s*|inv\.?\s*)?(?P<opys>\d+)\s*[-–/\s]\s*"
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

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.fond}/{self.spr}"


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
    return Shifra(repo=repo, fond=m.group("fond"),
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
    """Тека справи як АБСОЛЮТНИЙ шлях.

    🔴 Реєстр справ зберігає шляхи ВІДНОСНИМИ до простору — щоб простір можна
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


def describe(case_dir: str | Path, *, shifra: str = "", title: str = "",
             doc_type: str = "", year_from: int | None = None,
             year_to: int | None = None, place: str = "", note: str = "",
             repo_hint: str = "") -> dict[str, Any]:
    """Записати або доповнити опис справи в її теці. Повертає готовий сайдкар.

    Порожнє поле НЕ затирає наявне: правка одного заголовка не має стирати
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
            "теку СПРАВОЮ, а не купою файлів.")

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

    ⚠ Прибирає РІВНО сайдкар, нічого більше: скани й прочитане лишаються. Без
    опису тека просто повертається в стан «матеріал без шифри».
    """
    f = case_path(case_dir) / SIDECAR
    if not f.is_file():
        return False
    f.unlink()
    return True
