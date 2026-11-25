"""📐 Метадані опису від агента: те, що машині вгадувати важко, а на чому стоїть вибір схеми.

Агент учасника дивиться 2–3 сторінки опису (першу сторінку таблиці, середню й останню, де зазвичай
засвідчувальний напис) і записує `nysh opys meta <тека> …` → `<тека>/opys_meta.json`:

- `forma` — `blank` (друкований бланк із шапкою й лініями), `hand_ruled` (розграфлено від руки,
  лінії ледь видно), `typed` (машинопис);
- `rozvorot` — у кадрі розворот двох сторінок чи одна;
- `kolonky` — ролі колонок зліва направо (`ROLI`); права сторінка розвороту інакша — `kolonky_prava`;
- `sprav` і `sprav_dzherelo` — скільки справ в описі й звідки це число (засвідчувальний напис,
  останній номер); 0 — невідомо;
- `storinky` — перша й остання сторінка таблиці справ (титул і засвідчувальний напис — поза нею).

🔴 Це робочий файл учасника, не частина пакета Супряги: маніфест пакета на сервері строгий, а
метадані потрібні лише будівникові таблиці. `sprav` — число, прочитане агентом оком: воно є
знаменником повноти й підставою вибору схеми, але номери справ ним не виправляються.

Що з ними робить будівник таблиці (`ruled.build`):
- сторінки поза `storinky` — не таблиця справ (там шумові «справи» засвідчувального напису);
- між `nomer` і `nazva` є інша колонка (бланк «Содержаніе дѣлъ»: «Когда началось» з цифрами днів) —
  колонку № для плям чорнила брати вужчою;
- `sprav` — знаменник повноти, від якої залежить, де ставити межі з чорнила (`dochyt.skhema`).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILE = "opys_meta.json"
FORMY = ("blank", "hand_ruled", "typed")
#: Ролі колонок опису: № справи, діловодний №, коли почалось, назва, коли скінчилось, аркуші,
#: відмітка, інше.
ROLI = ("nomer", "delovod", "pochatok", "nazva", "kinets", "arkushi", "vidmitka", "inshe")


class MetaError(ValueError):
    """Метадані не годяться — текст каже, що виправити."""


@dataclass(frozen=True)
class Meta:
    forma: str = "hand_ruled"
    rozvorot: bool = True
    kolonky: tuple[str, ...] = ()
    kolonky_prava: tuple[str, ...] = ()
    sprav: int = 0
    sprav_dzherelo: str = ""
    storinky: tuple[int, int] | None = None
    zapovniv: str = ""
    koly: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def u_tablytsi(self, stem: str | int) -> bool:
        """Сторінка належить таблиці справ (без `storinky` — будь-яка)."""
        if not self.storinky:
            return True
        try:
            n = int(stem)
        except (TypeError, ValueError):
            return True
        return self.storinky[0] <= n <= self.storinky[1]

    def vuzko(self, part: int = 0) -> bool:
        """Між № і назвою стоїть інша колонка (на цій сторінці розвороту)."""
        k = self.kolonky_prava if part == 1 and self.kolonky_prava else self.kolonky
        return "nomer" in k and "nazva" in k and k.index("nazva") - k.index("nomer") > 1


def vidbytok_dochytu(m: Meta) -> str:
    """Відбиток полів, від яких залежать кропи дочиту (форма — шапка бланка, колонки — ширина
    колонки №, сторінки таблиці). Мітка часу й інше — ні: та сама правка не скидає дочиту."""
    import hashlib
    import json

    polia = {"forma": m.forma, "kolonky": list(m.kolonky), "kolonky_prava": list(m.kolonky_prava),
             "storinky": list(m.storinky) if m.storinky else None}
    return hashlib.sha256(json.dumps(polia, sort_keys=True, ensure_ascii=False).encode("utf-8")
                          ).hexdigest()[:16]


def perevirka(m: Meta) -> Meta:
    if m.forma not in FORMY:
        raise MetaError(f"форма «{m.forma}»: є {', '.join(FORMY)}")
    for k in (*m.kolonky, *m.kolonky_prava):
        if k not in ROLI:
            raise MetaError(f"роль колонки «{k}»: є {', '.join(ROLI)}")
    for kk in (m.kolonky, m.kolonky_prava):
        if kk and ("nomer" not in kk or "nazva" not in kk):
            raise MetaError("у колонках мають бути принаймні `nomer` і `nazva`")
        if kk and kk.index("nomer") > kk.index("nazva"):
            raise MetaError("колонка № стоїть правіше назви — так будівник таблиці не вміє")
    if m.sprav < 0 or m.sprav > 200_000:
        raise MetaError("кількість справ — від 0 (невідомо) до 200 000")
    if m.sprav and not m.sprav_dzherelo.strip():
        raise MetaError("назвіть, звідки число справ (засвідчувальний напис, останній номер)")
    if m.storinky and (m.storinky[0] < 1 or m.storinky[1] < m.storinky[0]):
        raise MetaError("сторінки таблиці — «перша-остання», перша ≥ 1")
    return m


def load(d: Path) -> Meta | None:
    p = Path(d) / FILE
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    st = raw.get("storinky")
    return perevirka(Meta(
        forma=raw.get("forma", "hand_ruled"), rozvorot=bool(raw.get("rozvorot", True)),
        kolonky=tuple(raw.get("kolonky") or ()), kolonky_prava=tuple(raw.get("kolonky_prava") or ()),
        sprav=int(raw.get("sprav") or 0), sprav_dzherelo=str(raw.get("sprav_dzherelo") or ""),
        storinky=(int(st[0]), int(st[1])) if st else None, zapovniv=str(raw.get("zapovniv") or ""),
        koly=str(raw.get("koly") or "")))


def save(d: Path, m: Meta) -> Path:
    from nyshporka.utils.atomic import atomic_write_text

    m = perevirka(m)
    raw = asdict(m)
    raw.pop("extra", None)
    raw["kolonky"], raw["kolonky_prava"] = list(m.kolonky), list(m.kolonky_prava)
    raw["storinky"] = list(m.storinky) if m.storinky else None
    raw["koly"] = m.koly or datetime.now(UTC).isoformat(timespec="seconds")
    p = Path(d) / FILE
    atomic_write_text(p, json.dumps(raw, ensure_ascii=False, indent=1), newline="\n")
    return p


def rozibraty_storinky(s: str) -> tuple[int, int] | None:
    """«3-34» → (3, 34); порожньо — None."""
    s = (s or "").strip().replace("–", "-")
    if not s:
        return None
    try:
        a, b = (int(x) for x in s.split("-", 1))
    except ValueError:
        raise MetaError("сторінки таблиці — «перша-остання», напр. 3-34") from None
    return a, b


def kudy_hlianuty(storinok: int) -> list[int]:
    """Які сторінки показати агентові: друга (перша таблиці часто після титулу), середня, остання."""
    if storinok <= 0:
        return []
    return sorted({min(2, storinok), max(1, storinok // 2), storinok})
