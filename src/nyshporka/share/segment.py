"""✂ Справа, якої один пакет не вміщує: частини → сегменти → пакети одного внеску.

Картотека на 272 288 кадрів (24+ алфавітні підтеки, два-три голоси) — це одна
архівна справа, але понад півмільйона файлів тексту. Пул приймає пакет до
`POOL_MAX_MEMBERS` файлів і `POOL_MAX_TEXT_BYTES` байтів, і ці стелі не
піднімаються: ними пул тримає пам'ять під час розбору пакета.

Тому справа їде кількома пакетами, і кожен знає, що він — сегмент
(`case.segment`): пул зводить їх в одну книгу й сумує прочитане, а не
показує 40 «справ» з однаковою шифрою.

Три поняття, і вони не змішуються:

* **частина** (`Part`) — тека кадрів, яку читали прогони справи (алфавітна
  підтека), разом з усіма голосами, що її читали. Голоси однієї частини завжди
  їдуть разом: пакет із одним голосом частини виглядав би повним прочитанням;
* **шматок** (`Piece`) — частина цілком або, коли сама вона пакета не вміщує,
  діапазон її сторінок;
* **сегмент** (`Segment`) — суміжні шматки, що вкладаються в стелі. Один
  сегмент = один пакет.

🔴 Сторінки в пакеті сегмента звуться `<частина>__<сторінка>`: у кожній підтеці
своє `0001.txt`, і без префікса знаменник (`bundle.tally` — об'єднання імен у
межах моделі) рахував би 40 частин як одну, а приймач клав би їх одна на одну.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from nyshporka.share import align, bundle

#: Стелі пулу (`nyshporka-online`: `app/tekst.py` MAX_CHLENIV, `app/config.py`
#: max_text_bytes). Клієнт звіряється з ними ДО заливки: пакет, що їх
#: перевищує, інакше падав уже на сервері, після того як байти доїхали.
POOL_MAX_MEMBERS = 20_000
POOL_MAX_TEXT_BYTES = 64 << 20

#: Ціль сегмента — з запасом під стелі: файли рахуються точно, а байти після
#: стискання відомі лише по запису (`publish.pack_segments` звіряє й ділить).
SEG_MAX_FILES = 18_000
#: Сирий текст: gzip бере його в 3–5 разів, тож 128 МБ сирого — ~30–40 МБ пакета.
SEG_MAX_RAW = 128 << 20

#: Схема маніфесту сегментованого пакета. Звичайні пакети лишаються на
#: `bundle.SCHEMA_PLAIN`, щоб старі клієнти брали їх без оновлення; сегмент
#: старий клієнт відкидає явно — поклав би його як цілу справу.
SCHEMA_SEGMENT = 3

#: Роздільник частини й сторінки в іменах файлів сегмента.
SEP = "__"

#: Службові файли пакета поза текстами: маніфест, README, перелік кадрів.
_TOP_FILES = 3

#: Мітка сегмента в імені прогону: `<прогін>.s.<ключ сегмента>`. Крапка, а не
#: дефіс: `<прогін>-*` — це сестринські голоси (`cloud.verify.voice_dirs`), і
#: сегменти стали б «голосами» головного прогону.
RUN_MARK = ".s."


def run_name(run: str, key: str) -> str:
    """Ім'я прогону сегмента — те саме в пакеті й у того, хто його прийняв."""
    return bundle.safe_name(run, default="run") + RUN_MARK + bundle.safe_name(key, default="seg")


def is_segment_run(name: str, key: str) -> bool:
    return name.endswith(RUN_MARK + bundle.safe_name(key, default="seg"))


@dataclass
class Part:
    """Тека кадрів справи й голоси, що її читали."""

    label: str
    frames_dir: Path | None
    runs: list[Path] = field(default_factory=list)
    #: {прогін: [імена txt]}
    pages: dict[str, list[str]] = field(default_factory=dict)
    #: {прогін: модель}
    models: dict[str, str] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return bundle.safe_name(self.label, default="part")

    @property
    def stems(self) -> list[str]:
        """Усі сторінки частини (об'єднання голосів), у порядку імен."""
        seen: set[str] = set()
        for names in self.pages.values():
            seen.update(Path(n).stem for n in names)
        return sorted(seen)


