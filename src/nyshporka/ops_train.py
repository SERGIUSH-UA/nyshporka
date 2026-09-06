"""🧪 Операції лабораторії — розмітка й навчання Писаря.

🔴 Усі — `section="lab"`, `agent=False`. Не «поки що»: перелік MCP-tool'ів має
стелю, за якою модель перестає читати описи, і лабораторні дії туди не йдуть
ніколи (`core/ops.py`). Агентові вистачає командного рядка: `nysh train …` і
`nysh op train.<ім'я> --describe`.

Модуль — аггрегатор: кожна половина конвеєра реєструє свої операції в
окремому файлі, щоб їх можна було писати паралельно, не б'ючись за один.
"""
from __future__ import annotations

import shutil
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

SECTION = "lab"


def _registry() -> Any:
    from nyshporka.train import sets as S

    return S.registry()


# ── реєстр наборів ───────────────────────────────────────────────────────────
class SetsArgs(BaseModel):
    name: str = Field(default="", description="один набір; порожньо — усі")
    all: bool = Field(default=False, description="показати й приховані набори")


@op("train.sets", summary="Набори для розмітки й трену: сторінки, кропи, мітки, злиття",
    args=SetsArgs, agent=False, section=SECTION)
def train_sets(a: SetsArgs) -> Envelope:
    """Що є на машині і в якому стані — зі знаменниками, а не самозвітом.

    🔴 Це приймач видимості для всього конвеєра. Число кропів береться З
    ДИСКА, число міток — із `lines.jsonl`, покриття злиття — з `_meta.json`
    теки `merge`. Набір, який тут не показує злиття, у корпус не потрапить,
    хоч би скільки рядків для нього звели.
    """
    from nyshporka.train import sets as S

    reg = _registry()
    if a.name:
        try:
            rows = [reg.stats(a.name)]
        except S.SetError as exc:
            return fail(str(exc))
    else:
        rows = []
        broken: list[str] = []
        for n in reg.names(hidden=a.all):
            try:
                rows.append(reg.stats(n))
            except S.SetError as exc:
                broken.append(f"{n}: {exc}")
    env = ok({"sets": rows, "root": str(reg.root), "n": len(rows)})
    if not a.name:
        for b in broken:
            env.warn("set_broken", b)
    lost = [r["name"] for r in rows if r["n_marked"] and not r["crops_present"]]
    if lost:
        # 🔴 Мітки без картинок — саме те, що сталося з 49 наборами в
        # дослідницькому конвеєрі. Мовчати про це означає дати збірнику корпусу
        # тихо пропустити набір, а людині — думати, що він у трені.
        env.warn("crops_missing",
                 f"мітки є, а кропів на диску немає: {', '.join(lost)} — "
                 f"перерізати з прогону (`nysh train cut`), інакше в корпус не ввійдуть")
    if not rows:
        env.suggest("train.cut", "наборів ще немає — нарізати перший із прогону")
    return env


# ── доктор лабораторії ───────────────────────────────────────────────────────
@op("train.doctor", summary="Що на цій машині є для розмітки й трену",
    args=NoArgs, agent=False, section=SECTION)
def train_doctor(_: NoArgs) -> Envelope:
    """Середовище рушіїв, карта, шляхи обчислень, набори — одним поглядом.

    Загальну готовність каже `nysh doctor`; тут — те, що потрібно саме
    трену: чи є `strhub` в середовищі рушіїв, скільки пам'яті на карті, чи є
    `gpurunner` на шляху, чи описані SSH-хости, і чи не розійшлися мітки з
    кропами.
    """
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.htr import gpu as G
    from nyshporka.setup import doctor as doc
    from nyshporka.train import sets as S

    d: dict[str, Any] = {}
    env = ok(d)

    # середовище рушіїв
    try:
        venv = doc.engine_venv()
        d["engine_venv"] = str(venv)
        d["engine_present"] = venv.is_dir()
    except WorkspaceError as exc:
        return fail(str(exc))
    if not d["engine_present"]:
        env.warn("engine_missing",
                 "середовища рушіїв немає — трен локально неможливий: nysh htr install")

    # карта
    try:
        card = G.detect_card()
    except Exception:
        card = None
    d["gpu"] = None if card is None else {
        "name": card.name, "capability": card.capability, "driver": card.driver}
    if card is None:
        env.warn("no_gpu", "відеокарти NVIDIA не видно — локальний трен піде на "
                           "процесорі й буде непрактично довгим; лишаються свій "
                           "сервер (--host) або gpurunner (--backend)")

    # шляхи обчислень
    d["gpurunner"] = shutil.which("gpurunner")
    hosts: list[str] = []
    try:
        from nyshporka.cloud import ssh as C

        hosts = [h.name for h in C.load_hosts()]
    except Exception:
        hosts = []
    d["ssh_hosts"] = hosts

    # набори
    reg = _registry()
    rows = []
    for n in reg.names(hidden=True):
        try:
            rows.append(reg.stats(n))
        except S.SetError as exc:
            env.warn("set_broken", f"{n}: {exc}")
    d["sets"] = {"n": len(rows),
                 "marked": sum(r["n_marked"] for r in rows),
                 "ok": sum(r["by_status"].get("ok", 0) for r in rows),
                 "crops": sum(r["n_crops"] for r in rows),
                 "holdout": [r["name"] for r in rows if r["role"] == "holdout"],
                 "without_crops": [r["name"] for r in rows
                                   if r["n_marked"] and not r["crops_present"]]}
    d["root"] = str(reg.root)
    if not rows:
        env.suggest("train.cut", "наборів немає — почати з нарізки прогону")
    elif not d["sets"]["holdout"]:
        env.warn("no_holdout",
                 "жоден набір не має ролі holdout — епоху не буде чим обирати, "
                 "а покращення val на тих самих справах не доказ")
    return env


