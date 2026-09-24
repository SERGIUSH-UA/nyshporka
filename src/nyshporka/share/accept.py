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

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.share import align, bundle, gates, journal
from nyshporka.share.bundle import Manifest


class AcceptError(RuntimeError):
    """Пакет не прийняти — з названою причиною."""


@dataclass
class Look:
    """Що видно в пакеті до того, як його розпаковано."""

    path: Path
    manifest: Manifest
    verdict: gates.Verdict
    frames: list[dict[str, Any]]
    alignment: align.Alignment
    inventory: bundle.Inventory | None = None

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


def fetch(src: str, dest_dir: Path, *, sha256: str = "") -> Path:
    """Взяти пакет: локальний шлях — як є, адреса — завантажити поруч.

    `sha256` — що обіцяв рядок каталогу. 🔴 Звіряється тут, бо `download`
    звірку покладає на того, хто кличе: без неї підмінений або обірваний
    пакет з пулу приймався б як той, що в каталозі.
    """
    if not str(src).lower().startswith(("http://", "https://")):
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
        Fetcher(headers={"User-Agent": app_ua()}).download(
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
    """
    path = fetch(src, journal.inbox(), sha256=sha256)
    try:
        manifest = bundle.read_manifest(path)
        frames = bundle.read_frames(path)
        inv = bundle.inventory(path)
    except bundle.BundleError as exc:
        raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc
    verdict = gates.Verdict()
    for why in inv.problems[:20]:
        verdict.refuse(f"вада пакета: {why}")
    if len(inv.problems) > 20:
        verdict.refuse(f"… і ще {len(inv.problems) - 20} вад пакета")
    if texts:
        try:
            _measure(path, inv, manifest, verdict)
        except bundle.BundleError as exc:
            raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc
    else:
        got = gates.check(manifest, partial_why=_partial_note(manifest))
        verdict.refusals += got.refusals
        verdict.warnings += got.warnings
    key = str(manifest.case.get("key_local") or "")
    local = _local_key(manifest) or key
    case_dir = align.case_dir_for(local) if local else None
    # Відбиток лежить у шапці кадрів маніфесту. Старий пакет його не має —
    # тоді прив'язка міряється як раніше, за іменами й кількістю.
    their_fp = manifest.frames.get("fingerprint")
    grade = align.grade(frames, case_dir, hash_frames=hash_frames,
                        their_fp=their_fp if isinstance(their_fp, dict) else None)
    return Look(path=path, manifest=manifest, verdict=verdict, frames=frames,
                alignment=grade, inventory=inv)


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
        v.refuse(f"маніфест називає голоси, яких у пакеті немає: {', '.join(nemaie[:5])}")
    raw = bundle.read_texts(path, inv, runs=[r for r in voices if r in inv.runs])
    for voice in m.voices:
        run = str(voice.get("run") or "")
        claim = str(voice.get("content_sha256") or "")
        if claim and run in raw and bundle.text_hash(raw[run]) != claim:
            v.refuse(f"голос {run}: хеш змісту не збігається з тим, що заявляє "
                     f"маніфест — тексти в пакеті не ті")
    counted = bundle.tally(bundle.decoded(raw), voices)
    zaiava = m.pages
    if zaiava > counted["pages"]:
        v.refuse(f"маніфест заявляє {zaiava} прочитаних сторінок, а в пакеті "
                 f"їх {counted['pages']}")
    # Далі ворота бачать ВИМІРЯНЕ: той самий маніфест, але з числами з диска.
    probe = copy.copy(m)
    probe.decode = {**m.decode, **counted}
    got = gates.check(probe, partial_why=_partial_note(m))
    v.refusals += got.refusals
    v.warnings += got.warnings


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
    existing = {d.name.casefold(): d for d in htr_root.iterdir() if d.is_dir()}
    own: list[str] = []
    theirs: list[str] = []
    for name in incoming:
        d = existing.get(name.casefold())
        if d is None:
            continue
        (theirs if _is_shared(d) else own).append(d.name)
    return sorted(own), sorted(theirs)


def _clear_run(run_dir: Path) -> None:
    """Прибрати файли раніше прийнятого прогону перед заміною на новий.

    Лише те, що могло приїхати пакетом (текст, мета, геометрія): інакше
    `--force` лишав би сторінки старого пакета поруч із новими, і тека
    стала б сумішшю двох чужих прочитань під позначкою одного.
    """
    for pat in (bundle.PACKED_TEXT, bundle.PACKED_GEOMETRY, bundle.META_NAME):
        for f in run_dir.glob(pat):
            if f.is_file():
                f.unlink()


def accept(src: str, *, hash_frames: bool = False, force: bool = False,
           keep_bundle: bool = True, sha256: str = "") -> dict[str, Any]:
    """Покласти пакет до себе. Повертає, що саме лягло і як воно прив'язалось."""
    from nyshporka.core.workspace import workspace

    seen = look(src, hash_frames=hash_frames, sha256=sha256)
    inv = seen.inventory or bundle.Inventory()
    if inv.problems:
        # Вади пакета (шляхи, спецфайли, стелі) не знімаються `--force`:
        # це не питання довіри до тексту, а питання, чи можна його класти
        # на диск узагалі.
        raise AcceptError("пакет не можна розкласти:\n"
                          + "\n".join(f"✗ {p}" for p in inv.problems[:20]))
    if not seen.verdict.passed and not force:
        raise AcceptError(
            "ворота не пропустили пакет:\n" + gates.describe(seen.verdict)
            + "\nПрийняти попри це: --force")

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
    if theirs and not force:
        raise AcceptError(
            f"прогони з такими іменами вже прийнято раніше: {', '.join(theirs)}. "
            f"Замінити новим пакетом: --force")
    for name in theirs:
        _clear_run(htr_root / name)

    # 🔴 Другий білий список — на прийманні: лише названі прогони, лише
    # текст і мета. Геометрія приїжджає окремим пакетом і лягає лише при
    # точній прив'язці (`accept_geometry`); у текстовому пакеті вона — ні.
    # Пакет схеми 1 ніс геометрію всередині, і для нього вона лишається.
    allowed = {bundle.META_NAME}
    old_schema = seen.manifest.schema < bundle.SCHEMA and seen.alignment.can_crop
    dirs = bundle.extract(
        seen.path, htr_root, runs=set(runs),
        keep=lambda n: (n in allowed or n.endswith(".txt")
                        or (old_schema and n.endswith(".lines.json"))))
    if not dirs:
        raise AcceptError("у пакеті не виявилось жодного прогону")

    key = _local_key(seen.manifest)
    case_dir = align.case_dir_for(key) if key else None
    content = str(seen.manifest.decode.get("content_sha256") or "")
    voices = {str(v.get("run")): v for v in seen.manifest.voices}
    for d in dirs:
        # 🔴 Позначки — ЛИШЕ на теки, які щойно лягли з пакета. Доти штампи
        # обходили ще й «голоси» `<прогін>-*`, тобто сусідні ВЛАСНІ прогони
        # людини: вони діставали чужу шифру й позначку «прийнято з пакета».
        _stamp_run(d, seen.manifest, seen.path, voice=voices.get(d.name) or {},
                   key=key, case_dir=case_dir, content=content,
                   alignment=seen.alignment.label)
    stamped_key = len(dirs) if key else 0
    stamped_dir = len(dirs) if case_dir is not None else 0

    proof = ""
    if keep_bundle:
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
    from nyshporka.cloud.verify import read_meta
    from nyshporka.core.workspace import workspace

    path = fetch(src, journal.inbox(), sha256=sha256)
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

    poverkh = sorted(f"{run}/{name}" for run, name in lezhyt
                     if (htr_root / run / name).is_file())
    if poverkh and not force:
        raise AcceptError(
            f"геометрія для цих сторінок уже є ({len(poverkh)}, напр. "
            f"{poverkh[0]}). Перезаписати: --force")

    # 🔴 Другий білий список — тут, на прийманні. Пакувальник кладе в
    # geom-пакет лише `*.lines.json`, але чужому tar це не зобов'язання:
    # підкинутий `_htr_meta.json` перетер би позначку походження тексту.
    dirs = bundle.extract(path, htr_root, runs=set(runs),
                          keep=lambda n: n.endswith(".lines.json"))
    if not dirs:
        raise AcceptError("геометрія не лягла: у пакеті не виявилось прогонів")

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


def _stamp_run(run_dir: Path, m: Manifest, src: Path, *, voice: dict[str, Any],
               key: str, case_dir: Path | None, content: str,
               alignment: str) -> None:
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
    if key:
        meta["case_key"] = key
    if case_dir is not None:
        meta["case_dir"] = str(case_dir).replace("\\", "/")
    mark = {
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
    }
    meta["shared"] = {k: v for k, v in mark.items() if v}
    write_json(path, meta)
