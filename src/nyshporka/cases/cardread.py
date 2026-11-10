"""Картки зйомки, прочитані машиною: межі справ на плівці без перегляду кожного кадру.

`cards.scan` знаходить картки за тоном кадру, але лише для кадрів на диску, а
шифру з листа читає людина. Плівка, яку взяли «лише прогнати», лежить у бакеті
(`_r2_frames.json`), і кадрів на диску немає. 10.11.2026 межі 174 плівок обходу
ANRM довелось шукати разовими скриптами; тут те саме — інструментом:

1. **Кандидати без кадрів.** Картка — чорне поле з кількома рядками друку, і
   JPEG тисне її в рази краще за аркуш: байтів на піксель < 0.045, аркуш —
   0.1–0.3. Сірі картки (частина ANRM) — відносно своєї плівки: 0.6 × медіани.
   Другий детектор — прогін: на картці рушій бачить короткі рядки з низькою
   впевненістю (conf < 0.85, знаків на рядок < 9). На плівці 005783207 він
   знайшов усі 32 картки без хибних, і ловить ті, що тон пропускає. Плюс
   кадр 1 — номер мікрофільму, за яким шукають сусідній ролик.
2. **Читання картки.** Windows OCR (ru + en-US) по інвертованому кадру: тип
   картки (ITEM, END OF ITEM, CONTINUED ON / FROM ANOTHER ROLL, END OF ROLL),
   фонд-опис-справа, том, роки, «ВЫБОРОЧНО», номер мікрофільму.
3. **Карта плівки.** Справа — від початкової картки до наступної. Номер у
   карту для `cases split` іде лише ПІДТВЕРДЖЕНИЙ (`confirm`): цифра OCR буває
   хибною, а текст під чужою шифрою гірший за «?». Решта — підказкою `ocr` і
   листом на око.

Кадри-кандидати ядро не качає: звідки їх узяти (FamilySearch, бакет), знає
споживач. Ядро каже, яких бракує (`Reading.missing`), і читає ті, що лежать
у `<тека>/_cards/` під іменами кадрів плівки.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.cases.cards import CardsError

#: Підтека теки плівки: кадри-кандидати, кеш розпізнавання, підсумок і карта.
#: Із «_» — бібліотека й реєстр таких тек не обходять, і раннер підтек не бачить.
CARDS_DIR = "_cards"
OCR_CACHE = "_ocr.jsonl"
RESULT = "cards.json"
MAP = "map.json"

#: Байтів на піксель JPEG, нижче яких кадр — кандидат у картки.
CARD_BPP = 0.045
#: …нижче цього поріг не опускається, навіть коли кандидатів забагато.
CARD_BPP_MIN = 0.02
#: Кандидатів більше за max(це, частка плівки) — плівка темна, поріг знижується.
CARD_BPP_CAP = 60
CARD_BPP_CAP_SHARE = 0.12
#: Жодного кандидата за абсолютним порогом — сірі картки: частка медіани плівки.
CARD_BPP_REL = 0.6
#: Прогін: сторінка з такою впевненістю й такими короткими рядками — кандидат.
RUN_CONF = 0.85
RUN_CHARS_PER_LINE = 9.0
#: Ширина інвертованого кадру для OCR: дрібний друк картки з 600 px не читається.
OCR_WIDTH = 1400

START = ("item", "cont_from")
END = ("end_item", "cont_on")
UNKNOWN = "?"
OUTSIDE = "-"


class OcrUnavailable(RuntimeError):
    """Розпізнавання карток на цій машині немає — причина для людини."""


# ── кандидати ────────────────────────────────────────────────────────────────

@dataclass
class Candidates:
    case_dir: Path
    names: list[str]                       # усі кадри плівки в порядку
    remote: bool                           # кадри в бакеті, на диску лише маніфест
    frames_dir: Path | None                # де лежать кадри, якщо на диску
    by_tone: list[str] = field(default_factory=list)
    by_run: list[str] = field(default_factory=list)
    threshold: float | None = None         # поріг байтів на піксель (лише бакет)
    dgs: str = ""                          # плівка FS з маніфесту, якщо названа

    @property
    def want(self) -> list[str]:
        """Кадри, які треба прочитати: темні, наступний за кожним, кандидати прогону, кадр 1."""
        pos = {n: i for i, n in enumerate(self.names)}
        out = set(self.by_tone) | set(self.by_run)
        # Наступний за темним: початкова картка з довгою назвою світліша за кінцеву
        # і порогом іноді не ловиться, а стоїть вона одразу за «END OF ITEM».
        for n in self.by_tone:
            i = pos.get(n)
            if i is not None and i + 1 < len(self.names):
                out.add(self.names[i + 1])
        if self.names:
            out.add(self.names[0])
        return sorted(out, key=lambda n: pos.get(n, 0))


def dark_by_bytes(bpp: dict[str, float]) -> tuple[list[str], float | None]:
    """Кадри, підозрілі на картку, за байтами на піксель; і поріг, яким їх узято."""
    if not bpp:
        return [], None
    cap = max(CARD_BPP_CAP, int(len(bpp) * CARD_BPP_CAP_SHARE))
    thr = CARD_BPP
    dark = [n for n, v in bpp.items() if v < thr]
    while len(dark) > cap and thr - 0.005 >= CARD_BPP_MIN:
        thr = round(thr - 0.005, 4)
        dark = [n for n, v in bpp.items() if v < thr]
    if not dark:
        vals = sorted(bpp.values())
        thr = round(CARD_BPP_REL * vals[len(vals) // 2], 4)
        dark = [n for n, v in bpp.items() if v < thr]
    return dark, thr


def dark_by_run(case_dir: Path, frames_dir: Path | None, names: list[str]) -> list[str]:
    """Кандидати з прогону теки: короткі рядки з низькою впевненістю."""
    stats = run_pages(case_dir, frames_dir)
    have = set(names)
    out = []
    for name, v in stats.items():
        lines = int(v.get("lines") or 0)
        if name not in have or not lines:
            continue
        if float(v.get("conf") or 1.0) >= RUN_CONF:
            continue
        if float(v.get("chars") or 0) / lines >= RUN_CHARS_PER_LINE:
            continue
        out.append(name)
    return out


def run_pages(case_dir: Path, frames_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Сторінки головного прогону теки (без голосів): ім'я кадру → лічильники рушія."""
    from nyshporka import htr_store as S
    from nyshporka.cases import split as SPL

    by_dir = S.runs_by_case_dir()
    names = sorted({str(r.get("name") or "") for key in SPL._dir_keys(*(
        [frames_dir, case_dir] if frames_dir else [case_dir]))
        for r in by_dir.get(key) or []} - {""})
    # Голос лежить у теці `<прогін>-<модель>`: головний — той, що не є продовженням іншого.
    mains = [n for n in names if not any(n != o and n.startswith(o + "-") for o in names)]
    out: dict[str, dict[str, Any]] = {}
    for name in mains:
        try:
            meta = json.loads((S.htr_root() / name / "_htr_meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for page, v in (meta.get("pages") or {}).items():
            if isinstance(v, dict):
                out.setdefault(str(page), v)
    return out


def candidates(case_dir: str | Path) -> Candidates:
    from nyshporka.cases import cards as CRD
    from nyshporka.cloud.verify import remote_manifest
    from nyshporka.share import align

    d = Path(case_dir)
    if not d.is_dir():
        raise CardsError(f"теки {d} немає")
    frames_dir = align._frames_dir(d)
    local = [p.name for p in align.frames_sorted(frames_dir)] if frames_dir else []
    try:
        remote = remote_manifest(d, local)
    except ValueError as exc:
        raise CardsError(str(exc)) from None
    if remote is not None:
        frames = remote["frames"]
        names = sorted(str(f["name"]) for f in frames)
        bpp = {str(f["name"]): int(f.get("size") or 0) / max(1, int(f.get("w") or 0) * int(f.get("h") or 0))
               for f in frames if f.get("w") and f.get("h")}
        tone, thr = dark_by_bytes(bpp)
        c = Candidates(d, names, True, None, threshold=thr, dgs=str(remote.get("dgs") or ""))
        c.by_tone = tone
    elif frames_dir is not None:
        tones = [CRD.tone_of(p) for p in align.frames_sorted(frames_dir)]
        c = Candidates(d, [t.name for t in tones], False, frames_dir)
        c.by_tone = [t.name for t in tones if t.card_loose]
    else:
        raise CardsError(f"у теці {d} немає ні кадрів, ні маніфесту кадрів у бакеті")
    c.by_run = dark_by_run(d, frames_dir, c.names)
    return c


def card_path(c: Candidates, name: str) -> Path | None:
    """Зображення кадру-кандидата: з теки кадрів або з `_cards/`."""
    for p in ([c.frames_dir / name] if c.frames_dir else []) + [c.case_dir / CARDS_DIR / name]:
        if p.is_file():
            return p
    return None


# ── читання картки ───────────────────────────────────────────────────────────

_PS_OCR = r"""param([string]$ListFile, [string]$OutFile)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) {
    $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null
$ru = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('ru')))
$en = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('en-US')))
$utf8 = New-Object System.Text.UTF8Encoding($false)
if ($ru -eq $null -and $en -eq $null) {
    [IO.File]::AppendAllText($OutFile, '{"fatal":"no_engine"}' + "`n", $utf8); exit 3 }
foreach ($path in [IO.File]::ReadAllLines($ListFile)) {
    if (-not $path) { continue }
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $r1 = ''; $r2 = ''
        if ($ru -ne $null) { $r1 = (Await ($ru.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])).Text }
        if ($en -ne $null) { $r2 = (Await ($en.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])).Text }
        $stream.Dispose()
        $obj = @{ path = $path; ru = $r1; en = $r2 }
    } catch { $obj = @{ path = $path; error = $_.Exception.Message } }
    [IO.File]::AppendAllText($OutFile, (ConvertTo-Json $obj -Compress) + "`n", $utf8)
}
"""


def _powershell() -> str:
    """Windows PowerShell 5.1: лише в ньому WinRT доступний без збірок-проєкцій."""
    if os.name != "nt":
        raise OcrUnavailable("розпізнавання карток є лише на Windows (Windows OCR); "
                             "шифри прочитайте з листа карток")
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if exe.is_file():
        return str(exe)
    found = shutil.which("powershell.exe")
    if not found:
        raise OcrUnavailable("не знайдено Windows PowerShell (powershell.exe) для Windows OCR")
    return found


def ocr(images: dict[str, Path], *, timeout: float = 1800) -> dict[str, dict[str, str]]:
    """Розпізнати картки: ім'я кадру → {"ru": …, "en": …} (або {"error": …})."""
    from PIL import Image, ImageOps

    if not images:
        return {}
    exe = _powershell()
    out: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="nysh-cards-") as td:
        tmp = Path(td)
        back: dict[str, str] = {}
        paths = []
        for i, (name, src) in enumerate(images.items()):
            p = tmp / f"{i:05d}.png"
            try:
                with Image.open(src) as im:
                    g = ImageOps.invert(im.convert("L"))
                    g = g.resize((OCR_WIDTH, max(1, int(g.height * OCR_WIDTH / max(1, g.width)))))
                    g.save(p)
            except OSError as exc:
                out[name] = {"error": f"кадр не відкрився: {exc}"}
                continue
            back[str(p).lower()] = name
            paths.append(str(p))
        if not paths:
            return out
        (tmp / "list.txt").write_text("\n".join(paths), encoding="utf-8")
        (tmp / "ocr.ps1").write_text(_PS_OCR, encoding="utf-8-sig")
        res = tmp / "out.jsonl"
        try:
            subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", str(tmp / "ocr.ps1"), str(tmp / "list.txt"), str(res)],
                           capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OcrUnavailable(f"Windows OCR не відпрацював: {exc}") from None
        lines = res.read_text(encoding="utf-8").splitlines() if res.is_file() else []
        for line in lines:
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("fatal"):
                raise OcrUnavailable("у Windows не встановлено жодної мови розпізнавання (ru чи "
                                     "en-US): Параметри → Час і мова → Мова → додати російську")
            whose = back.get(str(j.get("path") or "").lower())
            if whose:
                out[whose] = ({"error": str(j["error"])} if j.get("error")
                              else {"ru": str(j.get("ru") or ""), "en": str(j.get("en") or "")})
    return out


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if isinstance(j, dict) and j.get("name"):
            out[str(j["name"])] = j
    return out


def ocr_cached(c: Candidates, names: list[str], *, run_ocr: bool = True
               ) -> tuple[dict[str, dict[str, str]], str]:
    """Розпізнане по кадрах-кандидатах з кешем `_cards/_ocr.jsonl` (ключ — ім'я й розмір файла).

    Повертає розпізнане й стан: "ok" · "cached" (OCR не кликали) · "unavailable: <чому>".
    """
    cache_path = c.case_dir / CARDS_DIR / OCR_CACHE
    cache = _load_cache(cache_path)
    got: dict[str, dict[str, str]] = {}
    todo: dict[str, Path] = {}
    for name in names:
        p = card_path(c, name)
        if p is None:
            continue
        size = p.stat().st_size
        hit = cache.get(name)
        if hit and int(hit.get("size") or -1) == size and ("ru" in hit or "en" in hit):
            got[name] = {"ru": str(hit.get("ru") or ""), "en": str(hit.get("en") or "")}
        else:
            todo[name] = p
    if not todo:
        return got, "cached"
    if not run_ocr:
        return got, "unavailable: розпізнавання вимкнено"
    try:
        fresh = ocr(todo)
    except OcrUnavailable as exc:
        return got, f"unavailable: {exc}"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8") as fh:
        for name, r in fresh.items():
            if "error" in r:
                continue
            fh.write(json.dumps({"name": name, "size": todo[name].stat().st_size,
                                 "ru": r["ru"], "en": r["en"],
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
            got[name] = r
    return got, "ok"


# ── розбір тексту картки ─────────────────────────────────────────────────────

@dataclass
class Card:
    name: str
    kind: str                     # item · end_item · cont_on · cont_from · end_roll · target · other
    fond: str | None = None
    opys: str | None = None
    delo: str | None = None
    part: str | None = None       # том
    years: list[int] = field(default_factory=list)
    selective: bool = False       # «ВЫБОРОЧНО»: архів зняв справу не всю
    microfilm: str | None = None  # 7 цифр номера мікрофільму (кадр 1)
    #: Англійський текст тієї самої картки називає інший номер справи чи фонду:
    #: прочитанню не вірити (220-7-16: ru «ДЕЛО 46», en «AEJIO 16»).
    contested: bool = False
    #: Номер справи взято з англійського тексту: літеру номера (30А) там губить OCR.
    delo_from_en: bool = False
    text: str = ""

    @property
    def shifra(self) -> str | None:
        if self.fond and self.opys and self.delo:
            return f"{self.fond}-{self.opys}-{self.delo}"
        return None


def kind_of(en: str, ru: str) -> str:
    """Тип картки з англійського тексту (рамка картки GSU — англійська)."""
    e = (en or "").upper().replace("0", "O")
    r = (ru or "").upper()
    if re.search(r"END\s*O[FP]\s*R[O0]LL", e):
        return "end_roll"
    if re.search(r"CONT[I1L]NUED\s*FR[O0]M|FROM\s*ANOTHER", e) or ("CONTINUED" in e and "FROM" in e):
        return "cont_from"
    if re.search(r"CONT[I1L]NUED\s*ON\b", e) or ("CONTINUED" in e and " ON " in f" {e} "):
        return "cont_on"
    if re.search(r"END\s*O[FP]\s*[I1\[]TEM|O[FP]\s*[I1\[]TEM", e) or re.search(r"END\s*O[FБ]\s*[I1\[Т]", r):
        return "end_item"
    if "MEASURE" in e or ("REDUCTION" in e and not re.search(r"ARCH[I1]VE|OPERATOR", e)):
        return "target"
    if re.search(r"NAT[I1]ONAL|ARCH[I1]VE|M[I1]CR[O0]F[I1]LMED|OPERATOR|GENEALOG", e) or "ФОНД" in r:
        return "item"
    return "other"


#: Літера при номері (30А, 1А) — кирилицею, як в описі архіву; латинську OCR дає з англ. тексту.
_LAT_CYR = str.maketrans({"A": "А", "B": "Б", "V": "В", "G": "Г"})
#: Номер із літерою, яку OCR відсуває пробілом («ДЕЛО 30 А»); літера — окреме слово,
#: тож «ДЕЛО 23 YEAR» літери не дає.
_NUM = r"([0-9]{1,5})(?:\s?([АБВГAB])(?![А-ЯA-Z0-9]))?"


def _num(m: re.Match[str] | None, at: int = 1) -> str | None:
    if not m:
        return None
    return m.group(at) + ((m.group(at + 1) or "").translate(_LAT_CYR))


def en_numbers(en: str) -> tuple[str | None, str | None, str | None]:
    """Фонд, опис і номер справи з англійського тексту картки — незалежне друге прочитання.

    Рамка картки англійська, а шифра надрукована кирилицею, тож англійський
    двигун бачить «QOHA 211 VOLUME'S onncb 5 AEno 23 YEAR'S»: фонд стоїть перед
    VOLUME, опис і номер справи — два останні числа перед YEAR чи ROLL. Фонд «0»
    — уламок літери, а не фонд.
    """
    e = re.sub(r"\s+", " ", (en or "").upper())
    m = re.search(r"(?<!\d)([1-9]\d{0,3})\W{0,3}VOLUME", e)
    if not m:
        return None, None, None
    d = re.search(r"(\d{1,3})\D{1,15}?" + r"(\d{1,5})(?:\s?([AB])(?![A-Z0-9]))?" + r"\s*(?:ROLL|YEAR)",
                  e[m.end():])
    return m.group(1), (d.group(1) if d else None), (_num(d, 2) if d else None)


#: Літери, якими російський двигун пише цифри в полі шифри: «ОПИСЬ З», «ФOНД 2O».
_DIGIT_LOOK = str.maketrans({"З": "3", "О": "0", "O": "0", "I": "1", "L": "1", "|": "1"})
_SEP = r"[\W_]{0,3}"           # «опись_з»: підкреслення — теж розділювач


def _digits(r: str, word: str, width: int) -> str | None:
    """Число після слова шифри; літера-двійник цифри — лише поруч із цифрою або сама «З»."""
    m = re.search(word + _SEP + "([0-9ЗОOIL|]{1," + str(width) + "})(?![0-9А-ЯA-Z])", r)
    if not m:
        return None
    tok = m.group(1)
    if not re.search(r"[0-9]", tok) and tok != "З":
        return None
    return tok.translate(_DIGIT_LOOK)


def parse(name: str, ru: str, en: str) -> Card:
    """Розібрати текст картки. Цифри в російському тексті OCR плутає з літерами — нормалізуються."""
    r = (ru or "").upper().replace("Ё", "Е")
    fond = _digits(r, r"Ф[О0O]НД", 4)
    opys = _digits(r, r"[О0O]П[ИN]С[ЬБ]", 3)
    if opys is None and re.search(r"[О0O]П[ИN]СЫ(?![А-Я])", r):
        opys = "1"             # «ОПИСЬ 1» злилось у «ОПИСЫ» (136-1-420 на 005783228)
    # «ДЕТ 249» — OCR губить «ЛО»; «ДЕТЕЙ» сюди не йде: після слова мусять стояти цифри
    d = re.search(r"ДЕ(?:Л[О0O]|Т)" + _SEP + _NUM, r)
    part = re.search(r"\b[ТT]\.?\s?([0-9])\b|\bV\.?\s?([0-9])\b", r)
    years = [int(y) for y in re.findall(r"\b(1[6-9][0-9]{2})\b", r) if 1600 <= int(y) <= 1950]
    plain = re.sub(r"\s+", " ", f"{ru} {en}").strip()
    film = re.search(r"(?<!\d)(\d{7})(?!\d)", plain)
    k = kind_of(en, ru)
    delo = _num(d)
    en_fond, en_opys, en_delo = en_numbers(en)
    # Опис з англійського тексту в суперечку не йде: він плутається з сусідніми числами,
    # і звірка ним відкидала третину правильних пар (замір 10.11: 646 → 470).
    contested = bool((en_delo and delo and en_delo.rstrip("АБВГ") != delo.rstrip("АБВГ"))
                     or (en_fond and fond and en_fond != fond))
    # Номер справи, якого російський текст не дав («ДЕТ 249»), — з англійського, але лише
    # при фонді й описі з російського і англ. фонді, що не суперечить. Фонд і опис з
    # англійського не беруться: там перед VOLUME стоїть і номер ролика (3837 замість 88),
    # а опис плутається з сусідніми числами — 4 хибні пари з 159 на замірі 10.11.
    from_en = False
    if delo is None and en_delo and fond and opys and en_fond in (None, fond) and en_opys == opys:
        delo, from_en = en_delo, True
    return Card(
        name=name, kind=k, fond=fond, opys=opys, delo=delo, delo_from_en=from_en,
        part=(part.group(1) or part.group(2)) if part else None,
        years=years[:2],
        selective=bool(re.search(r"ВЫБОРОЧН|ВИБІРКОВ", r)),
        microfilm=film.group(1) if film and k == "other" else None,
        contested=contested,
        text=plain[:240],
    )


# ── карта плівки ─────────────────────────────────────────────────────────────

@dataclass
class Row:
    first: str
    last: str
    kind: str                              # "case" | "-"
    spr: str = UNKNOWN                     # у карту: шифра, «?» чи «-»
    ocr: str = ""                          # фонд-опис-справа з картки
    reads: list[str] = field(default_factory=list)   # прочитання шифри картками рядка
    contested: list[str] = field(default_factory=list)  # прочитання, яким суперечить англ. текст
    native: list[str] = field(default_factory=list)  # прочитання з номером справи з рос. тексту
    parts: list[str] = field(default_factory=list)   # томи
    years: list[int] = field(default_factory=list)
    start: str | None = None               # кадр початкової картки
    end: str | None = None                 # кадр кінцевої картки
    end_kind: str = ""                     # end_item · cont_on · next_start · end_roll · film_end
    cont_from: bool = False
    selective: bool = False
    confirmed: str = ""                    # passport · pair · numbers · ocr (з дозволу людини)

    def as_map(self) -> dict[str, Any]:
        row: dict[str, Any] = {"spr": self.spr, "first": self.first, "last": self.last}
        if self.ocr:
            row["ocr"] = self.ocr
        if self.kind == "case":
            row["years"] = self.years
            row["end"] = self.end_kind
        return row


def build_rows(names: list[str], cards: dict[str, Card]) -> list[Row]:
    """Відтинки плівки за прочитаними картками: справи й шматки поза справами."""
    pos = {n: i for i, n in enumerate(names)}
    events = sorted((c for c in cards.values() if c.name in pos), key=lambda c: pos[c.name])
    segs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    roll_end: int | None = None
    for c in events:
        i = pos[c.name]
        if c.kind in START:
            # друга картка того самого початку (пара «CONTINUED FROM» + ITEM, дубль картки)
            if cur and cur["e"] is None and i - cur["last_start"] <= 2:
                cur["last_start"] = i
                cur["cards"].append(c)
                cur["cont_from"] |= c.kind == "cont_from"
                continue
            if cur and cur["e"] is None:
                cur["e"], cur["end_kind"] = i - 1, "next_start"
            cur = {"s": i, "e": None, "start": i, "last_start": i, "end": None,
                   "end_kind": "", "cont_from": c.kind == "cont_from", "cards": [c]}
            segs.append(cur)
        elif c.kind in END:
            if cur and cur["end"] is not None and i - cur["end"] <= 2:
                # друга кінцева тієї самої справи (END OF ITEM двічі; END + CONTINUED ON):
                # межа — остання, і «на інший ролик» важить більше за «кінець пункту»
                cur["e"] = cur["end"] = i
                cur["end_kind"] = "cont_on" if "cont_on" in (c.kind, cur["end_kind"]) else c.kind
                cur["cards"].append(c)
            elif cur and (cur["e"] is None or (cur["e"] == i - 1 and cur["end_kind"] == "next_start")):
                cur["e"], cur["end"], cur["end_kind"] = i, i, c.kind
                cur["cards"].append(c)
            elif cur is None or cur["e"] is not None:
                # кінець без побаченого початку: голова плівки — хвіст справи без картки
                prev = segs[-1]["e"] if segs else -1
                cur = {"s": prev + 1, "e": i, "start": None, "last_start": None, "end": i,
                       "end_kind": c.kind, "cont_from": False, "cards": [c], "unseen": True}
                segs.append(cur)
        elif c.kind == "end_roll":
            roll_end = i
            if cur and cur["e"] is None:
                cur["e"], cur["end_kind"] = i - 1, "end_roll"
    rows: list[Row] = []
    n = len(names)
    for k, s in enumerate(segs):
        a = s["s"]
        if k + 1 < len(segs):
            b = segs[k + 1]["s"] - 1      # усе до наступної початкової — цієї справи
        elif s["e"] is not None:
            b = s["e"]
        else:
            b = (roll_end - 1) if roll_end is not None and roll_end > a else n - 1
            s["end_kind"] = s["end_kind"] or "film_end"
        if rows and a > _idx(rows[-1].last, pos) + 1:
            rows.append(Row(names[_idx(rows[-1].last, pos) + 1], names[a - 1], OUTSIDE, spr=OUTSIDE))
        elif not rows and a > 0:
            rows.append(Row(names[0], names[a - 1], OUTSIDE, spr=OUTSIDE))
        cs: list[Card] = s["cards"]
        reads = [x.shifra for x in cs if x.shifra and not x.contested]
        doubt = [x.shifra for x in cs if x.shifra and x.contested]
        native = [x.shifra for x in cs if x.shifra and not x.contested and not x.delo_from_en]
        rows.append(Row(
            names[a], names[b], "case",
            reads=reads, contested=doubt, native=native, ocr=_vote(reads) or _vote(doubt),
            parts=sorted({x.part for x in cs if x.part}),
            years=next((x.years for x in cs if x.years), []),
            start=names[s["start"]] if s["start"] is not None else None,
            end=names[s["end"]] if s["end"] is not None else None,
            end_kind=s["end_kind"] or ("next_start" if k + 1 < len(segs) else "film_end"),
            cont_from=bool(s["cont_from"]),
            selective=any(x.selective for x in cs),
        ))
    if rows and _idx(rows[-1].last, pos) < n - 1:
        rows.append(Row(names[_idx(rows[-1].last, pos) + 1], names[-1], OUTSIDE, spr=OUTSIDE))
    return _merge_volumes(rows)


def _idx(name: str, pos: dict[str, int]) -> int:
    return pos[name]


def _vote(reads: list[str]) -> str:
    """Шифра, яку картки рядка називають найчастіше (порівну — перша)."""
    if not reads:
        return ""
    best = max(reads, key=lambda r: (reads.count(r), -reads.index(r)))
    return best


def _merge_volumes(rows: list[Row]) -> list[Row]:
    """Томи однієї справи підряд (Т1, Т2) — одна справа: `cases split` не пускає її двічі.

    Те саме — дві початкові картки тієї самої шифри без кінцевої між ними
    (005783228: ITEM 2-2-249 на к.4, ще одна «CONTINUED FROM» тієї ж справи на к.56):
    справа закінчується лише карткою END OF ITEM чи CONTINUED ON.
    """
    out: list[Row] = []
    for r in rows:
        prev = out[-1] if out else None
        if (prev is not None and r.kind == "case" and prev.kind == "case" and r.ocr
                and r.ocr == prev.ocr
                and (((r.parts or prev.parts) and not r.cont_from) or prev.end_kind == "next_start")):
            prev.last, prev.end, prev.end_kind = r.last, r.end, r.end_kind
            prev.reads += r.reads
            prev.contested += r.contested
            prev.native += r.native
            prev.parts = sorted(set(prev.parts) | set(r.parts))
            prev.selective |= r.selective
            continue
        out.append(r)
    return out


def own_shifra(case_dir: Path) -> tuple[str, str | None]:
    """Архів і фонд-опис-справа з паспорта теки (справа — лише номер, не «film…»)."""
    try:
        meta = json.loads((case_dir / "_source.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", None
    repo = str(meta.get("repo") or "")
    f, o, s = (str(meta.get(k) or "").strip() for k in ("fond", "opys", "spr"))
    if f and o and re.fullmatch(r"\d+[А-ЯA-Zа-яa-z]?", s or ""):
        return repo, f"{f}-{o}-{s}"
    return repo, None


def confirm(rows: list[Row], repo: str, own: str | None, *, accept_ocr: bool = False) -> None:
    """Вписати в карту шифри, яким можна вірити.

    🔴 Підтверджено — лише коли (а) картка називає шифру самої теки з паспорта,
    або (б) дві картки рядка (початкова й «END OF ITEM» чи дві початкові)
    прочитані однаково, англійський текст жодній не суперечить і хоч одна
    дала номер справи з російського тексту. Замір 10.11.2026 на 318 картках,
    прочитаних оком: пар (б) — 119 перевірених, хибних 0; одиночне прочитання
    хибне у 6 зі 195 (220-7-15 як «45», 211-1-26 як «11-1-26», загублена «А»),
    і помилка буває однаковою на обох картках, якщо номер узято з англ.
    тексту. Одиночне — «?» з підказкою: текст під сусідньою шифрою гірший за
    збірну теку. `accept_ocr` — слово людини взяти й одиночні.
    """
    for r in rows:
        if r.kind != "case" or r.spr not in (UNKNOWN, ""):
            continue
        if not r.ocr:
            continue
        agree = [x for x in r.reads if x == r.ocr]
        if own and r.ocr == own and r.reads:
            r.confirmed = "passport"
        elif (len(agree) >= 2 and len(agree) == len(r.reads) and not r.contested
              and r.ocr in r.native):
            r.confirmed = "pair"
        elif accept_ocr:
            r.confirmed = "ocr"
        else:
            continue
        r.spr = f"{repo} {r.ocr}".strip()


# ── уся плівка ───────────────────────────────────────────────────────────────

@dataclass
class Reading:
    case_dir: Path
    names: list[str]
    remote: bool
    want: list[str]
    missing: list[str]
    ocr_state: str
    cards: dict[str, Card] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    microfilm: str | None = None
    threshold: float | None = None
    by_tone: int = 0
    by_run: int = 0
    dgs: str = ""
    warnings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def cases(self) -> list[Row]:
        return [r for r in self.rows if r.kind == "case"]

    def as_json(self) -> dict[str, Any]:
        return {
            "case_dir": str(self.case_dir), "frames": len(self.names), "remote": self.remote,
            "dgs": self.dgs, "microfilm": self.microfilm,
            "candidates": {"want": len(self.want), "by_tone": self.by_tone, "by_run": self.by_run,
                           "threshold": self.threshold, "missing": len(self.missing)},
            "ocr": self.ocr_state,
            "cards": {k: v for k, v in _count(self.cards).items()},
            "rows": [asdict(r) for r in self.rows],
            "cases": len(self.cases),
            "unconfirmed": sum(1 for r in self.cases if r.spr == UNKNOWN),
        }


def _count(cards: dict[str, Card]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cards.values():
        out[c.kind] = out.get(c.kind, 0) + 1
    return out


def read(case_dir: str | Path, *, run_ocr: bool = True, accept_ocr: bool = False) -> Reading:
    """Кандидати → розпізнані картки → карта плівки з перевірками.

    Бракує кадрів-кандидатів (плівка в бакеті, `_cards/` порожня) — `missing`
    непорожній, а карти немає: читати межі з половини карток означало б
    зліпити дві справи в одну.
    """
    c = candidates(case_dir)
    want = c.want
    missing = [n for n in want if card_path(c, n) is None]
    rd = Reading(c.case_dir, c.names, c.remote, want, missing, "", threshold=c.threshold,
                 by_tone=len(c.by_tone), by_run=len(c.by_run), dgs=c.dgs)
    if missing:
        rd.ocr_state = "waiting: бракує кадрів-кандидатів"
        return rd
    texts, rd.ocr_state = ocr_cached(c, want, run_ocr=run_ocr)
    rd.cards = {n: parse(n, t.get("ru", ""), t.get("en", "")) for n, t in texts.items()}
    if c.names:
        first = rd.cards.get(c.names[0])
        rd.microfilm = first.microfilm if first else None
    rd.rows = build_rows(c.names, rd.cards)
    repo, own = own_shifra(c.case_dir)
    confirm(rd.rows, repo, own, accept_ocr=accept_ocr)
    rd.warnings = checks(rd, own)
    return rd


def checks(rd: Reading, own: str | None) -> list[tuple[str, str]]:
    """Що в межах плівки вимагає рішення: продовження, вибірковість, кілька справ, «?»."""
    out: list[tuple[str, str]] = []
    cases = rd.cases
    if rd.ocr_state.startswith("unavailable") and not rd.cards:
        return [("ocr_unavailable", rd.ocr_state.split(":", 1)[-1].strip())]
    if not cases:
        out.append(("no_cards", "жодної картки з шифрою не прочитано: тека — одна справа без "
                                "карток зйомки (цифрова зйомка, група = справа) або картки сірі "
                                "й світлі — подивіться лист кадрів-кандидатів"))
        return out
    nxt = f"; наступний ролик — мікрофільм {int(rd.microfilm) + 1}" if rd.microfilm else ""
    last, head = cases[-1], cases[0]
    if last.end_kind == "cont_on":
        out.append(("continued_on", f"справа {last.ocr or last.spr} (кадри {last.first}–{last.last}) "
                                    f"переходить на інший ролик: картка «CONTINUED ON ANOTHER ROLL» "
                                    f"{last.end}{nxt}"))
    if head.cont_from or head.start is None:
        why = "«CONTINUED FROM ANOTHER ROLL»" if head.cont_from else "кінцева картка без початкової"
        out.append(("continued_from", f"голова плівки — продовження справи "
                                      f"{head.ocr or '(шифру не прочитано)'} з іншого ролика ({why}, "
                                      f"кадри {head.first}–{head.last}); звести з головою — "
                                      f"`nysh cases join`"))
    sel = [r for r in cases if r.selective]
    if sel:
        out.append(("selective", "вибіркова зйомка архіву («ВЫБОРОЧНО»): "
                    + ", ".join(r.ocr or r.first for r in sel)
                    + " — у Супрягу з позначкою «неповна»"))
    if own and len(cases) > 1:
        out.append(("several_cases", f"тека за паспортом — одна справа {own}, а карток справ "
                                     f"{len(cases)}: розкласти `nysh cases split --map`"))
    if own and not any(r.ocr == own for r in cases):
        out.append(("own_not_seen", f"жодна картка не називає шифри теки {own}: звірте паспорт "
                                    f"із листом карток"))
    unk = [r for r in cases if r.spr == UNKNOWN]
    if unk:
        out.append(("fill_numbers", f"справ без підтвердженої шифри {len(unk)} із {len(cases)}: "
                                    f"підказка OCR — у полі «ocr», звірте з листом карток і впишіть "
                                    f"у карту замість «?»"))
    return out


def save(rd: Reading, map_path: Path | None = None) -> dict[str, Path]:
    """Підсумок і карту — у `_cards/` теки (карта — ще й куди попросили)."""
    from nyshporka.utils.atomic import atomic_write_text

    d = rd.case_dir / CARDS_DIR
    d.mkdir(parents=True, exist_ok=True)
    res = {**rd.as_json(), "warnings": [{"code": c, "text": t} for c, t in rd.warnings],
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    atomic_write_text(d / RESULT, json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    out = {"result": d / RESULT}
    if rd.rows:
        mp = map_path or d / MAP
        mp.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(mp, json.dumps([r.as_map() for r in rd.rows], ensure_ascii=False,
                                         indent=1) + "\n")
        out["map"] = mp
    return out


def sheet(rd: Reading, out_dir: str | Path, *, only_unconfirmed: bool = False,
          cell: int = 560, per_sheet: int = 8) -> list[Path]:
    """Лист на око: рядок на справу — початкові картки, кінцева й перший кадр після картки.

    Підпис рядка — підказка OCR і стан підтвердження; шифру людина читає з
    самої картки, а не з підпису.
    """
    from PIL import Image, ImageDraw

    c_dir = rd.case_dir / CARDS_DIR
    pos = {n: i for i, n in enumerate(rd.names)}

    def img(name: str | None) -> Path | None:
        if not name:
            return None
        p = c_dir / name
        if p.is_file():
            return p
        from nyshporka.share import align

        fd = align._frames_dir(rd.case_dir)
        q = fd / name if fd else None
        return q if q is not None and q.is_file() else None

    lines: list[tuple[str, list[str]]] = []
    for r in rd.cases:
        if only_unconfirmed and r.spr != UNKNOWN:
            continue
        names = [n for n in (r.start, r.end) if n]
        if r.start:
            nxt = rd.names[pos[r.start] + 1] if pos[r.start] + 1 < len(rd.names) else None
            if nxt and nxt != r.end:
                names.insert(1, nxt)
        label = (f"{r.first}–{r.last} · OCR {r.ocr or '—'}"
                 + (f" т.{','.join(r.parts)}" if r.parts else "")
                 + f" · {r.spr if r.spr != UNKNOWN else '?'}")
        lines.append((label, names))
    if not lines and not only_unconfirmed:
        # Карток не прочитано (немає OCR) — кадри-кандидати сіткою, шифри читає око.
        lines = [(f"кандидати {chunk[0]}–{chunk[-1]}", chunk)
                 for chunk in (rd.want[i:i + 4] for i in range(0, len(rd.want), 4))]
    if not lines:
        return []
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    height = int(cell * 0.7) + 22
    paths = []
    for start in range(0, len(lines), per_sheet):
        chunk = lines[start:start + per_sheet]
        cols = max(3, max(len(n) for _, n in chunk))
        canvas = Image.new("L", (cols * cell, len(chunk) * height), 255)
        draw = ImageDraw.Draw(canvas)
        for k, (label, names) in enumerate(chunk):
            y = k * height
            draw.text((6, y + 4), label, fill=0)
            for col, name in enumerate(names):
                p = img(name)
                if p is None:
                    continue
                with Image.open(p) as im:
                    im.draft("L", (cell * 2, cell * 2))
                    g = im.convert("L")
                    g.thumbnail((cell - 8, height - 30))
                canvas.paste(g, (col * cell + 4, y + 22))
                draw.rectangle((col * cell + 4, y + 22, col * cell + 70, y + 38), fill=255)
                draw.text((col * cell + 8, y + 24), Path(name).stem, fill=0)
        p = out / f"cards_{start // per_sheet + 1:02d}.jpg"
        canvas.save(p, "JPEG", quality=80)
        paths.append(p)
    return paths