# ── кропи з прогону ──────────────────────────────────────────────────────────
class CutArgs(BaseModel):
    run: str = Field(description="прогін, з якого різати (тека в reports/htr)")
    name: str = Field(description="ім’я набору — стане текою")
    pages: str = Field(default="", description="кома-список сторінок; порожньо — авто")
    pick: int = Field(default=0, description="скільки сторінок відібрати автоматично")
    title: str = Field(default="", description="людська назва набору")
    domain: str = Field(default="", description="жанр для арбітрів: «сповідний розпис», «метрика»")
    case: str = Field(default="", description="шифра справи, якщо прогін її не знає")
    no_engine: bool = Field(default=False,
                            description="різати полігоном пакетом, не кешем сегментації")


@op("train.cut", summary="Нарізати кропи рядків із прогону в набір для розмітки",
    args=CutArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_cut(a: CutArgs) -> Envelope:
    """Набір із прогону: кропи = рядки прогону, текст прогону = перший голос.

    🔴 Без окремої сегментації навмисно: геометрію рядків прогін уже записав,
    і кроп, вирізаний з неї, — це рівно той рядок, який дав текст. Нова
    сегментація дала б інші індекси, і голос прогону перестав би відповідати
    кропам.
    """
    from nyshporka.train import cut as C

    pages = [p.strip() for p in a.pages.split(",") if p.strip()]
    try:
        rep = C.make_set(a.run, a.name, pages=pages or None, pick=a.pick, title=a.title,
                         domain=a.domain, case=a.case, prefer_engine=not a.no_engine)
    except C.CutError as exc:
        return fail(str(exc))
    from nyshporka.train import sets as S

    st = S.registry().stats(a.name)
    env = ok({"set": a.name, "lines": rep.n_lines,
              "pages": [{"page": p.page, "n": p.n, "source": p.source,
                         "error": p.error} for p in rep.pages],
              "stats": st})
    for w in rep.warnings:
        env.warn("cut", w)
    if rep.n_lines:
        env.suggest("train.voices", "додати другий голос: без нього черга й злиття сліпі")
    return env


# ── голоси ───────────────────────────────────────────────────────────────────
class VoicesArgs(BaseModel):
    name: str = Field(description="набір")
    from_run: str = Field(default="", description="сусідній прогін тієї самої справи")
    models: str = Field(default="", description="кома-список ваг Писаря (.pt) для інферу")
    device: str = Field(default="cuda:0", description="пристрій для інферу")


@op("train.voices", summary="Додати голос рушія до набору: з сусіднього прогону або інфером",
    args=VoicesArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_voices(a: VoicesArgs) -> Envelope:
    """Другий голос — умова і для черги розмітки, і для злиття арбітрами.

    🔴 Голос із прогону береться лише після звірки: число рядків на кожній
    сторінці мусить збігтися з числом рамок набору. Інакше рядок N чужого
    прогону ліг би під кроп M — і цю помилку не видно, бо текст правдоподібний.
    """
    from nyshporka.train import sets as S
    from nyshporka.train import voices as V

    if not a.from_run and not a.models:
        return fail("вкажіть --from-run або --models")
    got: list[dict[str, Any]] = []
    try:
        if a.from_run:
            r = V.add_from_run(a.name, a.from_run)
            got.append({"voice": r.voice, "pages": r.pages, "lines": r.lines,
                        "how": "run"})
        for m in [x.strip() for x in a.models.split(",") if x.strip()]:
            r = V.run_model(a.name, m, device=a.device)
            got.append({"voice": r.voice, "pages": r.pages, "lines": r.lines,
                        "how": "infer"})
    except (S.SetError, V.VoiceError) as exc:
        return fail(str(exc))
    st = S.registry().stats(a.name)
    env = ok({"set": a.name, "added": got, "voices": st["voices"]})
    if len(st["voices"]) >= 2:
        env.suggest("train.export", "голосів досить — можна експортувати завдання арбітрам")
    return env
