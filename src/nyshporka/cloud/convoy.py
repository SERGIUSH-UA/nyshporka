"""🚛 Захід із кількох справ: N робіт, одна машина, один наглядач.

Черга справ на одній машині дешевша за чергу машин: холодний старт коштує
~5 хвилин оренди плюс час на ринку, і платити його за кожну справу окремо
немає за що. Наглядач це вміє давно (`htr plan --case` повторюваний), тож тут
лише те, що мусить знати НАШ бік: які справи їдуть, що з них поїде на машину,
куди ляже результат і чи можна їм їхати разом.

🔴 Чому контейнер, а не «план із кількох справ». `CloudPlan` живить і тонкий
шлях, де машина наша: одне з'єднання, один віддалений каталог, один pid, один
лог. Зробивши в ньому список справ, ми змусили б переписати найдорожче
перевірену частину пакета заради можливості, якої тонкий шлях усе одно не
дістане. Тому план лишається планом ОДНІЄЇ справи, а захід — контейнером.

🔴 Заходного `run_id` немає, і це рішення. На партію пишеться N записів стану,
кожен зі своїм детермінованим `run_id` і спільним наглядачем. Інакше справа,
пущена в партії, ховалась би під ідентифікатором партії — і повторна команда
`nysh cloud go <та сама справа>` не знайшла б живої роботи, тобто взяла б ДРУГУ
машину під те, що вже читається.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — лише для перевірки типів
    from collections.abc import Callable, Sequence

    from nyshporka.cloud.frames import FramesReport
    from nyshporka.cloud.go import CaseRef
    from nyshporka.cloud.plan import CloudPlan


class ConvoyError(RuntimeError):
    """Справи не можуть їхати разом — із поясненням, чому саме."""


@dataclass(frozen=True)
class Leg:
    """Одна справа заходу: усе, що з'ясовано про неї ДО наглядача."""

    ref: CaseRef
    plan: CloudPlan
    #: Що поїде на машину: оригінальна тека або стиснута копія.
    pack: Path
    #: ЗАВЖДИ оригінал: із нього ріжуться кропи, і саме він має опинитись у
    #: меті прогону після забору.
    source: Path
    frames: FramesReport
    #: Тека готової сегментації, визнаної придатною, або `None`.
    seed: Path | None = None
    #: Покриття кадрів кешем: 0.0 — засіву немає.
    coverage: float = 0.0
    #: Чи везти на машину вже прочитане цією ж моделлю. Тільки тонкий шлях:
    #: відчеплений захід відновлюється зі СВОЇХ точок, а не з наших текстів.
    resume: bool = False
    notes: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """Ім'я прогону — воно ж ім'я теки результату й префікс у сховищі."""
        return self.plan.out_dir.name

    @property
    def mb(self) -> float:
        """Скільки МБ поїде на машину — з тієї теки, яка справді поїде."""
        from nyshporka.cloud.verify import frames_in

        if self.pack == self.source:
            return self.frames.total_mb
        return sum(f.stat().st_size for f in frames_in(self.pack)) / 1e6


