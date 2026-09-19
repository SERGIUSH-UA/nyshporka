"""💵 Гроші заходу: кошторис, вилка, стелі, рішення «пускати чи питати людину».

Чиста арифметика над числами, які дав бекенд, — без мережі й без машини. Тому
вона окремо: це та частина оренди, яку можна перевірити тестом за мілісекунду,
і та, де помилка в один знак коштує справжніх грошей.

🔴 Жодного вигаданого числа. Ціну години, темп і баланс знає лише бекенд;
чого він не сказав, те лишається `None` і показується людині як «невідомо».
Підставити «типову» ціну означало б ухвалити рішення про оренду на числі, якого
не існує, — і показати його так само впевнено, як справжнє.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Стеля автозапуску без людини, якщо простір не каже іншого.
DEFAULT_AUTOSTART_MAX_USD = 2.0

#: Верх вилки відносно прогнозу ринку. 🔴 ×2 на невідомій щільності не
#: вистачило: сповідний розпис на 164 рядки проти типових 124, кожна п'ята
#: сторінка в стелі рядків — реальна ціна вийшла ×1.96 від прогнозу, і захід
#: зупинився на бюджеті за кілька сторінок до кінця.
FORK_DENSITY_KNOWN = 1.5
FORK_DENSITY_UNKNOWN = 2.5

#: Запас понад верх вилки. Нагляд спиняє захід, щойно витрачене сягне бюджету
#: мінус `STOP_MARGIN_USD`, тож бюджет, рівний верху вилки, спрацьовував би
#: раніше, ніж вилка вичерпана.
BUDGET_MARGIN_USD = 0.10
MIN_BUDGET_USD = 0.50

#: За скільки до бюджету зупинятись. Між «зупинити» й «погасити» ще лежить
#: забір прочитаного, і він теж тарифікується.
STOP_MARGIN_USD = 0.05

#: Стеля годин заходу, хоч би що казав прогноз.
MAX_HOURS_CAP = 14.0
MIN_HOURS = 4.0

#: Ключі кошторису бекенда, які ми читаємо. Будь-якого може не бути.
ESTIMATE_KEYS = ("empty", "reason", "candidates", "gpu", "num_gpus", "cores",
                 "price_usd_h", "pages_per_hour", "hours", "cost_usd",
                 "usd_per_1000", "balance_usd", "lines_per_page")


def as_number(value: object) -> float | None:
    """Число з чужої відповіді або `None`. Не число — теж `None`, не нуль."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            got = float(value.strip())
        except ValueError:
            return None
        return got if math.isfinite(got) else None
    return None


@dataclass(frozen=True)
class Estimate:
    """Кошторис бекенда, як він його дав. Порожні поля — «бекенд не сказав»."""

    empty: bool = False
    reason: str = ""
    candidates: int | None = None
    gpu: str = ""
    num_gpus: int | None = None
    cores: float | None = None
    price_usd_h: float | None = None
    pages_per_hour: float | None = None
    hours: float | None = None
    cost_usd: float | None = None
    usd_per_1000: float | None = None
    balance_usd: float | None = None
    #: Щільність, яку бекенд УРАХУВАВ у темпі. Відлуння `Need.lines_per_page`:
    #: лише воно дозволяє звузити вилку — бекенд, що щільність проігнорував,
    #: рахував на типову, і вужча вилка на його числі була б самообманом.
    lines_per_page: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cost(self) -> float | None:
        """Прогноз витрат: як назвав бекенд, інакше — його ж ціна × його години.

        Добуток двох чисел бекенда — не вигадка, а арифметика над ними; чого
        немає, того не добудовуємо.
        """
        if self.cost_usd is not None:
            return self.cost_usd
        if self.price_usd_h is not None and self.hours is not None:
            return round(self.price_usd_h * self.hours, 4)
        return None

    def as_dict(self) -> dict[str, Any]:
        return {"empty": self.empty, "reason": self.reason,
                "candidates": self.candidates, "gpu": self.gpu,
                "num_gpus": self.num_gpus, "cores": self.cores,
                "price_usd_h": self.price_usd_h,
                "pages_per_hour": self.pages_per_hour, "hours": self.hours,
                "cost_usd": self.cost, "usd_per_1000": self.usd_per_1000,
                "balance_usd": self.balance_usd,
                "lines_per_page": self.lines_per_page}

    def human(self) -> str:
        """Один рядок для людини. Невідоме так і називається."""
        def usd(v: float | None, fmt: str = "{:.2f}") -> str:
            return "невідомо" if v is None else "$" + fmt.format(v)

        if self.empty:
            return f"ринок порожній: {self.reason or 'жодна пропозиція не пройшла'}"
        card = (f"{self.gpu}" + (f"×{self.num_gpus}" if self.num_gpus else "")
                if self.gpu else "карта невідома")
        cores = f"{round(self.cores, 1):g} ядер" if self.cores else "ядра невідомі"
        pph = (f"~{self.pages_per_hour:.0f} стор/год"
               if self.pages_per_hour else "темп невідомий")
        hours = f"~{self.hours:.1f} год" if self.hours is not None else "час невідомий"
        return (f"{card} · {cores} · {usd(self.price_usd_h, '{:.3f}')}/год · "
                f"{pph} · {hours} · прогноз {usd(self.cost)} · "
                f"баланс {usd(self.balance_usd)}"
                + (f" · пропозицій {self.candidates}"
                   if self.candidates is not None else ""))


