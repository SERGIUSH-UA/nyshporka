"""🛰 Наглядацький шлях: справу веде відчеплений наглядач `gpurunner`.

Тонкий шлях (`cloud.run`) сам тримає SSH-з'єднання з машиною від оренди до
гасіння — і тому живе рівно доти, доки живий термінал. Тут інакше: Нишпорка
готує захід, віддає його наглядачеві й виходить. Наглядач орендує машину,
регулює флот під заміряний темп, доганяє пропуски, звіряє повноту, гасить
оренду й кличе облік — усе це вже після того, як наша команда завершилась.

    справа → кадри цілі? → завеликі — стиснути → архів ассетів за хешем →
    план → передполіт → кошторис вилкою → рішення → наглядач у фон

🔴 Ця схема НЕ нова. Вона возить справи дослідницького конвеєра сотнями
оплачених прогонів, і кожен її запобіжник куплений за гроші:
архів ассетів іменується за хешем вмісту, бо старий раннер на боксі
одного разу зробив флот утричі повільнішим; `case_dir` у плані підмінюється
оригінальною текою, бо інакше кроп ріжеться зі стиснутої копії; кошторис
береться в того самого наглядача, який потім спиниться на бюджеті, — інакше
бюджет рахувала б одна модель, а виконувала інша. Переносячи це сюди, нічого
з переліченого не «спрощувати».

Межа відповідальності: наглядач знає про ХМАРУ (ринок, оренда, доставка,
забір, гасіння), Нишпорка — про РОБОТУ (яка модель бойова, що таке справа, чия
вона, куди лягає текст). Тому стик — командний рядок `gpurunner htr …` з
машинним `--json`, а не спільний код.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.cloud import money as M
from nyshporka.cloud import state as ST

if TYPE_CHECKING:  # pragma: no cover — лише для перевірки типів
    from collections.abc import Callable, Iterable, Sequence

    from nyshporka.cloud.convoy import Convoy
    from nyshporka.cloud.go import GoResult

#: Ім'я, під яким раннер лежить в архіві ассетів і на машині. Наглядач
#: запускає саме його, тож перейменування тут — це зміна контракту з машиною.
RUNNER_ARCNAME = "htr_case_run.py"
#: Теки ВСЕРЕДИНІ архіву ассетів. Окремими константами, бо це не шляхи в
#: пакеті й не поради людині: так розкладає вміст машина, коли розпаковує
#: архів, і саме такої розкладки чекає раннер.
ARC_MODELS = "models"
ARC_SCRIPTS = "scripts"
#: Модуль читання рядків, який раннер підвантажує поруч із собою.
LINES_MODULE = "pysar_lines_infer.py"

#: Стеля годин заходу: більше не дозволяють посилання плану (`url_hours` 24 ≥
#: H·1.5 + 2). Не «очікуваний час» — саме допустимий.
MAX_HOURS_CAP = M.MAX_HOURS_CAP

#: Кадри ×2 (архів + розпаковане) плюс стільки ГБ на моделі, середовище й вихід.
DISK_OVERHEAD_GB = 5
DISK_MIN_GB = 15

#: Скільки ядер ХОЧЕТЬСЯ від машини. 🔴 Шістнадцять, а не шістдесят чотири:
#: ядра темпу не купують (дуель двох машин це показала), зате машини на 64
#: ядра на ринку може просто не бути — і захід стоїть у безкоштовному, але
#: марному чеканні, поки регулятор сам не опустить планку.
PREFER_CORES = 16.0


#: Чому захід їде без засіву сегментації — і скільки це коштує. 🔴 Ціна
#: називається завжди: мовчазний відкат виглядає як «усе гаразд», а рахунок
#: приходить удвічі більший.
_NO_SEED_WHY = ("засів сегментації їде першим чекпоінтом у сховище, а його "
                "тут немає — читаємо БЕЗ засіву: сторінка коштуватиме ще й "
                "сегментацію (замір 9.1 → 18.4 с/стор)")
_NO_SEED_NOTE = "перечитування пішло без засіву сегментації: сховища немає"


class SupervisorMissing(RuntimeError):
    """Наглядача немає на цій машині. Текст — для людини, дослівно."""


# ── наглядач ────────────────────────────────────────────────────────────────
def gpurunner_cmd() -> list[str]:
    """Чим кликати наглядача: модуль у цьому ж середовищі або програма в PATH.

    🔴 Спершу модуль (`python -m gpurunner`), а не програма: пакет оренди
    ставить наглядача поруч із нами, і саме його версія звірена з цим кодом.
    Програма з PATH може виявитись чужою збіркою з іншого середовища — а
    відчеплений процес успадковує її на весь захід.

    ⚙ `NYSH_GPURUNNER` сильніша за обидва здогади: коли Нишпорку кличуть із
    чужого простору, де наглядач живе у власному середовищі поруч, адресу знає
    лише той, хто кличе. Явно названий шлях не перевіряємо на існування тут —
    нехай відмовить сам виклик із зрозумілою причиною.
    """
    from importlib.util import find_spec

    named = os.environ.get("NYSH_GPURUNNER", "").strip()
    if named:
        return [named]
    try:
        if find_spec("gpurunner") is not None:
            return [sys.executable, "-m", "gpurunner"]
    except (ImportError, ValueError):
        pass
    found = shutil.which("gpurunner")
    if found:
        return [found]
    raise SupervisorMissing(
        "наглядача хмарних прогонів немає: `nysh cloud go` на орендованій "
        "машині веде його. Поставте: `pip install \"nyshporka[rent]\"`, "
        "далі `nysh cloud rent login`. Читати на СВОЇЙ "
        "машині по SSH можна й без нього: `nysh cloud go --thin` або "
        "`nysh cloud start <тека> --host <машина>`.")


def _env(session: str, exe: str) -> dict[str, str]:
    """Оточення викликів наглядача.

    `PATH` з текою програми — бо відчеплений процес першим ділом шукає себе
    через PATH. `GPURUNNER_REPO_DATA_DIR` — лише якщо простір справді тримає
    реєстр машин: без адреси наглядач заведе порожній реєстр у профілі
    користувача й піде орендувати машини, які цей простір уже забракував.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    env = {"PYTHONIOENCODING": "utf-8", "GPURUNNER_OWNER": session}
    folder = Path(exe).parent
    if folder.is_dir():
        env["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
    if not os.environ.get("GPURUNNER_REPO_DATA_DIR"):
        try:
            data = workspace().data / "gpurunner"
        except WorkspaceError:
            data = None
        if data is not None and data.is_dir():
            env["GPURUNNER_REPO_DATA_DIR"] = str(data)
    return env


def _run(cmd: list[str], *, env: dict[str, str],
         capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, env={**os.environ, **env}, text=True,
                          encoding="utf-8", errors="replace",
                          capture_output=capture, check=False)


# ── ассети ──────────────────────────────────────────────────────────────────
def assets_inputs(models: Sequence[Path]) -> list[tuple[str, Path]]:
    """Що їде на машину: ваги й скрипти ПОТОЧНОГО раннера.

    Розкладка всередині архіву та сама, що в перевірених заходах: ваги в теці
    моделей, раннер і модуль читання рядків — у теці скриптів, поруч патчі
    рушія. Машина зсипає всі модулі в одну теку, а раннер іде як скрипт, тож
    його тека стоїть першою в шляху пошуку модулів.
    """
    runner = runner_path()
    htr = runner.parent
    items = [(f"{ARC_MODELS}/{p.name}", p) for p in models]
    items.append((f"{ARC_SCRIPTS}/{RUNNER_ARCNAME}", runner))
    items.append((f"{ARC_SCRIPTS}/{LINES_MODULE}", htr / LINES_MODULE))
    items += [(f"{ARC_SCRIPTS}/patches/{p.name}", p)
              for p in sorted((htr / "patches").glob("*.py"))]
    items.append((f"{ARC_SCRIPTS}/{ENGINE_REQUIREMENTS}", engine_requirements_file()))
    return items


#: Вимоги середовища рушіїв у архіві ассетів (читає `gpurunner htr plan`).
ENGINE_REQUIREMENTS = "engine_requirements.txt"


def _plan_carries_engine(plan_path: Path) -> bool:
    """Чи склав наглядач план, що везе на бокс середовище рушіїв з маніфесту."""
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    params = plan.get("params") or {}
    if isinstance(params, dict):
        reqs = str(params.get("engine_requirements") or "")
    else:   # перелік `ключ=значення` — так план пишуть і прості збірки наглядача
        reqs = next((str(p).split("=", 1)[1] for p in params
                     if str(p).startswith("engine_requirements=")), "")
    return any(line.strip().startswith("kraken==") for line in reqs.splitlines())


def engine_requirements_file() -> Path:
    """Вимоги середовища рушіїв із маніфесту — файлом, що їде поруч із раннером.

    🔴 Одне джерело пінів. Доти бокс ставив власний перелік наглядача
    (`kraken==7.0.2`, PARSeq без коміту) — тобто хмара читала іншим
    середовищем, ніж машина людини, і розходження ловилось лише текстом
    (0.42% CER між хмарою й домом). Тепер раннер їде разом із тим, чим його
    рахувати, і архів, узятий через місяці, ставить саме свої піни.
    Ім'я файлу на диску — за хешем вмісту, тож хеш архіву змінюється лише
    тоді, коли змінились самі піни.
    """
    import tempfile

    from nyshporka.htr import manifest as HM

    man = HM.active()
    # torch — еталонні піни: бокс поставить їх колесом з індексу під свою карту
    lines = ["# середовище рушіїв Нишпорки — з htr/data/engines.yaml",
             *man.pip_specs(), *man.torch_reference]
    text = "\n".join(lines) + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    out = Path(tempfile.gettempdir()) / "nyshporka-engine" / f"requirements_{digest}.txt"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return out


def runner_path() -> Path:
    """Файл раннера — шлях, а не модуль.

    На боксі раннер запускає python СЕРЕДОВИЩА РУШІЇВ, де Нишпорки немає й не
    буде (там свій `kraken` під патчі). Саме тому в самому раннері немає жодного
    імпорту пакета, а знайти файл треба звідси — і без виконання модуля.
    """
    from importlib.util import find_spec

    spec = find_spec("nyshporka.htr.runner")
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin:
        raise SupervisorMissing("не знайшов файл раннера `nyshporka.htr.runner` "
                                "— перевстановіть Нишпорку")
    return Path(origin).resolve()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def assets_name(items: Sequence[tuple[str, Path]], *, stem: str) -> str:
    """Ім'я архіву за ХЕШЕМ вмісту: інший раннер — інше ім'я.

    🔴 Не за версією моделі. Одного разу на боксі лежав старий раннер без
    ліміту потоків, і флот ішов утричі повільніше; іншого разу план узагалі не
    звіряв скриптів. Сплутати архіви за побудовою неможливо лише так.
    """
    h = hashlib.sha256()
    for arc, p in sorted(items):
        h.update(arc.encode("utf-8"))
        h.update(_sha256(p).encode("ascii"))
    return f"assets_{stem}_{h.hexdigest()[:10]}.tgz"


def build_assets(items: Sequence[tuple[str, Path]], dest_dir: Path, *,
                 stem: str) -> Path:
    """Зібрати архів (або взяти готовий з тим самим іменем)."""
    missing = [str(p) for _, p in items if not p.is_file()]
    if missing:
        raise SupervisorMissing("для архіву ассетів бракує файлів: "
                                + ", ".join(missing))
    out = dest_dir / assets_name(items, stem=stem)
    if out.is_file():
        return out
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with tarfile.open(tmp, "w:gz") as tf:
        for arc, p in sorted(items):
            tf.add(p, arcname=arc)
    tmp.replace(out)
    return out


# ── дрібні рахунки ──────────────────────────────────────────────────────────
def disk_for(total_mb: float) -> int:
    """Скільки ГБ диску просити. Завищена вимога відсікає здорові машини."""
    return max(DISK_MIN_GB,
               math.ceil(total_mb * 2 / 1024 + DISK_OVERHEAD_GB))


def session_name(run_name: str, *, extra: int = 0) -> str:
    """Ім'я сесії наглядача: справа плюс час ДО СЕКУНД.

    🔴 Час тут не робить імені унікальним, і хвіст із чотирьох випадкових
    знаків — не прикраса. Повторний захід тієї самої справи (звична дія після
    збою) інакше дістав би ім'я вже зайнятої сесії: стан, журнал і вирок двох
    різних оренд змішалися б в один запис.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "-"
                   for c in run_name.lower()).strip("-")
    tail = secrets.token_hex(2)
    # `q3` у імені каже, що в черзі три справи: у переліку сесій видно розмір
    # заходу, не відкриваючи плану.
    queue = f"-q{extra + 1}" if extra else ""
    return f"htr-{safe or 'case'}{queue}-{datetime.now():%m%d-%H%M}-{tail}"


def nysh_exe() -> str:
    """Програма `nysh` цього середовища — для гачків обліку.

    Абсолютним шляхом: відчеплений наглядач не має нашого PATH, і «nysh» у
    його оточенні може не існувати або бути чужим.
    """
    exe = Path(sys.executable).parent / ("nysh.exe" if os.name == "nt" else "nysh")
    if exe.is_file():
        return str(exe)
    return shutil.which("nysh") or ""


def post_fetch_hooks(run_names: Sequence[str] | str) -> list[dict[str, Any]]:
    """Облік після ПОВНОГО забору — те саме, що робить тонкий шлях сам.

    Наглядач виконає їх лише при вердикті `ok`. Без цього реєстр казав би
    «декоду немає» про справу, яку щойно прочитано.

    🔴 Реєстр перебудовується ОДИН раз на захід, а текст індексується для
    КОЖНОЇ справи: пропущена справа партії — це рівно той хибний нуль, проти
    якого гачки й написані.

    🔴🔴 `cwd` — КОРІНЬ ПРОСТОРУ, і це не дрібниця. Простір Нишпорка визначає
    за робочою текою, а відчеплений наглядач живе своєю: без цього рядка
    `nysh text index --case <справа>` шукав справу в ЧУЖОМУ просторі й падав
    із порадою про формат шифри. Спіймано живим заходом 21.09.2026: реєстр
    перебудувався, а індекс тексту не дістав жодної з двох справ — тобто
    пошук по щойно прочитаному давав би нуль.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    exe = nysh_exe()
    if not exe:
        return []
    try:
        root = str(workspace().root)
    except WorkspaceError:
        return []
    names = [run_names] if isinstance(run_names, str) else list(run_names)
    return [{"cmd": [exe, "cases", "build"], "cwd": root, "timeout_sec": 3600},
            *({"cmd": [exe, "text", "index", "--case", name], "cwd": root,
               "timeout_sec": 3600}
              for name in names)]


def estimate_from(payload: dict[str, Any]) -> M.Estimate:
    """Кошторис наглядача (`htr supervise --dry-run --json`) → наш `Estimate`."""
    raw_best = payload.get("best")
    best: dict[str, Any] = raw_best if isinstance(raw_best, dict) else {}
    return M.parse_estimate({
        "empty": payload.get("empty"),
        "reason": payload.get("reason"),
        "candidates": payload.get("candidates"),
        "gpu": best.get("gpu"),
        "num_gpus": best.get("num_gpus"),
        "price_usd_h": best.get("dph"),
        "pages_per_hour": best.get("pages_per_hour"),
        "hours": best.get("hours"),
        "cost_usd": best.get("cost"),
        "usd_per_1000": best.get("usd_per_1000"),
        "balance_usd": payload.get("credit"),
        "lines_per_page": payload.get("lines_per_page"),
    })


#: Розфарбування rich у захопленому виводі. Без TTY його зазвичай немає, але
#: «зазвичай» тут недостатньо: один escape-байт робить JSON нерозбірним, а
#: нерозбірний кошторис читається як «наглядач мовчить».
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _json_out(text: str) -> dict[str, Any]:
    """JSON із виводу наглядача: цілий вивід або останній рядок-об'єкт.

    Обидва способи потрібні: кошторис друкується одним рядком (`json.dumps`), а
    стан — уже відформатованим на кілька рядків (`print_json`).
    """
    clean = _ANSI_RE.sub("", text).strip()
    if clean.startswith("{"):
        try:
            got = json.loads(clean)
        except ValueError:
            got = None
        if isinstance(got, dict):
            return got
    return _json_line(clean)


def _json_line(text: str) -> dict[str, Any]:
    """Останній рядок-об'єкт із виводу. Немає — порожньо."""
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                got = json.loads(stripped)
            except ValueError:
                continue
            if isinstance(got, dict):
                return got
    return {}


# ── захід ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Prepared:
    """Захід, складений і порахований, але ще не пущений.

    🔴 Окремо від старту, бо в партії рішення про гроші одне на всі черги: його
    можна винести лише тоді, коли кошторис кожної черги вже на руках.
    """

    session: str
    plan_path: Path
    env: dict[str, str]
    gr: list[str]
    est: M.Estimate
    #: Прогноз вартості; `None` — наглядач його не назвав.
    cost: float | None
    fork_low: float | None
    fork_high: float | None
    #: Стеля часу з прогнозу (або явна). Без прогнозу — `MAX_HOURS_CAP`.
    hours: float
    #: Архів ассетів, з яким складено план, — партія везе той самий на всі черги.
    assets: Path
    #: Команда складача плану (з рішенням про засів), якою план ДОСТАВЛЯЄТЬСЯ.
    plan_cmd: tuple[str, ...] = ()
    #: Чи залиті кадри й ассети. `False` — план складено для кошторису
    #: (`htr plan --no-upload`); `start` доставить його сам.
    staged: bool = True


def launch(convoy: Convoy, res: GoResult, say: Callable[..., None], *,
           budget: float | None = None, max_hours: float | None = None,
           max_rents: int = 0,
           confirm: bool = False, dry_run: bool = False, stage: bool = False,
           transport: str = "auto", max_usd_per_1000: float = 0.0,
           params: Sequence[str] = ()) -> None:
    """Підготувати захід і віддати його відчепленому наглядачеві.

    `convoy` — справи, що їдуть разом: у кожної своя тека для машини (оригінал
    або стиснута копія), свій оригінал для кропів, своя шифра, своє ім'я
    прогону й, можливо, свій засів сегментації. Наглядач приймає це списками,
    і ПОРЯДОК — єдине, що зв'язує ключ, ім'я та засів зі справою.
    """
    from nyshporka.cloud.go import GoRefused

    # 🔴 Кошторис — ДО заливки: на ньому вирішується, чи стартувати взагалі, а
    # заливка партії — гігабайти аплінка (`stage`). Сухий прогін не заливає
    # нічого, якщо людина не попросила доставити план наперед (`--stage`).
    p = prepare(convoy, res, say, max_hours=max_hours, transport=transport,
                max_usd_per_1000=max_usd_per_1000, params=params,
                stage=dry_run and stage)
    if p.cost is None and budget is None:
        raise GoRefused("кошторису немає: наглядач не назвав ні вартості, ні "
                        "ціни з годинами. Назвіть стелю витрат самі: `--budget`.")
    res.fork_low, res.fork_high = p.fork_low, p.fork_high
    high = budget if budget is not None else res.fork_high
    assert high is not None
    res.budget_usd, res.max_hours = round(high, 2), p.hours

    ceiling = M.autostart_ceiling()
    decision = M.decide_launch(high, p.est.balance_usd, ceiling, confirm)
    res.decision = decision.why
    fork = (f"${res.fork_low:.2f}–${res.fork_high:.2f}"
            if res.fork_high is not None else "вилки немає (кошторис невідомий)")
    say("money", f"вилка {fork} · бюджет заходу ${high:.2f} · стеля часу "
                 f"{p.hours:g} год · рішення: {decision.why}")
    if dry_run:
        res.verdict = "dry_run"
        res.why = (f"сухий прогін: оренди не було; план {p.plan_path}" if p.staged else
                   f"сухий прогін: оренди не було, кадри не заливались "
                   f"({convoy.total_mb / 1000:.1f} ГБ поїдуть на старті); план для "
                   f"кошторису {p.plan_path}")
        return
    if not decision.launch:
        raise GoRefused(decision.why, verdict=decision.kind)
    start(p, convoy, res, say, budget=high, max_hours=p.hours, max_rents=max_rents)


def prepare(convoy: Convoy, res: GoResult, say: Callable[..., None], *,
            max_hours: float | None = None, transport: str = "auto",
            max_usd_per_1000: float = 0.0, params: Sequence[str] = (),
            assets: Path | None = None, stage: bool = False) -> Prepared:
    """Скласти план заходу й спитати кошторис — нічого не орендуючи.

    `assets` — уже зібраний архів (партія збирає його один раз на всі черги).

    `stage=False` (типово) — план лише для кошторису: кадри й ассети НЕ
    заливаються, передполіт не йде (посилання ще нікуди не ведуть). Доставляє
    план `start` → `stage()`. 🔴 Доти кошторис стояв ПІСЛЯ заливки: партія
    ДАЖО 1-78 (три справи, 2 ГБ) 95 с везла кадри в сховище, перш ніж назвати
    ціну, — і везла б так само, якби рішенням було «не стартувати»
    (05.10.2026). `stage=True` — як доти: план одразу доставлений, придатний
    для `gpurunner htr supervise --plan … --machine …`.
    """
    from nyshporka.cloud.go import GoRefused

    try:
        gr = gpurunner_cmd()
    except SupervisorMissing as exc:
        raise GoRefused(str(exc)) from None
    plan = convoy.legs[0].plan
    session = session_name(convoy.legs[0].name, extra=len(convoy.legs) - 1)
    env = _env(session, gr[0] if len(gr) == 1 else sys.executable)

    # 1. ассети: бойові ваги + скрипти цього раннера
    models = [plan.model, *( [plan.voice] if plan.voice else [] ),
              *list(plan.extra_voices or ())]
    if assets is None:
        items = assets_inputs(models)
        stem = "_".join(p.stem for p in models)
        try:
            assets = build_assets(items, _workdir() / "assets", stem=stem)
        except SupervisorMissing as exc:
            raise GoRefused(str(exc)) from None
        say("assets", f"ассети: {assets.name}")

    # 2. план наглядача
    work = _workdir() / "runs" / session
    work.mkdir(parents=True, exist_ok=True)
    plan_path = work / "plan.json"
    voices = ",".join(p.name for p in models[1:])
    # 🔴 Засів сегментації їде ПЕРШИМ ЧЕКПОІНТОМ, а чекпоінти живуть у
    # сховищі — на самій машині їх ще немає, бо машини ще немає. Тому засів
    # можливий лише зі сховищем, і транспорт при ньому називається явно.
    seeded = any(leg.seed is not None for leg in convoy.legs)

    def make_cmd(*, seeded: bool) -> list[str]:
        """Команда складача плану — ціла, під заданий засів.

        🔴 Команда збирається ОДНІЄЮ функцією, а не латається на місці. Засів
        і щільніший флот — це одне рішення у двох місцях команди
        (`--seed-seg` і `-p cores_per_shard=…`), і рознісши їх, ми дістали б
        найдорожчу з можливих помилок: машина читає з повною сегментацією, а
        флот їй дали як для готової — тобто шарди душаться на вдвічі менших
        ядрах, і платимо ми за це погодинно. (Знайдено рев'ю 21.09.2026 на
        двох шляхах одразу: `--transport box` і відкат без сховища.)
        """
        out = [*gr, "htr", "plan"]
        # 🔴 Справи йдуть трьома паралельними списками, і порядок у них той
        # самий: наглядач зв'язує ключ, ім'я та засів зі справою ЛИШЕ за
        # позицією. Порожній елемент теж передається — пропуск зсунув би
        # решту на одну позицію, і справа дістала б чужу шифру.
        for leg in convoy.legs:
            out += ["--case", str(leg.pack), "--case-key", leg.plan.case_key,
                    "--name", leg.name]
            if seeded:
                out += ["--seed-seg", str(leg.seed) if leg.seed else ""]
        out += ["--out-root", str(convoy.out_root),
                "--model", plan.model.name, "--voices", voices,
                "--assets", str(assets),
                "--expect-script", f"{RUNNER_ARCNAME}={runner_path()}",
                "--disk", str(convoy.disk_gb()),
                "--max-hours", str(MAX_HOURS_CAP),
                "--prefer-cores", str(PREFER_CORES),
                # Чим везти дані: об'єктне сховище (якщо воно в людини є) або
                # сама машина. Вирішує наглядач — він єдиний знає, що
                # налаштовано; при засіві сховище обов'язкове.
                "--transport", "r2" if seeded else transport,
                "--out", str(plan_path)]
        if any(not leg.plan.case_key for leg in convoy.legs):
            # Шифри немає бодай у однієї справи — наглядач інакше відмовиться
            # від порожнього ключа. Прапорець заходовий, тож одна безіменна
            # тека знімає перевірку з усіх; це свідомо: сама перевірка — про
            # бібліотеку, а рішення «ця тека не архівна справа» вже ухвалила
            # людина.
            out.append("--key-not-in-library")
        # 🔴 Обчислені нами параметри йдуть ПЕРШИМИ, людські — після, бо
        # наглядач збирає їх у словник і останнє входження перемагає. Людина,
        # що набрала `-p lines_per_page=…`, мусить перекрити наш здогад.
        computed = [f"script={plan.script}"]
        # 🔴 ТИПОВА щільність, а не максимальна: це число йде у ВИБІР МАШИНИ
        # (темп, стеля часу, ціна тисячі сторінок). Максимум по черзі означав
        # би міряти ринок по найгустішій сторінці — 23.09.2026 саме так три
        # заходи поспіль дістали «ринок порожній», хоч машин було 87 зі 142.
        # Гроші так само лишаються на максимумі: вилку бюджету завищувати
        # безпечно, а стелю часу — ні.
        typical = convoy.lines_per_page_typical or convoy.lines_per_page
        if typical:
            computed.append(f"lines_per_page={typical}")
        if seeded and convoy.dense_fleet:
            # 🔴 Флот один на всю чергу, тож щільніший ставимо лише коли
            # засіяні ВСІ справи й засів справді їде: сторінка без кешу рахує
            # геометрію повністю й задушила б шарди, яким дали вдвічі менше ядер.
            from nyshporka.htr.seg import CORES_PER_SHARD_SEEDED, GB_PER_SHARD_SEEDED

            computed += [f"cores_per_shard={CORES_PER_SHARD_SEEDED}",
                         f"vram_gb_per_shard={GB_PER_SHARD_SEEDED}"]
        given = {item.split("=", 1)[0] for item in params if "=" in item}
        for item in [*(c for c in computed if c.split("=", 1)[0] not in given), *params]:
            out += ["-p", item]
        if plan.max_price_usd_h:
            out += ["--max-price", str(plan.max_price_usd_h)]
        if max_usd_per_1000:
            # 🔴 Головний поріг вибору машини. Дефолт наглядача калібрований на
            # МЕТРИКАХ; щільний аркуш (сповідка, клірова) читається вдвічі
            # довше, і на ньому той поріг або відсікає весь ринок, або спиняє
            # захід на ціні посеред роботи — тобто виглядає як «машин немає»
            # там, де насправді замалий дозвіл.
            out += ["--max-usd-per-1000", str(max_usd_per_1000)]
        return out

    def no_seed(why_said: bool = True) -> None:
        if why_said:
            say("warning", _NO_SEED_WHY)
        res.notes.append(_NO_SEED_NOTE)

    if seeded and transport == "box":
        # Людина сказала «вези на машину» — її вибір сильніший за нашу
        # економію. Але ціна мусить бути названа, інакше мовчазна відмова від
        # засіву виглядає як безплатна.
        no_seed()
        seeded = False
    upload_known = [True]

    def run_plan(base: list[str]) -> bool:
        """Скласти план командою `base` — доставленим (`stage`) або для кошторису."""
        plan_path.unlink(missing_ok=True)
        if stage or not upload_known[0]:
            return not _run(base, env=env).returncode and plan_path.is_file()
        got = _run([*base, "--no-upload"], env=env, capture=True)
        out = f"{got.stderr or ''}\n{got.stdout or ''}"
        if got.returncode and "--no-upload" in out:
            # Наглядач старший за план без заливки — їдемо як доти, але кажемо,
            # чому кошторис знову чекає на аплінк.
            upload_known[0] = False
            say("warning", "⚠ наглядач не вміє складати план без заливки (gpuhire "
                           "застарий) — кадри заливаються ДО кошторису. Оновіть: "
                           "`nysh update`")
            return not _run(base, env=env).returncode and plan_path.is_file()
        if got.returncode:
            say("warning", out.strip()[-1500:])
        return not got.returncode and plan_path.is_file()

    cmd = make_cmd(seeded=seeded)
    say("plan", "складаємо план і веземо кадри в сховище наглядача" if stage else
                f"складаємо план для кошторису — кадри ({convoy.total_mb / 1000:.1f} ГБ) "
                f"не заливаємо, поїдуть на старті")
    if not run_plan(cmd):
        if not seeded or transport != "auto":
            raise GoRefused(f"план заходу не склався — див. вивід вище; тека {work}")
        # Сховища немає, а транспорт людина не називала — не відмовляємо, а
        # їдемо без засіву й кажемо ЦІНУ: сторінка коштуватиме ще й
        # сегментацію (замір 9.1 → 18.4 с/стор). Повтор безплатний: перевірка
        # транспорту в наглядача стоїть до будь-якої заливки.
        no_seed()
        cmd = make_cmd(seeded=False)
        if not run_plan(cmd):
            raise GoRefused(f"план заходу не склався — див. вивід вище; тека {work}")
    staged = stage or not upload_known[0]
    _check_engine(plan_path)

    # 3. правки, яких наглядач знати не може
    _patch_plan(plan_path, convoy)

    # 4. передполіт: живі посилання й доступне сховище — ДО оренди. План для
    # кошторису його не проходить за побудовою: посилання ведуть у порожнечу.
    if staged:
        _preflight(gr, plan_path, env)

    # 5. кошторис — у того самого наглядача, який потім спиниться на бюджеті
    dry = _run([*gr, "htr", "supervise", "--plan", str(plan_path),
                "--dry-run", "--json"], env=env, capture=True)
    payload = _json_out(dry.stdout or "")
    if not payload:
        tail = (dry.stderr or dry.stdout or "").strip()[-300:]
        raise GoRefused(f"сухий прогін не дав кошторису (код {dry.returncode}): "
                        f"{tail}")
    est = estimate_from(payload)
    res.estimate = est.as_dict()
    say("estimate", est.human(), **est.as_dict())
    if est.empty:
        raise GoRefused(est.human(), verdict="market_empty")

    cost = est.cost
    low = high = None
    if cost is not None:
        low, high = M.budget_fork(cost, density_known=est.lines_per_page is not None)
    hours = max_hours if max_hours is not None else (
        M.max_hours_for(est.hours) if est.hours is not None else MAX_HOURS_CAP)
    return Prepared(session=session, plan_path=plan_path, env=env, gr=list(gr),
                    est=est, cost=cost, fork_low=low, fork_high=high, hours=hours,
                    assets=assets, plan_cmd=tuple(cmd), staged=staged)


def _check_engine(plan_path: Path) -> None:
    """🔴 Наглядач мусить везти на бокс середовище рушіїв з нашого маніфесту.

    Старий (gpuhire < 0.6) файла вимог в ассетах не бачить, бокс поставив би
    власний пін kraken, і раннер там не стартував би — після оплаченого
    холодного старту. Перевіряється сама можливість, а не номер версії:
    наглядач буває й чужою збіркою з PATH.
    """
    from nyshporka.cloud.go import GoRefused

    if not _plan_carries_engine(plan_path):
        raise GoRefused(
            "наглядач хмарних прогонів застарий: план не везе на машину середовище "
            "рушіїв (kraken з маніфесту), і раннер на боксі не стартував би. "
            "Оновіть: `nysh update` (пакет оренди `gpuhire` ≥ 0.6.1) і повторіть.")


def _preflight(gr: Sequence[str], plan_path: Path, env: dict[str, str]) -> None:
    from nyshporka.cloud.go import GoRefused

    if _run([*gr, "htr", "preflight", str(plan_path)], env=env).returncode:
        raise GoRefused("передполіт не пройшов (посилання або сховище) — "
                        "див. вивід вище; оренди не було")


def stage(p: Prepared, convoy: Convoy, say: Callable[..., None]) -> Prepared:
    """Доставити план, складений для кошторису: залити кадри й ассети, передполіт.

    Тією самою командою складача, що й план для кошторису (рішення про засів
    уже ухвалене), тож справи, імена й засів ті самі. Залитого раніше
    наглядач не заливає вдруге (`already_in_bucket`): повторний старт тієї
    самої справи везе лише змінене.
    """
    from nyshporka.cloud.go import GoRefused

    if p.staged:
        return p
    say("plan", f"заливаємо кадри ({convoy.total_mb / 1000:.1f} ГБ) і ассети в "
                f"сховище наглядача; залите раніше вдруге не їде")
    p.plan_path.unlink(missing_ok=True)
    if _run(list(p.plan_cmd), env=p.env).returncode or not p.plan_path.is_file():
        raise GoRefused(f"план заходу не доставився — див. вивід вище; тека "
                        f"{p.plan_path.parent}; оренди не було")
    _check_engine(p.plan_path)
    _patch_plan(p.plan_path, convoy)
    _preflight(p.gr, p.plan_path, p.env)
    return replace(p, staged=True)


def start(p: Prepared, convoy: Convoy, res: GoResult, say: Callable[..., None], *,
          budget: float, max_hours: float, max_rents: int = 0,
          batch: str = "") -> None:
    """Віддати складений захід відчепленому наглядачеві.

    `res` несе вилку й бюджет, які ляжуть у запис кожної справи; `batch` — id
    партії, якщо черга їде в ній.
    """
    from nyshporka.cloud.go import GoRefused

    # План для кошторису доставляється тут, ПІСЛЯ рішення про гроші й до запису
    # заходу: збій заливки — відмова без оренди, і записувати нема що.
    p = stage(p, convoy, say)
    session, plan_path, env, gr = p.session, p.plan_path, p.env, p.gr
    high, hours = budget, max_hours
    # 6. наглядач у фон
    res.rented = True
    # 🔴 Запис ПЕРЕД стартом, а не після. Між пуском наглядача й записом стану
    # ми можемо померти (Ctrl+C, обрив, повний диск) — і тоді захід іде, а для
    # нас його не існує: наступна команда тієї самої справи чесно візьме ДРУГУ
    # машину під ту саму роботу. Невдалий старт прибирає запис за собою.
    _remember(convoy, res, session=session, plan_path=plan_path, batch=batch)
    launched = _run([*gr, "htr", "supervise", "--plan", str(plan_path),
                     "--detach", "--session", session,
                     # 🔴 Повна точність, а не `:.2f`/`:.0f` (аудит 29.09.2026):
                     # наглядач читає float і вважає 0 «не перекривати», тож
                     # `--max-hours 0.4` їхав як «0» і захід жив 14 год плану.
                     "--budget", repr(float(high)), "--max-hours", repr(float(hours)),
                     *(["--max-rents", str(int(max_rents))] if max_rents else [])],
                    env=env)
    if launched.returncode:
        # 🔴 Запис НЕ видаляємо. «Не стартував» тут означає лише те, що
        # наглядач не показав свого стану за відведений час, — а процес при
        # цьому може бути живий і піти орендувати машину. Видалений запис
        # зробив би таку оренду невидимою для `state`, `stop` і наступного
        # `go`, тобто нікому не підзвітною; лишений — щонайгірше зайвий рядок
        # у переліку, який людина закриє `stop --force`.
        #
        # 🔴 І фаза лишається «running», а не «failed». Закрита фаза робила
        # запис невидимим для `find_live` і `ST.live()` — тобто рівно для
        # наступного `go`, який брав другу машину під ту саму справу, поки
        # перший наглядач міг уже орендувати свою (аудит 29.09.2026). Відкрита
        # фаза веде `go` питати наглядача, а його мовчання — це відмова.
        for run_id in convoy.run_ids:
            st = ST.load(run_id)
            if st is None:
                continue
            st.why = (f"наглядач {session} не доповів про старт (код "
                      f"{launched.returncode}); якщо він усе-таки живий — "
                      f"машина на ньому")
            st.note("detach_unclear", st.why)
            ST.save(st)
        raise GoRefused(
            f"наглядач не доповів про старт (код {launched.returncode}). "
            f"Найімовірніше машини не брали — але переконайтесь: "
            f"`nysh cloud rent status`. Якщо там щось тарифікується, захід "
            f"живий: `nysh cloud state {convoy.run_ids[0]}`.")
    res.verdict = "detached"
    queue = (f" черга з {len(convoy.legs)} справ: {convoy.label()}."
             if len(convoy.legs) > 1 else "")
    res.why = (f"наглядач {session} пішов у фон: орендує машину, читає, забирає "
               f"результат і гасить оренду сам.{queue}")
    for case in res.cases:
        case.verdict = "detached"
    first = convoy.run_ids[0]
    say("detached", f"▶ {session} — стан: `nysh cloud state {first}`, "
                    f"спинити: `nysh cloud stop {first}`")


def _workdir() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / "cloud" / "supervised"


def _patch_plan(plan_path: Path, convoy: Convoy) -> None:
    """Дві правки, яких складач плану зробити не може.

    🔴 `case_dir` — ОРИГІНАЛЬНА тека кадрів КОЖНОЇ справи: у мету прогону має
    лягти вона, бо кроп зі стиснутої копії вдвічі дрібніший, а дивиться на
    нього око. Підставити один оригінал усім справам не можна — на партії це
    означало б, що кропи ріжуться з чужої книги.
    `post_fetch` — облік цього простору абсолютними шляхами: відчеплений
    процес не має ні нашого PATH, ні нашої робочої теки.
    """
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    by_name = {leg.name: leg for leg in convoy.legs}
    for i, case in enumerate(cases):
        leg = by_name.get(str(case.get("name") or ""))
        if leg is None and i < len(convoy.legs):
            # Наглядач лишає порядок справ таким, яким ми його дали, тож
            # позиція — надійний запасний ключ.
            leg = convoy.legs[i]
        if leg is not None:
            from nyshporka.cloud.verify import frames_in
            from nyshporka.htr_store import lasting_case_dir

            # Тимчасова тека (стейджинг агента) помре — у мету йде тека справи.
            case["case_dir"] = lasting_case_dir(
                leg.source, leg.plan.case_key, [f.name for f in frames_in(leg.source)])
    hooks = post_fetch_hooks([leg.name for leg in convoy.legs])
    if hooks:
        data["post_fetch"] = hooks
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                         encoding="utf-8")


