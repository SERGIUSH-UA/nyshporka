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
