"""📜 Рецепт корпусу й параметри трену — дані, а не літерали в коді.

Рецепт каже, з яких джерел і в яких пропорціях збирається корпус, як
відбирається val, як ріжуться кропи і з якими гіперпараметрами йде трен.
Пакет везе два узагальнені рецепти (`train/data/recipes.yaml`); простір може
додати або перекрити свої у `config/train/recipes.yaml`. Так корпус
відтворюється з імені рецепта, а не з пам'яті того, хто його збирав.

🔴 `TrainParams` — дзеркало валідації джоби трену (той самий перелік ключів,
ті самі межі): один параметр, забутий тут, мовчки поїхав би в раннер
дефолтом і змінив би результат без сліду в команді. Тест тримає перелік.

🔴 Частка (`share: "8%"`) замість числа копій — для ручних міток так і треба:
фіксоване число підбиралось під двісті рядків, і коли їх стає шістсот, ті
самі ×35 дають уже не 8% батчів, а 20%. Але частка перераховується в ЦІЛЕ
число копій, і система сходинкова: 8% і 9% дають той самий `rep`, а 9.5%
стрибає вдвічі. Тому `resolve_reps` попереджає, коли ±0.5 пп змінює `rep`, і
план друкує `rep` поруч із замовленою і фактичною часткою.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from nyshporka.core.workspace import Workspace, WorkspaceError, workspace
from nyshporka.train import layout as L

DEFAULT_BASE = "hub:Hukyl/parseq-s-cyrillic-handwritten"
PACKAGE_RECIPES = Path(__file__).resolve().parent / "data" / "recipes.yaml"


class RecipeError(ValueError):
    """Рецепт не читається, не існує або суперечить сам собі."""


# ── параметри трену ──────────────────────────────────────────────────────────
class TrainParams(BaseModel):
    """Гіперпараметри, які їдуть у раннер як `params.json`.

    Дефолти — рецепт, доведений на серії тренів Писаря (v11–v17): `patience`
    м'який, `min_delta` малий і `min_epochs` як підлога, бо епоху обирає не
    val, а holdout ПОТІМ, локально; ранній зупинці лишається одна робота — не
    платити за завідомо мертві епохи.
    """

    epochs: int = 16
    batch: int = 64
    lr: float = 3e-4
    warmup_pct: float = 0.075
    weight_decay: float = 0.0
    val_frac: float = 0.08
    img_h: int = 0
    img_w: int = 0
    max_label_length: int = 0
    augment: str = "basic"
    workers: int = 0
    amp: bool = True
    amp_dtype: str = "auto"
    ddp: str = "auto"
    ddp_find_unused: bool = False
    ddp_timeout_min: float = 15.0
    lr_scale: str = "sqrt"
    compile: bool = False
    patience: int = 4
    #: 🔴 Підлога ранньої зупинки: на реальній кривій найкращий val прийшов на
    #: ep9 ПІСЛЯ провалу на ep8 — будь-яке терпіння, що спрацювало б раніше,
    #: зрізало б саме ту епоху, заради якої все й робиться.
    min_epochs: int = 9
    #: 🔴 0.0005, не 0.002: з більшим порогом епоха, що покращила val менше
    #: за поріг, каралась двічі — і ваги не збереглись, і лічильник тікав.
    min_delta: float = 0.0005
    save_epochs: bool = True
    charset_mode: str = "extend"
    charset_extra: str = "ѲѳѢѣЪъЫы"
    charset_min_freq: int = 20
    seed: int = 42
    limit: int = 0
    val_limit: int = 0
    profile: bool = True
    max_steps: int = 0
    wall_limit_h: float = 11.0
    pretrained: str = DEFAULT_BASE
    pretrained_dataset: str = ""
    resume: bool = False
    resume_dataset: str = ""

    @field_validator("charset_mode")
    @classmethod
    def _cm(cls, v: str) -> str:
        if v not in ("keep", "extend"):
            raise ValueError(f"charset_mode: keep|extend, а не {v!r}")
        return v

    @field_validator("augment")
    @classmethod
    def _aug(cls, v: str) -> str:
        if v not in ("basic", "none"):
            raise ValueError(f"augment: basic|none, а не {v!r}")
        return v

    @field_validator("amp_dtype")
    @classmethod
    def _amp(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("auto", "fp16", "bf16", "fp32"):
            raise ValueError("amp_dtype: auto|fp16|bf16|fp32")
        return v

    @field_validator("lr_scale")
    @classmethod
    def _lrs(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("sqrt", "linear", "none"):
            raise ValueError("lr_scale: sqrt|linear|none")
        return v

    @field_validator("ddp")
    @classmethod
    def _ddp(cls, v: str) -> str:
        v = str(v).strip().lower()
        if v not in ("auto", "on", "off") and not v.isdigit():
            raise ValueError("ddp: auto|on|off|<кількість карт>")
        return v

    @model_validator(mode="after")
    def _ranges(self) -> TrainParams:
        if self.batch < 1 or self.epochs < 1:
            raise ValueError("batch і epochs мають бути ≥ 1")
        if not 0.0 <= self.val_frac < 0.9:
            raise ValueError("val_frac у [0, 0.9)")
        if self.wall_limit_h < 0 or self.patience < 0 or self.min_epochs < 0:
            raise ValueError("wall_limit_h, patience, min_epochs ≥ 0")
        if self.min_epochs > self.epochs:
            raise ValueError(f"min_epochs ({self.min_epochs}) > epochs ({self.epochs})")
        if not 0.0 <= self.warmup_pct <= 1.0:
            raise ValueError("warmup_pct у [0, 1]")
        if self.charset_min_freq < 1 or self.ddp_timeout_min <= 0 or self.lr <= 0:
            raise ValueError("charset_min_freq ≥ 1, ddp_timeout_min > 0, lr > 0")
        if self.min_delta < 0 or min(self.limit, self.val_limit, self.max_steps) < 0:
            raise ValueError("min_delta, limit, val_limit, max_steps ≥ 0")
        if self.pretrained == "local" and not self.pretrained_dataset:
            raise ValueError("pretrained=local потребує pretrained_dataset")
        if self.resume and not self.resume_dataset:
            raise ValueError("resume=true потребує resume_dataset")
        return self

    def as_params(self) -> dict[str, Any]:
        """Словник для раннера — усі ключі, явно, без дефолтів «десь там»."""
        return self.model_dump()


#: Ключі, які знає валідація джоби трену. Тест звіряє з `TrainParams`.
JOB_PARAM_KEYS = frozenset({
    "dataset", "pretrained_dataset", "pretrained", "resume", "resume_dataset",
    "charset_mode", "charset_extra", "charset_min_freq", "epochs", "batch", "lr",
    "warmup_pct", "weight_decay", "val_frac", "img_h", "img_w", "max_label_length",
    "augment", "workers", "amp", "amp_dtype", "ddp", "ddp_find_unused",
    "ddp_timeout_min", "lr_scale", "compile", "patience", "min_epochs", "min_delta",
    "save_epochs", "modal_volume", "cpu", "memory", "seed", "limit", "val_limit",
    "profile", "max_steps", "wall_limit_h",
})
#: Ключі, що належать обчисленням, а не рецепту.
COMPUTE_KEYS = frozenset({"dataset", "modal_volume", "cpu", "memory"})


# ── рецепт корпусу ───────────────────────────────────────────────────────────
class MixEntry(BaseModel):
    """Джерело в корпусі: стеля рядків і кратність (числом або часткою)."""

    cap: int = 0
    rep: int | None = None
    share: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> MixEntry:
        if (self.rep is None) == (self.share is None):
            raise ValueError("у джерела має бути рівно одне з rep | share")
        if self.share is not None:
            _ = share_value(self.share)
        if self.rep is not None and self.rep < 1:
            raise ValueError("rep ≥ 1")
        return self


def share_value(s: str) -> float:
    try:
        v = float(str(s).rstrip("%").strip()) / 100.0
    except ValueError:
        raise ValueError(f"частка має вигляд «8%», а не {s!r}") from None
    if not 0 < v < 1:
        raise ValueError(f"частка {s!r} поза (0, 100%)")
    return v


class PseudoOpts(BaseModel):
    drop_conf: list[str] = Field(default_factory=lambda: ["low"])
    conf_weight: dict[str, float] = Field(default_factory=dict)
    #: Друк — понад цю кратність не береться; текст вважається друком, коли
    #: трапляється у `print_spread` і більше РІЗНИХ наборів.
    max_repeat: int = 3
    hand_repeat: int = 10
    print_spread: int = 4


class ValOpts(BaseModel):
    #: 🔴 СИМВОЛІВ, не рядків: CER корпусний, вагу в ньому визначає довжина.
    quota_chars: dict[str, int] = Field(default_factory=lambda: {"gt": 3000})
    min_len: int = 12


class CropOpts(BaseModel):
    height: int = 64
    max_width: int = 1024


class Recipe(BaseModel):
    name: str
    note: str = ""
    mix: dict[str, MixEntry]
    pseudo: PseudoOpts = Field(default_factory=PseudoOpts)
    val: ValOpts = Field(default_factory=ValOpts)
    crop: CropOpts = Field(default_factory=CropOpts)
    train: TrainParams = Field(default_factory=TrainParams)
    base: str = DEFAULT_BASE

    @model_validator(mode="after")
    def _shares(self) -> Recipe:
        total = sum(share_value(m.share) for m in self.mix.values() if m.share)
        if total >= 1.0:
            raise ValueError(f"частки джерел дають ≥100% ({total:.0%})")
        return self


class RecipeBook(BaseModel):
    version: int = 1
    recipes: dict[str, Recipe] = Field(default_factory=dict)
    smoke: dict[str, Any] = Field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        got = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RecipeError(f"{path}: {exc}") from None
    if not isinstance(got, dict):
        raise RecipeError(f"{path}: очікую словник, а не {type(got).__name__}")
    return got


def _parse_book(raw: dict[str, Any], where: str) -> RecipeBook:
    recipes: dict[str, Recipe] = {}
    for name, body in (raw.get("recipes") or {}).items():
        if not isinstance(body, dict):
            raise RecipeError(f"{where}: рецепт «{name}» — не словник")
        try:
            recipes[str(name)] = Recipe(name=str(name), **body)
        except ValueError as exc:
            raise RecipeError(f"{where}: рецепт «{name}»: {exc}") from None
    return RecipeBook(version=int(raw.get("version") or 1), recipes=recipes,
                      smoke=dict(raw.get("smoke") or {}))


def load_book(ws: Workspace | None = None) -> RecipeBook:
    """Пакетні рецепти + рецепти простору (ті перекривають за іменем)."""
    book = _parse_book(_load_yaml(PACKAGE_RECIPES), str(PACKAGE_RECIPES))
    try:
        w = ws if ws is not None else workspace()
        own = L.config_root(w) / "recipes.yaml"
    except WorkspaceError:
        own = None
    if own is not None and own.is_file():
        mine = _parse_book(_load_yaml(own), str(own))
        book.recipes.update(mine.recipes)
        if mine.smoke:
            book.smoke = mine.smoke
    return book


def get_recipe(name: str, *, smoke: bool = False, ws: Workspace | None = None,
               overrides: dict[str, Any] | None = None) -> Recipe:
    book = load_book(ws)
    if name not in book.recipes:
        raise RecipeError(f"рецепту «{name}» немає; є: {', '.join(sorted(book.recipes))}")
    rec = book.recipes[name]
    params = rec.train.model_dump()
    if smoke:
        params.update(book.smoke)
    if overrides:
        unknown = set(overrides) - set(TrainParams.model_fields)
        if unknown:
            raise RecipeError(f"невідомі параметри трену: {', '.join(sorted(unknown))}")
        params.update(overrides)
    # Підлога ранньої зупинки не може бути вищою за стелю: хто явно вкоротив
    # трен (`--epochs 3`, димовий прогін), той не мусить окремо згадувати, що
    # рецепт тримає підлогу на 9 епохах. Опускаємо мовчки, бо обидва числа
    # видно в плані.
    if int(params.get("min_epochs", 0)) > int(params.get("epochs", 1)):
        params["min_epochs"] = int(params["epochs"])
    try:
        train = TrainParams(**params)
    except ValueError as exc:
        raise RecipeError(f"параметри трену: {exc}") from None
    return rec.model_copy(update={"train": train})


# ── частки → кратності ───────────────────────────────────────────────────────
def resolve_reps(mix: dict[str, MixEntry], counts: dict[str, int]) -> tuple[dict[str, int], list[str]]:
    """`rep` для кожного джерела з наявними рядками; частки → ціле число копій.

    Хай F — батч-рядки джерел із фіксованим rep, s_i — бажані частки решти.
    Тоді T = F / (1 − Σs_i), rep_i = round(s_i·T / N_i). Частка тримається
    сама, скільки б рядків не додалось у ручні мітки.

    Повертає й попередження про сходинку: якщо ±0.5 пп до замовленої частки
    міняє `rep`, замовлена і фактична частки помітно різні — і план мусить
    показати `rep`, а не відсоток.
    """
    present = {s: n for s, n in counts.items() if n > 0 and s in mix}
    fixed = {s: int(mix[s].rep or 0) for s in present if mix[s].rep is not None}
    shares = {s: share_value(mix[s].share or "") for s in present if mix[s].share is not None}
    out = dict(fixed)
    warnings: list[str] = []
    if not shares:
        return out, warnings
    F = sum(present[s] * r for s, r in fixed.items())
    if F == 0:
        for s in shares:
            out[s] = 1
        warnings.append("жодного джерела з фіксованим rep не знайдено — частки не мають "
                        "знаменника, усім призначено rep=1")
        return out, warnings
    denom = 1.0 - sum(shares.values())
    T = F / denom

    def rep_for(frac: float, n: int) -> int:
        return max(1, round(frac * T / n))

    for s, frac in shares.items():
        n = max(1, present[s])
        r = rep_for(frac, n)
        out[s] = r
        lo, hi = rep_for(max(0.001, frac - 0.005), n), rep_for(frac + 0.005, n)
        if lo != r or hi != r:
            actual = r * n / (F + sum(out[x] * present[x] for x in shares))
            warnings.append(f"{s}: частка {frac:.1%} дає rep={r}, але ±0.5 пп змінює його "
                            f"({lo}…{hi}) — сходинка округлення; фактична частка {actual:.1%}. "
                            f"Звіряти rep, не відсоток")
    return out, warnings