def _remember(convoy: Convoy, res: GoResult, *, session: str,
              plan_path: Path, batch: str = "") -> None:
    """Записати захід так, щоб `nysh cloud state|stop` знали, кого питати.

    🔴 Запис на КОЖНУ справу, а не один на захід. Ідентифікатор справи
    детермінований, і саме за ним повторна команда тієї самої справи знаходить
    свою роботу; сховавши партію під спільним іменем, ми зробили б так, що
    `nysh cloud go <справа з партії>` не бачить живого заходу й бере ДРУГУ
    машину під те, що вже читається.

    🔴 `box` лишається порожнім навмисно: машину бере й гасить наглядач, і
    вигаданий запис про неї означав би, що Нишпорка спробує погасити чужу
    оренду, про яку знає лише з чуток.
    """
    ids = list(convoy.run_ids)
    for leg in convoy.legs:
        plan = leg.plan
        st = ST.RunState(
            run_id=plan.run_id, case_dir=str(plan.case_dir), case_key=plan.case_key,
            out_dir=str(plan.out_dir), backend=plan.backend,
            supervisor=session, supervisor_plan=str(plan_path),
            frames_total=plan.frames, phase="running", bills=False,
            source_dir=str(plan.source_dir or ""),
            siblings=[i for i in ids if i != plan.run_id],
            fork_low=res.fork_low, fork_high=res.fork_high,
            budget_usd=res.budget_usd, max_hours=res.max_hours, batch=batch)
        st.note("detach", f"наглядач {session}"
                          + (f", разом із {len(ids) - 1} іншими справами"
                             if len(ids) > 1 else ""))
        ST.save(st)


