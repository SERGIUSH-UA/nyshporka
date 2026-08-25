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
import os
import re
from dataclasses import dataclass
from pathlib import Path

from nyshporka.htr.pick import ScriptGuess

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

    #: Чим доведене письмо: `fixed` · `genre` · `epoch` · `folder` · `unknown`.
    #: 🔴 Їде в плані, а не лишається в голові того, хто рахував: «кирилиця»
    #: без цього поля читається однаково і як факт з опису справи, і як
    #: здогад з імені теки — а це різниця між прочитаною книгою й текою
    #: правдоподібного сміття.
    script_trust: str = "unknown"
    script_why: str = ""

    #: 🔴 Файл-лок GPU — ВЛАСТИВІСТЬ ТЕКИ ВИХОДУ, а не аргумент виклику.
    #: Дозволити викликачеві передати його означало б дозволити двом шардам
    #: узяти два різні локи, а саме цього лок і не має допустити: два
    #: одночасні проходи сегментації не влазять у пам'ять типової карти, і
    #: прогін не сповільнюється, а ЗАВАЛЮЄТЬСЯ.
    gpu_lock: Path | None = None

    def command(self, *, progress_json: bool = True, case_key: str = "",
                limit: int = 0, pages: str = "", shard: str = "",
                gpu_lock: str = "", gpu_sato: bool = True,
                seg_height: int = 0) -> list[str]:
        """Команда раннера.

        🔴 Важелі ресурсів приймаються ЗВІДСИ, а не зашиті. Раннер має їх
        десятками, але машина в читача одна й невідома нам: 4 ГБ відеопам'яті
        чи 24, шість ядер чи два, справа на 30 аркушів чи на три тисячі. Без
        цих ручок єдиною відповіддю на «не тягне» лишалось би «купіть іншу
        карту», і саме так найдовша робота ставала найкрихкішою.
        """
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
        if pages:
            cmd += ["--pages", pages]
        if shard:
            cmd += ["--shard", shard]
        if gpu_lock:
            cmd += ["--gpu-lock", gpu_lock]
        if not gpu_sato:
            # ⚠ Прапорець знімає sato З КАРТИ, а не з розрахунку: вихід
            # еквівалентний, змінюється лише те, ЧИМ він рахується. Це має
            # значення при шардингу — на карті найдорожча фаза йде під локом,
            # і три процеси стають у чергу замість паралельної роботи.
            cmd.append("--no-gpu-sato")
        if seg_height:
            cmd += ["--seg-height", str(seg_height)]
        if progress_json:
            cmd.append("--progress-json")
        return cmd

    def as_dict(self) -> dict[str, object]:
        return {"case_dir": str(self.case_dir), "out_dir": str(self.out_dir),
                "model": self.model.name, "voice": self.voice.name if self.voice else "",
                "script": self.script, "frames": self.frames,
                "script_trust": self.script_trust, "script_why": self.script_why}

    # ── шарди ────────────────────────────────────────────────────────────────
    def shards(self, workers: int = 1, *, device: str = "",
               **kw: object) -> tuple[list[list[str]], list[str]]:
        """Команди N процесів і застереження до них.

        🔴🔴 Три прапорці народжуються й помирають РАЗОМ, і саме тому вони тут,
        а не в руках викликача. `--shard` без спільного `--gpu-lock` на одній
        карті не сповільнює прогін — він його ЗАВАЛЮЄ: два одночасні проходи
        сегментації не влазять у пам'ять типової карти. А без `--no-gpu-sato`
        шардинг здебільшого не дає нічого: найдорожча фаза сторінки йде під
        локом, і процеси стають у чергу замість паралельної роботи.

        Доти ці три важелі можна було подати поодинці, і найпоширеніша помилка
        була ВИРАЗНОЮ — застереження в командному рядку її лише називало.
        Приймаючи одне число, ми робимо її невимовною.

        ⚠ На процесорі шарди згортаються до одного: там вони не діляться
        картою, а б'ються за ті самі ядра, тобто платять переключенням
        контексту й не виграють нічого.
        """
        notes: list[str] = []
        n = max(1, int(workers or 1))
        if n > 1 and not str(device or "").startswith("cuda"):
            notes.append(
                f"шарди згорнуто до одного: на «{device or 'cpu'}» вони не "
                f"діляться карткою, а змагаються за ті самі ядра")
            n = 1
        if n == 1:
            return [self.command(**kw)], notes  # type: ignore[arg-type]
        lock = str(self.gpu_lock or (self.out_dir / "_gpu.lock"))
        cmds = [self.command(shard=f"{k + 1}/{n}", gpu_lock=lock,
                             gpu_sato=False, **kw)  # type: ignore[arg-type]
                for k in range(n)]
        notes.append(
            f"{n} процеси під одним локом карти; sato знято з карти — виграш "
            f"дає саме поєднання, не шардинг сам собою")
        return cmds, notes


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
    """Письмо справи одним словом. Підказка від людини сильніша за здогад.

    Сам висновок робить `htr.pick`: він дивиться спершу в ОПИС справи, потім у
    жанр і роки, і лише в останню чергу — в ім'я теки. Доти тут стояв самий
    розбір імені, тобто найслабша з чотирьох ознак працювала як єдина.

    🔴 Коли не сказати нічого, повертається `cyrillic` — але це НЕ «письмо
    визначено». Це остання підстава читати хоч чимось, і саме тому повний
    висновок разом із рівнем довіри везе `guess_script_full()`: план мусить
    сказати людині, що письмо ВГАДАНО, бо помилка тут дає не збій, а
    правдоподібне сміття.
    """
    return guess_script_full(case_dir, hint).script or "cyrillic"


