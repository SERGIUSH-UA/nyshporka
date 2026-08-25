"""✅ Чи справу справді прочитано — і чим це доведено.

Єдине питання модуля: **скільки сторінок є на диску проти скількох мало бути**.
Усе інше — код повернення, «готово» в лозі, вердикт віддаленого процесу — тут
доказом не вважається, і це не педантизм:

* є клас відмов, за якого лог обривається без traceback, перелік збоїв у меті
  порожній, а прогін виглядає успішним — виміряно на прогоні, де процес помер
  на 15-й сторінці з 18;
* брак відеопам'яті з'їдає сторінки взагалі мовчки: шард падає, пише у ВЛАСНИЙ
  лог і виходить із нульовим кодом, тож підсумок чистий, а сторінок немає;
* карантин **переживає перезапуск**, тож другий захід не повторює
  проблемних сторінок і чесно рапортує «повністю» — при тому, що на диску 518
  із 531.

🔴 Тому знаменників тут ТРИ, і вони незалежні: кадри в теці, число з мети
прогону, тексти на диску. Розбіжність між першими двома — сама по собі подія,
а не дрібниця: вона означає, що читали не те, що збирались.

🔴 Нуль знаменника — **не «повно»**, а «нема з чим звіряти». Порожня тека, з
якої нічого не очікували, інакше проходить як бездоганно виконана робота.

⚠ Приймач тут — дзеркало `htr.runner.missing_pages`, а не виклик його. Раннер
живе в іншому інтерпретаторі й тягне на імпорті `numpy` та `PIL`, яких у ядрі
немає; рівність двох реалізацій доводить тест — так само, як для каналу
прогресу.

⚠ Чим це відрізняється від `htr.run.completeness()`, яка вже є. Та звіряє
ЧИСЛА — скільки кадрів проти скількох текстів — і для локального прогону цього
досить: тека та сама, прогін один, розійтись нема куди. Хмарний прогін ламає всі
три припущення: кадри розпаковувала чужа машина, прогонів було кілька (шарди,
догін), а результат приїхав частинами. Тому тут звірка ПОКАДРОВА (той самий
кадр ↔ той самий текст, а не «однаково штук»), із карантином і з голосами.
Замінювати нею локальну не станемо: у неї інша ціна помилки й інший читач.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Розширення кадрів. Дзеркало `htr.run._IMG_EXT`.
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

META_NAME = "_htr_meta.json"
QUARANTINE_NAME = "_htr_quarantine.json"


@dataclass(frozen=True)
class Completeness:
    """Вирок про повноту — разом зі знаменником, яким його винесено."""

    complete: bool
    expected: int
    got: int
    missing: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    #: Чим узято знаменник: `кадри` | `мета прогону` | `—`.
    source: str = ""
    detail: str = ""
    #: Усі три числа. Показуються завжди: саме їх розбіжність і є діагнозом.
    denominators: dict[str, int] = field(default_factory=dict)
    #: Чи розходяться знаменники між собою.
    disagree: bool = False

    @property
    def missing_count(self) -> int:
        return len(self.missing)

    def as_dict(self) -> dict[str, Any]:
        return {"complete": self.complete, "expected": self.expected,
                "got": self.got, "missing_count": self.missing_count,
                "missing": self.missing[:50], "quarantined": self.quarantined[:50],
                "source": self.source, "detail": self.detail,
                "denominators": dict(self.denominators), "disagree": self.disagree}

    def human(self) -> str:
        if not self.expected:
            return f"⚠ {self.detail or 'нема з чим звіряти'}"
        mark = "✅" if self.complete else "🔴"
        tail = f" · бракує {self.missing_count}" if self.missing else ""
        q = f" · карантин {len(self.quarantined)}" if self.quarantined else ""
        return (f"{mark} сторінок з текстом: {self.got} з {self.expected} "
                f"({self.source}){tail}{q}")


def frames_in(case_dir: Path) -> list[Path]:
    """Кадри ПРЯМО в теці. Підтеки не рахуються — їх не бачить і раннер."""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        return []
    return sorted(p for p in case_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in IMG_EXT)


def missing_pages(pages_all: list[Path], out_dir: Path,
                  side_dirs: tuple[Path, ...] = ()) -> list[str]:
    """Кадри без тексту на диску. Дзеркало `htr.runner.missing_pages`.

    Побічні теки голосів перевіряються теж: ансамбль пише їх у тому самому
    проході, тож текст основного голосу без тексту другого — це недороблена
    сторінка, а не «модель промовчала».
    """
    gone: list[str] = []
    for p in pages_all:
        if not (out_dir / f"{p.stem}.txt").exists():
            gone.append(p.name)
            continue
        for d in side_dirs:
            if not (d / f"{p.stem}.txt").exists():
                gone.append(p.name)
                break
    return gone


def voice_dirs(out_dir: Path) -> tuple[Path, ...]:
    """Сестринські теки голосів — `<прогін>-<тег>` поруч із головною.

    🔴 Саме сестринські, а не вкладені. Складені в одну теку голоси дають
    нуль знахідок при пошуку БЕЗ жодної помилки: файли перетирають один одного
    за іменем, і залишається текст того голосу, який писав останнім.
    """
    out_dir = Path(out_dir)
    parent = out_dir.parent
    if not parent.is_dir():
        return ()
    prefix = out_dir.name + "-"
    return tuple(sorted(d for d in parent.iterdir()
                        if d.is_dir() and d.name.startswith(prefix)))


def read_meta(out_dir: Path) -> dict[str, Any]:
    """Мета прогону. Побита або відсутня — порожньо, це не привід падати."""
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(Path(out_dir) / META_NAME, default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}


def read_quarantine(out_dir: Path) -> list[str]:
    """Сторінки, які прогін відклав. 🔴 Це НЕ зроблені сторінки.

    Карантин — не властивість кадру, а наслідок зіткнення щільної сторінки з
    розбиттям на процеси: ті самі кадри в один потік проходять з першого разу.
    Тому вони перелічуються окремо — щоб було видно, що доганяти.
    """
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(Path(out_dir) / QUARANTINE_NAME, default={})
    except CorruptFileError:
        return []
    if isinstance(raw, dict):
        return sorted(str(k) for k in raw)
    if isinstance(raw, list):
        return sorted(str(x) for x in raw)
    return []


def texts_in(out_dir: Path) -> int:
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return 0
    return sum(1 for p in out_dir.glob("*.txt") if not p.name.startswith("_"))


def verify(out_dir: Path | str, *, case_dir: Path | str = "",
           expected_hint: int = 0, check_voices: bool = True) -> Completeness:
    """Звести три знаменники й винести вирок.

    `case_dir` — тека кадрів, якщо вона є локально (для хмарного прогону вона
    є завжди: звідти кадри й везли). `expected_hint` — число з плану, коли
    самої теки під рукою немає.
    """
    out = Path(out_dir)
    frames = frames_in(Path(case_dir)) if case_dir else []
    meta = read_meta(out)
    meta_total = int(meta.get("frames_total") or 0)

    dens = {"кадри": len(frames), "мета прогону": meta_total,
            "підказка плану": int(expected_hint or 0)}
    known = [v for v in dens.values() if v > 0]

    if not known:
        return Completeness(
            complete=False, expected=0, got=texts_in(out),
            source="—", denominators=dens,
            detail=("нема з чим звіряти: ні кадрів у теці, ні числа в меті "
                    "прогону. Нуль без знаменника не є доказом повноти"))

    # 🔴 Беремо НАЙБІЛЬШИЙ відомий знаменник. Помилка в бік «здається, бракує»
    # коштує зайвої перевірки; помилка в протилежний бік закриває справу як
    # прочитану, і ніхто до неї більше не повернеться.
    expected = max(known)
    source = next(k for k, v in dens.items() if v == expected)
    disagree = len({v for v in known}) > 1

    sides = voice_dirs(out) if check_voices else ()
    if frames:
        missing = missing_pages(frames, out, sides)
        got = len(frames) - len(missing)
    else:
        got = texts_in(out)
        missing = []

    quarantined = read_quarantine(out)
    # 🔴 Карантин не додається до зробленого навіть тоді, коли текст сторінки
    # якимось чином є: саме на цій поблажці захід рапортував «повністю» при
    # тринадцятьох відкладених сторінках.
    complete = got >= expected and not missing and not quarantined

    bits: list[str] = []
    if disagree:
        pairs = ", ".join(f"{k}: {v}" for k, v in dens.items() if v > 0)
        bits.append(f"⚠ знаменники розходяться ({pairs}) — читали не те, "
                    f"що збирались, або тека справи змінилась після прогону")
    if quarantined:
        bits.append(f"{len(quarantined)} сторінок у карантині — вони НЕ "
                    f"прочитані, і повторний прогін їх не візьме")
    if missing and not quarantined:
        bits.append(f"бракує тексту для {len(missing)} кадрів")
    if sides:
        bits.append(f"голоси: {', '.join(d.name for d in sides)}")

    return Completeness(complete=complete, expected=expected, got=got,
                        missing=missing, quarantined=quarantined, source=source,
                        detail="; ".join(bits), denominators=dens,
                        disagree=disagree)


def tail_is_small(c: Completeness, *, frac: float = 0.02, cap: int = 100) -> bool:
    """Чи хвіст такий малий, що доганяти його вдома дешевше.

    🔴 Правило не про гроші, а про накладні: холодний старт чужої машини коштує
    близько восьми хвилин незалежно від того, дві там сторінки чи двісті. На
    дрібному хвості весь захід і є ці вісім хвилин.
    """
    left = c.missing_count + len(c.quarantined)
    if left <= 0 or not c.expected:
        return False
    return left <= cap and left <= max(1, int(c.expected * frac))
