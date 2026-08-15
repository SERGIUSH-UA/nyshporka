"""▶️ Запуск читання справи: зібрати команду й повести підпроцес.

Раннер живе в ІНШОМУ інтерпретаторі, тож «запустити читання» — це не виклик
функції, а побудова командного рядка. Усе, що для цього треба знати, зібрано
тут, а не розсіяно по консолі, CLI й агенту: три місця, де рядок команди
збирають окремо, розходяться від першої ж нової опції.

🔴 Модель обирається за ПИСЬМОМ, і письмо каже ПРЕФІКС імені, а не розширення.
`.mlmodel` буває двох письм: `skryba_*` — латинка, `diak_*` — кирилиця.
Невідповідність рушія письму дає ТИХЕ сміття: текст виходить, впевненість не
падає, і виглядає це як погані скани. Тому вибір моделі не вгадується з теки.

🔴 Тека справи має бути ПЛАСКОЮ. `--case-dir` не рекурсивний: тека з підтеками
читається як порожня («у теці немає сторінок jpg»). Це коштувало прогонів, тому
перевіряється до запуску, а не після.
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path

_IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


class ReadError(RuntimeError):
    """Прогін не можна почати — з поясненням, що саме заважає."""


@dataclass(frozen=True)
class Plan:
    """Що саме буде запущено. Показується ДО старту."""

    case_dir: Path
    out_dir: Path
    model: Path
    script: str
    frames: int
    python: Path
    runner: Path
    voice: Path | None = None

    #: Спільний кеш сегментації простору. 🔴 Ставиться ЗВІДСИ, бо простір знає
    #: лише ця сторона: раннер їде в чужому інтерпретаторі й, не отримавши
    #: шляху, кладе кеш поруч із виходом. Тоді другий прогін тієї самої справи
    #: (інша модель, другий голос) не бачить готової сегментації й рахує її
    #: заново — а це найдорожча частина сторінки.
    seg_cache: Path | None = None

    def command(self, *, progress_json: bool = True,
                case_key: str = "", limit: int = 0) -> list[str]:
        cmd = [str(self.python), str(self.runner),
               "--case-dir", str(self.case_dir),
               "--out-dir", str(self.out_dir),
               "--model", str(self.model),
               "--script", self.script]
        if self.seg_cache is not None:
            cmd += ["--seg-cache-dir", str(self.seg_cache)]
        if self.voice is not None:
            cmd += ["--models", str(self.voice)]
        if case_key:
            cmd += ["--case-key", case_key]
        if limit:
            cmd += ["--limit", str(limit)]
        if progress_json:
            cmd.append("--progress-json")
        return cmd

    def as_dict(self) -> dict[str, object]:
        return {"case_dir": str(self.case_dir), "out_dir": str(self.out_dir),
                "model": self.model.name, "voice": self.voice.name if self.voice else "",
                "script": self.script, "frames": self.frames}


def count_frames(case_dir: Path) -> int:
    """Кадри ПРЯМО в теці. Підтеки не рахуються — їх не бачить і раннер."""
    if not case_dir.is_dir():
        return 0
    return sum(1 for p in case_dir.iterdir()
               if p.is_file() and p.suffix.lower() in _IMG_EXT)


def _has_subdirs_with_frames(case_dir: Path) -> list[str]:
    out = []
    for d in case_dir.iterdir():
        if d.is_dir() and any(p.suffix.lower() in _IMG_EXT
                              for p in d.iterdir() if p.is_file()):
            out.append(d.name)
    return out


def model_dirs() -> list[Path]:
    """Де шукати ваги — за спаданням довіри.

    1. **Кеш паків** — те, що завантажив застосунок і звірив за sha256.
    2. **Тека простору** (`data/spotter/models`) — те, що людина поклала сама:
       власний файн-тюн, ваги з чужого релізу, модель, натренована вчора.

    🔴 Друге джерело обов'язкове, і це не поступка. Дослідник, у якого ваги вже
    лежать, інакше мусив би або качати те саме вдруге, або відмовитись від
    застосунку — при тому, що його власна модель нерідко краща за роздавану.
    Звірку хешем це не послаблює: пак, який приніс застосунок, перевіряється
    завжди, а про модель, покладену вручну, ми чесно кажемо, звідки вона.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.setup import packs

    out = [packs.target_dir("model")]
    with contextlib.suppress(WorkspaceError):
        out.append(workspace().spotter / "models")
    return [d for d in out if d.is_dir()]


#: Файл, у якому дослідник називає БОЙОВІ ваги за письмом.
PRODUCTION_NAME = "PRODUCTION.json"

#: Хвіст версії в імені: `pysar_cyr_v17.pt`, `skryba_f792_v6.mlmodel`.
_VER_RE = re.compile(r"_v(\d+)[a-z]*\.(?:pt|mlmodel)$", re.IGNORECASE)


def production_choice() -> dict[str, str]:
    """Письмо → ім'я бойової моделі, як його назвав дослідник.

    🔴 Без цього файлу вибір падає на «найновішу за іменем», а «найновіша» ≠
    «найкраща»: у дослідницькому конвеєрі бойовою двічі лишалась не остання
    версія, бо пізніші програвали на голдовому зрізі. Мовчки взяти останню
    означає читати справу гіршою моделлю й не знати про це.
    """
    import json

    for d in model_dirs():
        p = d / PRODUCTION_NAME
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out = {}
        for script, row in (raw.get("production") or {}).items():
            name = (row or {}).get("model") if isinstance(row, dict) else row
            if name:
                out[str(script)] = str(name)
        if out:
            return out
    return {}


def _version_of(path: Path) -> int:
    m = _VER_RE.search(path.name)
    return int(m.group(1)) if m else -1


