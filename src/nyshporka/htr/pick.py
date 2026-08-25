"""🖋 Чим читати цю справу — і на чому цей висновок стоїть.

Питання, на яке відповідає модуль, одне: **яким письмом написана справа**. Від
нього залежить рушій, а помилка тут не дає збою — вона дає осмислене на вигляд
сміття. Кириличний рушій на латинській книзі чесно видає текст, впевненість не
просідає, і виглядає це як погана якість сканів, а не як неправильний вибір.

🔴 Тому висновок їде РАЗОМ із рівнем довіри й причиною. «Кирилиця» без
пояснення читається однаково і тоді, коли письмо записане в опису справи, і
тоді, коли його вгадали з імені теки, — а це різниця між фактом і здогадом.

Порядок довіри, від найсильнішого:

  `fixed`   письмо записане в опису справи (`_source.json` → `script`/`langs`);
  `genre`   жанр у назві: обляти й нотаріат — латинка, ревізії й метрики — кирилиця;
  `epoch`   роки: діловодство Правобережжя до 1830-х латинкою, після 1840-х кирилицею;
  `folder`  ім'я теки — найслабше, лишається лише як остання підказка;
  `unknown` не сказати нічого; тоді питають людину, а не вгадують.

🔴 `unknown` — повноцінна відповідь, а не невдача. Мовчазне «нехай буде
кирилиця» коштує ночі прогону й теки правдоподібного сміття; чесне «жанр і
роки не дають відповіді — подивіться скан оком» коштує одного погляду.

Модуль навмисно НЕ тягне середовища рушіїв (на відміну від `htr.run`): те саме
питання ставить і бібліотека, де жодного рушія може не бути встановлено.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Жанрові слова, що видають кириличне діловодство. Шукаються в назві, типі
#: документа й примітці опису — тобто в тому, що написала людина, а не машина.
_CYR_HINTS = ("ревізьк", "казк", "сказк", "метричн", "сповід", "клірові",
              "посемейн", "церкв", "консистор", "духовн", "переписн", "селян",
              "міщан", "ревизск", "метрическ", "исповед", "клирові")

#: Те саме для латинки: актові книги Правобережжя й костельне діловодство.
_LAT_HINTS = ("облят", "нотаріальн", "декрет", "земськ", "гродськ", "ґродськ",
              "костел", "kostel", "тестамент", "ksi", "akta", "parafial")


@dataclass(frozen=True)
class ScriptGuess:
    """Письмо справи + чим це доведено."""

    script: str            # latin | cyrillic | mixed | unknown
    why: str               # людський рядок для картки
    trust: str             # fixed | genre | epoch | folder | unknown

    @property
    def is_guess(self) -> bool:
        """Чи це здогад, який людина мусить звірити оком."""
        return self.trust != "fixed"

    def as_dict(self) -> dict[str, str]:
        return {"script": self.script, "script_why": self.why,
                "script_trust": self.trust}


def guess_script(info: dict[str, Any] | None) -> ScriptGuess:
    """Письмо з опису справи — того, що віддає `library.describe_case`.

    🔴 Зафіксоване в опису б'є будь-яку евристику, і саме заради випадків, де
    евристика безсила за побудовою: тримовна книга (російська рамка, латинські
    обляти XVIII ст., польські контракти) не має «свого» письма взагалі, і
    жанр із роками про це не скажуть. Такі справи вимагають ДВОХ прогонів
    окремими теками, і сказати це може лише той, хто книгу бачив.
    """
    info = info or {}
    fixed = str(info.get("script") or "").strip()
    if fixed:
        langs = ", ".join(str(x) for x in (info.get("langs") or []) if x)
        why = "письмо записане в опису справи"
        return ScriptGuess(fixed, why + (f" · мови: {langs}" if langs else ""),
                           "fixed")

    text = " ".join(str(info.get(k) or "") for k in
                    ("title", "doc_type", "why", "group")).lower()
    cyr = any(h in text for h in _CYR_HINTS)
    lat = any(h in text for h in _LAT_HINTS)
    if lat and not cyr:
        return ScriptGuess("latin", "жанр у назві: обляти, нотаріат, костел — "
                                    "польська латинка", "genre")
    if cyr and not lat:
        return ScriptGuess("cyrillic", "жанр у назві: ревізії, метрики, "
                                       "сповідки — російська кирилиця", "genre")
    if cyr and lat:
        # Обидва жанри в одній назві — це не «не знаємо», а сигнал про книгу,
        # де письма справді два.
        return ScriptGuess("mixed", "у назві є й латинські, й кириличні жанри — "
                                    "схоже на книгу з двома письмами", "genre")

    y0, y1 = _year(info.get("year_from")), _year(info.get("year_to"))
    if y1 is not None and y1 <= 1830:
        return ScriptGuess("latin", f"до 1830 ({y1}) діловодство Правобережжя "
                                    f"велося польською латинкою", "epoch")
    if y0 is not None and y0 >= 1840:
        return ScriptGuess("cyrillic", f"після 1840 ({y0}) — російська кирилиця",
                           "epoch")
    return ScriptGuess("unknown",
                       "жанр і роки не дають відповіді — подивіться скан оком "
                       "або вкажіть письмо явно", "unknown")


def guess_script_for_dir(case_dir: str | Path, hint: str = "") -> ScriptGuess:
    """Письмо теки: підказка людини → опис справи → ім'я теки.

    ⚠ Ім'я теки — найслабша ланка, і саме на ній трималось усе до появи цього
    модуля. З назви на кшталт `spr-90` не видно нічого, а мовчазний дефолт
    «кирилиця» перетворював відсутність відповіді на впевнену неправильну.
    """
    if hint in ("latin", "cyrillic", "mixed"):
        return ScriptGuess(hint, "письмо вказали ви", "fixed")

    info: dict[str, Any] | None = None
    try:
        from nyshporka.library import describe_case

        info = describe_case(str(case_dir))
    except Exception:
        info = None
    if info:
        got = guess_script(info)
        if got.trust != "unknown":
            return got

    name = Path(str(case_dir)).name.lower()
    if any(k in name for k in ("kostel", "parafial", "notar", "f792", "latin",
                               "oblat", "grod")):
        return ScriptGuess("latin", f"з імені теки «{name}» — і це лише здогад",
                           "folder")
    return ScriptGuess("unknown",
                       f"про теку «{name}» опису немає, а саме ім'я нічого не "
                       f"каже — подивіться скан оком або вкажіть письмо явно",
                       "unknown")


def _year(v: Any) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1500 <= n <= 2100 else None


def engines_for(script: str) -> list[dict[str, str]]:
    """Рушії, придатні для цього письма — З МАНІФЕСТУ, а не зі словника тут.

    🔴 Рушії описані даними (`htr/data/engines.yaml`), і другий їх перелік у
    коді розійшовся б із першим мовчки: доданий рушій просто не з'являвся б у
    підказці, хоч читати ним можна.
    """
    from nyshporka.htr import manifest as M

    try:
        man = M.active()
    except Exception:
        return []
    scripts = ("latin", "cyrillic") if script == "mixed" else (script,)
    out = []
    for s in scripts:
        for e in man.engines_for_script(s):
            out.append({"id": e.id, "label": e.label, "kind": e.kind,
                        "script": e.script, "note": e.note})
    return out


def covered(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Які рушії вже пройшли цю справу — ключ `engine_id`, найповніший прогін.

    🔴 Без цієї зведенки видно «прогін уже був», але не видно, що прочитана з
    нього ПОЛОВИНА. На книзі з двома письмами перший прогін закриває лише своє,
    а другий рушій треба ставити окремою текою — і саме тут людина вирішує, чи
    справу дочитано.
    """
    got: dict[str, dict[str, Any]] = {}
    for r in runs:
        # 🔴 ВСІ рушії прогону, а не перший. Прогін двома голосами записує
        # обидві моделі одним полем через «+», і взявши лише перший, ми
        # оголосили б другий голос відсутнім — тобто порадили б поставити ще
        # одну ніч на роботу, яка вже зроблена.
        ids = [str(x) for x in (r.get("engine_ids") or []) if x]
        if not ids:
            one = str(r.get("engine_id") or r.get("engine") or "")
            ids = [one] if one else []
        for key in ids:
            cur = got.get(key)
            if cur is None or (r.get("pages_done") or 0) > (cur.get("pages_done") or 0):
                got[key] = {"run": r.get("name"), "model": r.get("model"),
                            "pages_done": r.get("pages_done") or 0,
                            "done": bool(r.get("done")),
                            "script": r.get("script") or "",
                            "updated": r.get("updated") or ""}
    return got


