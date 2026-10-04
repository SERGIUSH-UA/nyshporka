"""📦 Паки: ваги моделей і каталоги — качаються при першому запуску.

У колесі їх немає навмисно. Ваги трьох моделей — сотні мегабайтів, а pip-пакет
на 300 МБ ставиться довго, оновлюється боляче й тягне все три навіть тому, хто
читатиме лише латинку.

🔴 sha256 перевіряється завжди, і це не про зловмисника. Обірвана закачка лишає
файл, який виглядає як модель: `torch.load` на ньому впаде десь усередині, з
повідомленням про формат тензора — тобто причину («не докачалось») доведеться
здогадувати. Дешевше звірити хеш і сказати прямо.

🔴 Версія в імені файлу — частина контракту. «Найновіша» не означає «найкраща»:
у дослідницькому конвеєрі бойовими лишались не останні версії, бо пізніші
програвали на голдовому зрізі. Тому пак називає версію, а не «latest».
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

#: Звідки качаються паки. Реліз на GitHub, а не власний хост: у нього є
#: дзеркала, і він переживе автора проєкту.
BASE_URL = "https://github.com/SERGIUSH-UA/nyshporka/releases/download"

MANIFEST_NAME = "packs.json"


@dataclass(frozen=True)
class Pack:
    """Один завантажуваний артефакт."""

    id: str
    kind: str            # model | catalog
    filename: str
    sha256: str
    size: int
    release: str         # тег релізу
    label: str = ""
    script: str = ""     # для моделей: письмо (latin / cyrillic)
    engine: str = ""     # kraken | parseq
    note: str = ""
    #: Пак попереднього покоління. Не качається за замовчуванням — новий
    #: користувач не платить за ваги, якими вже ніхто не читає, — але якщо він
    #: УЖЕ лежить у людини, то лишається кандидатом нижчого пріоритету. Так
    #: оновлений застосунок читає й тоді, коли нові ваги ще не довантажені
    #: (офлайн, обірване `nysh models get`): гірше, але не «читати нічим».
    superseded: bool = False

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.release}/{self.filename}"


def manifest_path() -> Path:
    return Path(__file__).resolve().parent / "data" / MANIFEST_NAME


def catalog() -> list[Pack]:
    """Що взагалі можна завантажити. Перелік їде з пакетом, самі файли — ні."""
    raw = json.loads(manifest_path().read_text(encoding="utf-8"))
    return [Pack(**p) for p in raw.get("packs", [])]


#: Види паків, чия втрата тиха → лягають у дані, а не в кеш.
_DATA_KINDS = {"catalog"}


def target_dir(kind: str) -> Path:
    """Куди кладеться пак.

    🔴 Не в простір дослідження. Ваги — річ відтворювана й спільна для всіх
    просторів; класти їх у простір означало б і дублювати сотні мегабайтів на
    кожен архів, і тягнути їх у резервну копію дослідження, де їм не місце.

    🔴 А от `user_cache_dir` проти `user_data_dir` вирішується не зручністю, а
    тим, як гучно чути втрату. Кеш операційна система має право прибрати:
      • ваги зникли — читання не запуститься, `doctor` скаже, і людина поставить
        їх заново; втрата гучна, кеш тут доречний;
      • **каталог зник — пошук просто знайде менше**, і «метрик цього села
        немає» стане неправдою, якої ніхто не помітить.
    Тобто саме правило «нуль мусить щось означати» забороняє класти довідники в
    кеш. Тека каталогу збігається з `catalog.store.catalog_dir()`.
    """
    from platformdirs import user_cache_dir, user_data_dir

    base = user_data_dir if kind in _DATA_KINDS else user_cache_dir
    return Path(base("Nyshporka", appauthor=False)) / kind


def path_of(pack: Pack) -> Path:
    return target_dir(pack.kind) / pack.filename


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def verify(pack: Pack) -> bool:
    """Файл на місці й цілий.

    🔴 Пак без хеша не вважається цілим ніколи. Це не формальність: маніфест
    у дереві коду має заглушки доти, доки реліз не складено, і «пропустити
    перевірку, якщо хеша немає» означало б, що застосунок мовчки приймає
    будь-що з тим іменем — включно з половиною файлу.
    """
    if not pack.sha256 or not pack.size:
        return False
    p = path_of(pack)
    return p.is_file() and p.stat().st_size == pack.size and \
        sha256_of(p) == pack.sha256


def installed() -> list[str]:
    """Id паків, які лежать на диску Й проходять звірку.

    Недокачаний файл у перелік не потрапляє: «модель є» про нього було б
    брехнею, яка проявиться аж посеред прогону.
    """
    return [p.id for p in catalog() if verify(p)]


def missing(kind: str = "", *, include_superseded: bool = False) -> list[Pack]:
    """Чого бракує. Замінені паки сюди не входять: їх ніхто не мусить качати."""
    return [p for p in catalog()
            if (not kind or p.kind == kind) and (include_superseded or not p.superseded)
            and not verify(p)]


#: Запас над розміром пака з маніфесту: розмір там може бути округлений.
PACK_SIZE_SLACK = 1 << 20


def fetch(pack: Pack, *, on_progress: Callable[..., None] | None = None,
          force: bool = False) -> Path:
    """Завантажити пак і звірити хеш. Повертає шлях.

    Запис іде через сусідній тимчасовий файл: обрив на самому записі не має
    лишати напівфабрикату під бойовим іменем — саме він потім і виглядає як
    «модель зламана».
    """
    import httpx

    dst = path_of(pack)
    if not force and verify(pack):
        return dst
    if not pack.sha256:
        # Відмова, а не «завантажимо й повіримо». Модель, про цілість якої ми
        # не можемо нічого сказати, читатиме справу годинами й видасть текст,
        # який не відрізнити від поганого почерку.
        raise RuntimeError(
            f"{pack.id}: у маніфесті немає sha256 — цей пак ще не входить у "
            f"складений реліз. Качати без звірки не буду.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    got = 0
    # 🔴 Розмір пака відомий з маніфесту — він і стеля (із запасом на
    # округлення в маніфесті). Доти качання читало скільки дадуть, і підмінена
    # чи зациклена відповідь заповнювала диск раніше, ніж звірка sha256
    # встигала відмовити (аудит 29.09.2026).
    cap = pack.size + PACK_SIZE_SLACK if pack.size else 0
    try:
        with httpx.stream("GET", pack.url, follow_redirects=True,
                          timeout=120) as r:
            r.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes():
                    got += len(chunk)
                    if cap and got > cap:
                        raise RuntimeError(
                            f"{pack.filename}: сервер віддає понад {cap} байт при "
                            f"заявлених {pack.size} — це не той файл, качання обірвано")
                    fh.write(chunk)
                    if on_progress:
                        on_progress(done=got, total=pack.size, unit="Б")
        digest = sha256_of(tmp)
        if digest != pack.sha256:
            raise RuntimeError(
                f"{pack.filename}: sha256 не збігся "
                f"(очікували {pack.sha256[:12]}…, отримали {digest[:12]}…). "
                f"Найімовірніше — обірвана закачка; спробуйте ще раз.")
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def iter_needed(kind: str = "") -> Iterator[Pack]:
    yield from missing(kind)


def as_dict() -> dict[str, Any]:
    """Стан паків для звіту й для екрана.

    ⚠ Розділяє «немає» і «зіпсоване»: перше лікується завантаженням, друге —
    повторним, і плутати їх означає радити не те.
    """
    rows = []
    for p in catalog():
        path = path_of(p)
        rows.append({
            "id": p.id, "kind": p.kind, "label": p.label or p.id,
            "size": p.size, "script": p.script, "engine": p.engine,
            "superseded": p.superseded,
            "state": ("ok" if verify(p)
                      else "broken" if path.exists()
                      else "superseded" if p.superseded else "absent"),
            "path": str(path),
        })
    return {"dir": str(target_dir("model").parent), "packs": rows}
