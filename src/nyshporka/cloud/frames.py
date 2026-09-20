"""🎞 Кадри перед дорогою: чи цілі, чи всі, чи не завеликі.

Усе тут стоїть ДО оренди й нічого не коштує, а ловить те, що після оренди
коштує найдорожче:

* **обрізаний кадр.** Завантажувач, убитий посеред запису, лишає файл
  правильного імені й неправильного вмісту. Рушій на ньому не падає — він
  читає верхню половину аркуша й віддає текст, тож справа виглядає прочитаною;
* **тека, яка ще качається.** Захід, пущений на недокачану справу, читає
  частину й чесно рапортує «повністю»: знаменник він бере з тієї самої теки;
* **кадри по 6–12 МБ.** Модель працює з рядковими кропами, і зайві пікселі їй
  нічого не дають, а платять за них двічі — сегментація йде по повному растру
  (заміряно: 61 с на сторінку проти 17 с на висоті 3100), і на машину їде
  вп'ятеро більше байтів. Шість оренд поспіль уже давали нуль сторінок саме
  так: архів качався довше, ніж жила машина.

🔴 Оригінали не чіпаються ніколи. Стиснута копія лягає в похідні дані простору
(`derived/cloud/frames/<ім'я справи>`), а в мету прогону після забору
вписується тека оригіналів: кроп зі стиснутого кадру вдвічі дрібніший, а
знахідку звіряють саме кропом.
"""
from __future__ import annotations

import contextlib
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.cloud.base import CloudError

#: Тека, у яку писали пізніше за стільки секунд тому, — ще качається.
STILL_WRITING_SEC = 300

#: Медіана кадру понад стільки МБ — стискати перед дорогою.
SHRINK_MEDIAN_MB = 3.0

#: Формати, які читач на орендованій машині бере з архіву кадрів. 🔴 Вужче за
#: те, що вміє локальне читання: TIFF у цей перелік не входить, і кадр у ньому
#: мовчки випав би зі знаменника — тобто половина справи виглядала б
#: прочитаною повністю. Такі кадри перетворюються на JPEG при стисканні.
CLOUD_READY_EXT = {".jpg", ".jpeg", ".png"}

#: Робоча висота кадру. А/Б формату робився на парафіяльній книзі: сірий JPEG
#: висотою 3100 проти RGB PNG 4800×6400 дав символів 1.02×, рядків від восьми
#: символів 1.00×, і знахідка шуканого прізвища збереглась. Тобто зменшення —
#: не компроміс, а усунення марної роботи.
TARGET_HEIGHT = 3100
JPEG_QUALITY = 90

#: Скільки хвоста файла читати в пошуках маркера кінця.
_TAIL_BYTES = 8192

#: Сайдкар завантажувача плівок: `{…: {"file": ім'я, "size": байт, …}}`.
FS_SIDECAR = "_fs_meta.json"


class FramesError(CloudError):
    """Кадри не годяться в дорогу — з поясненням, що саме з ними не так."""


@dataclass(frozen=True)
class FramesReport:
    """Що знайшла звірка кадрів."""

    n: int
    total_mb: float
    median_mb: float
    bad: list[str] = field(default_factory=list)
    #: Скільки хвилин тому записано найсвіжіший кадр, якщо менше п'яти, —
    #: інакше `None`.
    still_writing_min: float | None = None
    #: Кадри у форматі, якого читач на машині не бере (`.tif` і подібні).
    #: 🔴 Не дрібниця: локальне читання TIFF розуміє, а хмарний захід пакує
    #: лише JPEG і PNG — тож такий кадр мовчки випадає зі знаменника, і
    #: половина справи виглядає прочитаною повністю.
    alien: list[str] = field(default_factory=list)

    @property
    def heavy(self) -> bool:
        return self.median_mb > SHRINK_MEDIAN_MB or bool(self.alien)

    def as_dict(self) -> dict[str, Any]:
        return {"n": self.n, "total_mb": self.total_mb,
                "median_mb": self.median_mb, "bad": self.bad[:50],
                "bad_count": len(self.bad),
                "still_writing_min": self.still_writing_min,
                "alien": self.alien[:50], "alien_count": len(self.alien),
                "heavy": self.heavy}