@dataclass
class Piece:
    """Частина цілком (`stems is None`) або діапазон її сторінок."""

    part: Part
    stems: list[str] | None = None
    #: 1-based номер шматка частини, що не влізла цілою; 0 — частина ціла.
    n: int = 0
    of: int = 0

    def names(self, run: str) -> list[str]:
        all_names = self.part.pages.get(run) or []
        if self.stems is None:
            return list(all_names)
        want = set(self.stems)
        return [n for n in all_names if Path(n).stem in want]

    @cached_property
    def files(self) -> int:
        return sum(len(self.names(r.name)) for r in self.part.runs)

    @cached_property
    def models(self) -> frozenset[str]:
        return frozenset(self.part.models.get(r.name, "") for r in self.part.runs)

    @cached_property
    def raw_bytes(self) -> int:
        total = 0
        for r in self.part.runs:
            for n in self.names(r.name):
                try:
                    total += (r / n).stat().st_size
                except OSError:
                    continue
        return total

    @property
    def label(self) -> str:
        base = clean_label(self.part.label)
        return f"{base} ({self.n}/{self.of})" if self.n else base


@dataclass
class Segment:
    """Один пакет внеску."""

    pieces: list[Piece]
    n: int = 0
    of: int = 0

    @property
    def models(self) -> list[str]:
        seen: list[str] = []
        for p in self.pieces:
            for r in p.part.runs:
                m = p.part.models.get(r.name, "")
                if m not in seen:
                    seen.append(m)
        return seen

    @property
    def key(self) -> str:
        """Стабільний ключ: перший шматок. Не номер — номери зсуваються."""
        first = self.pieces[0]
        return first.part.slug + (f"~{first.n}" if first.n else "")

    @property
    def label(self) -> str:
        return _join(self.pieces[0].label, self.pieces[-1].label)

    @property
    def files(self) -> int:
        # Тексти + мета на кожну модель + службові файли пакета.
        return sum(p.files for p in self.pieces) + len(self.models) + _TOP_FILES

    @property
    def raw_bytes(self) -> int:
        return sum(p.raw_bytes for p in self.pieces)

    @property
    def pages(self) -> int:
        return sum(len(p.stems if p.stems is not None else p.part.stems)
                   for p in self.pieces)

    def as_json(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "n": self.n, "of": self.of,
                "dirs": [p.part.label for p in self.pieces],
                "pages": self.pages, "files": self.files,
                "bytes_raw": self.raw_bytes, "models": self.models}


