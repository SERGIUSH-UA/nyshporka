"""📦 Формат `.nyshtext` — переносний пакет прочитаного.

Звичайний `tar.gz` стандартною бібліотекою. Ні `zstandard`, ні `zstd` у ядрі
пакета немає, а виграш стиску на справі в чотири мегабайти не вартий залежності,
яку доведеться ставити кожному, хто просто хоче прочитати чужий текст.

Що важить пакет. Замір на реальному сторі: текст плюс паспорт — **≈1.1 КБ на
сторінку стиснуто**, тобто справа на 3772 аркуші виходить у 3–4 МБ. Геометрія
рядків (`*.lines.json`) додає ×10 і лежить лише під 45% сторінок, тому вона за
прапорцем. Кропи рятунку (6.8 ГБ із 19.4 на цій машині) не їдуть ніколи.

🔴 Білий список, а не глоб-виключення. Тека прогону сусідить із дослідженням,
і правило «беремо все, крім переліченого» помиляється в один бік: новий
службовий файл поїде в пакет сам, без жодного рішення. `PACKED` перелічує те,
що їде, і все інше лишається вдома за замовчуванням.

🔴 `case_dir` вирізається з мети. Це шлях машини, на якій читали, і на Windows
у ньому стоїть домашня тека з іменем користувача — тобто публікація декоду інакше
публікує ім'я автора й розкладку його диска. Поле й так мертве після переносу:
приймач ставить своє (`cloud.run.stamp_case_dir`).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from nyshporka.utils import tarsafe

#: Розширення пакета. Одне слово, щоб його впізнавали й ті, хто Нишпорки не має.
SUFFIX = ".nyshtext"
MANIFEST_NAME = "manifest.json"
FRAMES_NAME = "frames.jsonl"
README_NAME = "README.md"
RUNS_SUB = "runs"
META_NAME = "_htr_meta.json"

#: Версія формату. Читач старшої версії відмовляє явно, а не розбирає наосліп.
SCHEMA = 1

#: Що взагалі їде в пакет. Решта — ні, і це рішення, а не недогляд.
PACKED_TEXT = "*.txt"
PACKED_GEOMETRY = "*.lines.json"
PACKED = (PACKED_TEXT, META_NAME)

#: Поля мети, які не переживають переїзд: шлях чужої машини й сліди її диска.
META_STRIPPED = ("case_dir", "case_dir_cloud", "logs", "review")


class BundleError(RuntimeError):
    """Пакет не зібрати або не прочитати — з названою причиною."""


# ── маніфест ─────────────────────────────────────────────────────────────────

@dataclass
class Voice:
    """Один прогін-голос усередині справи."""

    run: str
    engine: str = ""
    model: str = ""
    script: str = ""
    pages: int = 0
    lines: int = 0
    chars: int = 0
    conf_mean: float | None = None
    geometry: bool = False

    def as_json(self) -> dict[str, Any]:
        out = {"run": self.run, "engine": self.engine, "model": self.model,
               "script": self.script, "pages": self.pages, "lines": self.lines,
               "chars": self.chars, "geometry": self.geometry}
        if self.conf_mean is not None:
            out["conf_mean"] = round(self.conf_mean, 3)
        return out


@dataclass
class Manifest:
    """Заяви пакета про себе: чия це справа, скільки прочитано і ким зібрано.

    🔴 Блок `decode` — не оздоба, а знаменник, перенесений разом із текстом.
    Без нього чужий декод виробляє хибні нулі оптом: людина грепне три
    сторінки, прийняті за три тисячі, і чесно доповість «роду тут немає».
    Ворота (`gates`) не випускають пакет, у якому цього блоку немає.
    """

    case: dict[str, Any] = field(default_factory=dict)
    refs: list[dict[str, str]] = field(default_factory=list)
    frames: dict[str, Any] = field(default_factory=dict)
    decode: dict[str, Any] = field(default_factory=dict)
    publisher: dict[str, str] = field(default_factory=dict)
    note: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    license: dict[str, str] = field(default_factory=dict)
    tool: str = ""
    created: str = ""
    schema: int = SCHEMA

    # ── читання ──
    @property
    def shifra(self) -> str:
        return str(self.case.get("shifra") or "")

    @property
    def voices(self) -> list[dict[str, Any]]:
        v = self.decode.get("voices")
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    @property
    def pages(self) -> int:
        return int(self.decode.get("pages") or 0)

    @property
    def frames_total(self) -> int:
        return int(self.frames.get("total") or 0)

    def models(self) -> list[str]:
        seen: list[str] = []
        for v in self.voices:
            m = str(v.get("model") or "").strip()
            if m and m not in seen:
                seen.append(m)
        return seen

    def as_json(self) -> dict[str, Any]:
        return {"schema": self.schema, "case": self.case, "refs": self.refs,
                "frames": self.frames, "decode": self.decode,
                "publisher": self.publisher, "note": self.note,
                "links": self.links, "extra": self.extra,
                "license": self.license, "tool": self.tool,
                "created": self.created}

    @classmethod
    def from_json(cls, raw: Any) -> Manifest:
        if not isinstance(raw, dict):
            raise BundleError("маніфест не є об'єктом JSON")
        got = int(raw.get("schema") or 0)
        if got > SCHEMA:
            raise BundleError(
                f"пакет зібрано схемою {got}, ця Нишпорка знає {SCHEMA} — "
                f"оновити: nysh update")
        def _d(k: str) -> dict[str, Any]:
            v = raw.get(k)
            return dict(v) if isinstance(v, dict) else {}
        def _l(k: str) -> list[Any]:
            v = raw.get(k)
            return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        return cls(case=_d("case"), refs=_l("refs"), frames=_d("frames"),
                   decode=_d("decode"), publisher=_d("publisher"),
                   note=str(raw.get("note") or ""), links=_l("links"),
                   extra=_d("extra"), license=_d("license"),
                   tool=str(raw.get("tool") or ""),
                   created=str(raw.get("created") or ""), schema=got or SCHEMA)


# ── збірка ───────────────────────────────────────────────────────────────────

def _tool_version() -> str:
    from nyshporka import __version__

    return f"nyshporka {__version__}"


def clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Мета без слідів машини, на якій читали. Див. 🔴 у шапці модуля."""
    return {k: v for k, v in meta.items() if k not in META_STRIPPED}