# ── стан і зупинка відчепленого заходу ──────────────────────────────────────
def find_live(run_ids: Iterable[str]) -> tuple[ST.RunState, dict[str, Any]] | None:
    """Відчеплений захід цієї ж роботи, який ЩЕ ЙДЕ, — разом зі станом наглядача.

    🔴 Питається наглядач, а не наш запис. Наш запис — знімок хвилини, коли ми
    відчепились, і він однаково каже «running» і про живу роботу, і про ту, що
    скінчилась три години тому. Друга машина під ту саму справу коштує рівно
    стільки ж, скільки перша.
    """
    for run_id in sorted(run_ids):
        try:
            st = ST.load(run_id)
        except Exception:
            continue
        if st is None or not st.supervisor or st.phase in ("done", "failed"):
            continue
        data = state_of(st)
        if not data:
            # 🔴 Мовчання — не «заходу немає». Наглядач міг саме перезаписувати
            # свій стан, його програма могла не знайтись, вивід міг зіпсуватись
            # — а машина при цьому працює. Розв'язувати цю неоднозначність на
            # користь оренди означає платити за ту саму справу двічі, тож
            # вважаємо захід живим і віддаємо рішення людині.
            return st, {}
        if not finished(data):
            return st, data
        if data:
            # Наглядач завершився, а наш запис лишився відкритим — закриваємо
            # його зараз, інакше він мулятиме очі в кожному `nysh cloud state`.
            absorb(st, data)
    return None


