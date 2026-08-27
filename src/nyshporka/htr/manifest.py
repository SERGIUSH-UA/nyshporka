"""🖋 Маніфест рушіїв читання — читання `engines.yaml`.

Тут лише розбір і питання до маніфесту. Створення середовища — `htr/env.py`,
сам прогін — `htr/runner.py` (той їде під іншим інтерпретатором і не імпортує
нічого з пакета).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BUILTIN = Path(__file__).resolve().parent / "data" / "engines.yaml"

#: Межа між іменем пакета й рештою pip-специфікації.
#: `@` тут перший навмисно: у формі PEP 508 (`strhub @ git+https://…`) ім'я
#: стоїть ЛІВОРУЧ від нього, і різати спершу за версією означало б віддати
#: цілий рядок разом з URL.
_SPEC_BREAK = ("@", "==", ">=", "<=", "~=", "!=", ">", "<", "[", ";")


def dist_name(spec: str) -> str:
    """Ім'я пакета з pip-специфікації: `kraken==7.0.2` → `kraken`.

    🔴 Різати мусить ОДНА функція. Доти цей вираз стояв копією в
    `env.inspect`, а `env.setup` замість нього шукав ім'я підрядком — і саме
    розбіжність двох способів відповісти на одне питання дала тиху ваду:
    пакет, названий у звіті, не знаходився у власній специфікації.

    ⚠ Для git-специфікації БЕЗ форми PEP 508 (`git+https://…` без `ім'я @`)
    імені в рядку немає взагалі, і функція чесно поверне сам рядок: вигадати
    його нема з чого. Такі записи мають ім'я окремим полем у `vcs_packages`.
    """
    out = str(spec).strip()
    for mark in _SPEC_BREAK:
        out = out.split(mark)[0]
    return out.strip()


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    kind: str          # kraken | parseq
    script: str        # latin | cyrillic
    model_glob: str
    note: str = ""


@dataclass(frozen=True)
class Patch:
    id: str
    module: str
    verify: str
    tested_on: str
    requires_cuda: bool = False
    gain: str = ""


@dataclass(frozen=True)
class BaseModel:
    id: str
    doi: str
    filename: str
    note: str = ""


@dataclass(frozen=True)
class Manifest:
    python: str
    packages: tuple[str, ...]
    vcs_packages: tuple[dict[str, str], ...]
    torch_default: tuple[str, ...]
    cuda_index: str
    cuda_matrix: tuple[dict[str, str], ...]
    engines: tuple[Engine, ...] = ()
    patches: tuple[Patch, ...] = ()
    base_models: tuple[BaseModel, ...] = ()

    # ── питання до маніфесту ─────────────────────────────────────────────────
    def engine_for_model(self, filename: str) -> Engine | None:
        """Модель → рушій, за іменем файлу.

        🔴 Розширення каже рушій (`.mlmodel` → kraken, `.pt` → parseq), а
        префікс імені — письмо. Тобто `.mlmodel` буває двох письм, і вибір «за
        розширенням» без префікса поставив би на латинську справу кириличну
        модель. Невідповідність рушія письму дає тихе сміття: текст виходить,
        впевненість не падає, і виглядає це як погана якість сканів.
        """
        from fnmatch import fnmatch

        name = Path(filename).name
        for e in self.engines:
            if fnmatch(name, e.model_glob):
                return e
        return None

    def kind_for_suffix(self, suffix: str) -> str | None:
        """Рушій за самим лише розширенням — коли ім'я нічого не каже."""
        s = suffix.lower()
        if s in (".mlmodel",):
            return "kraken"
        if s in (".pt", ".ckpt", ".pth"):
            return "parseq"
        return None

    def engines_for_script(self, script: str) -> tuple[Engine, ...]:
        return tuple(e for e in self.engines if e.script == script)

    def cuda_tag(self, capability: str) -> str | None:
        """Compute capability картки → тег колеса torch (`cu126`).

        Порожньо, якщо карта поза відомими межами: краще лишити CPU-збірку, ніж
        поставити колесо, яке не запуститься. Мовчазний CPU повільний, але
        робочий; неправильний CUDA-білд не працює взагалі.
        """
        try:
            cap = float(capability)
        except (TypeError, ValueError):
            return None
        for row in self.cuda_matrix:
            lo, hi = float(row["min_capability"]), float(row["max_capability"])
            if lo <= cap <= hi:
                return str(row["tag"])
        return None

    def cuda_index_url(self, tag: str) -> str:
        return self.cuda_index.format(tag=tag)

    def pip_specs(self) -> list[str]:
        """Усе, що ставиться в середовище, крім torch.

        Плаский перелік — для того, хто ставить УСЕ підряд і не вибирає
        (`cloud.run`). Тому, хто вибирає, потрібен `install_specs()`: тут
        зв'язок «ім'я ↔ специфікація» втрачено за побудовою.
        """
        return [*self.packages, *(v["spec"] for v in self.vcs_packages)]

    def install_specs(self) -> dict[str, str]:
        """Ім'я, яким пакет названо у звіті → чим саме його ставити.

        🔴 Існує тому, що відновлювати цей зв'язок здогадом НЕ МОЖНА, а саме це
        й робив `env.setup`: він шукав ім'я пакета підрядком у pip-специфікації.
        Для PyPI-рядків збігалося випадково (`kraken` ⊂ `kraken==7.0.2`), а для
        git-залежності специфікація — URL, у якому імені пакета немає взагалі:
        `strhub` проти `git+https://github.com/baudm/parseq.git`. Наслідок був
        мовчазний — PARSeq випадав зі списку встановлення, `pip` виходив з нуля,
        і `doctor` слав по колу назад у ту саму команду.

        ⚠ Ключі двох половин живуть у РІЗНИХ просторах імен, і це не деталь:
        для `packages` ключ — ім'я дистрибутиву (ним питають
        `importlib.metadata`), для `vcs_packages` — ім'я імпорту (ним питають
        сам `import`). Обидва мусять збігатися з тим, що `env.inspect` кладе в
        `missing`, інакше вибір знову промахнеться.
        """
        out = {dist_name(spec): spec for spec in self.packages}
        out.update({v["name"]: v["spec"] for v in self.vcs_packages})
        return out