def _meta(d: Path) -> dict[str, Any]:
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(d / bundle.META_NAME, default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _family(name: str, names: list[str]) -> str:
    """Головний прогін для голосу `<прогін>-<тег>`: найдовший префікс із набору."""
    best = name
    for other in names:
        if other != name and name.startswith(other + "-") and len(other) < len(best):
            best = other
    return best


def parts_of(run_dirs: list[Path]) -> list[Part]:
    """Розкласти прогони справи на частини — за текою кадрів, яку вони читали.

    Тека кадрів — з мети (`case_dir`). Де її немає або вона чужа (слот
    хмарного боксу — `frames_dir_key` дає «»), частиною стає головний прогін
    разом із сестринськими голосами `<прогін>-<тег>`.
    """
    from nyshporka import htr_store as S

    names = [d.name for d in run_dirs]
    by_key: dict[str, Part] = {}
    order: list[str] = []
    for d in run_dirs:
        meta = _meta(d)
        raw_dir = str(meta.get("case_dir") or "")
        fkey = S.frames_dir_key(raw_dir) if raw_dir else ""
        if fkey:
            key = "f:" + fkey
            frames_dir: Path | None = Path(raw_dir)
            label = Path(raw_dir.replace("\\", "/")).name or d.name
        else:
            fam = _family(d.name, names)
            key, frames_dir, label = "r:" + fam, None, fam
        part = by_key.get(key)
        if part is None:
            part = by_key[key] = Part(label=label, frames_dir=frames_dir)
            order.append(key)
        part.runs.append(d)
        part.pages[d.name] = sorted(p.name for p in d.glob(bundle.PACKED_TEXT))
        part.models[d.name] = str(meta.get("model") or d.name)
    parts = [by_key[k] for k in order]
    # Порядок частин — за іменем, як у файловому менеджері: «Бан…» перед «Бас…».
    parts.sort(key=lambda p: p.label)
    _unique_slugs(parts)
    return parts


def _unique_slugs(parts: list[Part]) -> None:
    """Дві частини з однаковим безпечним іменем дали б однакові імена сторінок."""
    seen: dict[str, int] = {}
    for p in parts:
        s = p.slug
        if s in seen:
            seen[s] += 1
            p.label = f"{p.label} [{seen[s]}]"
        else:
            seen[s] = 1


def _pieces(part: Part, max_files: int, max_raw: int) -> list[Piece]:
    """Частина цілком або діапазонами сторінок, якщо сама не влазить."""
    whole = Piece(part)
    voices = max(1, len(part.runs))
    if whole.files + voices + _TOP_FILES <= max_files and whole.raw_bytes <= max_raw:
        return [whole]
    stems = part.stems
    per_file = max(1, (max_files - voices - _TOP_FILES) // voices)
    avg = whole.raw_bytes / max(1, len(stems))
    per_raw = max(1, int(max_raw / max(1.0, avg * voices)))
    step = max(1, min(per_file, per_raw))
    chunks = [stems[i:i + step] for i in range(0, len(stems), step)]
    return [Piece(part, stems=c, n=i, of=len(chunks))
            for i, c in enumerate(chunks, 1)]


def plan(parts: list[Part], *, max_files: int = SEG_MAX_FILES,
         max_raw: int = SEG_MAX_RAW) -> list[Segment]:
    """Жадібно зібрати суміжні шматки в сегменти під стелі."""
    segs: list[Segment] = []
    cur: list[Piece] = []
    files = raw = 0
    models: set[str] = set()
    for part in parts:
        for piece in _pieces(part, max_files, max_raw):
            # Розміри шматків рахуються раз: на 272 тис. сторінок перерахунок
            # усього сегмента на кожен крок — це мільйони `stat`.
            m = models | piece.models
            t_files = files + piece.files + len(m) + _TOP_FILES
            if cur and (t_files > max_files or raw + piece.raw_bytes > max_raw):
                segs.append(Segment(cur))
                cur, files, raw, models = [], 0, 0, set()
                m = set(piece.models)
            cur.append(piece)
            files += piece.files
            raw += piece.raw_bytes
            models = set(m)
    if cur:
        segs.append(Segment(cur))
    for i, s in enumerate(segs, 1):
        s.n, s.of = i, len(segs)
    return segs


def set_id(shifra: str, segs: list[Segment]) -> str:
    """Ідентифікатор набору: та сама справа, той самий поділ — той самий набір."""
    body = "\n".join([shifra, *(s.key for s in segs)])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def stage(seg: Segment, root: Path) -> list[Path]:
    """Теки прогонів сегмента: одна на модель, сторінки з префіксом частини.

    Жорсткі посилання, де диск їх дає, — копіювати пів мільйона дрібних
    файлів заради пакування нема чого. Стара тека стейджу зноситься: вона
    відтворюється з прогонів цілком.
    """
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    staged: dict[str, Path] = {}
    metas: dict[str, dict[str, Any]] = {}
    for piece in seg.pieces:
        part = piece.part
        for run in part.runs:
            model = part.models.get(run.name, run.name)
            d = staged.get(model)
            if d is None:
                d = root / run_name(run.name, seg.key)
                d.mkdir()
                staged[model] = d
                base = _meta(run)
                base["pages"] = {}
                base["frames_total"] = 0
                base.pop("case_dir", None)
                metas[model] = base
            src_pages = _meta(run).get("pages")
            src_pages = src_pages if isinstance(src_pages, dict) else {}
            stems = set()
            for name in piece.names(run.name):
                dst = d / f"{part.slug}{SEP}{name}"
                if dst.exists():
                    continue        # той самий аркуш двома прогонами моделі
                _link_or_copy(run / name, dst)
                stems.add(Path(name).stem)
            m = metas[model]
            for img, row in src_pages.items():
                if Path(str(img)).stem in stems:
                    m["pages"][f"{part.slug}{SEP}{img}"] = row
            m["frames_total"] = int(m.get("frames_total") or 0) + len(stems)
    for model, d in staged.items():
        (d / bundle.META_NAME).write_text(
            json.dumps(metas[model], ensure_ascii=False), encoding="utf-8")
    return list(staged.values())


def frames_for(seg: Segment, *, hash_frames: bool = False) -> list[dict[str, Any]]:
    """Перелік кадрів сегмента — лише його кадри, імена з префіксом частини.

    🔴 Не всі кадри справи: перелік на 272 тис. рядків сам перевищив би стелю
    `frames.jsonl` у пулі, а покриття сегмента міряється його власними кадрами.
    """
    out: list[dict[str, Any]] = []
    for piece in seg.pieces:
        part = piece.part
        if part.frames_dir is None:
            continue
        want = set(piece.stems) if piece.stems is not None else None
        for row in align.frames_of(part.frames_dir, hash_frames=hash_frames):
            name = str(row.get("name") or "")
            if want is not None and Path(name).stem not in want:
                continue
            out.append({**row, "name": f"{part.slug}{SEP}{name}"})
    for i, row in enumerate(out, 1):
        row["n"] = i
    return out


def frames_on_disk(parts: list[Part]) -> int:
    """Кадрів у теках усіх частин — знаменник цілої справи, коли картка мовчить."""
    return sum(len(align.frames_sorted(p.frames_dir)) for p in parts
               if p.frames_dir is not None)


def segment_block(seg: Segment, set_key: str) -> dict[str, Any]:
    """Поле `case.segment` маніфесту."""
    return {"set": set_key, "key": seg.key, "label": seg.label,
            "n": seg.n, "of": seg.of,
            "dirs": [p.label for p in seg.pieces]}


def describe(m: bundle.Manifest) -> dict[str, Any] | None:
    """`case.segment` маніфесту, якщо пакет — сегмент."""
    got = (m.case or {}).get("segment")
    return got if isinstance(got, dict) and got.get("key") else None


#: Технічний префікс теки частини: `part-01__…`, `chastyna_3 …`, `частина-2__…`.
_PART_PREFIX = re.compile(r"^(?:part|chast\w*|частина)[\s_-]*\d+(?:__|[\s_-]+)", re.I)
#: Позначка шматка частини в кінці мітки: «(1/2)».
_PIECE_MARK = re.compile(r"\s*\((\d+)/(\d+)\)\s*$")
_RANGE = " - "


def _ends(text: str) -> tuple[str, str]:
    """«Аб… - Ак…» → («Аб…», «Ак…»); без дефіса — той самий кінець з обох боків."""
    left, sep, right = text.partition(_RANGE)
    return left.strip(), (right.strip() if sep else left.strip())


def clean_label(raw: str) -> str:
    """Мітка частини для людини: діапазон абетки без технічних імен тек.

    Тека дослідника `part-01__Аб... - Ак...__Бем... - Берл...` (частина з
    кількох пачок: перша «Аб…–Ак…», остання «Бем…–Берл…») стає «Аб… - Берл…».
    Те, що не схоже на діапазон, лишається як було, лише без префікса частини.
    Сира назва теки лишається в `dirs` маніфесту — для людини вона шум, а
    для зіставлення з диском потрібна.
    """
    text = str(raw or "").strip()
    mark = _PIECE_MARK.search(text)
    suffix = f" ({mark.group(1)}/{mark.group(2)})" if mark else ""
    if mark:
        text = text[:mark.start()]
    body = _PART_PREFIX.sub("", text).replace("...", "…").strip(" _")
    batches = [b.strip(" _") for b in body.split(SEP) if b.strip(" _")]
    if len(batches) >= 2:
        body = f"{_ends(batches[0])[0]}{_RANGE}{_ends(batches[-1])[1]}"
    return (body or str(raw or "").strip()) + suffix


def _join(a: str, b: str) -> str:
    """Мітка сегмента з міток першого й останнього шматків.

    Цілі частини зводяться в один діапазон («Аб… - Ак…» + «Ал… - Ар…» →
    «Аб… - Ар…»); шматок частини (з позначкою) лишається названим цілком.
    """
    if a == b:
        return a
    if _PIECE_MARK.search(a) or _PIECE_MARK.search(b):
        return f"{a} — {b}"
    return f"{_ends(a)[0]}{_RANGE}{_ends(b)[1]}"


def _bound(label: str) -> str:
    """Початок мітки частини для порівняння за абеткою: «Бан… - Бар…» → «бан»."""
    head = clean_label(label.split(" — ")[0]).split(_RANGE)[0]
    head = _PIECE_MARK.sub("", head)
    return head.replace("…", "").replace("...", "").strip().casefold()


def pick(rows: list[Any], prefix: str) -> list[Any]:
    """Сегменти справи, що покривають прізвища на `prefix` (абетка картотеки).

    Сегменти впорядковані за абеткою частин, тож прізвище лежить у сегменті з
    НАЙБІЛЬШИМ початком, не більшим за нього. Частина, поділена за сторінками
    на шматки, має той самий початок у всіх шматках, а де саме в ній межа
    абетки — невідомо (з тексту картки її не виміряти: рушій калічить першу
    літеру прізвища), тож беруться всі шматки цієї частини. Мітки, що
    збігаються з запитом підрядком, беруться теж — на випадок, коли частини
    названо не абеткою.
    """
    want = prefix.strip().casefold()
    if not want:
        return list(rows)
    segs = sorted((r for r in rows if getattr(r, "segment", "")),
                  key=lambda r: int(getattr(r, "segment_n", 0) or 0))
    out = [r for r in segs if want in clean_label(
        str(getattr(r, "segment_label", ""))).casefold()]
    bounds = [(_bound(str(getattr(r, "segment_label", ""))), r) for r in segs]
    under = [b for b, _ in bounds if b and b <= want]
    if under:
        best = max(under)
        out.extend(r for b, r in bounds if b == best and r not in out)
    return out