def parse_estimate(raw: object) -> Estimate:
    """Відповідь `backend.estimate(need)` → `Estimate`. Сміття — порожній кошторис."""
    if not isinstance(raw, dict):
        return Estimate(raw={})
    n_gpu = as_number(raw.get("num_gpus"))
    cand = as_number(raw.get("candidates"))
    return Estimate(
        empty=bool(raw.get("empty")), reason=str(raw.get("reason") or ""),
        candidates=int(cand) if cand is not None else None,
        gpu=str(raw.get("gpu") or ""),
        num_gpus=int(n_gpu) if n_gpu is not None else None,
        cores=as_number(raw.get("cores")), price_usd_h=as_number(raw.get("price_usd_h")),
        pages_per_hour=as_number(raw.get("pages_per_hour")),
        hours=as_number(raw.get("hours")), cost_usd=as_number(raw.get("cost_usd")),
        usd_per_1000=as_number(raw.get("usd_per_1000")),
        balance_usd=as_number(raw.get("balance_usd")),
        lines_per_page=as_number(raw.get("lines_per_page")),
        raw={k: raw[k] for k in ESTIMATE_KEYS if k in raw})


def ask_estimate(backend: object, need: object) -> Estimate | None:
    """Спитати в бекенда кошторис. `None` — бекенд кошторисів не дає.

    Метод `estimate(need) -> dict` необов'язковий і кличеться через `getattr`:
    контракт бекенда (`cloud.base`) його не вимагає, і бекенд своєї машини його
    не має. 🔴 Нічого не орендує — це обіцянка плагіна, на яку спирається
    `nysh cloud plan`; сюди ж вона винесена словом, бо перевірити її звідси нічим.
    """
    fn = getattr(backend, "estimate", None)
    if not callable(fn):
        return None
    return parse_estimate(fn(need))


def budget_fork(cost: float, *, density_known: bool) -> tuple[float, float]:
    """(низ, верх) вилки витрат.

    Низ — прогноз. Верх — прогноз зі множником на щільність письма, округлений
    УГОРУ до п'яти центів, плюс запас на поріг зупинки, не нижче пів долара.
    """
    factor = FORK_DENSITY_KNOWN if density_known else FORK_DENSITY_UNKNOWN
    # `round(…, 6)` перед `ceil`: 0.30 × 1.5 × 20 у двійковій арифметиці дає
    # 9.000000000000002, і стеля чесно округлювала б «рівно 45 центів» до 50.
    high = max(MIN_BUDGET_USD,
               math.ceil(round(cost * factor * 20, 6)) / 20 + BUDGET_MARGIN_USD)
    return round(cost, 2), round(high, 2)


def max_hours_for(hours: float) -> float:
    """Стеля допустимого часу: утричі від прогнозу плюс година на ринок і сетап."""
    return float(min(MAX_HOURS_CAP, max(MIN_HOURS, math.ceil(hours * 3 + 1))))


@dataclass(frozen=True)
class Decision:
    """Пускати чи ні — і чому, одним реченням."""

    launch: bool
    #: `ok` | `no_credit` | `needs_confirm`
    kind: str
    why: str


def decide_launch(high: float, balance: float | None, ceiling: float,
                  confirm: bool) -> Decision:
    """Чи стартувати без людини.

    🔴 Брак балансу перевіряється ПЕРШИМ і `--confirm` його не перебиває:
    дозвіл людини знімає стелю автозапуску, а не арифметику. Захід, на який
    грошей не вистачає, обірветься посередині — з оплаченою заливкою й без
    результату.

    Невідомий баланс (`None`) не блокує: бекенд міг його просто не назвати, і
    відмова тут замкнула б оренду для всіх таких бекендів. Стелі заходу діють
    однаково.
    """
    if balance is not None and balance < high:
        return Decision(False, "no_credit",
                        f"на рахунку ${balance:.2f}, а верх вилки ${high:.2f} — "
                        f"поповніть баланс у провайдера оренди")
    if high <= ceiling:
        return Decision(True, "ok",
                        f"верх вилки ${high:.2f} ≤ стелі автозапуску ${ceiling:.2f}")
    if confirm:
        return Decision(True, "ok",
                        f"верх вилки ${high:.2f} понад стелю ${ceiling:.2f}, "
                        f"дозвіл --confirm")
    return Decision(False, "needs_confirm",
                    f"верх вилки ${high:.2f} понад стелю автозапуску "
                    f"${ceiling:.2f} — старт лише з --confirm від людини")


# ── стеля автозапуску простору ───────────────────────────────────────────────
def autostart_ceiling() -> float:
    """Стеля автозапуску з `<простір>/config/cloud.json` → `rent.autostart_max_usd`.

    Лежить поруч з описом машин і сховища: це той самий клас налаштувань —
    знаряддя цього простору, не властивість пакета. Немає або нечитабельне —
    типові два долари, не виняток: стеля мусить діяти завжди.
    """
    from nyshporka.cloud.ssh import hosts_path
    from nyshporka.utils.atomic import read_json

    try:
        raw = read_json(hosts_path(), default={})
    except Exception:
        return DEFAULT_AUTOSTART_MAX_USD
    rent = raw.get("rent") if isinstance(raw, dict) else None
    got = as_number(rent.get("autostart_max_usd")) if isinstance(rent, dict) else None
    return got if got is not None and got >= 0 else DEFAULT_AUTOSTART_MAX_USD


def set_autostart_ceiling(usd: float) -> float:
    """Записати стелю автозапуску, не чіпаючи решти файла."""
    from nyshporka.cloud.ssh import update_config

    if usd < 0 or not math.isfinite(usd):
        raise ValueError("стеля мусить бути невід'ємним числом")
    value = round(float(usd), 2)

    def mutate(data: dict[str, Any]) -> None:
        rent = dict(data["rent"]) if isinstance(data.get("rent"), dict) else {}
        rent["autostart_max_usd"] = value
        data["rent"] = rent

    update_config(mutate)
    return value
