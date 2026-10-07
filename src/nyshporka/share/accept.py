"""📥 Прийняти чужий пакет: подивитись, перевірити, покласти до себе.

Прийняті прогони лягають у `reports/htr/<прогін>/` — туди ж, де лежить своє.
Це не недбалість, а головне рішення модуля: весь пошук по прочитаному
(`nysh text index/find/grep/ctx`) працює далі без жодного нового рядка коду,
бо він шукає саме там. Відрізняє чуже поле `shared` у меті прогону, і воно ж
доїжджає до стору, щоб знаменник пошуку міг сказати, чия це робота.

🔴 Ворота проганяються ВДРУГЕ, тут. Пакувальник міг бути іншої версії, чи
взагалі не наш, і «у нього ж перевірено» — це не перевірка.

🔴 Мета чиститься від слідів чужої машини й дістає теку кадрів ЦІЄЇ
(`cloud.run.stamp_case_dir`). Інакше кроп шукатиме аркуш за шляхом, якого тут
немає, — або, гірше, знайде випадкову теку з тим самим іменем.

Геометрія приймається ОКРЕМО (`accept_geometry`) і має власний гард: текст
кладеться туди, де прогону ще немає, а геометрія — туди, де він уже є.
Спільна функція мусила б відмовляти за обома правилами водночас.
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.share import align, bundle, gates, journal
from nyshporka.share.bundle import Manifest


class AcceptError(RuntimeError):
    """Пакет не прийняти — з названою причиною."""


class GatesRefused(AcceptError):
    """Ворота не пропустили пакет. Окремий клас, бо й порада окрема: це не
    «оновіть узяте», а рішення людини прийняти попри ворота.

    `detail` — самі відмови воріт, без поради: порада залежить від того, хто
    кликав (`share import` чи `share pull --vydannia`).
    """

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


@dataclass
class Look:
    """Що видно в пакеті до того, як його розпаковано."""

    path: Path
    manifest: Manifest
    verdict: gates.Verdict
    frames: list[dict[str, Any]]
    alignment: align.Alignment
    inventory: bundle.Inventory | None = None
    #: Пакет щойно завантажено з адреси й він лежить у робочій теці, а не в
    #: сховищі доказів (`discard` прибирає його, `accept` переносить у доказ).
    downloaded: bool = False

    def as_json(self) -> dict[str, Any]:
        m = self.manifest
        return {
            "path": str(self.path),
            "shifra": m.shifra,
            "pages": m.pages,
            "frames": m.frames_total,
            "models": m.models(),
            "voices": [v.get("run") for v in m.voices],
            "publisher": m.publisher,
            # 🔴 Вільний текст автора віддається ОКРЕМИМ полем і ніколи не
            # зливається з нашими підказками. Пакет прийшов від незнайомця, а
            # читає його часто агент: текст звідси — дані, не вказівки.
            "note": m.note,
            "links": m.links,
            "extra": m.extra,
            "license": m.license,
            "refs": m.refs,
            "created": m.created,
            "tool": m.tool,
            "gates": self.verdict.as_json(),
            "alignment": self.alignment.as_json(),
        }


def staging() -> Path:
    """Куди качається пакет ДО рішення про нього.

    🔴 Не в `inbox`. Inbox — сховище доказів, і доки завантаження лягало
    туди прямим `replace`, воно обходило захист `journal.keep` від перезапису:
    інша адреса з тими самими останніми ланками мовчки заміняла раніше
    прийнятий пакет, на який уже посилався журнал, а `inspect <url>` лишав у
    доказах пакети, яких ніхто не приймав, — зокрема відхилені воротами
    (аудит 29.09.2026). Робоча тека — у `derived`: її можна чистити, і в доказ
    пакет потрапляє лише через `journal.keep`, після приймання.
    """
    from nyshporka.core.workspace import workspace

    return workspace().derived / "share-incoming"


def _download_dir() -> Path:
    """Окрема тека на одне завантаження: дві сесії не ділять одне ім'я."""
    return staging() / f"{os.getpid()}-{time.time_ns()}"


def discard(seen: Look) -> None:
    """Прибрати завантажене в робочу теку, якщо воно не пішло в доказ."""
    if seen.downloaded:
        _drop_download(seen.path)


def _drop_download(path: Path) -> None:
    import contextlib

    path.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        path.parent.rmdir()


