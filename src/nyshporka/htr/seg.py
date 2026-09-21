"""Готова сегментація: знайти, перевірити й вирішити, чи можна їй вірити.

Коли ту саму справу читає ДРУГА модель, сегментація в неї та сама (`kraken.blla`
в обох рушіях) і вже лежить поруч із першим прогоном. На кеші сторінка коштує
лише розпізнавання: замір 18.4 → 9.1 с/стор на повторному прогоні іншою
моделлю. Звідси два споживачі цього модуля: локальне перечитування й хмарне,
де кеш їде на машину першим чекпоінтом і бокс не сегментує справу вдруге.

Кеш лежить у двох місцях, і обидва треба знати:

- забраний із хмари — `<тека прогону>/data/derived/htr_seg/*/`;
- локальний — спільний кеш простору, адресу дає `htr.run.seg_cache_dir`.

🔴 КЕШ НЕ ЗНАЄ ЗОБРАЖЕННЯ. Його ключ несе параметри нарізки, а не хеш кадру —
тож кеш, знятий із кадрів ІНШОГО розміру (напр. стиснених до 3100 px для
хмари), дає полігони не з тих місць **без жодної помилки**: рядки вийдуть
інші, текст вийде інший, і в лозі не буде ні слова. Тому геометрія звіряється
з `.lines.json` першого прогону ДО того, як кеш кудись поїде. Це головний
запобіжник усього модуля, і він коштує п'яти відкритих кадрів.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — лише для перевірки типів
    from collections.abc import Sequence

#: Параметри нарізки, з якими кеш пишуть і хмарний раннер, і `nysh read` за
#: замовчуванням (`--sato-sigmas 1,3`, `--max-endpoints 400`, `--seg-height 0`).
#: Кеш з іншими не влучить: раннер мовчки сегментує наново, і єдиним наслідком
#: буде рахунок за роботу, яку ми думали, що не робимо.
EXPECTED_KEY = {"sato": "1,3", "max_endpoints": 400, "seg_height": 0}

#: Скільки кадрів звіряти з `.lines.json` першого прогону. П'ять, а не всі:
#: розбіжність геометрії — це властивість ТЕКИ (стиснули або ні), а не
#: окремого кадру, тож перший же промах її показує.
GEOMETRY_SAMPLE = 5

#: Від якого покриття кадрів кешем план кладе менше ядер на шард.
DENSE_FLEET_COVERAGE = 0.9

#: Ядер на шард, коли сегментація вже є. Геометрія й sato — ~74% процесора
#: сторінки (`htr/patches/README.md`), тож шард бере вдвічі менше ядер. Це
#: СТЕЛЯ регулятора, а не розмір флоту: далі флот міряє темп сам і спиняється
#: на коліні карти.
CORES_PER_SHARD_SEEDED = 0.5

#: VRAM на шард, коли сегментація вже є: `blla` не вантажиться. Замір
#: 15.09.2026 (Скриба v6 на готовій сегментації, RTX A4000×2): 0.70 ГБ карти на
#: шард; беремо з запасом на поодинокий промах кешу, де `blla` таки вантажиться.
GB_PER_SHARD_SEEDED = 1.0


@dataclass(frozen=True)
class SegCache:
    """Вирок про готову сегментацію: що знайдено і чи можна їй вірити."""

    path: Path | None
    frames: int
    covered: int
    usable: bool
    why: str

    @property
    def coverage(self) -> float:
        return self.covered / self.frames if self.frames else 0.0


def _stem(cache_file: Path) -> str:
    return cache_file.name.split(".")[0]


def candidates(case_dir: Path, *, base_out: Path, derived: Path) -> list[Path]:
    """Де може лежати сегментація цієї справи — забрана з хмари й локальна."""
    from nyshporka.htr.run import seg_cache_dir

    out: list[Path] = []
    cloud = base_out / "data" / "derived" / "htr_seg"
    if cloud.is_dir():
        out += sorted(d for d in cloud.iterdir() if d.is_dir())
    local = seg_cache_dir(case_dir, derived)
    if local.is_dir():
        out.append(local)
    # 🔴 Друга форма локального імені — без обрізання слуга до 60 символів.
    # Теки, написані до того, як обрізання з'явилось, інакше стають невидимі, і
    # справа сегментується наново за гроші. Дешевше подивитись обидві адреси.
    slug = re.sub(r"[^\w.\-]+", "_", Path(case_dir).name)
    if len(slug) > 60:
        long = local.with_name(f"{slug}__{local.name.rsplit('__', 1)[-1]}")
        if long.is_dir() and long not in out:
            out.append(long)
    return out


def key_problem(files: Sequence[Path]) -> str:
    """Чи знятий кеш із тими параметрами нарізки, з якими читатиме раннер."""
    base = [f for f in files if ".c400." in f.name] or list(files)
    for f in base[:3]:
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                key = json.load(fh).get("key") or {}
        except (OSError, ValueError):
            return f"{f.name} не читається"
        wrong = {k: key.get(k) for k, v in EXPECTED_KEY.items() if key.get(k) != v}
        if wrong:
            return ", ".join(f"{k}={v!r}" for k, v in wrong.items())
    return ""


def geometry_problem(frames: Sequence[Path], base_out: Path) -> str:
    """Кадри, які поїдуть читатись, мусять мати розмір, який бачив перший прогін.

    🔴 Це і є той запобіжник, заради якого існує модуль: кеш, знятий із
    оригіналів, у прогоні по стиснутій копії дає кропи не з тих місць, і
    жоден лічильник цього не покаже.
    """
    from PIL import Image

    checked = 0
    for frame in frames:
        lines = base_out / f"{frame.stem}.lines.json"
        if not lines.is_file():
            continue
        try:
            size = json.loads(lines.read_text(encoding="utf-8")).get("size")
            with Image.open(frame) as im:
                got = list(im.size)
        except (OSError, ValueError):
            continue
        if size and list(size) != got:
            return (f"кеш знятий із кадрів іншого розміру ({frame.name}: "
                    f"{got[0]}×{got[1]} проти {size[0]}×{size[1]} у першому "
                    f"прогоні — стиснені для хмари?)")
        checked += 1
        if checked >= GEOMETRY_SAMPLE:
            break
    return ""


def frames_of(case_dir: Path) -> list[Path]:
    """Кадри так, як їх бачить рушій: прямо в теці, без підтек."""
    from nyshporka.htr.run import _IMG_EXT

    d = Path(case_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in _IMG_EXT)


def inspect(case_dir: Path, frames: Sequence[Path] | None = None, *,
            base_out: Path, derived: Path | None = None) -> SegCache:
    """Найкраща придатна сегментація для цих кадрів — або чому її немає.

    `case_dir` — тека справи, за якою адресується локальний кеш; `frames` —
    кадри, які САМЕ ПОЇДУТЬ читатись (для хмари це стиснута копія, і саме її
    геометрію треба звіряти; `None` — беруться кадри самої теки); `base_out` —
    тека ПЕРШОГО прогону, де лежать `.lines.json` і, можливо, забраний із
    хмари кеш.
    """
    from nyshporka.core.workspace import workspace

    derived = derived or workspace().derived
    frames = list(frames) if frames is not None else frames_of(Path(case_dir))
    best: tuple[Path, int, list[Path]] | None = None
    for d in candidates(Path(case_dir), base_out=base_out, derived=derived):
        files = sorted(d.glob("*.seg.json.gz"))
        stems = {_stem(f) for f in files}
        covered = sum(1 for fr in frames if fr.stem in stems)
        if covered and (best is None or covered > best[1]):
            best = (d, covered, files)
    n = len(frames)
    if best is None:
        return SegCache(None, n, 0, False,
                        "готової сегментації немає — сегментуватиметься наново")
    d, covered, files = best
    if problem := key_problem(files):
        return SegCache(d, n, covered, False,
                        f"кеш знятий з іншими параметрами нарізки ({problem}) — не влучить")
    if problem := geometry_problem(frames, base_out):
        return SegCache(d, n, covered, False, problem)
    return SegCache(d, n, covered, True, f"{covered}/{n} кадрів ({100 * covered / n:.0f}%)")