#: Фази наглядача, після яких він уже нічого не робить.
DONE_PHASES = ("done", "failed", "finished", "stopped")


def finished(data: dict[str, Any]) -> bool:
    """Чи наглядач уже все — за його власним словом."""
    phase = str(data.get("phase") or "")
    return bool(data.get("verdict")) or (phase in DONE_PHASES and phase != "")


def _my_case(st: ST.RunState, data: dict[str, Any]) -> dict[str, Any] | None:
    """Рядок ЦІЄЇ справи у стані наглядача.

    🔴 Шукається за іменем прогону чи текою виходу, а не береться найбільший.
    Доти тут стояв `max(pages_done)` по всіх справах — на одній справі це те
    саме число, а на черзі запис справи A показував би сторінки справи C: люди
    й агенти читали б чужий поступ як свій і вирішували б за ним, коли забирати
    результат.
    """
    rows = [c for c in (data.get("cases") or []) if isinstance(c, dict)]
    if not rows:
        return None
    name = Path(st.out_dir).name if st.out_dir else ""
    for row in rows:
        if name and str(row.get("case") or row.get("name") or "") == name:
            return row
        out = str(row.get("out_dir") or "")
        if out and st.out_dir and Path(out) == Path(st.out_dir):
            return row
    # Захід на одну справу: ім'я могло змінитись (перейменована тека), але
    # плутати нема з чим.
    return rows[0] if len(rows) == 1 else None


