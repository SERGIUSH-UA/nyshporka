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
    from nyshporka.sources.http import Fetcher, HttpError

    name = str(src).rstrip("/").rsplit("/", 1)[-1] or ("bundle" + bundle.SUFFIX)
    if not name.endswith(bundle.SUFFIX):
        name += bundle.SUFFIX
    dest = Path(dest_dir) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        Fetcher().download(src, dest)
    except HttpError as exc:
        raise AcceptError(f"не завантажити {src}: {exc}") from exc
    return dest


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
    grade = align.grade(frames, case_dir, hash_frames=hash_frames)
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
    }


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