def _pil() -> Any:
    """Pillow — ліниво й зі зрозумілою відмовою.

    Оркестрація хмарного заходу живе й там, де немає ні рушія, ні його
    залежностей, тож імпорт на рівні модуля валив би `nysh cloud --help` на
    машині, де зображень ніхто не відкриває.
    """
    try:
        from PIL import Image
    except ImportError:
        raise FramesError(
            "для звірки й стискання кадрів потрібен Pillow, а його в цьому "
            "середовищі немає. Поставте: `pip install pillow` (або перевстановіть "
            "Нишпорку — Pillow входить у її основні залежності).") from None
    return Image


def _fs_sidecar(d: Path) -> dict[str, dict[str, Any]]:
    """Що завантажувач плівок записав про кожен кадр. `{}` — сайдкара немає."""
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(d / FS_SIDECAR, default={})
    except (CorruptFileError, OSError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in (raw.values() if isinstance(raw, dict) else []):
        if isinstance(entry, dict) and entry.get("file"):
            out[str(entry["file"])] = entry
    return out


def check_frames(case_dir: Path | str, *, now: float | None = None) -> FramesReport:
    """Цілість кожного кадру: розмір, кінець файла, розбір заголовка, сайдкар.

    🔴 Кінець файла перевіряється окремо, бо `verify()` у Pillow обрізаного
    JPEG не ловить: він читає заголовок, а обрив сидить у хвості. Саме такий
    кадр лишає завантажувач, убитий посеред запису.

    🔴 Сайдкар знає РОЗМІР кожного скачаного кадру. Розбіжність означає, що
    кадр перезаписано або обрізано (дві копії черги вже писали в одну теку), а
    кадр, записаний у сайдкар, але відсутній на диску, — що тека неповна.
    Сайдкара може не бути зовсім: тоді цієї перевірки просто немає.
    """
    from nyshporka.cloud.verify import frames_in

    image = _pil()
    d = Path(case_dir)
    frames = frames_in(d)
    sidecar = _fs_sidecar(d)
    on_disk = {f.name for f in frames}
    bad: list[str] = [f"{name}: є в {FS_SIDECAR}, на диску немає"
                      for name in sorted(set(sidecar) - on_disk)]
    sizes: list[int] = []
    newest = 0.0
    for f in frames:
        stat = f.stat()
        size = stat.st_size
        newest = max(newest, stat.st_mtime)
        sizes.append(size)
        want = (sidecar.get(f.name) or {}).get("size")
        if isinstance(want, int) and not isinstance(want, bool) and want != size:
            bad.append(f"{f.name}: {size} байт, а завантажувач записав {want} — "
                       f"перезаписаний або обрізаний")
            continue
        if size == 0:
            bad.append(f"{f.name}: 0 байт")
            continue
        with f.open("rb") as fh:
            fh.seek(max(0, size - _TAIL_BYTES))
            tail = fh.read()
        suffix = f.suffix.lower()
        if suffix in (".jpg", ".jpeg") and b"\xff\xd9" not in tail:
            bad.append(f"{f.name}: обрізаний (немає кінця JPEG)")
            continue
        if suffix == ".png" and b"IEND" not in tail:
            bad.append(f"{f.name}: обрізаний (немає кінця PNG)")
            continue
        try:
            with image.open(f) as im:
                im.verify()
        except Exception as exc:    # будь-яка відмова розбору = битий кадр
            bad.append(f"{f.name}: не розбирається ({type(exc).__name__})")
    alien = [f.name for f in frames if f.suffix.lower() not in CLOUD_READY_EXT]
    total = sum(sizes) / 1e6
    median = statistics.median(sizes) / 1e6 if sizes else 0.0
    age = ((now if now is not None else time.time()) - newest) if newest else None
    writing = (round(max(0.0, age) / 60, 1)
               if age is not None and age < STILL_WRITING_SEC else None)
    return FramesReport(n=len(frames), total_mb=round(total, 1),
                        median_mb=round(median, 2), bad=bad,
                        still_writing_min=writing, alien=alien)


# ── стискання ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ShrinkResult:
    """Що зробило стискання."""

    dst: Path
    total: int
    done: int
    skipped: int
    rotated: int = 0
    #: Кадри, де ширина більша за висоту. Саме число, без вироку: це або
    #: телефонна зйомка з книгою на боці, або законний кадр-розворот.
    landscape: int = 0
    src_bytes: int = 0
    dst_bytes: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return round(self.src_bytes / self.dst_bytes, 1) \
            if self.src_bytes and self.dst_bytes else 0.0


def shrink_dir_for(case_dir: Path | str) -> Path:
    """Куди стискати кадри: `<похідні>/cloud/frames/<ім'я справи>`.

    🔴 Ім'я теки = ім'я справи, бо план бере з нього ім'я прогону й теку
    результату. Стиснуте в `frames-<щось>` дало б прогін із чужим іменем, і
    текст ліг би не поруч зі справою, а в теку, якої ніхто не шукатиме.
    """
    from nyshporka.core.workspace import workspace

    d = Path(case_dir)
    name = d.parent.name if d.name == "pages" else d.name
    return workspace().derived / "cloud" / "frames" / name


def shrink(src: Path | str, dst: Path | str, *, target_h: int = TARGET_HEIGHT,
           quality: int = JPEG_QUALITY, rotate_landscape: bool = False,
           on_line: Any = None) -> ShrinkResult:
    """Зменшити кадри до робочого розміру: сірий JPEG заданої висоти.

    Ідемпотентно: наявне в цілі пропускається, тож перерване стискання
    доганяється повторним викликом. Кадр пишеться в тимчасовий файл і лише
    потім дістає своє ім'я — інакше обірваний запис лишив би в цілі рівно той
    обрізаний кадр, від якого стоїть `check_frames`, і наступний виклик
    пропустив би його як готовий.

    🔴 Кадр НА БОЦІ. Зменшення без повороту стискає аркуш, покладений на бік,
    по короткій стороні: висота рядка падає вдвічі, і рушій розсипається ще до
    сегментації. На замовній телефонній зйомці це норма, а не виняток (706
    кадрів із 711 в одній партії). Правило повороту одне й перевірене оком:
    ширина більша за висоту → 90° за годинниковою. EXIF не питаємо — на тому ж
    матеріалі він був виставлений на восьми кадрах із 711.

    🔴 Але безумовно крутити НЕ МОЖНА: є законно-ландшафтний матеріал —
    кадр-розворот, два аркуші в одному. Тихий поворот таких кадрів був би тією
    самою мовчазною пасткою з іншого боку. Тому без `rotate_landscape` не
    крутиться нічого, а число ландшафтних кадрів повертається у результаті —
    щоб вибір не лишився мовчазним у жодному напрямку.
    """
    from nyshporka.cloud.verify import frames_in

    image = _pil()
    say = on_line or (lambda _s: None)
    src_dir, dst_dir = Path(src), Path(dst)
    if not src_dir.is_dir():
        raise FramesError(f"немає теки {src_dir}")
    files = frames_in(src_dir)
    stems: dict[str, str] = {}
    for p in files:
        # 🔴 Усе стає `<ім'я>.jpg`, тож `0001.png` і `0001.jpg` зіллються в
        # один кадр, і захід прочитає на сторінку менше без жодної помилки.
        if p.stem in stems:
            raise FramesError(
                f"у теці два кадри з одним іменем: {stems[p.stem]} і {p.name}. "
                f"Після стискання вони стали б одним файлом — перейменуйте один.")
        stems[p.stem] = p.name
    dst_dir.mkdir(parents=True, exist_ok=True)
    stale = sorted(q.name for q in frames_in(dst_dir) if q.stem not in stems)
    if stale:
        # Не видаляємо: тека з таким іменем могла лишитись від ІНШОЇ справи з
        # тим самим іменем теки, і зносити чуже мовчки — не наше рішення.
        raise FramesError(
            f"у {dst_dir} лежать кадри, яких немає у справі "
            f"({', '.join(stale[:5])}{' …' if len(stale) > 5 else ''}) — це "
            f"стиснута копія іншої теки з тим самим іменем. Приберіть її й "
            f"повторіть.")

    landscape = 0
    for p in files:
        try:
            with image.open(p) as probe:
                if probe.width > probe.height:
                    landscape += 1
        except Exception:
            pass        # битий кадр назве основний прохід, не передпрохід

    done = skipped = rotated = 0
    src_bytes = dst_bytes = 0
    failed: list[str] = []
    for p in files:
        out = dst_dir / (p.stem + ".jpg")
        if out.exists():
            skipped += 1
            dst_bytes += out.stat().st_size
            continue
        # pid і потік в імені: два заходи однієї справи (інша модель, інше
        # письмо) стискають у ту саму теку, і спільний тимчасовий файл дав би
        # кадр, зшитий із двох половин. Вміст у них однаковий, тож хто з двох
        # перейменує останнім — байдуже.
        tmp = out.with_name(f"{out.name}.{os.getpid()}.{threading.get_ident()}.part")
        try:
            # 🔴 `with`, а не голий `open`: присвоєння результату `resize` губить
            # посилання на ВІДКРИТИЙ файл, не закриваючи його. На кількасот
            # кадрів дескриптори вичерпуються, і процес гине мовчки — без
            # винятку й без рядка в лозі (тека на 942 кадри падала на 700–870-му).
            with image.open(p) as opened:
                im = opened
                # 🔴 Поворот СТРОГО ПЕРЕД зменшенням: `target_h` міряє довгу
                # сторону аркуша, а на кадрі, покладеному на бік, довга сторона
                # — це ширина.
                if rotate_landscape and im.width > im.height:
                    im = im.transpose(image.ROTATE_270)   # 90° за годинниковою
                    rotated += 1
                if im.height > target_h:
                    w = round(im.width * target_h / im.height)
                    im = im.resize((w, target_h), image.LANCZOS)
                # Сірий: колір у скорописі не несе сигналу, а важить утричі більше.
                im = im.convert("L")
            im.save(tmp, "JPEG", quality=quality, optimize=True)
            im.close()
            tmp.replace(out)
            src_bytes += p.stat().st_size
            dst_bytes += out.stat().st_size
            done += 1
        except Exception as exc:        # один битий кадр не валить пакет
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            if out.exists():
                # Сусідній захід тієї самої справи встиг покласти цей кадр
                # першим (на Windows заміна відкритого файла відмовляє).
                skipped += 1
            else:
                failed.append(f"{p.name}: {type(exc).__name__}")
        if done and done % 100 == 0:
            say(f"стиснуто {done} з {len(files)}")

    got = len(frames_in(dst_dir))
    if failed or got != len(files):
        # 🔴 Приймач — число кадрів у ЦІЛІ, а не лічильник у пам'яті.
        raise FramesError(
            f"стискання дало {got} кадрів із {len(files)}"
            + (f"; не вийшли: {'; '.join(failed[:5])}" if failed else "")
            + ". Читати неповну копію немає сенсу.")
    if rotate_landscape:
        left = []
        for q in frames_in(dst_dir):
            try:
                with image.open(q) as probe:
                    if probe.width > probe.height:
                        left.append(q.name)
            except Exception:
                pass
        if left:
            raise FramesError(
                f"після повороту в цілі лишилось {len(left)} ландшафтних кадрів: "
                f"{', '.join(left[:5])}{' …' if len(left) > 5 else ''}")
    return ShrinkResult(dst=dst_dir, total=len(files), done=done, skipped=skipped,
                        rotated=rotated, landscape=landscape,
                        src_bytes=src_bytes, dst_bytes=dst_bytes)


# ── щільність письма ─────────────────────────────────────────────────────────
#: Менше стількох прочитаних сторінок — щільності не називаємо: медіана з
#: трьох аркушів описує ці три аркуші, а не книгу.
DENSITY_MIN_PAGES = 10


def lines_per_page(out_dir: Path | str, *, sample: int = 200) -> float | None:
    """Медіана рядків на сторінку з уже прочитаного. `None` — міряти нема з чого.

    Потрібна кошторису: темп читання рахується від щільності, і прогноз на
    типові 124 рядки промахується вдвічі на сповідному розписі. Перший захід
    її не знає, і це чесний стан; повторний (догін, перечитування після стелі
    бюджету) — знає з текстів, які вже лежать на диску.
    """
    d = Path(out_dir)
    if not d.is_dir():
        return None
    counts: list[int] = []
    for p in sorted(d.glob("*.txt")):
        if p.name.startswith("_"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        counts.append(sum(1 for ln in text.splitlines() if ln.strip()))
        if len(counts) >= sample:
            break
    if len(counts) < DENSITY_MIN_PAGES:
        return None
    return float(statistics.median(counts))