def _run_stats(run_dir: Path) -> tuple[int, int, int]:
    """Сторінок, рядків, символів у теці прогону — рахуючи по ДИСКУ.

    🔴 Не з `meta.pages`. Мета каже, що прогін вважає зробленим, а пакет несе
    те, що справді лежить: розбіжність між цими числами і є найчастіший спосіб
    віддати неповний декод під виглядом повного.
    """
    pages = lines = chars = 0
    for txt in sorted(run_dir.glob(PACKED_TEXT)):
        try:
            body = txt.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        pages += 1
        rows = [r for r in body.splitlines() if r.strip()]
        lines += len(rows)
        chars += sum(len(r) for r in rows)
    return pages, lines, chars


def _conf_mean(meta: dict[str, Any]) -> float | None:
    vals = []
    pages = meta.get("pages")
    if isinstance(pages, dict):
        for p in pages.values():
            if isinstance(p, dict) and isinstance(p.get("conf"), (int, float)):
                vals.append(float(p["conf"]))
    return sum(vals) / len(vals) if vals else None


def voice_of(run_dir: Path, *, geometry: bool) -> Voice:
    """Описати одну теку прогону так, як її побачить отримувач."""
    from nyshporka import htr_store as S
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        meta = read_json(run_dir / META_NAME, default={})
    except CorruptFileError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    pages, lines, chars = _run_stats(run_dir)
    has_geo = geometry and any(run_dir.glob(PACKED_GEOMETRY))
    return Voice(run=run_dir.name, engine=S.run_engine(meta),
                 model=str(meta.get("model") or ""),
                 script=str(meta.get("script") or ""),
                 pages=pages, lines=lines, chars=chars,
                 conf_mean=_conf_mean(meta), geometry=bool(has_geo))


def _members(run_dir: Path, *, geometry: bool) -> list[Path]:
    """Файли теки прогону, які їдуть. Білий список `PACKED`, див. шапку.

    🔴 Перелік береться саме з `PACKED`, а не повторюється тут своїми рядками.
    Інакше константа лишилась би описом наміру, а поїхало б те, що перелічено
    в коді, — і розійтись ці двоє могли б мовчки.
    """
    seen: list[Path] = []
    patterns = (*PACKED, *((PACKED_GEOMETRY,) if geometry else ()))
    for pat in patterns:
        for f in sorted(run_dir.glob(pat)):
            if f.is_file() and f not in seen:
                seen.append(f)
    return seen


