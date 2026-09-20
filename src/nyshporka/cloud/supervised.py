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
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.cloud import money as M
from nyshporka.cloud import state as ST

if TYPE_CHECKING:  # pragma: no cover — лише для перевірки типів
    from collections.abc import Callable, Iterable, Sequence

    from nyshporka.cloud.go import GoResult
    from nyshporka.cloud.plan import CloudPlan

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


class SupervisorMissing(RuntimeError):
    """Наглядача немає на цій машині. Текст — для людини, дослівно."""


# ── наглядач ────────────────────────────────────────────────────────────────
def gpurunner_cmd() -> list[str]:
    """Чим кликати наглядача: модуль у цьому ж середовищі або програма в PATH.

    🔴 Спершу модуль (`python -m gpurunner`), а не програма: `nyshporka[rent]`
    ставить наглядача поруч із нами, і саме його версія звірена з цим кодом.
    Програма з PATH може виявитись чужою збіркою з іншого середовища — а
    відчеплений процес успадковує її на весь захід.
    """
    from importlib.util import find_spec

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
        "машині веде його. Поставте: `pip install \"nyshporka[rent]\"` "
        "(або `nysh update`), далі `nysh cloud rent login`. Читати на СВОЇЙ "
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
    return items


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


def session_name(run_name: str) -> str:
    """Ім'я сесії наглядача: справа плюс час ДО СЕКУНД.

    🔴 Час тут не робить імені унікальним, і хвіст із чотирьох випадкових
    знаків — не прикраса. Повторний захід тієї самої справи (звична дія після
    збою) інакше дістав би ім'я вже зайнятої сесії: стан, журнал і вирок двох
    різних оренд змішалися б в один запис.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "-"
                   for c in run_name.lower()).strip("-")
    tail = secrets.token_hex(2)
    return f"htr-{safe or 'case'}-{datetime.now():%m%d-%H%M}-{tail}"


def nysh_exe() -> str:
    """Програма `nysh` цього середовища — для гачків обліку.

    Абсолютним шляхом: відчеплений наглядач не має нашого PATH, і «nysh» у
    його оточенні може не існувати або бути чужим.
    """
    exe = Path(sys.executable).parent / ("nysh.exe" if os.name == "nt" else "nysh")
    if exe.is_file():
        return str(exe)
    return shutil.which("nysh") or ""


def post_fetch_hooks(run_name: str) -> list[dict[str, Any]]:
    """Облік після ПОВНОГО забору — те саме, що робить тонкий шлях сам.

    Наглядач виконає їх лише при вердикті `ok`. Без цього реєстр казав би
    «декоду немає» про справу, яку щойно прочитано.
    """
    exe = nysh_exe()
    if not exe:
        return []
    return [{"cmd": [exe, "cases", "build"], "timeout_sec": 3600},
            {"cmd": [exe, "text", "index", "--case", run_name],
             "timeout_sec": 3600}]


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
def launch(plan: CloudPlan, res: GoResult, say: Callable[..., None], *,
           pack_dir: Path, source_dir: Path, total_mb: float,
           budget: float | None = None, max_hours: float | None = None,
           confirm: bool = False, dry_run: bool = False,
           params: Sequence[str] = ()) -> None:
    """Підготувати захід і віддати його відчепленому наглядачеві.

    `plan` — наш план (справа, письмо, бойові ваги, шифра, тека виходу);
    `pack_dir` — тека, яка поїде на машину (оригінал або стиснута копія);
    `source_dir` — завжди ОРИГІНАЛ: із нього ріжуться кропи, і саме він має
    опинитись у меті прогону.
    """
    from nyshporka.cloud.go import GoRefused

    try:
        gr = gpurunner_cmd()
    except SupervisorMissing as exc:
        raise GoRefused(str(exc)) from None
    session = session_name(plan.out_dir.name)
    env = _env(session, gr[0] if len(gr) == 1 else sys.executable)

    # 1. ассети: бойові ваги + скрипти цього раннера
    models = [plan.model, *( [plan.voice] if plan.voice else [] ),
              *list(plan.extra_voices or ())]
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
    cmd = [*gr, "htr", "plan",
           "--case", str(pack_dir),
           "--case-key", plan.case_key,
           "--name", plan.out_dir.name,
           "--out-root", str(plan.out_dir.parent),
           "--model", plan.model.name, "--voices", voices,
           "--assets", str(assets),
           "--expect-script", f"{RUNNER_ARCNAME}={runner_path()}",
           "--disk", str(disk_for(total_mb)),
           "--max-hours", str(MAX_HOURS_CAP),
           "--prefer-cores", str(PREFER_CORES),
           "--out", str(plan_path)]
    if not plan.case_key:
        # Шифри немає — наглядач інакше відмовиться від порожнього ключа.
        cmd.append("--key-not-in-library")
    for item in params:
        cmd += ["-p", item]
    if plan.max_price_usd_h:
        cmd += ["--max-price", str(plan.max_price_usd_h)]
    if plan.lines_per_page:
        cmd += ["-p", f"lines_per_page={plan.lines_per_page}"]
    say("plan", "складаємо план і веземо кадри в сховище наглядача")
    if _run(cmd, env=env).returncode or not plan_path.is_file():
        raise GoRefused(f"план заходу не склався — див. вивід вище; тека {work}")

    # 3. правки, яких наглядач знати не може
    _patch_plan(plan_path, source_dir=source_dir, run_name=plan.out_dir.name)

    # 4. передполіт: живі посилання й доступне сховище — ДО оренди
    if _run([*gr, "htr", "preflight", str(plan_path)], env=env).returncode:
        raise GoRefused("передполіт не пройшов (посилання або сховище) — "
                        "див. вивід вище; оренди не було")

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
    if cost is None and budget is None:
        raise GoRefused("кошторису немає: наглядач не назвав ні вартості, ні "
                        "ціни з годинами. Назвіть стелю витрат самі: `--budget`.")
    if cost is not None:
        res.fork_low, res.fork_high = M.budget_fork(
            cost, density_known=est.lines_per_page is not None)
    high = budget if budget is not None else res.fork_high
    assert high is not None
    hours = max_hours if max_hours is not None else (
        M.max_hours_for(est.hours) if est.hours is not None else MAX_HOURS_CAP)
    res.budget_usd, res.max_hours = round(high, 2), hours

    ceiling = M.autostart_ceiling()
    decision = M.decide_launch(high, est.balance_usd, ceiling, confirm)
    res.decision = decision.why
    fork = (f"${res.fork_low:.2f}–${res.fork_high:.2f}"
            if res.fork_high is not None else "вилки немає (кошторис невідомий)")
    say("money", f"вилка {fork} · бюджет заходу ${high:.2f} · стеля часу "
                 f"{hours:g} год · рішення: {decision.why}")
    if dry_run:
        res.verdict = "dry_run"
        res.why = f"сухий прогін: оренди не було; план {plan_path}"
        return
    if not decision.launch:
        raise GoRefused(decision.why, verdict=decision.kind)

    # 6. наглядач у фон
    res.rented = True
    launched = _run([*gr, "htr", "supervise", "--plan", str(plan_path),
                     "--detach", "--session", session,
                     "--budget", f"{high:.2f}", "--max-hours", f"{hours:.0f}"],
                    env=env)
    if launched.returncode:
        raise GoRefused(f"наглядач не стартував (код {launched.returncode}) — "
                        f"машини не брали")
    _remember(plan, res, session=session, plan_path=plan_path)
    res.verdict = "detached"
    res.why = (f"наглядач {session} пішов у фон: орендує машину, читає, забирає "
               f"результат і гасить оренду сам")
    say("detached", f"▶ {session} — стан: `nysh cloud state {plan.run_id}`, "
                    f"спинити: `nysh cloud stop {plan.run_id}`")


def _workdir() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / "cloud" / "supervised"


def _patch_plan(plan_path: Path, *, source_dir: Path, run_name: str) -> None:
    """Дві правки, яких складач плану зробити не може.

    🔴 `case_dir` — ОРИГІНАЛЬНА тека кадрів: у мету прогону має лягти вона, бо
    кроп зі стиснутої копії вдвічі дрібніший, а дивиться на нього око.
    `post_fetch` — облік цього простору абсолютними шляхами: відчеплений
    процес не має ні нашого PATH, ні нашої робочої теки.
    """
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    for case in data.get("cases") or []:
        case["case_dir"] = str(source_dir)
    hooks = post_fetch_hooks(run_name)
    if hooks:
        data["post_fetch"] = hooks
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                         encoding="utf-8")


def _remember(plan: CloudPlan, res: GoResult, *, session: str,
              plan_path: Path) -> None:
    """Записати захід так, щоб `nysh cloud state|stop` знали, кого питати.

    🔴 `box` лишається порожнім навмисно: машину бере й гасить наглядач, і
    вигаданий запис про неї означав би, що Нишпорка спробує погасити чужу
    оренду, про яку знає лише з чуток.
    """
    st = ST.RunState(
        run_id=plan.run_id, case_dir=str(plan.case_dir), case_key=plan.case_key,
        out_dir=str(plan.out_dir), backend=plan.backend,
        supervisor=session, supervisor_plan=str(plan_path),
        frames_total=plan.frames, phase="running", bills=False,
        source_dir=str(plan.source_dir or ""),
        fork_low=res.fork_low, fork_high=res.fork_high,
        budget_usd=res.budget_usd, max_hours=res.max_hours)
    st.note("detach", f"наглядач {session}")
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
        if data and not finished(data):
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


def absorb(st: ST.RunState, data: dict[str, Any]) -> ST.RunState:
    """Перенести підсумок наглядача в наш запис заходу.

    🔴 Без цього завершений захід назавжди лишається в переліку як «читає з
    нуля сторінок»: наш запис — знімок хвилини відчеплення, і сам себе він не
    оновить ніколи, бо роботу вів не наш процес.
    """
    verdict = str(data.get("verdict") or "")
    for case in data.get("cases") or []:
        if isinstance(case, dict) and case.get("pages_done"):
            st.pages_done = max(st.pages_done, int(case["pages_done"] or 0))
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
    st.released = True          # машину гасить наглядач, і він доповів, що все
    st.verdict = verdict if verdict in ST.VERDICTS else (
        "ok" if verdict == "ok" else "failed")
    st.phase = "done" if st.verdict in ("ok", "cancelled") else "failed"
    return ST.save(st)


def state_of(st: ST.RunState) -> dict[str, Any]:
    """Стан заходу в наглядача. Порожньо — спитати не вдалось."""
    if not st.supervisor:
        return {}
    try:
        gr = gpurunner_cmd()
    except SupervisorMissing:
        return {}
    done = _run([*gr, "htr", "state", "--session", st.supervisor, "--json"],
                env=_env(st.supervisor, gr[0] if len(gr) == 1 else sys.executable),
                capture=True)
    return _json_out(done.stdout or "")


def stop(st: ST.RunState) -> tuple[bool, str]:
    """Спинити відчеплений захід руками наглядача: (вдалось, що сказав)."""
    if not st.supervisor:
        return False, "це не відчеплений захід"
    try:
        gr = gpurunner_cmd()
    except SupervisorMissing as exc:
        return False, str(exc)
    done = _run([*gr, "htr", "stop", "--session", st.supervisor],
                env=_env(st.supervisor, gr[0] if len(gr) == 1 else sys.executable),
                capture=True)
    tail = (done.stdout or done.stderr or "").strip().splitlines()[-1:]
    return not done.returncode, " ".join(tail)
