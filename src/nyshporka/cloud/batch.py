"""🚚 Партія: багато справ, кілька машин, ОДНЕ рішення про гроші.

`nysh cloud go A B C … --boxes N` ділить справи на N черг — по машині й по
наглядачу на чергу — і пускає всі черги одразу. Людина бачить вилку ВСІЄЇ
партії й підтверджує її один раз.

🔴 Навіщо це в пакеті. 01.10.2026 агент дістав від людини одне рішення на
33 справи й $20, а пакет умів лише одну чергу на одній машині з власною
стелею. Спільної стелі на кілька машин не було, тож агент написав власний
диспетчер оренд: групи до 4 справ / 4000 сторінок, до трьох машин разом, свій
облік загальної суми — 13 робочих оренд там, де вистачило б трьох. Потреба
була законна, відповіді на неї в пакеті не було.

🔴 Чому статичний поділ, а не диспетчер «звільнилась машина — пускай наступну
групу». Довга черга на машині і є найдешевша форма: старт платиться раз. Кінці
черг вирівнює поділ за обсягом роботи. Тож нового довгоживучого процесу, який
може померти посеред партії, немає: кожну машину від оренди до гасіння веде
той самий наглядач, що й одну чергу.
"""
from __future__ import annotations

import secrets
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.cloud import money as M

if TYPE_CHECKING:  # pragma: no cover — лише для перевірки типів
    from collections.abc import Callable, Sequence

    from nyshporka.cloud.convoy import Convoy, Leg
    from nyshporka.cloud.go import GoResult

#: Частка стелі часу, яку може зайняти прогноз черги. Решта — запас на ринок,
#: сетап і темп, нижчий за прогноз: черга, якій прогнозують 10 год зі стелі 14,
#: має всі шанси впертись у стелю посеред роботи.
HOURS_HEADROOM = 1.5


# ── поділ ────────────────────────────────────────────────────────────────────
def _pages(leg: Leg) -> int:
    left = leg.plan.pages_left
    return max(1, int(left)) if left is not None else max(1, int(leg.plan.frames or 0))


def weights(legs: Sequence[Leg]) -> list[float]:
    """Вага справи — рядки, які прочитає машина: сторінки × щільність.

    Невідома щільність — медіана відомих у партії: сторінки сповідки й
    метрики різняться за ціною вдвічі, і рахувати їх однаково значить дати
    одній машині вдвічі більше роботи. Невідомо ніде — лише сторінки.
    """
    known = [float(leg.plan.lines_per_page) for leg in legs if leg.plan.lines_per_page]
    fallback = statistics.median(known) if known else 1.0
    return [_pages(leg) * float(leg.plan.lines_per_page or fallback) for leg in legs]


def split(legs: Sequence[Leg], boxes: int) -> list[list[Leg]]:
    """Розкласти справи на `boxes` черг якомога рівніше (жадібно: найважча
    справа — у найлегшу чергу).

    Порядок справ усередині черги — як у команді: людина назвала їх у
    порядку, в якому хоче бачити результат.
    """
    n = max(1, min(boxes, len(legs)))
    w = weights(legs)
    order = sorted(range(len(legs)), key=lambda i: (-w[i], i))
    load = [0.0] * n
    slots: list[list[int]] = [[] for _ in range(n)]
    for i in order:
        k = min(range(n), key=lambda j: (load[j], j))
        slots[k].append(i)
        load[k] += w[i]
    return [[legs[i] for i in sorted(slot)] for slot in slots if slot]


def share_budget(total: float, forks: Sequence[tuple[float, float]]) -> list[float]:
    """Поділити загальну стелю між чергами.

    Кожна черга спершу дістає свій НИЗ (прогноз), решта ділиться пропорційно
    запасу вилки (верх − низ): саме запас покриває невідому щільність, і
    черзі, де вона невідома, його треба більше.
    """
    lows = [low for low, _ in forks]
    spare = total - sum(lows)
    gaps = [max(0.0, high - low) for low, high in forks]
    if sum(gaps) <= 0:
        gaps = [max(high, 0.01) for _, high in forks]
    return [round(low + spare * g / sum(gaps), 2) for low, g in zip(lows, gaps, strict=True)]


# ── облік партії ─────────────────────────────────────────────────────────────
@dataclass
class BatchRecord:
    """Партія, як вона лежить на диску: які черги, які наглядачі, скільки грошей."""

    batch_id: str
    created: str = ""
    budget_total: float | None = None
    fork_low: float | None = None
    fork_high: float | None = None
    #: По запису на чергу: `session`, `run_ids`, `cases`, `pages`, `budget_usd`,
    #: `max_hours`, `started`, `why`.
    queues: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"batch_id": self.batch_id, "created": self.created,
                "budget_total": self.budget_total, "fork_low": self.fork_low,
                "fork_high": self.fork_high, "queues": [dict(q) for q in self.queues],
                "dropped": [list(d) for d in self.dropped]}


