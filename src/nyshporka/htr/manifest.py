"""🖋 Маніфест рушіїв читання — читання `engines.yaml`.

Тут лише розбір і питання до маніфесту. Створення середовища — `htr/env.py`,
сам прогін — `htr/runner.py` (той їде під ІНШИМ інтерпретатором і не імпортує
нічого з пакета).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BUILTIN = Path(__file__).resolve().parent / "data" / "engines.yaml"


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

        🔴 Розширення каже РУШІЙ (`.mlmodel` → kraken, `.pt` → parseq), а
        префікс імені — ПИСЬМО. Тобто `.mlmodel` буває двох письм, і вибір «за
        розширенням» без префікса поставив би на латинську справу кириличну
        модель. Невідповідність рушія письму дає ТИХЕ сміття: текст виходить,
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
        """Усе, що ставиться в середовище, крім torch."""
        return [*self.packages, *(v["spec"] for v in self.vcs_packages)]


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
