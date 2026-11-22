"""✍ Шаблон нормалізації назв справ і розбір відповіді моделі.

Нормалізацію виконує агент учасника (підагент) чи Batch API — пакет сам у мережу
не ходить. Тут лише те, що має бути однаковим у всіх: текст запиту, розмір
пачки, номер версії для маніфесту й перевірка відповіді.

Шаблон — варіант Б2, перевірений 22.11.2026 на описах XIX ст. (Claude Sonnet,
effort low, 20 назв на запит, ~$0.00044 за рядок через Batch API): назв, які
збігаються з людським описом, на скорописі 38 → 60 %, вигаданих прізвищ 0–7 на
60 рядків проти 49 у вільної нормалізації. Ворота `names.invented` звіряють
саме цей контракт.

Сирий текст лишається поруч завжди (`Row.title_raw`); нормалізований — для
читання й пошуку, а не замість.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from importlib import resources
from typing import Literal

#: Версія шаблону. Іде в маніфест (`normalization.version`); змінюється з
#: кожною правкою тексту запиту.
VERSION = "b2-1"
PROMPT_ID = "nyshporka.opysy.norm_prompt"
#: Назв на один запит: більша пачка частіше губить порядок і довжину масиву.
BATCH = 20

Orthography = Literal["ru_modern", "keep"]

#: Правило правопису виходу. Заміряно лише `ru_modern` (російська ділова XIX ст.).
ORTHOGRAPHY: dict[str, str] = {
    "ru_modern": ("Вихід — СУЧАСНОЮ орфографією: без ѣ, і, ѳ, ѵ і кінцевого ъ "
                  "(ѣ→е, і→и, ѳ→ф, ѵ→и; «-аго» → «-ого»)."),
    "keep": "Мова й орфографія — як в оригіналі.",
}


class NormError(ValueError):
    """Відповідь моделі не годиться: не масив, інша довжина, не рядки."""


def prompt(source: str, orthography: Orthography = "ru_modern") -> str:
    """Текст запиту без вхідних назв (їх дописують JSON-масивом після нього).

    `source` — одним реченням: архів, фонд, установа, століття, мова. Наприклад:
    «ДАОО, фонд 445, Балтський повітовий суд, 1800–1870, російською».
    """
    if orthography not in ORTHOGRAPHY:
        raise ValueError(f"правопис «{orthography}»: є {', '.join(ORTHOGRAPHY)}")
    tpl = resources.files("nyshporka.opysy").joinpath("data", "norm_prompt.md").read_text(
        encoding="utf-8")
    return tpl.replace("{source}", source.strip()).replace(
        "{orthography}", ORTHOGRAPHY[orthography])


def request(source: str, titles: list[str], orthography: Orthography = "ru_modern") -> str:
    """Повний запит на одну пачку: шаблон + JSON-масив назв."""
    return prompt(source, orthography) + json.dumps(titles, ensure_ascii=False)


def batches(titles: list[str], size: int = BATCH) -> Iterator[tuple[int, list[str]]]:
    """Пачки назв: (зсув першої назви, назви)."""
    for i in range(0, len(titles), size):
        yield i, titles[i:i + size]


def parse(answer: str, expected: int) -> list[str]:
    """Відповідь моделі → назви. Довжина й порядок мусять збігтися з входом.

    🔴 Масив іншої довжини не «підрізається»: зсув на одну назву пришиває
    кожну нормалізацію до чужої справи, і ворота цього не побачать.
    """
    text = answer.strip()
    lo, hi = text.find("["), text.rfind("]")
    if lo < 0 or hi < lo:
        raise NormError("у відповіді немає JSON-масиву")
    try:
        got = json.loads(text[lo:hi + 1])
    except json.JSONDecodeError as exc:
        raise NormError(f"масив не розбирається: {exc.msg}") from exc
    if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
        raise NormError("очікувався масив рядків")
    if len(got) != expected:
        raise NormError(f"назв у відповіді {len(got)}, а на вході {expected}")
    return [x.strip() for x in got]
