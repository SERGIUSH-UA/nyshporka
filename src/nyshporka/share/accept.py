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


def fetch(src: str, dest_dir: Path) -> Path:
    """Взяти пакет: локальний шлях — як є, адреса — завантажити поруч."""
    if not str(src).lower().startswith(("http://", "https://")):
        p = Path(src)
        if not p.is_file():
            raise AcceptError(f"пакета немає: {p}")
        return p
    from nyshporka.sources.http import Fetcher, HttpError, app_ua

    dest = Path(dest_dir) / _name_for(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Свій рядок, а не браузерний: качається пакет із нашого ж сховища,
        # і в його логах клієнт мусить бути відрізнимий від людини. Докладно
        # — у `share/upload.py`.
        Fetcher(headers={"User-Agent": app_ua()}).download(src, dest)
    except HttpError as exc:
        raise AcceptError(f"не завантажити {src}: {exc}") from exc
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


def look(src: str, *, hash_frames: bool = False) -> Look:
    """Подивитись пакет, не розпаковуючи: заява, ворота, ступінь прив'язки."""
    path = fetch(src, journal.inbox())
    try:
        manifest = bundle.read_manifest(path)
    except (OSError, ValueError, bundle.BundleError) as exc:
        raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc
    frames = bundle.read_frames(path)
    verdict = gates.check(manifest, partial_why=_partial_note(manifest))
    key = str(manifest.case.get("key_local") or "")
    local = _local_key(manifest) or key
    case_dir = align.case_dir_for(local) if local else None
    # Відбиток лежить у шапці кадрів маніфесту. Старий пакет його не має —
    # тоді прив'язка міряється як раніше, за іменами й кількістю.
    their_fp = manifest.frames.get("fingerprint")
    grade = align.grade(frames, case_dir, hash_frames=hash_frames,
                        their_fp=their_fp if isinstance(their_fp, dict) else None)
    return Look(path=path, manifest=manifest, verdict=verdict, frames=frames,
                alignment=grade)


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


def accept(src: str, *, hash_frames: bool = False, force: bool = False,
           keep_bundle: bool = True) -> dict[str, Any]:
    """Покласти пакет до себе. Повертає, що саме лягло і як воно прив'язалось."""
    from nyshporka.cloud.run import stamp_case_dir, stamp_case_key
    from nyshporka.core.workspace import workspace

    seen = look(src, hash_frames=hash_frames)
    if not seen.verdict.passed and not force:
        raise AcceptError(
            "ворота не пропустили пакет:\n" + gates.describe(seen.verdict)
            + "\nПрийняти попри це: --force")

    htr_root = workspace().htr_reports
    existing = {d.name for d in htr_root.iterdir()} if htr_root.is_dir() else set()
    incoming = bundle.run_names(seen.path)
    clash = sorted(existing & set(incoming))
    if clash and not force:
        raise AcceptError(
            f"прогони з такими іменами вже є: {', '.join(clash)}. Прийняти "
            f"поверх: --force")

    dirs = bundle.extract(seen.path, htr_root)
    if not dirs:
        raise AcceptError("у пакеті не виявилось жодного прогону")

    key = _local_key(seen.manifest)
    case_dir = align.case_dir_for(key) if key else None
    stamped_key = stamped_dir = 0
    for d in dirs:
        if key:
            stamped_key += stamp_case_key(d, key)
        if case_dir is not None:
            stamped_dir += stamp_case_dir(d, case_dir)
        _stamp_shared(d, seen.manifest, seen.path)

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
                    reindex: bool = True) -> dict[str, Any]:
    """Докласти геометрію рядків до вже прийнятого тексту.

    Окрема функція, а не прапорець в `accept()`, бо гард у тієї протилежний:
    вона відмовляє, коли прогін уже є, а тут прогін УЖЕ МУСИТЬ бути. Геометрія
    без тексту марна: рамки рядків нема на що класти.

    🔴 Позначка `shared` не чіпається. Її поставив текстовий імпорт, і вона
    каже, ЧИЙ ТЕКСТ лежить у теці. Переписана іменем geom-файла, вона
    відповідала б на інше питання — «звідки рамки», — і доказ походження
    тексту зник би.
    """
    from nyshporka.core.workspace import workspace

    path = fetch(src, journal.inbox())
    try:
        manifest = bundle.read_manifest(path)
    except (OSError, ValueError, bundle.BundleError) as exc:
        raise AcceptError(f"не прочитати пакет {path.name}: {exc}") from exc

    lezhyt = [(run, name) for run, name in bundle.members(path)
              if name.endswith(".lines.json")]
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

    poverkh = sorted(f"{run}/{name}" for run, name in lezhyt
                     if (htr_root / run / name).is_file())
    if poverkh and not force:
        raise AcceptError(
            f"геометрія для цих сторінок уже є ({len(poverkh)}, напр. "
            f"{poverkh[0]}). Перезаписати: --force")

    # 🔴 Другий білий список — тут, на прийманні. Пакувальник кладе в
    # geom-пакет лише `*.lines.json`, але чужому tar це не зобов'язання:
    # підкинутий `_htr_meta.json` перетер би позначку походження тексту.
    dirs = bundle.extract(path, htr_root, keep=lambda n: n.endswith(".lines.json"))
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


def _stamp_shared(run_dir: Path, m: Manifest, src: Path) -> None:
    """Позначити прогін чужим — у ньому самому й у теках голосів.

    Позначка живе в меті, а не в окремому реєстрі, навмисно: мета переїжджає
    разом із текою, і прогін, пересунутий руками, не перестає бути чужим.
    """
    from nyshporka.cloud.verify import META_NAME, voice_dirs
    from nyshporka.utils.atomic import CorruptFileError, read_json, write_json

    mark = {
        "from": str((m.publisher or {}).get("handle") or ""),
        "contact": str((m.publisher or {}).get("contact") or ""),
        "bundle": src.name,
        "shifra": m.shifra,
        "license": str((m.license or {}).get("text") or ""),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    mark = {k: v for k, v in mark.items() if v}
    for d in (run_dir, *voice_dirs(run_dir)):
        path = d / META_NAME
        if not path.is_file():
            continue
        try:
            meta = read_json(path, default=None)
        except CorruptFileError:
            continue
        if not isinstance(meta, dict):
            continue
        meta["shared"] = mark
        write_json(path, meta)
