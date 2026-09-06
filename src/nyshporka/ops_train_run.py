"""🧪 Операції трену: корпус → запуск → пульс → забір → оцінка → просування.

Друга половина лабораторії (перша — розмітка в `ops_train`). Ті самі правила:
`section="lab"`, `agent=False`, вхід — лише командний рядок (`nysh train …`).

🔴 План друкується завжди, старт — окремо. Година карти і гроші не
витрачаються на те, чого людина не бачила: `train.start` без `yes` віддає
план і зупиняється, а `dry_run` — лише план.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

SECTION = "lab"


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _kv(s: str) -> dict[str, Any]:
    """`epochs=3,lr=1e-4` → словник із числами, де вони числа."""
    out: dict[str, Any] = {}
    for part in _csv(s):
        if "=" not in part:
            raise ValueError(f"очікую ключ=значення, а не {part!r}")
        k, v = part.split("=", 1)
        v = v.strip()
        if v.lower() in ("true", "false"):
            out[k.strip()] = v.lower() == "true"
        else:
            try:
                out[k.strip()] = int(v) if v.lstrip("-").isdigit() else float(v)
            except ValueError:
                out[k.strip()] = v
    return out


# ── корпус ───────────────────────────────────────────────────────────────────
class PlanArgs(BaseModel):
    recipe: str = Field(default="own", description="рецепт із recipes.yaml")
    only: str = Field(default="", description="лише ці джерела, через кому")
    include_unsure: bool = Field(default=False, description="брати й мітки unsure")
    seed: int = Field(default=42)


@op("train.plan", summary="Що піде в корпус за рецептом: джерела, кратності, частки, алфавіт",
    args=PlanArgs, agent=False, section=SECTION)
def train_plan(a: PlanArgs) -> Envelope:
    """Сухий прогін збірки — рівно те, що побачить `train.build`.

    🔴 Звіряти `rep`, не відсоток: частка перераховується в ціле число копій, і
    система сходинкова. Попередження про сходинку — саме про це.
    """
    from nyshporka.train import corpus as C
    from nyshporka.train import recipes as R

    try:
        rec = R.get_recipe(a.recipe)
        cp = C.plan(rec, only=_csv(a.only) or None, include_unsure=a.include_unsure,
                    seed=a.seed)
    except (R.RecipeError, C.CorpusError) as exc:
        return fail(str(exc))
    hist = C.charset_of(cp)
    letters = sum(v for k, v in hist.items() if k.isalpha()) or 1
    env = ok({**cp.as_dict(), "train": rec.train.as_params(),
              "hist": {c: {"n": hist.get(c, 0), "pct": round(hist.get(c, 0) / letters * 100, 4)}
                       for c in C.HIST}})
    for w in cp.warnings:
        env.warn("plan", w)
    env.suggest("train.build", "зібрати корпус за цим планом")
    return env


class BuildArgs(BaseModel):
    name: str = Field(description="ім'я корпусу — стане текою й tgz")
    recipe: str = Field(default="own")
    only: str = Field(default="")
    include_unsure: bool = Field(default=False)
    prune: bool = Field(default=False, description="прибрати кропи поза маніфестом")
    force: bool = Field(default=False, description="перезібрати наявний")
    seed: int = Field(default=42)
    workers: int = Field(default=8)


@op("train.build", summary="Зібрати корпус: кропи, маніфести, corpus.json, tgz",
    args=BuildArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_build(a: BuildArgs) -> Envelope:
    """Один артефакт на всі шляхи обчислень — `<корпус>.tgz`."""
    from nyshporka.train import corpus as C
    from nyshporka.train import recipes as R

    try:
        rec = R.get_recipe(a.recipe)
        cp = C.plan(rec, only=_csv(a.only) or None, include_unsure=a.include_unsure,
                    seed=a.seed)
        rep = C.build(a.name, cp, seed=a.seed, prune=a.prune, workers=a.workers,
                      force=a.force)
    except (R.RecipeError, C.CorpusError) as exc:
        return fail(str(exc))
    env = ok({"name": rep.name, "out": str(rep.out), "tgz": str(rep.tgz), "sha256": rep.sha256,
              "rows_train": rep.rows_train, "rows_val": rep.rows_val,
              "val_by_source": rep.val_by_source, "copied": rep.copied, "failed": rep.failed,
              "pruned": rep.pruned, "plan": cp.as_dict()})
    for w in rep.warnings:
        env.warn("build", w)
    env.suggest("train.start", f"запустити трен: nysh train start --corpus {rep.name}")
    return env


# ── запуск ───────────────────────────────────────────────────────────────────
class StartArgs(BaseModel):
    corpus: str = Field(description="ім'я зібраного корпусу")
    recipe: str = Field(default="", description="рецепт; порожньо — той, що в корпусі")
    compute: str = Field(default="auto", description="auto | local | ssh | gpurunner")
    host: str = Field(default="", description="ssh: ім'я хоста з nysh cloud hosts")
    backend: str = Field(default="", description="gpurunner: modal | vast | kaggle …")
    gpu: str = Field(default="", description="бажана карта (gpurunner)")
    params: str = Field(default="", description="перекриття: epochs=3,lr=1e-4")
    smoke: bool = Field(default=False, description="димовий прогін: одна коротка епоха")
    base: str = Field(default="", description="базові ваги: id репозиторію HF або шлях до .pt; порожньо — з рецепта")
    dry_run: bool = Field(default=False, description="лише план")
    yes: bool = Field(default=False, description="запустити без підтвердження плану")


@op("train.start", summary="Запустити трен за корпусом: план завжди, старт — з підтвердженням",
    args=StartArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_start(a: StartArgs) -> Envelope:
    """План (години, ціна, карта, команда) і — за `yes` — запуск.

    🔴 `run_id` детермінований: той самий корпус і параметри підхоплюють свій
    прогін, а не заводять другий рахунок.
    """
    from nyshporka.train import compute as CP
    from nyshporka.train import corpus as C
    from nyshporka.train import layout as L
    from nyshporka.train import recipes as R
    from nyshporka.train import state as ST

    try:
        man = C.load_manifest(a.corpus)
        recipe_name = a.recipe or str((man.get("recipe") or {}).get("name") or "own")
        overrides = _kv(a.params)
        if a.base:
            overrides["pretrained"] = a.base
        rec = R.get_recipe(recipe_name, smoke=a.smoke, overrides=overrides)
        params = rec.train.as_params()
        run_id = L.run_id_for(a.corpus, recipe_name + ("-smoke" if a.smoke else ""), params)
        tgz = L.corpora_root() / f"{a.corpus}.tgz"
        job = CP.TrainJob(run_id=run_id, corpus_name=a.corpus, corpus_tgz=tgz, params=params,
                          rows_train=int(man.get("rows_train") or 0), gpu=a.gpu,
                          backend=a.backend, host=a.host)
        trainer = CP.select(a.compute, host=a.host, backend=a.backend)
        plan = trainer.plan(job)
    except (C.CorpusError, R.RecipeError, CP.ComputeError, ValueError) as exc:
        return fail(str(exc))
    try:
        existing: ST.RunState | None = ST.load(run_id)
    except ST.StateError:
        existing = None
    d: dict[str, Any] = {"run_id": run_id, "corpus": a.corpus, "recipe": recipe_name,
                         "compute": trainer.kind, "plan": plan.as_dict(), "params": params,
                         "started": False,
                         "existing": existing.as_dict() if existing else None}
    env = ok(d)
    for w in plan.warnings:
        env.warn("plan", w)
    if existing and existing.phase in ("running", "staging"):
        env.warn("running", f"прогін {run_id} уже йде ({existing.phase}) — дивіться "
                            f"nysh train status")
        return env
    if a.dry_run or not a.yes or not plan.ok:
        if not plan.ok:
            env.warn("not_ready", "шлях обчислень не готовий — див. попередження вище")
        else:
            env.warn("confirm", f"це план; запустити: nysh train start --corpus {a.corpus} "
                                f"--compute {trainer.kind} --yes")
        return env
    st = ST.RunState(run_id=run_id, recipe=recipe_name,
                     corpus={"name": a.corpus, "tgz": str(tgz),
                             "sha256": man.get("sha256", ""),
                             "rows_train": man.get("rows_train"), "rows_val": man.get("rows_val")},
                     params_sha=ST.params_sha(params))
    st.set_phase("staging").save()
    try:
        trainer.start(job, st)
    except CP.ComputeError as exc:
        st.set_phase("failed", str(exc)).incident(str(exc)).save()
        return fail(str(exc))
    d["started"] = True
    d["state"] = st.as_dict()
    env.suggest("train.status", "стежити за прогоном")
    return env


class RunArgs(BaseModel):
    run: str = Field(default="", description="прогін; порожньо — останній")
    all: bool = Field(default=False, description="усі прогони")


def _run_state(run: str) -> Any:
    from nyshporka.train import state as ST

    if run:
        return ST.load(run)
    st = ST.latest()
    if st is None:
        raise ST.StateError("прогонів ще немає")
    return st


@op("train.status", summary="Пульс прогону: жива карта, епоха, чекпойнти, підсумок",
    args=RunArgs, agent=False, section=SECTION)
def train_status(a: RunArgs) -> Envelope:
    """Стан із ДИСКА (лог, ваги епох, summary), а не з пам'яті того, хто запускав."""
    from nyshporka.train import compute as CP
    from nyshporka.train import state as ST

    if a.all:
        return ok({"runs": [r.as_dict() for r in ST.list_runs()]})
    try:
        st = _run_state(a.run)
        trainer = CP.select(str(st.compute.get("kind") or "local"))
        pulse = trainer.poll(st)
    except (ST.StateError, CP.ComputeError) as exc:
        return fail(str(exc))
    if pulse.finished and st.phase == "running":
        st.set_phase("fetched" if trainer.kind == "local" else "running",
                     "трен завершено").save()
    if pulse.rc not in (None, 0) and st.phase == "running":
        st.set_phase("failed", pulse.note).incident(pulse.note).save()
    st.epochs_done = max(st.epochs_done, pulse.epoch)
    st.save()
    env = ok({"state": st.as_dict(), "pulse": pulse.as_dict()})
    if pulse.finished:
        env.suggest("train.fetch" if trainer.kind != "local" else "train.eval",
                    "забрати ваги" if trainer.kind != "local" else "обрати епоху по holdout")
    return env