def absorb(st: ST.RunState, data: dict[str, Any]) -> ST.RunState:
    """Перенести підсумок наглядача в наш запис заходу.

    🔴 Без цього завершений захід назавжди лишається в переліку як «читає з
    нуля сторінок»: наш запис — знімок хвилини відчеплення, і сам себе він не
    оновить ніколи, бо роботу вів не наш процес.
    """
    verdict = str(data.get("verdict") or "")
    mine = _my_case(st, data)
    if mine is not None:
        st.pages_done = max(st.pages_done, int(mine.get("pages_done") or 0))
    raw_budget = data.get("budget")
    budget: dict[str, Any] = raw_budget if isinstance(raw_budget, dict) else {}
    spent = M.as_number(budget.get("spent_usd"))
    if spent is not None:
        # Лічильник оренди веде наглядач, і його число — єдине справжнє: своєї
        # машини ми тут не бачили жодної секунди.
        st.rent_started = st.rent_started or st.started
        st.rent_ended = st.rent_ended or time.time()
        st.box = {**st.box, "price_usd_h": 0.0, "spent_usd": spent}
    st.why = str(data.get("why") or verdict or "наглядач завершився")
    # 🔴 «Погашено» — лише коли наглядач сам так каже. Вердикт `orphaned` і
    # прохання до людини означають протилежне: машина могла лишитись живою, і
    # саме тоді запис мусить світитись у переліку, а не виглядати закритим.
    st.released = not (verdict == "orphaned"
                       or bool(data.get("human_action_required")))
    st.verdict = verdict if verdict in ST.VERDICTS else (
        "ok" if verdict == "ok" else "failed")
    st.phase = "done" if st.verdict in ("ok", "cancelled") else "failed"
    return ST.save(st)