def plan(run_dirs: list[Path], *, geometry: bool = False) -> dict[str, Any]:
    """Що саме ляже в пакет — до того, як його зібрано.

    Окрема функція, бо `--dry-run` мусить показувати ТОЙ САМИЙ перелік, який
    потім поїде, а не свій власний здогад про нього.
    """
    files: list[dict[str, Any]] = []
    voices: list[Voice] = []
    for d in run_dirs:
        voices.append(voice_of(d, geometry=geometry))
        for f in _members(d, geometry=geometry):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            files.append({"arc": f"{RUNS_SUB}/{d.name}/{f.name}",
                          "src": str(f), "bytes": size})
    return {"files": files, "voices": [v.as_json() for v in voices],
            "bytes": sum(int(f["bytes"]) for f in files),
            "pages": sum(v.pages for v in voices),
            "lines": sum(v.lines for v in voices),
            "chars": sum(v.chars for v in voices)}


def write(dest: Path, manifest: Manifest, run_dirs: list[Path], *,
          frames: list[dict[str, Any]] | None = None,
          geometry: bool = False) -> dict[str, Any]:
    """Зібрати пакет. Повертає шлях, розмір і sha256 — рядок для каталогу.

    Пишеться в `.part` і перейменовується: обірвана збірка не лишає файлу, що
    виглядає як готовий пакет.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    body = json.dumps(manifest.as_json(), ensure_ascii=False, indent=2)
    with tarfile.open(tmp, "w:gz") as tar:
        _add_bytes(tar, MANIFEST_NAME, body.encode("utf-8"))
        _add_bytes(tar, README_NAME, readme(manifest).encode("utf-8"))
        if frames:
            rows = "\n".join(json.dumps(f, ensure_ascii=False) for f in frames)
            _add_bytes(tar, FRAMES_NAME, (rows + "\n").encode("utf-8"))
        for d in run_dirs:
            for f in _members(d, geometry=geometry):
                arc = f"{RUNS_SUB}/{d.name}/{f.name}"
                if f.name == META_NAME:
                    _add_bytes(tar, arc, _clean_meta_bytes(f))
                else:
                    tar.add(f, arcname=arc)
    tmp.replace(dest)
    return {"path": str(dest), "bytes": dest.stat().st_size,
            "sha256": sha256_of(dest)}


def _clean_meta_bytes(path: Path) -> bytes:
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        meta = read_json(path, default={})
    except CorruptFileError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return json.dumps(clean_meta(meta), ensure_ascii=False,
                      indent=2).encode("utf-8")


def _add_bytes(tar: tarfile.TarFile, name: str, blob: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(blob)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(blob))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── читання ──────────────────────────────────────────────────────────────────

def read_manifest(path: Path) -> Manifest:
    """Маніфест без розпакування пакета — для `inspect` і для воріт."""
    with tarfile.open(path, "r:gz") as tar:
        try:
            src = tar.extractfile(MANIFEST_NAME)
        except KeyError:
            src = None
        if src is None:
            raise BundleError(
                f"у пакеті немає {MANIFEST_NAME} — це не пакет обміну Нишпорки")
        raw = json.loads(src.read().decode("utf-8"))
    return Manifest.from_json(raw)


def read_frames(path: Path) -> list[dict[str, Any]]:
    """Перелік кадрів пакета. Його може не бути — це не помилка."""
    out: list[dict[str, Any]] = []
    with tarfile.open(path, "r:gz") as tar:
        try:
            src = tar.extractfile(FRAMES_NAME)
        except KeyError:
            return out
        if src is None:
            return out
        for row in src.read().decode("utf-8").splitlines():
            row = row.strip()
            if not row:
                continue
            try:
                got = json.loads(row)
            except ValueError:
                continue
            if isinstance(got, dict):
                out.append(got)
    return out


def run_names(path: Path) -> list[str]:
    """Імена прогонів у пакеті — у порядку, у якому їх клали."""
    seen: list[str] = []
    with tarfile.open(path, "r:gz") as tar:
        for name in tar.getnames():
            parts = PurePosixPath(name).parts
            if len(parts) >= 2 and parts[0] == RUNS_SUB and parts[1] not in seen:
                seen.append(parts[1])
    return seen


def extract(path: Path, htr_root: Path) -> list[Path]:
    """Розкласти прогони пакета в теки прочитаного. Повертає теки, що лягли.

    🔴 Гард шляхів той самий, що й у хмарного забору (`utils.tarsafe`): пакет
    приїхав від людини, якої ми не знаємо, і довіряти іменам у ньому підстав
    рівно стільки ж, скільки орендованому боксу.
    """
    import shutil

    htr_root = Path(htr_root)
    htr_root.mkdir(parents=True, exist_ok=True)
    touched: dict[str, Path] = {}
    with tarfile.open(path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            if len(parts) < 3 or parts[0] != RUNS_SUB:
                continue
            rest = parts[1:]
            if not tarsafe.safe_member_parts(rest):
                continue
            base = htr_root / rest[0]
            dest = base.joinpath(*rest[1:])
            # Другий рубіж — уже на побудованому шляху.
            if not tarsafe.under(dest, base):
                continue
            src = tar.extractfile(member)
            if src is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            with tmp.open("wb") as fh:
                shutil.copyfileobj(src, fh, 1 << 20)
            tmp.replace(dest)
            touched[rest[0]] = base
    return list(touched.values())


# ── ім'я файлу ───────────────────────────────────────────────────────────────

_UNSAFE_NAME = re.compile(r"[^0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ._-]+")


def suggest_name(manifest: Manifest) -> str:
    """Ім'я файлу пакета з шифри: `ДАХмО_315-1-8433.nyshtext`."""
    c = manifest.case
    parts = [str(c.get("repo") or ""), str(c.get("fond") or ""),
             str(c.get("opys") or ""), str(c.get("spr") or "")]
    stem = "-".join(p for p in parts[1:] if p)
    head = parts[0] or "case"
    raw = f"{head}_{stem}" if stem else (manifest.shifra or "case")
    safe = _UNSAFE_NAME.sub("_", raw).strip("_") or "case"
    return safe + SUFFIX


