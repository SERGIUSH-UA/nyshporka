"""📚 Бібліотека справ — що взагалі є на руках, і що з цим уже вирішено.

Відповідає на питання, якого не закриває жоден інший екран: **що я маю**.
`cases.list` каже про справи, взяті під облік у цьому просторі; бібліотека
зводить ширше — канон і диск разом, з людськими вердиктами поверх.

🔴 Вердикт тут — рішення ЛЮДИНИ, і воно не застаріває. Скан застаріває від
зміни моделі, декод — від нового прогону, а «я переглянув цю справу очима, роду
немає» лишається правдою й через рік. Саме тому вердикти живуть окремим файлом,
а не полем зведення, яке перезбирають.

🔴 Своєї «перезбірки» тут НЕМАЄ навмисно. Зведення будує `cases.build` — той
самий прохід, що збирає реєстр справ (`build_library` + `write_library`
всередині). Друга довга операція поруч виглядала б як окрема кнопка, робила б
те саме й дозволяла б двом проходам писати в один файл одночасно.

⚠ Порожня бібліотека і НЕЗІБРАНА бібліотека — різні відповіді, і плутати їх
дорого: «0 справ» читається як факт («у мене нічого немає»), тоді як насправді
зведення просто не будували. Тому операції нижче розрізняють ці стани явно, а
`shown: null` означає «невідомо», а не нуль.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class LibraryArgs(BaseModel):
    q: str = Field(default="", description="шифр, назва або місце — підрядком")
    repo: str = Field(default="", description="архів: DAHMO, DAVO, CDIAK…")
    verdict: Literal["", "any", "none", "no_clan", "clan_found", "recheck"] = Field(
        default="", description="фільтр за людським вердиктом; "
                                "`any` — будь-який, `none` — вердикту немає")
    on_disk: bool | None = Field(
        default=None, description="лише ті, що є на диску (або лише яких немає)")
    limit: int = Field(default=200, ge=1, le=2000)


#: Поля, які їдуть у браузер. Не весь `CaseEntry`: у ньому є службові сліди
#: збірки (`desc_source`, `rtypes_inferred`, `tag`), і показувати їх означало б
#: пропонувати рішення на підставі того, як зведення себе зібрало.
_FIELDS = ("key", "repo", "repo_label", "fond", "opys", "spr", "shifra", "title",
           "year_from", "year_to", "doc_type", "place", "parish", "path",
           "on_disk", "frames", "script", "langs", "curated", "group", "why")


def _row(case: Any, verdicts: dict[str, Any]) -> dict[str, Any] | None:
    """Рядок видачі або порожньо, якщо запис не є записом.

    ⚠ Один кривий елемент у зведенні не має ховати решту: тут це рядок, який
    просто не показують, а не відмова на весь екран.
    """
    if not isinstance(case, dict):
        return None
    out = {k: case.get(k) for k in _FIELDS}
    v = verdicts.get(case.get("key") or "") or {}
    out["verdict"] = v.get("verdict") or ""
    out["verdict_note"] = v.get("note") or ""
    out["verdict_date"] = v.get("date") or ""
    return out


def _matches(row: dict[str, Any], a: LibraryArgs) -> bool:
    if a.repo and (row.get("repo") or "").upper() != a.repo.upper():
        return False
    if a.on_disk is not None and bool(row.get("on_disk")) is not a.on_disk:
        return False
    if a.verdict == "any" and not row["verdict"]:
        return False
    if a.verdict == "none" and row["verdict"]:
        return False
    if a.verdict not in ("", "any", "none") and row["verdict"] != a.verdict:
        return False
    if a.q:
        hay = " ".join(str(row.get(k) or "")
                       for k in ("shifra", "title", "place", "parish", "doc_type"))
        if a.q.casefold() not in hay.casefold():
            return False
    return True


# 🔴 `agent=False` в обох — рішення, а не «поки не зробили».
#
# `library.list` агентові нічого не додає: те саме про справи в роботі він уже
# питає через `cases.list`, а зайвий tool росте в переліку, який модель мусить
# читати цілком при кожному виклику.
#
# `library.verdict` — принциповіше. Вердикт по справі виносить ЛЮДИНА, і
# «роду тут немає» від агента закриває напрям пошуку назавжди: наступна сесія
# прочитає його як доведений факт і туди більше не гляне. Тому дія лишається
# рівно там, де сидить той, хто дивився очима.
@op("library.list", summary="Бібліотека: які справи є на руках і що з ними вирішено",
    args=LibraryArgs, section="material", agent=False)
def library_list(a: LibraryArgs) -> Envelope:
    """Зведення справ із людськими вердиктами.

    🔴 «Зведення ще не збирали» НЕ виглядає як «справ немає». Нуль без
    знаменника не результат: побачивши «0 справ», людина вирішує, що шукати
    нема де, — і закриває напрям, якого ніхто не відкривав. Тому кількість тут
    `null`, а не 0, і поруч стоїть застереження з тим, чим це лікується.
    """
    from nyshporka import library as L

    # 🔴 Три стани, а не два, і читаються вони ТУТ, а не через `load_library()`.
    # Той ковтає будь-який виняток і віддає `[]`, тобто зводить «файла немає» і
    # «файл побитий» до «справ немає» — рівно того хибного нуля, від якого
    # написаний докстрінг модуля. Побита бібліотека при цьому виглядала б
    # гірше за відсутню: `built: true`, «0 справ», жодного натяку на причину.
    if not L.LIBRARY_PATH.exists():
        env = ok({"cases": [], "shown": None, "total": None, "built": False})
        env.warn("no_library_yet",
                 "бібліотеку ще не збирали — це не означає, що справ немає")
        env.stale_because(["зведення справ ще не будували"], fix="nysh cases build")
        env.suggest("cases.build", "зібрати зведення з канону й диска")
        return env
    try:
        raw = json.loads(L.LIBRARY_PATH.read_text(encoding="utf-8"))
        cases = list(raw.get("cases") or [])
    except Exception as exc:
        return fail(f"зведення справ не читається ({type(exc).__name__}: {exc}) — "
                    f"файл {L.LIBRARY_PATH.name} побитий; перезберіть його "
                    f"командою `nysh cases build`")

    verdicts = L.load_verdicts()
    rows = [r for r in (_row(c, verdicts) for c in cases) if r is not None]
    skipped = len(cases) - len(rows)
    hit = [r for r in rows if _matches(r, a)]
    env = ok({"cases": hit[:a.limit], "shown": min(len(hit), a.limit),
              "total": len(rows), "built": True,
              # 🔴 Перелік архівів — з УСІЄЇ бібліотеки, а не з видачі. Зібраний
              # із відфільтрованого, він схлопується до одного пункту після
              # першого ж вибору: решта архівів зникає зі списку, і повернутись
              # до них нема чим — екран починає брехати про діючий фільтр.
              "repos": sorted({r["repo"] for r in rows if r.get("repo")}),
              "kinds": {k: v["label"] for k, v in L.VERDICT_KINDS.items()}})
    if skipped:
        env.warn("bad_rows",
                 f"{skipped} записів зведення пропущено — вони не схожі на справи; "
                 f"перезбирання (`nysh cases build`) зазвичай це лікує")
    if len(hit) > a.limit:
        env.warn("truncated",
                 f"показано {a.limit} із {len(hit)} — звузьте фільтр, "
                 f"інакше решта лишиться непоміченою")
    # 🔴 Знаменник поруч із видачею, а не лише в підсумку: «нічого не знайшлось»
    # означає різне при 12 справах у бібліотеці й при 1200.
    if not hit:
        env.warn("empty_filter",
                 f"під фільтр не підпало жодної справи з {len(rows)} у бібліотеці")
    return env


class VerdictArgs(BaseModel):
    key: str = Field(description="ключ справи з бібліотеки, напр. DAHMO/315/8433")
    verdict: Literal["", "no_clan", "clan_found", "recheck"] = Field(
        default="", description="порожньо — зняти вердикт")
    note: str = Field(default="", description="чим саме доведено")
    pages: int | None = Field(default=None, description="скільки аркушів переглянуто")


@op("library.verdict", summary="Позначити справу вердиктом людини",
    args=VerdictArgs, section="material", mutates=True, agent=False)
def library_verdict(a: VerdictArgs) -> Envelope:
    """Рішення ока по справі.

    🔴 Нуль без знаменника — не результат. «Роду немає» без числа переглянутих
    аркушів наступного разу читається як доведений факт, хоча може означати
    «глянув перші три сторінки». Тому при `no_clan` без `pages` конверт
    попереджає — але не відмовляє: вердикт виносить людина, і машина не має
    права не пустити її рішення.
    """
    from datetime import date

    from nyshporka import library as L

    if not a.key.strip():
        return fail("не сказано, якій справі ставити вердикт")
    try:
        cur = L.set_verdict(a.key.strip(), a.verdict or None, note=a.note,
                            pages=a.pages, date=date.today().isoformat())
    except ValueError as exc:
        return fail(str(exc))
    env = ok({"key": a.key.strip(), "verdict": cur})
    if a.verdict == "no_clan" and not a.pages:
        env.warn("no_denominator",
                 "«роду немає» без числа переглянутих аркушів — наступна сесія "
                 "прочитає це як доведений нуль")
    return env