@dataclass(frozen=True)
class Convoy:
    """Захід: справи, що їдуть разом на одній машині."""

    legs: tuple[Leg, ...]
    #: Справи, які до заходу не потрапили, і чому: `(що просили, причина)`.
    dropped: tuple[tuple[str, str], ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.legs:
            raise ConvoyError("у заході немає жодної справи")
        # 🔴 Унікальність імен перевіряється ТУТ, а не в наглядача. Він теж її
        # ловить, але вже після заливки — а на партії з тисяч кадрів це
        # чверть години стискання й доставки перед відмовою. Дві теки з
        # однаковим іменем — буденність (`pages`, `spr-1` у різних архівах), і
        # колізія не падає сама собою: вона тихо зливає кадри в один префікс
        # сховища й перезаписує чужий декод.
        self._unique(lambda leg: leg.name, "ім'я прогону")
        self._unique(lambda leg: str(leg.plan.out_dir), "тека результату")
        self._unique(lambda leg: str(leg.plan.run_id), "ідентифікатор заходу")
        roots = {leg.plan.out_dir.parent for leg in self.legs}
        if len(roots) > 1:
            # Корінь виводу в наглядача ОДИН на захід, тож справи з різних
            # просторів разом не їдуть: інакше половина результату лягла б не
            # туди, і виглядало б це як «робота втрачена».
            raise ConvoyError(
                "справи заходу мусять лягати в один корінь результатів, а тут "
                + ", ".join(sorted(str(r) for r in roots)))
        backends = {leg.plan.backend for leg in self.legs}
        if len(backends) > 1:
            raise ConvoyError("справи заходу мусять їхати на один бекенд: "
                              + ", ".join(sorted(backends)))

    def _unique(self, key: Callable[[Leg], str], what: str) -> None:
        seen: dict[str, Leg] = {}
        for leg in self.legs:
            k = key(leg)
            if k in seen:
                raise ConvoyError(
                    f"дві справи заходу мають спільн{'у' if what[0] == 'т' else 'е'} "
                    f"{what} «{k}»: {seen[k].source} і {leg.source}. Разом вони "
                    f"перезаписали б результат одна одної — везіть їх окремо "
                    f"або перейменуйте теку")
            seen[k] = leg

    @property
    def one(self) -> Leg:
        """Єдина справа заходу — там, де кілька не бувають (тонкий шлях)."""
        return self.legs[0]

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(leg.plan.run_id for leg in self.legs)

    @property
    def out_root(self) -> Path:
        return self.legs[0].plan.out_dir.parent

    @property
    def total_mb(self) -> float:
        """Скільки даних поїде разом — СУМА по теках, що справді їдуть."""
        return sum(leg.mb for leg in self.legs)

    @property
    def pages(self) -> int:
        return sum(leg.plan.frames if leg.plan.pages_left is None
                   else max(1, leg.plan.pages_left) for leg in self.legs)

    @property
    def lines_per_page(self) -> float | None:
        """Щільність письма для кошторису — МАКСИМУМ по справах.

        🔴 Наглядач бере одне число на захід. Максимум завищує прогноз часу,
        тобто розширює вилку бюджету — і захід не спиняється на грошах посеред
        роботи. Мінімум чи середнє дали б зупинку на найщільнішій справі, а це
        найдорожчий із можливих результатів: машина відпрацювала, а частина
        роботи лишилась неоплаченою й недочитаною.
        """
        known = [leg.plan.lines_per_page for leg in self.legs if leg.plan.lines_per_page]
        return max(known) if known else None

    @property
    def dense_fleet(self) -> bool:
        """Чи можна класти щільніший флот — лише коли засіяні ВСІ справи.

        🔴 Флот один на всю чергу. Сторінка, якої в кеші немає, рахує геометрію
        повністю, тож одна незасіяна справа задушила б шарди, яким дали вдвічі
        менше ядер.
        """
        from nyshporka.htr.seg import DENSE_FLEET_COVERAGE

        return all(leg.coverage >= DENSE_FLEET_COVERAGE for leg in self.legs)

    @property
    def seeds(self) -> tuple[Path | None, ...]:
        return tuple(leg.seed for leg in self.legs)

    def disk_gb(self) -> int:
        """Диска на всю чергу.

        🔴 Сума БАЙТІВ, а константи один раз. Сума `need.disk_gb` по справах
        додала б запас і середовище рушіїв на кожну зайву справу — десятки
        зайвих гігабайтів, які мовчки відсікають здорові машини з ринку.
        """
        from nyshporka.cloud.supervised import disk_for

        return disk_for(self.total_mb)

    def label(self) -> str:
        """Як захід зветься в людському виводі."""
        first = self.legs[0].name
        return first if len(self.legs) == 1 else f"{first} +{len(self.legs) - 1}"


def of(legs: Sequence[Leg], dropped: Sequence[tuple[str, str]] = ()) -> Convoy:
    """Зібрати захід, перевіривши, що справи можуть їхати разом."""
    return Convoy(tuple(legs), tuple(dropped))