def batches_dir() -> Path:
    from nyshporka.cloud.state import runs_dir

    return runs_dir() / "batches"


def save(rec: BatchRecord) -> BatchRecord:
    from nyshporka.utils.atomic import write_json

    write_json(batches_dir() / f"{rec.batch_id}.json", rec.as_dict())
    return rec


def load(batch_id: str) -> BatchRecord | None:
    from nyshporka.utils.atomic import read_json

    raw = read_json(batches_dir() / f"{batch_id}.json", default=None)
    if not isinstance(raw, dict):
        return None
    known = set(BatchRecord.__dataclass_fields__)
    return BatchRecord(**{k: v for k, v in raw.items() if k in known})


def all_batches() -> list[BatchRecord]:
    """Усі партії простору, новіші першими."""
    d = batches_dir()
    if not d.is_dir():
        return []
    out = [r for p in d.glob("*.json") if (r := load(p.stem)) is not None]
    return sorted(out, key=lambda r: r.created, reverse=True)


def new_id() -> str:
    return f"batch-{datetime.now():%m%d-%H%M}-{secrets.token_hex(2)}"


# ── захід ────────────────────────────────────────────────────────────────────
def launch(convoy: Convoy, res: GoResult, say: Callable[..., None], *,
           boxes: int, budget: float | None = None, max_hours: float | None = None,
           max_rents: int = 0, confirm: bool = False, dry_run: bool = False,
           stage: bool = False,
           transport: str = "auto", max_usd_per_1000: float = 0.0,
           params: Sequence[str] = ()) -> None:
    """Скласти черги, спитати кошторис кожної, ухвалити ОДНЕ рішення й пустити.

    🔴 Жодна черга не стартує, поки не порахована вся партія: рішення про гроші
    — одне, і стартувати першу машину, не знаючи, чи вкладеться десята, означає
    дізнатись про брак грошей посеред партії, з оплаченими стартами.
    """
    from nyshporka.cloud import convoy as CV
    from nyshporka.cloud import go as GO
    from nyshporka.cloud import supervised as SUP

    queues = split(convoy.legs, boxes)
    say("batch", f"партія: {len(convoy.legs)} справ на {len(queues)} "
                 f"{'машини' if len(queues) < 5 else 'машин'}")

    # 1. план і кошторис кожної черги — без оренди
    prepared: list[tuple[Convoy, SUP.Prepared, GoResult]] = []
    assets: Path | None = None
    for k, legs in enumerate(queues, 1):
        conv = CV.of(legs)
        sub = GO.GoResult(backend=res.backend, dry_run=dry_run)
        GO._fill_cases(sub, conv)
        say("batch", f"черга {k}: {conv.label()} · {conv.pages} стор.")
        p = SUP.prepare(conv, sub, say, max_hours=max_hours, transport=transport,
                        max_usd_per_1000=max_usd_per_1000, params=params,
                        assets=assets, stage=dry_run and stage)
        assets = p.assets
        res.notes.extend(n for n in sub.notes if n not in res.notes)
        prepared.append((conv, p, sub))

    # 2. перевірки, що ловляться лише на партії
    for k, (_conv, p, _sub) in enumerate(prepared, 1):
        limit = max_hours if max_hours is not None else M.MAX_HOURS_CAP
        if p.est.hours is not None and p.est.hours * HOURS_HEADROOM > limit:
            raise GO.GoRefused(
                f"черга {k}: прогноз {p.est.hours:.1f} год — забагато на одну "
                f"машину при стелі {limit:g} год. Візьміть більше машин: "
                f"`--boxes {boxes + 1}` або більше")
    forks = [(p.fork_low, p.fork_high) for _c, p, _s in prepared]
    known = all(low is not None and high is not None for low, high in forks)
    if not known and budget is None:
        raise GO.GoRefused("кошторису немає бодай для однієї черги: наглядач не "
                           "назвав ні вартості, ні ціни з годинами. Назвіть "
                           "стелю партії самі: `--budget`.")
    if not known:
        raise GO.GoRefused("стелю партії нема на що поділити: кошторису немає "
                           "бодай для однієї черги. Пустіть черги окремими "
                           "заходами зі своїми `--budget`.")
    pairs = [(float(low), float(high)) for low, high in forks]  # type: ignore[arg-type]
    res.fork_low = round(sum(low for low, _ in pairs), 2)
    res.fork_high = round(sum(high for _, high in pairs), 2)
    if budget is not None and budget < res.fork_low:
        raise GO.GoRefused(
            f"стеля партії ${budget:.2f} нижча за сам прогноз ${res.fork_low:.2f} — "
            f"бракує ${res.fork_low - budget:.2f}. Підніміть `--budget` або "
            f"зменшіть партію")
    total = budget if budget is not None else res.fork_high
    shares = (share_budget(total, pairs) if budget is not None
              else [high for _, high in pairs])
    hours = [p.hours for _c, p, _s in prepared]
    res.budget_usd, res.max_hours = round(total, 2), max(hours)

    # 3. ОДНЕ рішення про гроші
    balances = [p.est.balance_usd for _c, p, _s in prepared
                if p.est.balance_usd is not None]
    decision = M.decide_launch(total, min(balances) if balances else None,
                               M.autostart_ceiling(), confirm)
    res.decision = decision.why
    for k, ((conv, _p, _s), share, h) in enumerate(zip(prepared, shares, hours,
                                                      strict=True), 1):
        res.queues.append({"queue": k, "session": "", "cases": [leg.name for leg in conv.legs],
                           "run_ids": list(conv.run_ids), "pages": conv.pages,
                           "fork_usd": list(forks[k - 1]), "budget_usd": share,
                           "max_hours": h, "started": False, "why": ""})
    say("money", f"вилка партії ${res.fork_low:.2f}–${res.fork_high:.2f} · стеля "
                 f"${total:.2f} на {len(prepared)} машин · рішення: {decision.why}")
    if dry_run:
        res.verdict = "dry_run"
        res.why = (f"сухий прогін партії: {len(prepared)} черг, оренди не було")
        return
    if not decision.launch:
        raise GO.GoRefused(decision.why, verdict=decision.kind)

    # 4. запис партії — ПЕРЕД першим стартом (як `_remember` для справи)
    rec = BatchRecord(batch_id=new_id(), created=datetime.now().isoformat(timespec="seconds"),
                      budget_total=round(total, 2), fork_low=res.fork_low,
                      fork_high=res.fork_high,
                      dropped=[list(d) for d in convoy.dropped])
    res.batch_id = rec.batch_id
    for q, (_c, p, _s) in zip(res.queues, prepared, strict=True):
        q["session"] = p.session
    rec.queues = res.queues
    save(rec)

    # 5. старт черг. 🔴 Упала одна — пущені НЕ гасимо: вони живі, оплачені й
    # підзвітні; гасити чужими руками те, що вже веде наглядач, — шлях до
    # машини без господаря.
    cases: list[Any] = []
    for q, (conv, p, sub), share, h in zip(res.queues, prepared, shares, hours,
                                           strict=True):
        sub.fork_low, sub.fork_high = p.fork_low, p.fork_high
        sub.budget_usd, sub.max_hours = share, h
        try:
            SUP.start(p, conv, sub, say, budget=share, max_hours=h,
                      max_rents=max_rents, batch=rec.batch_id)
        except GO.GoRefused as exc:
            q["why"] = str(exc)
            for c in sub.cases:
                c.verdict, c.why = "refused", str(exc)
            say("warning", f"⚠ черга {q['queue']} не стартувала: {exc}")
        else:
            q["started"] = True
            res.rented = True
        cases.extend(sub.cases)
        save(rec)
    res.cases = cases
    started = [q for q in res.queues if q["started"]]
    if not started:
        raise GO.GoRefused("жодна черга партії не стартувала: "
                           + "; ".join(q["why"] for q in res.queues))
    if len(started) < len(res.queues):
        res.verdict = "partial_start"
        res.why = (f"пущено {len(started)} з {len(res.queues)} черг партії "
                   f"{rec.batch_id}; що не стартувало — у `queues[].why`")
        return
    res.verdict = "detached"
    res.why = (f"партія {rec.batch_id}: {len(started)} наглядачів пішли у фон, "
               f"кожен орендує свою машину, читає свою чергу й гасить оренду сам")