@op("train.fetch", summary="Забрати ваги з машини, де йшов трен",
    args=RunArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_fetch(a: RunArgs) -> Envelope:
    from nyshporka.train import compute as CP
    from nyshporka.train import state as ST

    try:
        st = _run_state(a.run)
        trainer = CP.select(str(st.compute.get("kind") or "local"))
        out = trainer.fetch(st)
    except (ST.StateError, CP.ComputeError) as exc:
        return fail(str(exc))
    n = len(list(out.glob("parseq_ep*.pt"))) if out.is_dir() else 0
    st.set_phase("fetched", f"чекпойнтів {n}").save()
    env = ok({"run_id": st.run_id, "out": str(out), "ckpts": n,
              "summary": (out / "ptrain_summary.json").is_file()})
    if trainer.kind == "gpurunner" and str(st.compute.get("backend")) == "vast":
        env.warn("vast_bill", "vast тарифікує до cancel — тепер `nysh train stop`")
    env.suggest("train.eval", "обрати епоху по holdout")
    return env


@op("train.stop", summary="Зупинити прогін (локальний процес або оренду)",
    args=RunArgs, mutates=True, agent=False, section=SECTION)
def train_stop(a: RunArgs) -> Envelope:
    from nyshporka.train import compute as CP
    from nyshporka.train import state as ST

    try:
        st = _run_state(a.run)
        trainer = CP.select(str(st.compute.get("kind") or "local"))
        trainer.stop(st)
    except (ST.StateError, CP.ComputeError) as exc:
        return fail(str(exc))
    if st.phase in ("running", "staging"):
        st.set_phase("failed", "зупинено людиною").incident("stop").save()
    return ok({"run_id": st.run_id, "phase": st.phase})


# ── оцінка й просування ──────────────────────────────────────────────────────
class EvalArgs(BaseModel):
    run: str = Field(default="", description="прогін; порожньо — останній")
    sets: str = Field(default="", description="holdout-набори через кому; порожньо — за роллю")
    models: str = Field(default="", description="чинні моделі для порівняння: pysar_cyr_v17")
    also: str = Field(default="", description="інші файли ваг через кому")
    thresh: int = Field(default=80, description="поріг нечіткого збігу назви")
    mode: str = Field(default="strip", description="strip | loose")
    device: str = Field(default="cuda:0")
    refresh: bool = Field(default=False, description="перерахувати, ігноруючи кеш прогнозів")


@op("train.eval", summary="Обрати епоху по holdout: recall назв і CER усіх чекпойнтів одним прогоном",
    args=EvalArgs, long=True, agent=False, section=SECTION)
def train_eval(a: EvalArgs) -> Envelope:
    from nyshporka.train import select as SEL
    from nyshporka.train import state as ST

    try:
        st = _run_state(a.run)
        rep = SEL.evaluate(st.run_id, sets=_csv(a.sets) or None, models=_csv(a.models) or None,
                           also=[Path(p) for p in _csv(a.also)], thresh=a.thresh, mode=a.mode,
                           device=a.device, refresh=a.refresh)
    except (ST.StateError, SEL.SelectError) as exc:
        return fail(str(exc))
    env = ok(rep.as_dict())
    for w in rep.warnings:
        env.warn("eval", w)
    env.suggest("train.promote", f"просунути {rep.winner_recall}: nysh train promote "
                                 f"{st.run_id} --epoch <N> --as pysar_cyr_vN.pt --why …")
    return env


class PromoteArgs(BaseModel):
    run: str = Field(description="прогін")
    as_name: str = Field(description="ім'я файла ваг: pysar_cyr_v18.pt")
    why: str = Field(description="чим краща і на чому виміряно")
    epoch: int = Field(default=-1, description="номер епохи; -1 — переможець за recall")
    label: str = Field(default="", description="або мітка: best | epNN")
    force: bool = Field(default=False, description="без select.json / поверх наявного файла")


@op("train.promote", summary="Зробити чекпойнт бойовою моделлю: копія, картка, PRODUCTION.json",
    args=PromoteArgs, mutates=True, agent=False, section=SECTION)
def train_promote(a: PromoteArgs) -> Envelope:
    from nyshporka.train import promote as P

    try:
        got = P.promote(a.run, as_name=a.as_name, why=a.why,
                        epoch=None if a.epoch < 0 else a.epoch, label=a.label, force=a.force)
    except (P.PromoteError, Exception) as exc:
        return fail(str(exc))
    env = ok(got)
    if got["card"].get("forced"):
        env.warn("forced", "просунуто без заміру на holdout — картка це каже")
    env.suggest("read.plan", "прочитати справу новою моделлю на сторінці з відомим позитивом")
    return env