def state_of(st: ST.RunState) -> dict[str, Any]:
    """Стан заходу в наглядача. Порожньо — спитали, а відповіді немає.

    🔴 «Наглядач мовчить» і «нема чим його спитати» — різні речі, і зводити їх
    до одного порожнього словника не можна. Тут це коштувало пів години:
    `nysh` із середовища, де пакета оренди немає (наприклад `.venv` чужого
    проєкту, який кличе Нишпорку обгорткою), не міг навіть спитати — а команда
    казала «наглядач не відповідає: він міг завершитись або впасти», поки
    наглядач читав справу. Тому причина «спитати нічим» іде нагору винятком, і
    вирішує викликач: він знає, чи є в нього що сказати людині натомість.
    """
    if not st.supervisor:
        return {}
    gr = gpurunner_cmd()
    done = _run([*gr, "htr", "state", "--session", st.supervisor, "--json"],
                env=_env(st.supervisor, gr[0] if len(gr) == 1 else sys.executable),
                capture=True)
    return _json_out(done.stdout or "")


@dataclass(frozen=True)
class StopResult:
    """Чим скінчилась спроба спинити відчеплений захід."""

    ok: bool
    #: Що сказав наглядач — ЦІЛКОМ, не останній рядок.
    said: str
    #: Чи вбито самого наглядача (тоді машину нікому гасити).
    killed: bool = False
    #: Машина, про яку знав наглядач, — щоб людині було що шукати в кабінеті.
    machine: str = ""