def _build(raw: dict[str, Any]) -> Manifest:
    rt = raw.get("runtime") or {}
    torch = rt.get("torch") or {}
    return Manifest(
        python=str(rt.get("python") or "3.11"),
        packages=tuple(str(p) for p in (rt.get("packages") or [])),
        vcs_packages=tuple({"name": str(v.get("name") or ""),
                            "spec": str(v.get("spec") or ""),
                            "note": str(v.get("note") or "")}
                           for v in (rt.get("vcs_packages") or [])),
        torch_default=tuple(str(p) for p in (torch.get("default") or [])),
        cuda_index=str(torch.get("cuda_index") or ""),
        cuda_matrix=tuple({str(k): str(v) for k, v in (row or {}).items()}
                          for row in (torch.get("cuda_matrix") or [])),
        engines=tuple(Engine(
            id=str(e.get("id") or ""), label=str(e.get("label") or ""),
            kind=str(e.get("kind") or ""), script=str(e.get("script") or ""),
            model_glob=str(e.get("model_glob") or ""), note=str(e.get("note") or ""))
            for e in (raw.get("engines") or [])),
        patches=tuple(Patch(
            id=str(p.get("id") or ""), module=str(p.get("module") or ""),
            verify=str(p.get("verify") or ""), tested_on=str(p.get("tested_on") or ""),
            requires_cuda=bool(p.get("requires_cuda")), gain=str(p.get("gain") or ""))
            for p in (raw.get("patches") or [])),
        base_models=tuple(BaseModel(
            id=str(b.get("id") or ""), doi=str(b.get("doi") or ""),
            filename=str(b.get("filename") or ""), note=str(b.get("note") or ""))
            for b in (raw.get("base_models") or [])),
    )


def load(path: Path | None = None) -> Manifest:
    src = path or BUILTIN
    return _build(yaml.safe_load(src.read_text(encoding="utf-8")) or {})


@lru_cache(maxsize=1)
def active() -> Manifest:
    return load()