def gaps(script: str, done: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Чого бракує й що зайве — трьома РІЗНИМИ відповідями, не однією.

    🔴 «Прогін є» мовчки читається як «справу прочитано», і саме так половина
    книги з двома письмами лишається непрочитаною. Тому окремо називається
    рушій, якого бракує, і окремо — прогін, чий рушій письму не відповідає:
    його текст може бути тихим сміттям, а виглядає він у переліку так само
    впевнено, як правильний.
    """
    want = {e["id"] for e in engines_for(script)}
    out: list[dict[str, str]] = []
    for eid in sorted(want - set(done)):
        out.append({"kind": "missing", "engine": eid,
                    "why": "цим рушієм справу ще не читали"})
    if script in ("latin", "cyrillic"):
        for eid, row in sorted(done.items()):
            if eid in want:
                continue
            out.append({"kind": "mismatch", "engine": eid,
                        "run": str(row.get("run") or ""),
                        "why": "рушій не відповідає письму справи — його текст "
                               "може бути сміттям, і тихим: впевненість не "
                               "просідає"})
    return out


def case_info(case_dir: str, *, script_hint: str = "") -> dict[str, Any]:
    """Картка справи ПЕРЕД запуском: опис, письмо з причиною, рушії, прогони.

    Усе, що людина мусить побачити до того, як віддасть машині ніч: скільки
    кадрів, яким письмом, чим читатимемо, що вже читали й чого бракує.
    """
    from nyshporka import htr_store as S
    from nyshporka.htr import run as R
    from nyshporka.library import describe_case

    case_dir = (case_dir or "").strip()
    info = None
    try:
        info = describe_case(case_dir) if case_dir else None
    except Exception:
        info = None

    guess = (guess_script(info) if info else ScriptGuess(
        "unknown", "справи немає в бібліотеці — опису читати нема з чого",
        "unknown"))
    if script_hint in ("latin", "cyrillic", "mixed"):
        guess = ScriptGuess(script_hint, "письмо вказали ви", "fixed")
    elif guess.trust == "unknown" and case_dir:
        guess = guess_script_for_dir(case_dir)

    try:
        runs = S.find_runs_for_case(case_dir) if case_dir else []
    except Exception:
        runs = []
    done = covered(runs)

    frames = 0
    try:
        # 🔴 Через гард простору, а не `abspath`. Тека приходить відносною
        # (`data/raw/…`), і `abspath` рахував би її від поточного каталогу
        # процесу — тобто кадрів «не було» в кожної справи, крім тих, що
        # передані повним шляхом. Нуль кадрів на екрані читається як «читати
        # нема чого».
        d = S.under_raw(case_dir)
        if d is not None and d.is_dir():
            frames = R.count_frames(d)
    except Exception:
        frames = 0

    y0, y1 = (info or {}).get("year_from"), (info or {}).get("year_to")
    years = "" if not (y0 or y1) else (str(y0) if y0 == y1
                                       else f"{y0 or '?'}–{y1 or '?'}")
    return {
        "found": bool(info),
        "case_dir": case_dir,
        "shifra": (info or {}).get("shifra") or "",
        "title": (info or {}).get("title") or "",
        "doc_type": (info or {}).get("doc_type") or "",
        "place": (info or {}).get("place") or "",
        "years": years,
        "langs": list((info or {}).get("langs") or []),
        # Кадри рахуються з ДИСКА, а не беруться з опису: опис може відставати
        # від теки, а читатимемо саме те, що лежить.
        "frames": frames,
        "frames_described": (info or {}).get("frames") or 0,
        **guess.as_dict(),
        "engines": engines_for(guess.script),
        "runs": runs,
        "covered": done,
        "gaps": gaps(guess.script, done),
    }