def readme(manifest: Manifest) -> str:
    """Сторінка для того, хто відкрив пакет без Нишпорки.

    Такий читач — не крайній випадок, а половина адресатів: у тредах люди
    ганяють чужий текст через ChatGPT і Codex, і пакет має лишатись корисним
    без жодного встановленого інструмента.
    """
    d = manifest.decode
    models = ", ".join(manifest.models()) or "не названо"
    lines = [
        f"# {manifest.shifra or 'Прочитане'}",
        "",
        "Машинно прочитаний текст архівної справи. Зображень тут немає — лише",
        "те, що рушій побачив на аркушах, і паспорт того, як це читали.",
        "",
        "## Що в теках",
        "",
        f"- `{RUNS_SUB}/<прогін>/NNNN.txt` — сторінка. Один рядок файлу = один",
        "  рядок тексту на аркуші, зверху вниз.",
        f"- `{RUNS_SUB}/<прогін>/{META_NAME}` — паспорт прогону: модель, рушій,",
        "  письмо, скільки сторінок зроблено.",
        f"- `{FRAMES_NAME}` — перелік кадрів справи (номер, ім'я файлу, хеш).",
        f"- `{MANIFEST_NAME}` — шифра, посилання на джерело сканів, знаменник.",
        "",
        "Тек прогонів буває кілька: одну книгу читають двома моделями, і їхні",
        "прочитання лежать поруч, аркуш до аркуша.",
        "",
        "## Знаменник — читати перед тим, як казати «тут цього немає»",
        "",
        f"- кадрів у справі: {manifest.frames_total or 'невідомо'}",
        f"- сторінок прочитано: {manifest.pages}",
        f"- рядків: {d.get('lines') or 0}, символів: {d.get('chars') or 0}",
        f"- моделі: {models}",
        "",
        "Текст машинний і скалічений: середина довгого слова спотворюється",
        "найчастіше. Прізвище шукають нечітким пошуком і за іменами теж, а",
        "знайдене звіряють із зображенням у джерелі — не приймають як факт.",
        "",
        "## Звідки взяти самі скани",
        "",
    ]
    if manifest.refs:
        for r in manifest.refs:
            url = r.get("url") or ""
            tail = f" — {url}" if url else ""
            lines.append(f"- {r.get('source', '')}: `{r.get('ref', '')}`{tail}")
    else:
        lines.append("- джерело не вказане; шукати за шифрою в каталозі архіву")
    lines += ["", "## Покласти в Нишпорку", "",
              "```", f"nysh share import <цей файл{SUFFIX}>", "```", ""]
    if manifest.note:
        lines += ["## Від того, хто зібрав", "", manifest.note, ""]
    pub = manifest.publisher
    if pub.get("handle") or pub.get("contact"):
        who = pub.get("handle") or ""
        contact = f" · {pub['contact']}" if pub.get("contact") else ""
        lines += [f"Зібрав: {who}{contact}", ""]
    if manifest.links:
        lines += ["## Посилання", ""]
        lines += [f"- [{x.get('label') or x.get('url')}]({x.get('url')})"
                  for x in manifest.links]
        lines.append("")
    lic = manifest.license.get("text") or "не вказано"
    lines += [f"Ліцензія тексту: {lic}. Зображення в пакет не входять.",
              f"Зібрано: {manifest.tool or 'Нишпорка'}, {manifest.created}."]
    return "\n".join(lines) + "\n"