def stop(st: ST.RunState, *, force: bool = False) -> StopResult:
    """Спинити відчеплений захід.

    🔴 За замовчуванням — ГРАЦІЙНО: ми просимо наглядача ЗГОРНУТИ захід, і він
    робить це тим самим шляхом, яким завершує роботу на стелі грошей: спиняє
    читання, забирає прочитане, звіряє повноту, гасить оренду. Убити його —
    означає лишити машину живою без нікого, хто її погасить, бо гасити її нам
    нічим: у нашому записі її немає й бути не може.

    ⚠ Просити «спинити раннер» (`quiesce`) для цього не годиться: раннер
    справді спиняється, але наглядач про це не знає й далі чекає прогресу —
    виміряно на живому заході 20.09.2026, машина тарифікувалась далі.

    `force` лишає саме цей — дорогий — шлях, і викликач мусить сказати про
    наслідки людині. Порядок «забрати → звірити → погасити» тут не обходиться,
    а делегується тому, хто його й виконує.
    """
    if not st.supervisor:
        return StopResult(False, "це не відчеплений захід")
    try:
        gr = gpurunner_cmd()
    except SupervisorMissing as exc:
        return StopResult(False, str(exc))
    box = state_of(st).get("box")
    machine = str((box or {}).get("instance_id") or "") if isinstance(box, dict) else ""
    verb = "stop" if force else "wrap-up"
    done = _run([*gr, "htr", verb, "--session", st.supervisor],
                env=_env(st.supervisor, gr[0] if len(gr) == 1 else sys.executable),
                capture=True)
    # 🔴 Увесь вивід, а не останній рядок: попередження «бокс міг лишитись
    # живим» у наглядача багаторядкове, і останнім рядком у ньому йде порада
    # про забір чекпоінтів — тобто зрізання хвоста викидало саме те єдине
    # речення, заради якого людина цю команду й читає.
    said = (done.stdout or "").strip() or (done.stderr or "").strip()
    return StopResult(not done.returncode, said[-1500:], killed=force,
                      machine=machine)