# ── стан партії ──────────────────────────────────────────────────────────────
def queue_states(rec: BatchRecord) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Стан кожної пущеної черги — у її наглядача, не в нашому записі."""
    from nyshporka.cloud import state as ST
    from nyshporka.cloud import supervised as SUP

    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for q in rec.queues:
        data: dict[str, Any] = {}
        if q.get("started") and q.get("run_ids"):
            st = ST.load(q["run_ids"][0])
            if st is not None and st.supervisor:
                data = SUP.state_of(st)
        out.append((q, data))
    return out


def summary(rows: Sequence[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    """Підсумок партії: витрачено, сторінки, скільки машин ще живі.

    🔴 Витрати невідомої черги не рахуються нулем: `spent_known` каже, по
    скількох чергах сума справжня.
    """
    from nyshporka.cloud import supervised as SUP

    spent = 0.0
    spent_known = 0
    pages_done = 0
    live = 0
    for _q, data in rows:
        budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
        got = M.as_number((budget or {}).get("spent_usd"))
        if got is not None:
            spent += got
            spent_known += 1
        pages_done += sum(int(c.get("pages_done") or 0) for c in data.get("cases") or []
                          if isinstance(c, dict))
        if data and not SUP.finished(data):
            live += 1
    return {"spent_usd": round(spent, 3), "spent_known": spent_known,
            "queues": len(rows), "pages_done": pages_done, "live": live}
