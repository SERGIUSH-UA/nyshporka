"""📋 Операції бланка: замір читання поклітинно проти звіреного оком."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class FormBenchArgs(BaseModel):
    case: str = Field(description="справа: ключ, шифра або тека кадрів")
    truth: str = Field(default="", description="файл {сторінка: [слова]}; порожньо — "
                                               "звірені оком читання нотатника справи")
    voices: list[str] = Field(default_factory=list,
                              description="ще теки голосів поза reports/htr (проба)")


@op("form.bench", summary="Замір бланка: частка звірених оком слів, видних у кожному "
                          "голосі справи й у всіх разом",
    args=FormBenchArgs,
    next_hints=(("text.voices", "подивитись голоси рядка"),),
    when="чи краще читаються бланки поклітинно — замір проти звіреного оком")
def form_bench(a: FormBenchArgs) -> Envelope:
    from nyshporka import htr_store as S
    from nyshporka.htr import form_bench as B

    try:
        scope = S.runs_for_scope(a.case)
    except ValueError as exc:
        return fail(str(exc))
    voices: dict[str, Path] = {r["name"]: S.htr_root() / r["name"] for r in scope["rows"]}
    for v in a.voices:
        p = Path(v)
        if not p.is_dir():
            return fail(f"теки голосу немає: {p}")
        voices[p.name] = p
    if a.truth:
        try:
            truth = B.truth_from_file(Path(a.truth))
        except (OSError, ValueError) as exc:
            return fail(f"істина не читається: {exc}")
        source = a.truth
    else:
        from nyshporka.pagestore.store import load_case, resolve_case

        try:
            cf = load_case(resolve_case(a.case))
        except ValueError as exc:
            return fail(str(exc))
        truth = B.truth_from_notes(cf.notes if cf else [])
        source = "нотатник справи"
    if not truth:
        return fail("звіреного оком немає: `nysh note read <справа> <скан> --line N --text …` "
                    "або --truth <файл>")
    if not voices:
        return fail("у справи немає жодного прогону")
    env = ok({**B.score(truth, voices).as_dict(), "truth": source})
    return env


class FormExtractArgs(BaseModel):
    case: str = Field(description="справа: ключ, шифра або тека кадрів")
    template: str = Field(default="", description="ім'я шаблону; порожньо — за написом на сторінці")
    run: str = Field(default="", description="тека голосу клітинок; порожньо — `-cells` справи")
    apply: bool = Field(default=False, description="записати в сховище сторінок; без нього — "
                                                   "лише показати, що вийде")


@op("form.extract", summary="Бланк → записи з ролями: клітинки голосу `-cells` за шаблоном",
    args=FormExtractArgs, mutates=True,
    next_hints=(("search.run", "шукати записи за роллю: where=records role=father"),),
    when="з прочитаних поклітинно бланків (РАЦС, анкети) зробити записи з ролями й полями")
def form_extract(a: FormExtractArgs) -> Envelope:
    """Машинні записи з бланків: `confidence: indirect`, `agent: form:<шаблон>`.

    🔴 Звірене людиною не затирається: машинний запис має власний `rid`
    (`…-form`), а сторінка, на якій уже є не машинний запис того самого типу,
    пропускається.
    """
    from collections import Counter

    from pydantic import ValidationError

    from nyshporka import htr_store as S
    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import Record
    from nyshporka.records import form as F

    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))
    if a.run:
        run_dir = Path(a.run)
        if not run_dir.is_dir():
            run_dir = S.htr_root() / a.run
    else:
        try:
            rows = S.runs_for_scope(a.case)["rows"]
        except ValueError as exc:
            return fail(str(exc))
        cells = [r["name"] for r in rows if str(r["name"]).endswith("-cells")]
        if not cells:
            return fail("у справи немає голосу клітинок: спершу `nysh read <справа> --form-cells`")
        run_dir = S.htr_root() / cells[0]
    if not run_dir.is_dir():
        return fail(f"теки голосу немає: {run_dir}")
    templates = F.templates()
    if a.template and a.template not in templates:
        return fail(f"шаблону «{a.template}» немає; є: {', '.join(sorted(templates))}")
    cf = store.load_case(ref)
    human = {(Path(s).stem, r.rtype) for r in (cf.records if cf else [])
             if not r.agent.startswith("form:") for s in r.scans}
    meta_pages = {Path(n).stem: n for n in (S.read_meta(run_dir).get("pages") or {})} \
        if hasattr(S, "read_meta") else {}
    recs: list[Record] = []
    filled: Counter[str] = Counter()
    pages = matched = kept_human = 0
    bad: list[str] = []
    for txt in sorted(run_dir.glob("*.txt")):
        pages += 1
        cells_ = F.read_page(run_dir, txt.stem)
        t = F.pick(templates, cells_, a.template)
        if t is None:
            continue
        matched += 1
        if (txt.stem, t.rtype) in human:
            kept_human += 1
            continue
        got = F.extract(t, cells_)
        if not any(k.split(".")[-1] in ("surname", "given", "patronymic") for k in got):
            continue
        filled.update(got.keys())
        data = F.to_record(t, got, scan=meta_pages.get(txt.stem, f"{txt.stem}.jpg"),
                           run=run_dir.name)
        try:
            rec = Record(**data)
        except ValidationError as exc:
            bad.append(f"{txt.stem}: {exc.errors()[0].get('msg')}")
            continue
        rec.rid = f"{rec.rid}-form"
        recs.append(rec)
    report = None
    if a.apply and recs:
        report = store.add_records(ref, recs)
    env = ok({"run": run_dir.name, "pages": pages, "matched": matched, "records": len(recs),
              "kept_human": kept_human, "filled": dict(sorted(filled.items())),
              "applied": bool(report), "invalid": bad,
              "sample": [r.model_dump(mode="json") for r in recs[:3]]})
    if kept_human:
        env.warn("kept_human", f"{kept_human} сторінок мають записи, внесені людиною чи "
                               f"агентом, — машинні туди не кладуться")
    if not a.apply and recs:
        env.warn("dry_run", f"{len(recs)} записів лише показано — `--apply`, щоб записати")
    return env
