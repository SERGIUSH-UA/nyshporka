"""🧮 Скільки шардів, скільки годин, скільки грошей — чиста арифметика.

Ні мережі, ні диска, ні машини: сюди приходять числа заліза, звідси виходить
план. Тому це єдина частина хмарного прогону, яку можна перевірити тестом за
мілісекунду — і саме тому вона окремо.

🔴 Головне, що ця арифметика знає про читання рукопису: **воно впирається в
ядра, а не в карту**. Профіль часу сторінки — близько 74% на геометрії рядків,
яку рахує процесор, і близько 17% на самій мережі розпізнавання. Наслідок
зворотний до інтуїції: сторінка на потужній карті з двома ядрами на шард іде
вдвічі повільніше, ніж на слабкій карті з шістьма. Відеопам'ять не прискорює
нічого — вона лише обмежує, скільки шардів улізе.

🔴 Ємність карт рахується ПОКАРТКОВО. Наївне «сума пам'яті × запас ÷ на шард»
щедріше за чесне: дві карти по 8 ГБ дають у ньому п'ять шардів замість
чотирьох, і зайвий шард не сповільнює прогін, а завалює його — сторінки
падають в OOM, шард виходить із нульовим кодом, а підсумок мовчить.

⚠ Числа профілю — заміри, а не константи природи. Інший рушій, інша
роздільність кадру, інша щільність письма дадуть інші; тому вони зібрані в
іменований профіль, який можна замінити, а не розсипані по коду.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

#: Скільки сторінок за годину дає одне ядро. Заміри розкидані в межах 22-45
#: залежно від щільності письма; беремо нижню межу — план, який недооцінює
#: швидкість, помиляється в бік «встигли», а протилежний обриває роботу.
PAGES_PER_HOUR_PER_CORE = 35.0

#: Стеля одного шарда. ⚠ Майже не залежить від того, яка карта: шард упирається
#: в послідовні фази, а не в обчислення.
PAGES_PER_HOUR_PER_SHARD = 250.0

#: Стеля всього конвеєра — далі впирається вже читання й запис.
PIPELINE_MAX_PAGES_PER_HOUR = 4500.0


@dataclass(frozen=True)
class EngineProfile:
    """Заміряна поведінка рушія. Замінний, а не зашитий."""

    name: str = "typical"
    pages_per_hour_per_core: float = PAGES_PER_HOUR_PER_CORE
    pages_per_hour_per_shard: float = PAGES_PER_HOUR_PER_SHARD
    pipeline_max_pages_per_hour: float = PIPELINE_MAX_PAGES_PER_HOUR
    #: Скільки відеопам'яті просить шард із двома голосами.
    gb_per_shard: float = 2.5
    #: Менше цього ядер на шард — шарди починають заважати один одному.
    min_cores_per_shard: float = 2.0
    #: Скільки пам'яті карти лишаємо драйверу й піковим сторінкам.
    vram_headroom: float = 0.90
    max_shards: int = 32
    #: Холодний старт: розпакувати кадри, поставити рушій, прогріти карту.
    #: Не залежить від обсягу — тому й вирішує долю МАЛЕНЬКОЇ справи.
    overhead_sec_cold: int = 480
    overhead_sec_warm: int = 45


DEFAULT_PROFILE = EngineProfile()


@dataclass(frozen=True)
class Sizing:
    """Скільки процесів ставити — і що саме заважає поставити більше."""

    shards: int
    shards_per_gpu: int
    pages_per_hour: float
    #: `ядра` | `шарди` | `конвеєр` — що є вузьким місцем. Показується людині:
    #: без цього рядка «чому так повільно» не має відповіді, і наступний крок
    #: вгадується, а не обирається.
    limited_by: str
    gb_per_shard: float
    cores: float
    vram_gb_min: float
    gpus: int
    #: Чому шардів не більше: `пам'ять карти` | `ядра` | `стеля профілю`.
    capped_by: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"shards": self.shards, "shards_per_gpu": self.shards_per_gpu,
                "pages_per_hour": round(self.pages_per_hour, 1),
                "limited_by": self.limited_by, "capped_by": self.capped_by,
                "gb_per_shard": self.gb_per_shard, "cores": self.cores,
                "vram_gb_min": self.vram_gb_min, "gpus": self.gpus}


class SizingError(ValueError):
    """Машина не годиться — з поясненням, чого саме бракує."""


def plan_sizing(*, cores: float, vram_gb_min: float, gpus: int = 1,
                profile: EngineProfile = DEFAULT_PROFILE,
                gb_per_shard: float | None = None,
                shards: int = 0, max_shards: int = 0) -> Sizing:
    """Скільки шардів витримає ця машина.

    `shards` — явне число від людини. 🔴 Воно перебиває розрахунок, але НЕ
    стелю: людина краще за нас знає щільність своєї книги (розворот на дві
    сторінки бере вдвічі більше пам'яті, і жодна проба заліза цього не бачить),
    але дозволити їй поставити більше, ніж фізично влізе, означає поміняти
    повільний прогін на завалений.
    """
    gb = float(gb_per_shard or profile.gb_per_shard)
    if gb <= 0:
        raise SizingError("пам'ять на шард мусить бути додатною")
    if cores <= 0:
        raise SizingError("не виміряно жодного ядра — плану немає з чого будувати")

    # 🔴 Покартково: ємність найменшої карти × число карт, а не сума пам'яті.
    per_gpu = int(vram_gb_min * profile.vram_headroom / gb) if vram_gb_min > 0 else 0
    by_vram = max(per_gpu, 0) * max(gpus, 1)
    by_cores = int(cores / profile.min_cores_per_shard)
    ceiling = max_shards or profile.max_shards

    # Без карти читання теж іде — просто повільніше; тоді пам'ять не обмежує.
    limits: list[tuple[int, str]] = [(by_cores, "ядра"), (ceiling, "стеля профілю")]
    if vram_gb_min > 0:
        limits.append((by_vram, "пам'ять карти"))
    cap, capped_by = min(limits, key=lambda p: p[0])
    cap = max(cap, 1)

    chosen = min(shards, cap) if shards > 0 else cap
    if shards > 0 and chosen < shards:
        capped_by = f"{capped_by} (просили {shards})"

    per_gpu_real = max(1, chosen // max(gpus, 1)) if vram_gb_min > 0 else chosen
    speeds = [
        (profile.pages_per_hour_per_core * cores, "ядра"),
        (profile.pages_per_hour_per_shard * chosen, "шарди"),
        (profile.pipeline_max_pages_per_hour, "конвеєр"),
    ]
    pph, limited_by = min(speeds, key=lambda p: p[0])
    return Sizing(shards=chosen, shards_per_gpu=per_gpu_real,
                  pages_per_hour=pph, limited_by=limited_by, gb_per_shard=gb,
                  cores=cores, vram_gb_min=vram_gb_min, gpus=max(gpus, 1),
                  capped_by=capped_by)


def predict_hours(pages: int, sizing: Sizing, *, warm: bool = False,
                  profile: EngineProfile = DEFAULT_PROFILE) -> float:
    """Скільки годин це триватиме, разом із холодним стартом.

    🔴 Накладні враховуються завжди. Саме вони роблять невигідним хмарний прогін
    маленької справи: вісім хвилин підготовки не залежать від того, тридцять
    там кадрів чи три тисячі, і на тридцяти вони і є весь захід.
    """
    if pages <= 0 or sizing.pages_per_hour <= 0:
        return 0.0
    overhead = profile.overhead_sec_warm if warm else profile.overhead_sec_cold
    return round(pages / sizing.pages_per_hour + overhead / 3600.0, 2)


def predict_cost(pages: int, sizing: Sizing, price_usd_h: float | None, *,
                 warm: bool = False,
                 profile: EngineProfile = DEFAULT_PROFILE) -> float | None:
    """Скільки це коштуватиме. `None` — машина безплатна або ціна невідома."""
    if not price_usd_h:
        return None
    return round(predict_hours(pages, sizing, warm=warm, profile=profile)
                 * float(price_usd_h), 4)


def with_gb_per_shard(sizing: Sizing, gb: float, *,
                      profile: EngineProfile = DEFAULT_PROFILE) -> Sizing:
    """Перерахувати під іншу пам'ять на шард, не втрачаючи заміру заліза."""
    return plan_sizing(cores=sizing.cores, vram_gb_min=sizing.vram_gb_min,
                       gpus=sizing.gpus, profile=replace(profile, gb_per_shard=gb))