def local_models() -> list[Path]:
    """Ваги, покладені людиною поруч із дослідженням.

    🔴 Збіг імені з паком НЕ виключає файл. Спершу тут стояв такий фільтр — і
    він робив невидимими саме бойові ваги: `pysar_cyr_v17.pt` є в переліку
    паків, але сам пак не завантажений (реліз ще не складено), тож модель, яка
    лежить у людини на диску, зникала з вибору, а читання тихо падало на
    старішу версію. Дублікати прибираються ПОТІМ, за шляхом.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        d = workspace().spotter / "models"
    except WorkspaceError:
        return []
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.suffix in {".pt", ".mlmodel"})


def pick_model(script: str, *, second_voice: bool = False) -> tuple[Path, Path | None]:
    """Модель під письмо (+ другий голос, якщо просять і якщо він є).

    Другий голос — не «краще про всяк випадок»: CTC (Дяк) прив'язаний до
    пікселів і калічить локально, зберігаючи корінь, тоді як PARSeq має
    внутрішню мовну модель і підставляє правдоподібне слово. Тобто вони
    помиляються ПО-РІЗНОМУ, і саме тому другий голос витягує те, чого перший
    не бачить.
    """
    from nyshporka.htr import manifest as M
    from nyshporka.setup import packs

    man = M.active()
    # (шлях, письмо, рушій) — паки й локальні ваги в одному переліку.
    cands: list[tuple[Path, str, str]] = []
    for pack in packs.catalog():
        if packs.verify(pack):
            cands.append((packs.path_of(pack), pack.script, pack.engine))
    seen = {p for p, _, _ in cands}
    for path in local_models():
        if path in seen:
            continue
        eng = man.engine_for_model(path.name)
        if eng is not None:
            cands.append((path, eng.script, eng.kind))

    if not cands:
        raise ReadError(
            "жодної моделі письма не знайдено — `nysh models get`, або покладіть "
            "власні ваги у `<простір>/data/spotter/models`. Без ваг читати "
            "нічим: рушій є, читати нема чим.")

    # Порядок вибору: назване дослідником → найвища версія → решта. Сортуємо
    # спадно, тож перший підхожий кандидат і є найкращий із наявних.
    named = production_choice()
    cands.sort(key=lambda c: (c[0].name == named.get(c[1], ""), _version_of(c[0])),
               reverse=True)

    main: Path | None = None
    voice: Path | None = None
    for path, scr, kind in cands:
        if scr != script:
            continue
        if kind == "parseq" and main is None:
            main = path
        elif kind == "kraken" and voice is None:
            voice = path
    # Для латинки основний рушій — kraken (Скриба), другого голосу немає.
    if main is None:
        main, voice = voice, None
    if main is None:
        have_str = ", ".join(sorted({f"{p.name} ({s})" for p, s, _ in cands}))
        raise ReadError(
            f"немає моделі для письма «{script}». Є: {have_str}. "
            f"Довантажити: `nysh models get`.")
    return main, (voice if second_voice else None)


def guess_script(case_dir: Path, hint: str = "") -> str:
    """Письмо справи. Підказка від людини сильніша за здогад.

    ⚠ Здогад тут слабкий за побудовою — з імені теки нічого не видно. Він і не
    має бути сильним: помилка тиха, тож у сумнівному випадку краще спитати
    людину, ніж вгадати й віддати сміття.
    """
    if hint in ("latin", "cyrillic"):
        return hint
    name = case_dir.name.lower()
    if re.search(r"kostel|parafial|notar|f792|latin", name):
        return "latin"
    return "cyrillic"


def plan(case_dir: str | Path, *, out_dir: str | Path = "", script: str = "",
         second_voice: bool = True) -> Plan:
    """Зібрати план прогону або пояснити, чого бракує."""
    from nyshporka.core.workspace import workspace
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    case = Path(case_dir).expanduser().resolve()
    if not case.is_dir():
        raise ReadError(f"теки немає: {case}")
    frames = count_frames(case)
    if not frames:
        nested = _has_subdirs_with_frames(case)
        if nested:
            raise ReadError(
                f"у самій теці кадрів немає, вони в підтеках "
                f"({', '.join(nested[:4])}). Читання не рекурсивне — вкажіть "
                f"підтеку або зберіть кадри в одну пласку теку.")
        raise ReadError(f"у теці {case} немає зображень сторінок")

    venv = doc.engine_venv()
    rep = E.inspect(venv)
    if not rep.ok or rep.python is None:
        why = "; ".join(rep.problems) or (
            f"бракує: {', '.join(rep.missing)}" if rep.missing else "не зібране")
        raise ReadError(f"середовище рушіїв не готове ({why}) — `nysh htr install`")

    scr = guess_script(case, script)
    model, voice = pick_model(scr, second_voice=second_voice)
    runner = Path(__file__).resolve().parent / "runner.py"
    ws = workspace()
    out = Path(out_dir) if out_dir else ws.htr_reports / case.name
    # Кеш сегментації — СПІЛЬНИЙ на простір і на справу, а не на прогін: сенс
    # він має рівно тоді, коли ту саму справу читає друга модель.
    import hashlib

    slug = re.sub(r"[^\w.\-]+", "_", case.name)[:60]
    stamp = hashlib.blake2b(str(case).lower().encode("utf-8"),
                            digest_size=4).hexdigest()
    seg = ws.derived / "htr_seg" / f"{slug}__{stamp}"
    return Plan(case_dir=case, out_dir=out, model=model, script=scr,
                frames=frames, python=rep.python, runner=runner, voice=voice,
                seg_cache=seg)
