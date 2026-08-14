r"""Рядок реєстру справ і зв'язок «прогін → справа».

Поля рядка діляться на п'ять шарів за походженням, і кожен шар має власну ознаку
«чи взагалі був»: `htr_*` порожні означають «декоду не було», а не «декод порожній».
Саме цю різницю губила ручна інвентаризація.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Стан матеріалу на диску. `ordered` — картка справи (`_source.json`) без жодного
#: кадру: справу знайдено й описано, але не завантажено. Такі теки не потрапляли
#: в бібліотеку взагалі (вона вимагає зображень), тож «замовлене» було невидиме.
STATES = ("ordered", "partial", "on_disk")

#: Три голоси HTR за іменем моделі. Письмо каже ПРЕФІКС, не розширення:
#: `skryba_*.mlmodel` — латинка, `diak_*.mlmodel` — кирилиця, обидва kraken.
VOICES = ("pysar", "diak", "skryba")


@dataclass
class RunLink:
    """Прив'язка одного прогону (HTR або fuzzy) до справи.

    `key=None` — прогін не прив'язався; це стан реєстру, а не помилка збірки:
    такі рядки видно через `nysh cases orphans`. Мовчазне відкидання дало б
    хибне «все прив'язано» — та сама пастка, що й мовчазний нуль у пошуку.
    """

    run: str                       # ім'я теки прогону / ключ clan_hunt
    key: str | None = None         # "DAHMO/315/7864"
    resolved_by: str = ""          # case_dir | run_name | derived | override | none
    note: str = ""                 # чому саме так (для overrides і спірних випадків)
    case_dir: str = ""             # як записано в меті прогону (буває шлях боксу)


@dataclass
class CaseRow:
    """Одна справа з усіма шарами обробки."""

    # ── опис (nyshporka.library) ────────────────────────────────────────────────
    key: str
    #: `case` — архівна справа; `bundle` — одиниця роботи, справою НЕ є (вибірка
    #: по селу з багатьох плівок). Кадри збірки перетинаються з кадрами її справ,
    #: тож у підсумках вони рахуються окремо, інакше сторінки подвоїлись би.
    kind: str = "case"
    shifra: str = ""
    repo: str | None = None
    repo_label: str | None = None
    fond: str | None = None
    opys: str | None = None
    spr: str | None = None
    title: str = ""
    doc_type: str = ""
    record_types: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    place_raw: str = ""
    #: Розібрана географія. `place_raw` лишається як є — розбір його не замінює,
    #: бо в ньому бувають застереження дослідника («⚠ НЕ Вербка Волоська»).
    settlement: str = ""            # головне поселення справи
    settlements: list[str] = field(default_factory=list)
    uezd: str = ""                  # головний повіт
    uezds: list[str] = field(default_factory=list)
    guberniya: str = ""
    place_id: str | None = None     # PL* канону, якщо збіг певний
    geo_blob: str = ""              # нормалізований рядок для пошуку (кир.↔лат.)
    parish: str | None = None
    script: str = ""
    desc_source: str = "code"

    # ── матеріал на диску ───────────────────────────────────────────────────
    path: str | None = None
    extra_paths: list[str] = field(default_factory=list)
    state: str = "ordered"
    frames: int = 0
    expected: int | None = None    # скільки кадрів обіцяє сайдкар (`frames`)

    # ── HTR (reports/htr/*/_htr_meta.json) ──────────────────────────────────
    htr_pysar: bool = False
    htr_pysar_model: str = ""
    htr_pysar_pages: int = 0
    htr_diak: bool = False
    htr_diak_model: str = ""
    htr_diak_pages: int = 0
    htr_skryba: bool = False
    htr_skryba_model: str = ""
    htr_skryba_pages: int = 0
    htr_runs: list[str] = field(default_factory=list)
    htr_pages_max: int = 0
    htr_updated: str = ""

    # ── fuzzy-пошук роду (data/clan_hunt/state.json) ────────────────────────
    fuzzy_scanned: str = ""        # дата останнього scan
    fuzzy_model: str = ""
    fuzzy_pages: int = 0           # сторінок у прогоні, який шукали
    fuzzy_hits: int = 0            # сильних сторінок-кандидатів
    fuzzy_reviewed: int = 0        # з них розібрано оком (вердикти)
    fuzzy_swept: bool = False      # позначено як прочесане суцільним заходом
    fuzzy_runs: list[str] = field(default_factory=list)

    # ── канон ───────────────────────────────────────────────────────────────
    canon_source_id: str | None = None
    canon_facts: int = 0
    canon_persons: int = 0
    canon_scans: int = 0           # згадані аркуші: citations.page ∪ media[]

    # ── око (data/pages/**) ─────────────────────────────────────────────────
    pages_noted: int = 0
    pages_full: int = 0

    # ── людські рішення ─────────────────────────────────────────────────────
    verdict: str = ""              # no_clan | clan_found | recheck
    verdict_note: str = ""
    curated: bool = False
    group: str | None = None
    why: str | None = None

    # ── похідні ознаки (рахуються при збірці, зберігаються заради фільтрів) ──
    htr_stage: str = "none"        # none | partial | pysar | diak | both
    fuzzy_stage: str = "none"      # none | scanned | swept | reviewed

    @property
    def htr_coverage(self) -> float:
        """Частка сторінок справи, покритих найповнішим прогоном (0..1).

        Ловить обірвані прогони: 11817 має 1271 сторінку декоду на 1297 кадрів,
        і без цього числа справа виглядала б готовою.
        """
        if not self.frames or not self.htr_pages_max:
            return 0.0
        return min(1.0, self.htr_pages_max / self.frames)