def guess_script_full(case_dir: Path, hint: str = "") -> ScriptGuess:
    """Письмо + рівень довіри + причина. `unknown` лишається `unknown`."""
    from nyshporka.htr import pick

    return pick.guess_script_for_dir(case_dir, hint)


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

    guess = guess_script_full(case, script)
    scr = guess.script if guess.script in ("latin", "cyrillic") else "cyrillic"
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
                seg_cache=seg, gpu_lock=out / "_gpu.lock",
                script_trust=guess.trust, script_why=guess.why)


def shard_env(workers: int, *, cores: int = 0) -> dict[str, str]:
    """Змінні середовища для шардів: скільки потоків бере кожен на BLAS.

    🔴 Без цього кожен шард бачить усі ядра машини й забирає їх під матричні
    операції — три процеси по вісім потоків на восьми ядрах душать одне одного
    рівно на тому місці, де прогін і впирається (найдорожче в сторінці рахує
    ПРОЦЕСОР, а не карта). Ділимо навпіл ще раз: половина ядер лишається на
    решту фаз і на саму систему.

    ⚠ Це середовище, а не аргументи, тож ним однаково користуються обидва
    запускачі — і командний рядок, і застосунок.

    🔴 `cores` передається, коли прогін іде НЕ на цій машині. Без цього
    хмарний захід ділив би ядра чужої машини за числом наших: на ноутбуці з
    чотирма ядрами кожен із восьми шардів орендованої машини отримував би один
    потік замість шести — тобто найдорожча фаза сторінки лишалась би без
    процесора рівно там, де його вдосталь.
    """
    n = max(1, int(workers or 1))
    if n == 1:
        return {}
    if cores <= 0:
        try:
            cores = os.cpu_count() or 2
        except Exception:
            cores = 2
    per = max(1, int(cores) // (2 * n))
    return {"OMP_NUM_THREADS": str(per), "MKL_NUM_THREADS": str(per),
            "OPENBLAS_NUM_THREADS": str(per)}


def case_key_for(case_dir: str | Path) -> tuple[str, str]:
    """Шифра справи для мети прогону + звідки її взято.

    🔴 Прогін без шифри стає нічиїм: текст є, а до якої справи належить —
    невідомо. Замір перед ремонтом: із 909 прогонів ключ мали СІМ, і зшивати
    решту довелося правкою JSON руками. Тому ключ шукається САМ, а не чекає,
    що людина набере його щоразу.

    Два канали, обидва стоять на факті:
      1. опис, що лежить У ТІЙ САМІЙ теці (`_source.json`) — подорожує разом
         із матеріалом, тому найнадійніший;
      2. резолвер бібліотеки за шляхом теки.

    🔴 Розбору ІМЕНІ теки тут немає навмисно. Приписаний не тій справі текст
    гірший за неприписаний: рік в імені прогону вже одного разу став номером
    подільської справи, і декод ліг під чужу книгу, виглядаючи як факт.
    """
    d = Path(str(case_dir))
    try:
        from nyshporka.cases.register import read_sidecar

        key = str(read_sidecar(d).get("shifra") or "").strip()
        if key:
            return key, "опис у теці справи"
    except Exception:
        pass
    try:
        from nyshporka.cases.resolve import LibraryIndex, _from_path

        got = _from_path(str(d), LibraryIndex())
        if got:
            return str(got), "резолвер за шляхом теки"
    except Exception:
        pass
    return "", ""


def completeness(case_dir: str | Path, out_dir: str | Path, *,
                 partial: bool = False) -> dict[str, object]:
    """Скільки сторінок ДІЙСНО має текст — приймач по диску, не по коду виходу.

    🔴 Є клас відмов, за якого сторінка вбиває процес: лог обривається, перелік
    збоїв порожній, код повернення успішний. Виміряний випадок — 14 сторінок із
    18. Єдине, що це ловить, — число готових текстів проти числа кадрів.

    ⚠ Для часткового прогону (`--limit`, `--pages`) повнота не міряється: там
    прочитано менше НАВМИСНО, і червоне на здоровому прогоні привчає
    відмахуватись від приймача.

    🔴 Шардинг часткового прогону НЕ робить. У командному рядку один процес —
    це справді один шард із кількох, і там прогін частковий; у застосунку
    завдання володіє ВСІМА шардами, тож їхнє об'єднання є повним прогоном.
    Переплутати означає або лякати червоним справний прогін, або тихо прийняти
    третину справи як прочитану.
    """
    out = Path(str(out_dir))
    pages = len(list(out.glob("*.txt"))) if out.is_dir() else 0
    frames = count_frames(Path(str(case_dir)))
    missing = 0 if partial else max(0, frames - pages)
    return {"pages": pages, "frames": frames, "missing": missing,
            "partial": bool(partial), "ok": missing == 0}


def model_candidates() -> list[dict[str, str]]:
    """Ваги, доступні для читання: пак чи власний файл, письмо, рушій, версія.

    🔴 Той самий перелік, з якого вибирає `pick_model()`. Другий перелік поруч
    розійшовся б із першим тихо: людина бачила б у списку одну модель, а
    прогін ішов би іншою — і пояснити різницю в тексті було б нічим.
    """
    from nyshporka.htr import manifest as M
    from nyshporka.setup import packs

    try:
        man = M.active()
    except Exception:
        return []
    named = production_choice()
    seen: set[Path] = set()
    out: list[dict[str, str]] = []

    for pack in packs.catalog():
        p = packs.path_of(pack)
        ready = False
        with contextlib.suppress(Exception):
            ready = packs.verify(pack)
        seen.add(p)
        out.append({"id": pack.id, "filename": p.name, "path": str(p),
                    "script": pack.script, "engine": pack.engine,
                    "source": "пак", "state": "ok" if ready else "не завантажено",
                    "version": str(_version_of(p)),
                    "production": str(p.name == named.get(pack.script, ""))})
    for p in local_models():
        if p in seen:
            continue
        eng = man.engine_for_model(p.name)
        if eng is None:
            # 🔴 Чужі ваги без відомого префікса лишаються ВИДИМИМИ, але без
            # письма: сховати їх означало б сказати «моделі немає» тому, у кого
            # вона лежить на диску. Вибрати таку модель можна лише свідомо.
            out.append({"id": p.stem, "filename": p.name, "path": str(p),
                        "script": "", "engine": "", "source": "власні ваги",
                        "state": "поза маніфестом", "version": str(_version_of(p)),
                        "production": "False"})
            continue
        out.append({"id": p.stem, "filename": p.name, "path": str(p),
                    "script": eng.script, "engine": eng.kind,
                    "source": "власні ваги", "state": "ok",
                    "version": str(_version_of(p)),
                    "production": str(p.name == named.get(eng.script, ""))})
    return out