def fetch(src: str, dest_dir: Path, *, sha256: str = "") -> Path:
    """Взяти пакет: локальний шлях — як є, адреса — завантажити поруч.

    `sha256` — що обіцяв рядок каталогу. 🔴 Звіряється тут, бо `download`
    звірку покладає на того, хто кличе: без неї підмінений або обірваний
    пакет з пулу приймався б як той, що в каталозі.
    """
    if not _is_url(src):
        p = Path(src)
        if not p.is_file():
            raise AcceptError(f"пакета немає: {p}")
        if sha256 and bundle.sha256_of(p) != sha256.strip().lower():
            raise AcceptError(f"{p.name} не збігається з очікуваним sha256 — "
                              f"це не той пакет")
        return p
    from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline

    if offline():
        raise AcceptError("мережу вимкнено (NYSHPORKA_NO_NETWORK) — пакет не качається")
    dest = Path(dest_dir) / _name_for(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".dl")
    try:
        # Свій рядок, а не браузерний: качається пакет із нашого ж сховища,
        # і в його логах клієнт мусить бути відрізнимий від людини. Докладно
        # — у `share/upload.py`.
        Fetcher(headers={"User-Agent": app_ua(), **_kliuch_vydachi(src)}).download(
            src, tmp, max_bytes=bundle.MAX_DOWNLOAD_BYTES)
    except (HttpError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise AcceptError(f"не завантажити {src}: {exc}") from exc
    if sha256 and bundle.sha256_of(tmp) != sha256.strip().lower():
        tmp.unlink(missing_ok=True)
        raise AcceptError(f"завантажене з {src} не збігається з каталогом "
                          f"(sha256) — пакет підмінений або обірваний")
    tmp.replace(dest)
    return dest


def _kliuch_vydachi(src: str) -> dict[str, str]:
    """Ключ Супряги на завантаження — лише адресі видачі пулу (`/v1/d/`).

    Без ключа пул не знає, ЧИЄ це завантаження: бачить клієнта й версію, а
    автор справи — лише «хтось качав». З ключем завантаження стає особою в
    обліку. Качати можна й без нього: ключа нема — заголовка нема, і пул
    віддає пакет так само.

    🔴 Лише `/v1/d/`, а не будь-яка довірена адреса: старі рядки каталогу
    ведуть прямо на `cdn.` — це байтове сховище, ключ йому ні до чого, а
    чужий `Authorization` сховище може прочитати як спробу підпису. Далі 302
    на `cdn.` ключ теж не їде: httpx знімає його при переході на інший хост.
    """
    from urllib.parse import urlsplit

    from nyshporka.share.catalog import may_send_key
    from nyshporka.share.upload import token

    if "/v1/d/" not in urlsplit(src).path or not may_send_key(src):
        return {}
    kliuch = token()
    return {"Authorization": f"Bearer {kliuch}"} if kliuch else {}


#: Скільки останніх ланок адреси йде в ім'я збереженого файлу. Чотири — щоб
#: у назві стояв ще й архів: `dahmo-315-1-8433-1-text.nyshtext`. Унікальності
#: він не додає (її дає номер внеску), зате робить теку inbox читною для ока.
_NAME_PARTS = 4


def _name_for(url: str) -> str:
    """Ім'я, під яким завантажений пакет ляже в inbox.

    🔴 Не остання ланка адреси. У пулі всі пакети звуться однаково —
    `b/<архів>/<справа>/<внесок>/text.nyshtext`, — тож за останньою ланкою
    КОЖНА книга лягала б у той самий `inbox/text.nyshtext`. А inbox — це не
    кеш, а доказ: журнал записує туди шлях і sha256 прийнятого пакета, і
    друга прийнята книга мовчки робила б доказ першої хибним (шлях є, байти
    чужі, хеш не сходиться). Геометрія додає ще один такий самий загальний
    `geom.nyshtext`.

    🔴 Унікальним ім'я робить НОМЕР ВНЕСКУ, а не кількість узятих ланок.
    Номер глобальний на весь пул, тож двох однакових імен бути не може навіть
    тоді, коли «315-1-8433» трапляється в кожному другому архіві країни. Якщо
    схема ключів колись зміниться так, що номера в адресі не стане, це місце
    доведеться переписати — сама по собі довша назва нічого не гарантує.

    Те саме при повторному завантаженні тієї самої адреси: ім'я детерміноване,
    тож повтор не плодить копій доказу.
    """
    from urllib.parse import urlsplit

    lanky = [p for p in urlsplit(url).path.split("/") if p]
    raw = "-".join(lanky[-_NAME_PARTS:]) or "bundle"
    name = bundle.safe_name(raw, "bundle")
    return name if name.endswith(bundle.SUFFIX) else name + bundle.SUFFIX


def look(src: str, *, hash_frames: bool = False, sha256: str = "",
         texts: bool = True) -> Look:
    """Подивитись пакет, не розпаковуючи: заява, ворота, ступінь прив'язки.

    🔴 Ворота міряють ВМІСТ, а не заяву. Числа `decode` у маніфесті пише
    той, хто пакував, і пакет з одним рядком тексту, що заявляє три тисячі
    сторінок, доти проходив ворота знаменника — рівно той хибний нуль
    оптом, від якого вони стоять. Тепер сторінки, рядки й хеш змісту
    рахуються з текстів у самому пакеті, а розбіжність із заявою —
    відмова з названою причиною.

    `texts=False` — пакет геометрії: текстів у ньому немає за побудовою.

    Завантажене з адреси лежить у робочій теці (`staging`); хто кликав
    `look` лише подивитись, прибирає його `discard`.
    """
    downloaded = _is_url(src)
    path = fetch(src, _download_dir(), sha256=sha256)
    try:
        return _look_at(path, hash_frames=hash_frames, texts=texts,
                        downloaded=downloaded)
    except BaseException:
        if downloaded:
            _drop_download(path)
        raise


def _is_url(src: str) -> bool:
    return str(src).lower().startswith(("http://", "https://"))


def _look_at(path: Path, *, hash_frames: bool, texts: bool, downloaded: bool) -> Look:
    try:
        manifest = bundle.read_manifest(path)
        frames = bundle.read_frames(path)
        inv = bundle.inventory(path)
    except bundle.BundleError as exc:
        raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc
    verdict = gates.Verdict()
    for why in inv.problems[:20]:
        verdict.refuse(f"вада пакета: {why}", rule="bundle_defect")
    if len(inv.problems) > 20:
        verdict.refuse(f"… і ще {len(inv.problems) - 20} вад пакета",
                       rule="bundle_defect")
    if texts:
        try:
            _measure(path, inv, manifest, verdict)
        except bundle.BundleError as exc:
            raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc
    else:
        verdict.extend(gates.check(manifest, partial_why=_partial_note(manifest)))
    # 🔴 Лише ключ, розв'язаний ТУТ. Запасний `key_local` із пакета давав
    # чужому пакетові самому вибрати, з якою нашою справою його звіряти:
    # безглузда шифра плюс ключ нашої справи — і прив'язку до кадрів міряли
    # проти теки, яку назвав відправник (аудит 29.09.2026).
    local = _local_key(manifest)
    case_dir = align.case_dir_for(local) if local else None
    # Відбиток лежить у шапці кадрів маніфесту. Старий пакет його не має —
    # тоді прив'язка міряється як раніше, за іменами й кількістю.
    their_fp = manifest.frames.get("fingerprint")
    grade = align.grade(frames, case_dir, hash_frames=hash_frames,
                        their_fp=their_fp if isinstance(their_fp, dict) else None)
    return Look(path=path, manifest=manifest, verdict=verdict, frames=frames,
                alignment=grade, inventory=inv, downloaded=downloaded)


def _voice_runs(m: Manifest) -> dict[str, str]:
    """Прогони, які маніфест називає голосами: `{прогін: модель}`."""
    return {str(v.get("run")): str(v.get("model") or "")
            for v in m.voices if str(v.get("run") or "")}


def _measure(path: Path, inv: bundle.Inventory, m: Manifest, v: gates.Verdict) -> None:
    """Ворота над ВИМІРЯНИМ: знаменник і хеші — з текстів пакета."""
    import copy

    voices = _voice_runs(m)
    chuzhi = sorted(r for r in inv.runs if r not in voices)
    if chuzhi:
        v.warn("unlisted_runs",
               f"у пакеті є прогони, яких маніфест не називає голосами: "
               f"{', '.join(chuzhi[:5])} — вони не розкладаються")
    nemaie = sorted(r for r in voices if r not in inv.runs)
    if nemaie:
        v.refuse(f"маніфест називає голоси, яких у пакеті немає: {', '.join(nemaie[:5])}",
                 rule="voices_missing", field="voices")
    raw = bundle.read_texts(path, inv, runs=[r for r in voices if r in inv.runs])
    for voice in m.voices:
        run = str(voice.get("run") or "")
        claim = str(voice.get("content_sha256") or "")
        if claim and run in raw and bundle.text_hash(raw[run]) != claim:
            v.refuse(f"голос {run}: хеш змісту не збігається з тим, що заявляє "
                     f"маніфест — тексти в пакеті не ті",
                     rule="content_hash", field="voices.content_sha256")
    counted = bundle.tally(bundle.decoded(raw), voices)
    zaiava = m.pages
    if zaiava > counted["pages"]:
        v.refuse(f"маніфест заявляє {zaiava} прочитаних сторінок, а в пакеті "
                 f"їх {counted['pages']}", rule="pages_overclaimed", field="decode.pages")
    # Далі ворота бачать ВИМІРЯНЕ: той самий маніфест, але з числами з диска.
    probe = copy.copy(m)
    probe.decode = {**m.decode, **counted}
    v.extend(gates.check(probe, partial_why=_partial_note(m)))


def _partial_note(m: Manifest) -> str:
    """Уривок, пояснений автором пакета, лишається уривком — але не відмовою."""
    why = m.extra.get("partial") if isinstance(m.extra, dict) else ""
    return str(why or "")


def _local_key(m: Manifest) -> str:
    """Ключ ЦІЄЇ машини для чужої шифри.

    🔴 Не `key_local` з пакета. Той збирався чужою бібліотекою й чужим паком
    архівів, тож `DAHMO/196/712` у відправника цілком може бути
    `DAHMO/196-1/712` тут. Шифра людською формою переживає переїзд, ключ — ні.
    """
    shifra = m.shifra
    if not shifra:
        return ""
    try:
        from nyshporka.pagestore.store import resolve_case

        return str(resolve_case(shifra).key)
    except Exception:
        return ""


def _is_shared(run_dir: Path) -> bool:
    """Чи тека — раніше ПРИЙНЯТИЙ чужий прогін (а не своя робота)."""
    from nyshporka.cloud.verify import read_meta

    return bool(read_meta(run_dir).get("shared"))


def _clashes(htr_root: Path, incoming: list[str]) -> tuple[list[str], list[str]]:
    """Зіткнення імен: (з власними прогонами, з раніше прийнятими).

    🔴 Без регістру. На Windows `SPR-1` і `spr-1` — одна тека, і точне
    порівняння рядків пропускало чужий `spr-1` поверх власного `SPR-1` без
    жодного `--force`.
    """
    if not htr_root.is_dir():
        return [], []
    dirs = [d for d in htr_root.iterdir() if d.is_dir()]
    existing = {d.name.casefold(): d for d in dirs}
    own: list[str] = []
    theirs: list[str] = []
    for name in incoming:
        d = existing.get(name.casefold()) or _opened_as(htr_root / name, dirs)
        if d is None:
            continue
        (theirs if _is_shared(d) else own).append(d.name)
    return sorted(own), sorted(theirs)


def _opened_as(path: Path, dirs: list[Path]) -> Path | None:
    """Що файлова система відкриває під цим іменем, хоч рядком воно інше.

    🔴 Звірка рядків бачить лише довгі імена з `iterdir()`. На NTFS із
    короткими іменами 8.3 назва `DAHMO_~1` відкриває наявну теку
    `DAHMO_1789_…`, і чужий пакет ліг би поверх власного прочитання людини
    (аудит 29.09.2026). Тому питається сам диск: ім'я зайняте — шукаємо, ЯКУ
    саме теку воно відкриває. Не знайшли серед перелічених (файл, посилання) —
    однаково зайнято, і це рахується як своє: поверх невідомого не кладемо.
    """
    try:
        if not path.exists():
            return None
    except OSError:
        return path
    for d in dirs:
        try:
            if path.samefile(d):
                return d
        except OSError:
            continue
    return path


#: Скільки разів перечекати зайняту теку на Windows: антивірус, індексатор чи
#: в'ювер тримає дескриптор усередині, і перейменування падає PermissionError.
_RENAME_TRIES = 5
_RENAME_PAUSE = 0.2

#: Префікс тимчасової теки приймання поруч із прогонами. Крапка — бо імена з
#: крапкою на початку стор не вважає прогонами (`htr_store._case_dir`), а
#: самі прогони лежать у ній на глибині 2, куди `*/_htr_meta.json` не сягає.
_STAGE_PREFIX = ".nysh-import-"


def _rename_dir(src: Path, dest: Path) -> None:
    """`os.rename` теки з перечікуванням зайнятого дескриптора (Windows)."""
    for attempt in range(_RENAME_TRIES):
        try:
            os.rename(src, dest)
            return
        except PermissionError:
            if attempt == _RENAME_TRIES - 1:
                raise
            time.sleep(_RENAME_PAUSE)


def _is_packed(name: str) -> bool:
    """Чи файл того роду, що приїжджає пакетом (текст, мета, геометрія)."""
    return (name == bundle.META_NAME or name.endswith(".txt")
            or name.endswith(".lines.json"))


def _carry_extras(old: Path, new: Path) -> None:
    """Перенести з відсунутої старої теки те, що НЕ приїхало пакетом.

    Заміна прогону міняє лише текст, мету й геометрію — як і доти
    (`--force` не лишає сторінок старого пакета поруч із новими). Решта, що
    людина чи інструменти поклали в теку після приймання, переїжджає в нову.
    """
    for item in old.iterdir():
        if item.is_file() and _is_packed(item.name):
            continue
        target = new / item.name
        if not target.exists():
            _rename_dir(item, target)


def _swap_in(stage: Path, staged: list[Path], htr_root: Path,
             previous: dict[str, Path]) -> tuple[list[Path], bool]:
    """Поставити підготовлені теки на місце. → (теки, чи все стару прибрано).

    Стара тека (раніше прийнятий прогін) спершу відсувається всередину
    `stage`, потім нова стає на її ім'я; не вдалось — стара повертається.
    Отже на місці прогону в будь-яку мить або стара тека зі своєю
    позначкою, або нова зі своєю, і ніколи — текст без позначки.
    """
    placed: list[Path] = []
    clean = True
    for d in staged:
        dest = htr_root / d.name
        old = previous.get(d.name.casefold())
        aside: Path | None = None
        if old is not None and old.is_dir():
            aside = stage / ".old" / old.name
            aside.parent.mkdir(parents=True, exist_ok=True)
            _rename_dir(old, aside)
        try:
            if dest.exists():
                # Тека з'явилась після перевірки зіткнень — чужого поверх
                # не кладемо (POSIX `rename` мовчки зайняв би порожню теку).
                raise FileExistsError(f"{dest} з'явилась під час приймання")
            _rename_dir(d, dest)
        except OSError:
            if aside is not None and old is not None:
                _rename_dir(aside, old)
            raise
        if aside is not None:
            try:
                _carry_extras(aside, dest)
            except OSError:
                clean = False
        placed.append(dest)
    return placed, clean


def accept(src: str, *, hash_frames: bool = False, force: bool = False,
           replace: bool = False, keep_bundle: bool = True,
           sha256: str = "") -> dict[str, Any]:
    """Покласти пакет до себе. Повертає, що саме лягло і як воно прив'язалось.

    Два різні дозволи, і змішувати їх не можна (аудит 29.09.2026):

    * `replace` — замінити раніше ПРИЙНЯТИЙ чужий прогін новішим пакетом;
    * `force` — те саме плюс прийняти попри відмову воріт.

    `share pull --vydannia --force` обіцяв лише перше, а передавав друге:
    «оновити взяті роки» тихо приймало й пакети, яких ворота не пропустили,
    тобто той самий хибний знаменник оптом, від якого ворота стоять.
    """
    seen = look(src, hash_frames=hash_frames, sha256=sha256)
    try:
        return _accept_seen(seen, src, force=force, replace=replace or force,
                            keep_bundle=keep_bundle)
    finally:
        discard(seen)


def _accept_seen(seen: Look, src: str, *, force: bool, replace: bool,
                 keep_bundle: bool) -> dict[str, Any]:
    from nyshporka.core.workspace import workspace

    inv = seen.inventory or bundle.Inventory()
    if inv.problems:
        # Вади пакета (шляхи, спецфайли, стелі) не знімаються `--force`:
        # це не питання довіри до тексту, а питання, чи можна його класти
        # на диск узагалі.
        raise AcceptError("пакет не можна розкласти:\n"
                          + "\n".join(f"✗ {p}" for p in inv.problems[:20]))
    if not seen.verdict.passed and not force:
        raise GatesRefused(
            "ворота не пропустили пакет:\n" + gates.describe(seen.verdict)
            + "\nПрийняти попри це: --force",
            detail=gates.describe(seen.verdict))

    htr_root = workspace().htr_reports
    runs = [r for r in _voice_runs(seen.manifest) if r in inv.runs]
    if not runs:
        raise AcceptError("у пакеті не виявилось жодного прогону, названого в маніфесті")
    own, theirs = _clashes(htr_root, runs)
    if own:
        # 🔴 Власний прогін не перезаписується НІКОЛИ, навіть із `--force`:
        # це робота людини, а приймання чужого пакета — не спосіб її стерти.
        raise AcceptError(
            f"прогони з такими іменами вже є, і вони ВАШІ: {', '.join(own)}. "
            f"Чужий пакет поверх власного прочитання не кладеться — перейменуйте "
            f"свою теку, якщо справді хочете мати обидва")
    if theirs and not replace:
        raise AcceptError(
            f"прогони з такими іменами вже прийнято раніше: {', '.join(theirs)}. "
            f"Замінити новим пакетом: --force")
    previous = {name.casefold(): htr_root / name for name in theirs}

    # 🔴 Другий білий список — на прийманні: лише названі прогони, лише
    # текст і мета. Геометрія приїжджає окремим пакетом і лягає лише при
    # точній прив'язці (`accept_geometry`); у текстовому пакеті вона — ні.
    # Пакет схеми 1 ніс геометрію всередині, і для нього вона лишається.
    allowed = {bundle.META_NAME}
    old_schema = seen.manifest.schema < bundle.SCHEMA and seen.alignment.can_crop
    key = _local_key(seen.manifest)
    case_dir = align.case_dir_for(key) if key else None
    content = str(seen.manifest.decode.get("content_sha256") or "")
    voices = {str(v.get("run")): v for v in seen.manifest.voices}
    # 🔴 Сторінки пакета названі іменами кадрів ДОНОРА. Якщо та сама справа на
    # цій машині лежить під іншими іменами, текст не знаходив свого скана: він
    # був у прогоні, а аркуш до нього показати було нічим. Імена переводяться
    # на місцеві лише там, де тотожність кадрів доведена id джерела.
    names = (align.page_names(seen.frames, case_dir)
             if seen.alignment.label == align.EXACT else {})
    names = {a: b for a, b in names.items() if a != b}

    # 🔴 Розпакування, позначка й заміна — у тимчасовій сусідній теці, а на
    # місце прогону тека стає ОДНИМ перейменуванням. Доти старе стиралось,
    # новий текст лягав просто в `reports/htr/<прогін>/`, а позначка `shared`
    # ставилась останньою: обрив між цими кроками (Ctrl+C, повний диск)
    # лишав чужий текст без позначки — він читався як власна робота людини, а
    # повторний `import --force` відмовляв «вони ВАШІ» (аудит 29.09.2026).
    htr_root.mkdir(parents=True, exist_ok=True)
    stage = htr_root / f"{_STAGE_PREFIX}{os.getpid()}-{time.time_ns()}"
    clean = True
    try:
        staged = bundle.extract(
            seen.path, stage, runs=set(runs),
            keep=lambda n: (n in allowed or n.endswith(".txt")
                            or (old_schema and n.endswith(".lines.json"))))
        if not staged:
            raise AcceptError("у пакеті не виявилось жодного прогону")
        for d in staged:
            # 🔴 Позначки — ЛИШЕ на теки, які щойно лягли з пакета. Доти штампи
            # обходили ще й «голоси» `<прогін>-*`, тобто сусідні ВЛАСНІ прогони
            # людини: вони діставали чужу шифру й позначку «прийнято з пакета».
            _stamp_run(d, seen.manifest, seen.path, voice=voices.get(d.name) or {},
                       key=key, case_dir=case_dir, content=content,
                       alignment=seen.alignment.label, names=names,
                       frames=seen.frames)
        dirs, clean = _swap_in(stage, staged, htr_root, previous)
    finally:
        # Не вдалось перенести з відсунутої теки щось, що не з пакета, — тоді
        # вона лишається в `stage`: це чиясь робота, і стирати її не нам.
        if clean:
            shutil.rmtree(stage, ignore_errors=True)
    stamped_key = len(dirs) if key else 0
    stamped_dir = len(dirs) if case_dir is not None else 0

    proof = ""
    # Завантажене з адреси йде в доказ завжди: робоча тека чиститься, і
    # журнал інакше вказував би на файл, якого вже немає.
    if keep_bundle or seen.downloaded:
        proof = str(journal.keep(seen.path, seen.path.name))

    journal.record(
        journal.IMPORTED, shifra=seen.manifest.shifra, case_key=key,
        pages=seen.manifest.pages, bytes=seen.path.stat().st_size,
        sha256=bundle.sha256_of(seen.path),
        publisher=str((seen.manifest.publisher or {}).get("handle") or ""),
        contact=str((seen.manifest.publisher or {}).get("contact") or ""),
        source=str(src), path=proof or str(seen.path),
        alignment=seen.alignment.label, runs=[d.name for d in dirs])

    return {
        "runs": [d.name for d in dirs],
        "shifra": seen.manifest.shifra,
        "case_key": key,
        "pages": seen.manifest.pages,
        "alignment": seen.alignment.as_json(),
        # Скільки сторінок перейшло на імена місцевих кадрів (за id джерела).
        "renamed": len(names),
        "stamped_key": stamped_key,
        "stamped_case_dir": stamped_dir,
        "proof": proof,
        "gates": seen.verdict.as_json(),
        "note": seen.manifest.note,
        "publisher": seen.manifest.publisher,
        # 🔴 Версія формату віддається назовні, бо в пакеті схеми 1 ті самі
        # поля означають інше: геометрія лежала всередині, а `Voice.geometry`
        # казав «пакувальник її туди поклав». Розкладається такий пакет
        # правильно (рамки лягають разом із текстом, `extract` їх не
        # фільтрує), але мовчки прийняти його за новий не можна — саме на це
        # поле версії й заведене.
        "schema": seen.manifest.schema,
    }


def accept_geometry(src: str, *, force: bool = False, keep_bundle: bool = False,
                    reindex: bool = True, sha256: str = "") -> dict[str, Any]:
    """Докласти геометрію рядків до вже прийнятого тексту.

    Окрема функція, а не прапорець в `accept()`, бо гард у тієї протилежний:
    вона відмовляє, коли прогін уже є, а тут прогін УЖЕ МУСИТЬ бути. Геометрія
    без тексту марна: рамки рядків нема на що класти.

    🔴 Позначка `shared` не чіпається. Її поставив текстовий імпорт, і вона
    каже, ЧИЙ ТЕКСТ лежить у теці. Переписана іменем geom-файла, вона
    відповідала б на інше питання — «звідки рамки», — і доказ походження
    тексту зник би.
    """
    downloaded = _is_url(src)
    path = fetch(src, _download_dir(), sha256=sha256)
    try:
        return _accept_geometry_at(path, src, force=force, reindex=reindex,
                                   keep_bundle=keep_bundle or downloaded)
    finally:
        if downloaded:
            _drop_download(path)


def _accept_geometry_at(path: Path, src: str, *, force: bool, reindex: bool,
                        keep_bundle: bool) -> dict[str, Any]:
    from nyshporka.cloud.verify import read_meta
    from nyshporka.core.workspace import workspace

    try:
        manifest = bundle.read_manifest(path)
        inv = bundle.inventory(path)
    except bundle.BundleError as exc:
        raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc
    if inv.problems:
        raise AcceptError("пакет не можна розкласти:\n"
                          + "\n".join(f"✗ {p}" for p in inv.problems[:20]))

    lezhyt = [(run, name) for run, files in inv.runs.items()
              for name in files if name.endswith(".lines.json")]
    if not lezhyt:
        raise AcceptError(
            f"у {path.name} немає геометрії. Текст приймається інакше: "
            f"nysh share import {path.name}")

    htr_root = workspace().htr_reports
    runs = sorted({run for run, _ in lezhyt})
    nemaie = [r for r in runs if not (htr_root / r).is_dir()]
    if nemaie:
        raise AcceptError(
            f"геометрія без тексту марна — спершу прийміть текст. "
            f"Немає прогонів: {', '.join(nemaie)}")

    # 🔴 Лягає лише в прогін, ПРИЙНЯТИЙ із того самого внеску. Доти вистачало,
    # щоб тека існувала: рамки незнайомця лягали поруч із власним текстом
    # людини, і кроп її прочитання різав за чужими координатами.
    content = str(manifest.decode.get("content_sha256") or "")
    for r in runs:
        mark = read_meta(htr_root / r).get("shared")
        if not isinstance(mark, dict):
            raise AcceptError(
                f"прогін {r} — ваш власний, а не прийнятий із Супряги. Чужа "
                f"геометрія лягає лише до чужого тексту, з яким вона приїхала")
        theirs = str(mark.get("content_sha256") or "")
        if content and theirs and content != theirs:
            raise AcceptError(
                f"геометрія від іншого тексту, ніж прийнятий у {r} "
                f"(хеш змісту не збігається) — рамки лягли б не на ті рядки")
        if (not content or not theirs) and str(mark.get("shifra") or "") != manifest.shifra:
            raise AcceptError(
                f"геометрія для «{manifest.shifra}», а в {r} прийнято "
                f"«{mark.get('shifra')}»")
        label = str(mark.get("alignment") or "")
        if label and label != align.EXACT and not force:
            raise AcceptError(
                f"текст у {r} прив'язано як «{label}», а не «{align.EXACT}»: рамки "
                f"прив'язані до пікселів чужої зйомки й на ваших кадрах різали б "
                f"не ті рядки. Покласти попри це: --force")

    # Текст цього прогону міг лягти під іменами місцевих кадрів — тоді й рамки
    # лягають під ними ж.
    stems: dict[str, dict[str, str]] = {}
    for r in runs:
        got = (read_meta(htr_root / r).get("shared") or {}).get("page_stems")
        stems[r] = {str(a): str(b) for a, b in got.items()} if isinstance(got, dict) else {}

    def _misceve(run: str, name: str) -> str:
        stem = name[: -len(".lines.json")]
        return f"{stems[run].get(stem, stem)}.lines.json"

    poverkh = sorted(f"{run}/{_misceve(run, name)}" for run, name in lezhyt
                     if (htr_root / run / _misceve(run, name)).is_file())
    if poverkh and not force:
        raise AcceptError(
            f"геометрія для цих сторінок уже є ({len(poverkh)}, напр. "
            f"{poverkh[0]}). Перезаписати: --force")

    # 🔴 Другий білий список — тут, на прийманні. Пакувальник кладе в
    # geom-пакет лише `*.lines.json`, але чужому tar це не зобов'язання:
    # підкинутий `_htr_meta.json` перетер би позначку походження тексту.
    stage = htr_root / f"{_STAGE_PREFIX}{os.getpid()}-{time.time_ns()}"
    try:
        staged = bundle.extract(path, stage, runs=set(runs),
                                keep=lambda n: n.endswith(".lines.json"))
        if not staged:
            raise AcceptError("геометрія не лягла: у пакеті не виявилось прогонів")
        dirs = []
        for d in staged:
            for f in sorted(d.iterdir()):
                f.replace(htr_root / d.name / _misceve(d.name, f.name))
            dirs.append(htr_root / d.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    indexed = _reindex(dirs) if reindex else []

    proof = str(journal.keep(path, path.name)) if keep_bundle else ""
    journal.record(
        journal.GEOMETRY, shifra=manifest.shifra, case_key=_local_key(manifest),
        pages=len(lezhyt), bytes=path.stat().st_size,
        sha256=bundle.sha256_of(path),
        publisher=str((manifest.publisher or {}).get("handle") or ""),
        source=str(src), path=proof or str(path),
        runs=[d.name for d in dirs])

    return {
        "runs": [d.name for d in dirs],
        "shifra": manifest.shifra,
        "pages": len(lezhyt),
        "overwritten": len(poverkh),
        "indexed": indexed,
        "proof": proof,
    }


def _reindex(dirs: list[Path]) -> list[str]:
    """Перебудувати стор для тек, у які щойно лягла геометрія.

    🔴 Обов'язково `force`. Свіжість прогону міряється штампом «мета плюс
    тека», і поява нового файлу час теки міняє — але ПЕРЕЗАПИС наявного
    `*.lines.json` не міняє нічого: вміст файлу в штамп не входить. Тобто
    без примусу саме повторне докладання геометрії — те, заради якого людина
    покликала `--force`, — тихо не доїхало б до пошуку.

    🔴 А переіндекс потрібен узагалі тому, що рамки ВМЕРЗАЮТЬ у SQLite під
    час індексації. Файли лежать поруч із текстом, а кроп читає стор — і без
    цього кроку геометрія була б на диску й не працювала.
    """
    from nyshporka.search import store as ST

    if not ST.path().is_file():
        # Стору ще немає: перша ж `nysh text index` збере його разом із
        # геометрією. Заводити стор заради одного прогону — не наше рішення.
        return []
    return list(ST.ensure_all([d.name for d in dirs], force=True))


def _rename_pages(run_dir: Path, names: dict[str, str]) -> dict[str, str]:
    """Перевести файли сторінок на імена місцевих кадрів. Повертає стем → стем.

    Два проходи через тимчасові імена: відповідність — перестановка, і ім'я,
    яке одна сторінка звільняє, інша може в ту ж мить займати.
    """
    stems = {Path(a).stem: Path(b).stem for a, b in names.items()}
    stems = {a: b for a, b in stems.items() if a != b}
    moved: list[tuple[Path, Path]] = []
    for a, b in stems.items():
        for suffix in _PAGE_SUFFIXES:
            src = run_dir / f"{a}{suffix}"
            if src.is_file():
                tmp = run_dir / f".nysh-rename-{len(moved)}{suffix}"
                src.rename(tmp)
                moved.append((tmp, run_dir / f"{b}{suffix}"))
    for tmp, dst in moved:
        tmp.replace(dst)
    return stems


def _page_src(m: Manifest, frames: list[dict[str, Any]],
              names: dict[str, str]) -> dict[str, str]:
    """Сторінка (наше ім'я) → id скана в джерелі — для джерел, які вміють
    показати окремий скан (Сканотека: `185R` → скан 185, права сторінка).

    Лише для таких: в інших джерел id кадру вже є в імені файла чи в нашому
    переліку кадрів, і мета на 2000 сторінок розрослась би без потреби.
    """
    from nyshporka.core import skanoteka, szukaj

    if not any(isinstance(r, dict) and r.get("source") in (skanoteka.SOURCE, szukaj.SOURCE)
               for r in m.refs or []):
        return {}
    out: dict[str, str] = {}
    for f in frames:
        name, src = str(f.get("name") or ""), str(f.get("src") or "")
        if name and src:
            out[names.get(name, name)] = src
    return out


#: Файли однієї сторінки прогону: текст і рамки рядків.
_PAGE_SUFFIXES = (".txt", ".lines.json")


def _stamp_run(run_dir: Path, m: Manifest, src: Path, *, voice: dict[str, Any],
               key: str, case_dir: Path | None, content: str,
               alignment: str, names: dict[str, str] | None = None,
               frames: list[dict[str, Any]] | None = None) -> None:
    """Підготувати мету прийнятого прогону: чистка, шифра, тека кадрів, позначка.

    Один прохід на теку, а не три штампи поспіль: кожен із них окремо
    обходив ще й сусідні теки `<прогін>-*` (див. `accept`).

    🔴 Чужа мета чиститься тим самим білим списком, що й на пакувальнику
    (`bundle.clean_meta`): пакет міг зібрати не наш пакувальник, і в ньому
    лишились би `case_dir` на мережеву теку чи робочі нотатки чужої машини.

    🔴 Мети в пакеті може не бути зовсім — тоді вона ЗАВОДИТЬСЯ з голосу
    маніфесту. Без неї тека не мала б позначки `shared` і читалась би як
    власна робота людини.

    Позначка живе в меті, а не в окремому реєстрі, навмисно: мета переїжджає
    разом із текою, і прогін, пересунутий руками, не перестає бути чужим.
    """
    from nyshporka.cloud.verify import META_NAME
    from nyshporka.utils.atomic import CorruptFileError, read_json, write_json

    path = run_dir / META_NAME
    try:
        raw = read_json(path, default={})
    except CorruptFileError:
        raw = {}
    meta = bundle.clean_meta(raw if isinstance(raw, dict) else {})
    for field_ in ("model", "engine", "script"):
        if not meta.get(field_) and voice.get(field_):
            meta[field_] = str(voice[field_])
    # 🔴 Ключ справи — лише наш. Чужий `case_key` пережив би `clean_meta` (він у
    # білому списку, бо потрібен отримувачу, у якого шифра розв'язалась), і
    # прогін з нерозв'язаною шифрою приєднався б до справи, яку назвав
    # відправник: його сторінки рахувались би покриттям нашої справи, а нуль
    # по ній — довіреним (аудит 29.09.2026).
    if key:
        meta["case_key"] = key
    else:
        meta.pop("case_key", None)
    if case_dir is not None:
        meta["case_dir"] = str(case_dir).replace("\\", "/")
    stems = _rename_pages(run_dir, names or {})
    if names and isinstance(meta.get("pages"), dict):
        meta["pages"] = {names.get(str(k), str(k)): v for k, v in meta["pages"].items()}
    mark: dict[str, Any] = {
        "from": str((m.publisher or {}).get("handle") or ""),
        "contact": str((m.publisher or {}).get("contact") or ""),
        "bundle": src.name,
        "shifra": m.shifra,
        "license": str((m.license or {}).get("text") or ""),
        # Чим звірити геометрію, що доїде другим пакетом: вона мусить бути
        # від ТОГО САМОГО тексту (`accept_geometry`).
        "content_sha256": content,
        "alignment": alignment,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        # Знаменник автора пакета й причина, з якої прочитано не все. Доти
        # вони лишались у пакеті-доказі: уривок на 14% після прийому нічим не
        # відрізнявся від прочитаної справи.
        "pages": m.pages,
        "frames": m.frames_total,
        "partial": _partial_note(m),
        # Стем сторінки в пакеті → стем на цій машині. Геометрія, що доїде
        # другим пакетом, названа так само, як був названий текст, і мусить
        # лягти під ті самі нові імена (`accept_geometry`).
        "page_stems": stems,
        # Звідки скани: без цього прийнятий текст не мав куди послати людину
        # звіряти сторінку з оригіналом, хоч пакет це знав.
        "refs": [r for r in (m.refs or []) if isinstance(r, dict)],
        "page_src": _page_src(m, frames or [], names or {}),
    }
    meta["shared"] = {k: v for k, v in mark.items() if v}
    write_json(path, meta)
