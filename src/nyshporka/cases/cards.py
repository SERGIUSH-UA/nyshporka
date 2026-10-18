"""Картки-мішені на плівці: де кінчається одна справа і починається інша.

Плівка FamilySearch з українських архівів несе кілька справ підряд, і кожну
обрамляють службові картки зйомки: на початку — картка з шифрою («ШИФР НА
МИКРОФИЛЬМЕ ф.931, о.1, д.924»), місцем, роками й великим номером пункту, у
кінці — «END OF ITEM» з тією самою шифрою. На межі справ кінцева й початкова
стоять поряд. Картка — білий друк на чорному, тож її видно за тоном кадру без
жодного рушія розпізнавання: чорного там 85–95 %, на аркуші книги — до 35 %,
на темній обкладинці — 55–75 % при значно світлішому середньому тоні.

Машина тут лише знаходить картки й пропонує межі. Шифру з картки читає людина
(чи агент оком) з одного листа-зведення, і вона ж заповнює карту, з якою
`nysh cases split` розкладає теку. Номер справи машина не вгадує: текст,
покладений під сусідню справу, гірший за збірну теку.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Піксель темніший за це — «чорний» (0–255).
DARK_LEVEL = 60
#: Частка чорних пікселів, з якої кадр схожий на картку.
CARD_DARK = 0.80
#: …і середній тон, не світліший за який (обкладинки світліші).
CARD_MEAN = 40.0
#: М'який поріг для зйомки, де картки сірі, а не чорні (ДАЧкО, котушки 2001 р.:
#: середній тон карток 51–62, сторінок — від 144). Вмикається, лише коли строгий
#: не знайшов на плівці жодної пари карток.
LOOSE_DARK = 0.50
LOOSE_MEAN = 80.0
#: Розмір мініатюри для заміру тону: довша сторона.
PROBE = 256
#: Скільки кадрів може мати шматок без карток, щоб вважатись службовим
#: (ракорд, авторське право, таблиця роздільності) — у карту йде як «поза справами».
LEADER_MAX = 6
#: Підпис у карті, який людина мусить замінити номером справи з картки.
UNKNOWN = "?"


class CardsError(RuntimeError):
    """Розібрати плівку не вийшло — з причиною для людини."""


@dataclass
class Tone:
    name: str
    dark: float
    mean: float

    @property
    def card(self) -> bool:
        return self.dark >= CARD_DARK and self.mean <= CARD_MEAN

    @property
    def card_loose(self) -> bool:
        return self.dark >= LOOSE_DARK and self.mean <= LOOSE_MEAN


@dataclass
class Segment:
    """Відтинок плівки: група карток або кадри між ними."""
    kind: str                      # "cards" | "case" | "leader"
    names: list[str]
    pos: tuple[int, int]           # з одиниці
    spr: str = UNKNOWN

    def as_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "spr": self.spr, "first": self.names[0],
                "last": self.names[-1], "from": self.pos[0], "to": self.pos[1],
                "frames": len(self.names)}


@dataclass
class Film:
    frames_dir: Path
    tones: list[Tone]
    segments: list[Segment] = field(default_factory=list)
    loose: bool = False            # картки знайдено м'яким порогом (сірі картки)

    @property
    def runs(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == "cards"]

    @property
    def lone_inside(self) -> list[Segment]:
        """Одиночні темні кадри між двома справами — їх варто подивитись.

        На краях плівки одиночні картки звичайні (номер котушки, перша початкова
        картка, «CONTINUED ON ANOTHER ROLL», «END OF ROLL»), тож про них не
        попереджаємо.
        """
        idx = [k for k, s in enumerate(self.segments) if s.kind == "case"]
        if len(idx) < 2:
            return []
        return [s for k, s in enumerate(self.segments)
                if s.kind == "cards" and len(s.names) == 1 and idx[0] < k < idx[-1]]

    @property
    def cases(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == "case"]

    def draft_map(self) -> list[dict[str, Any]]:
        """Карта для `nysh cases split --map`: справи з «?», решта — поза справами."""
        out = []
        for s in self.segments:
            row: dict[str, Any] = {"spr": s.spr if s.kind == "case" else "-",
                                   "first": s.names[0], "last": s.names[-1]}
            if s.kind == "cards":
                row["cards"] = True
            out.append(row)
        return out

    def as_json(self) -> dict[str, Any]:
        return {"frames_dir": str(self.frames_dir), "frames": len(self.tones),
                "card_runs": len(self.runs), "cases": len(self.cases),
                "segments": [s.as_json() for s in self.segments]}


def tone_of(path: Path) -> Tone:
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        im.draft("L", (PROBE, PROBE))   # JPEG декодується одразу зменшеним
        g = im.convert("L")
        g.thumbnail((PROBE, PROBE))
        a = np.asarray(g)
    return Tone(path.name, float((a < DARK_LEVEL).mean()), float(a.mean()))


def scan(case_dir: str | Path) -> Film:
    """Тон кожного кадру теки й відтинки «картки / справа / ракорд»."""
    from nyshporka.share import align

    d = Path(case_dir)
    frames_dir = align._frames_dir(d) if d.is_dir() else None
    if frames_dir is None:
        raise CardsError(f"у теці {d} немає кадрів")
    paths = align.frames_sorted(frames_dir)
    film = Film(frames_dir, [tone_of(p) for p in paths])
    film.segments = segments(film.tones)
    if not any(s.kind == "cards" and len(s.names) > 1 for s in film.segments):
        loose = segments(film.tones, loose=True)
        if any(s.kind == "cards" and len(s.names) > 1 for s in loose):
            film.segments, film.loose = loose, True
    return film


def segments(tones: list[Tone], *, loose: bool = False) -> list[Segment]:
    """Розрізати плівку на групи карток і кадри між ними.

    Шматок між двома групами — справа. Шматок до першої групи чи після
    останньої — справа лише тоді, коли він довший за ракорд (`LEADER_MAX`):
    плівка буває продовженням справи з іншої котушки («CONTINUED FROM ANOTHER
    ROLL»), і тоді її голова — хвіст чужої справи без своєї картки.
    """
    out: list[Segment] = []
    i, n = 0, len(tones)
    while i < n:
        j = i
        def is_c(t: Tone) -> bool:
            return t.card_loose if loose else t.card

        is_card = is_c(tones[i])
        while j + 1 < n and is_c(tones[j + 1]) == is_card:
            j += 1
        names = [t.name for t in tones[i:j + 1]]
        out.append(Segment("cards" if is_card else "case", names, (i + 1, j + 1)))
        i = j + 1
    # Ракорд — короткий шматок без справи на голові чи хвості плівки (авторське
    # право, таблиця роздільності). Службових карток перед ним буває кілька
    # («SOME EXPOSURES…», номер котушки), тож край визначається не за групами
    # карток, а за тим, що перед ним (чи після нього) немає жодної справи.
    cases = [k for k, s in enumerate(out) if s.kind == "case"]
    for k in (cases[:1] + cases[-1:]) if len(cases) > 1 else []:
        if len(out[k].names) <= LEADER_MAX:
            out[k].kind = "leader"
    # Скільки кадрів групи — справжні картки. Посеред плівки межа — «END OF ITEM»
    # і початкова, тобто дві; перша група після ракорду — лише початкова, бо
    # кінцевої попередньої справи там немає. Решта темних кадрів групи —
    # найчастіше чорна обкладинка книги (тоном від картки її не відрізнити), тож
    # вони йдуть у справу: зайва картка «CONTINUED» у справі шкодить менше, ніж
    # обкладинка, що з неї випала.
    first_case = next((k for k, s in enumerate(out) if s.kind == "case"), None)
    k = 0
    while k < len(out):
        s = out[k]
        if s.kind == "cards" and first_case is not None and k < first_case:
            keep = 1 if k == first_case - 1 else len(s.names)
        elif s.kind == "cards":
            keep = 2
        else:
            keep = len(s.names)
        if s.kind == "cards" and len(s.names) > keep:
            extra = s.names[keep:]
            s.names = s.names[:keep]
            s.pos = (s.pos[0], s.pos[0] + keep - 1)
            nxt = out[k + 1] if k + 1 < len(out) else None
            if nxt is not None and nxt.kind == "case":
                nxt.names = extra + nxt.names
                nxt.pos = (nxt.pos[0] - len(extra), nxt.pos[1])
            else:
                at = s.pos[1] + 1
                out.insert(k + 1, Segment("case", extra, (at, at + len(extra) - 1)))
        k += 1
    # Одиночний темний кадр посеред справи (чорний аркуш, вклейка) теж стає
    # межею: ховати його не можна, бо одиночною буває й справжня початкова
    # картка. Зайву межу видно на листі й знімає людина, злиттям частин у карті.
    return out


def numbering_gaps(names: list[str]) -> list[int]:
    """Номери, пропущені в суцільній нумерації кадрів (`0001.jpg`, `0002.jpg` …)."""
    import re

    nums = sorted(int(m.group(1)) for n in names
                  if (m := re.fullmatch(r"(\d+)\.\w+", n)))
    if len(nums) < 2:
        return []
    have = set(nums)
    return [i for i in range(nums[0], nums[-1] + 1) if i not in have]


def apply_numbers(film: Film, numbers: list[str]) -> None:
    """Підставити номери справ (у порядку плівки) замість «?»."""
    cases = film.cases
    if len(numbers) != len(cases):
        raise CardsError(f"справ на плівці {len(cases)}, а номерів {len(numbers)}")
    for s, num in zip(cases, numbers, strict=True):
        s.spr = num.strip()


def sheet(film: Film, out_dir: str | Path, *, cell: int = 720,
          per_sheet: int = 6) -> list[Path]:
    """Листи на око: кожна група карток рядком, поруч — перший кадр після неї.

    Шифру й межу читають з картки: у парі «END OF ITEM» + початкова кінцева
    закриває попередню справу, а початкова відкриває наступну.
    """
    from PIL import Image, ImageDraw

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[list[str]] = []
    segs = film.segments
    for k, s in enumerate(segs):
        if s.kind != "cards":
            continue
        row = list(s.names[:3])
        if k + 1 < len(segs):
            row.append(segs[k + 1].names[0])
        rows.append(row)
    if not rows:
        return []
    height = int(cell * 0.66)
    paths = []
    for start in range(0, len(rows), per_sheet):
        chunk = rows[start:start + per_sheet]
        cols = max(len(r) for r in chunk)
        canvas = Image.new("L", (cols * cell, len(chunk) * height), 255)
        draw = ImageDraw.Draw(canvas)
        for r, names in enumerate(chunk):
            for c, name in enumerate(names):
                with Image.open(film.frames_dir / name) as im:
                    im.draft("L", (cell * 2, cell * 2))
                    g = im.convert("L")
                    g.thumbnail((cell - 8, height - 8))
                x, y = c * cell, r * height
                canvas.paste(g, (x + 4, y + 4))
                draw.rectangle((x + 4, y + 4, x + 74, y + 26), fill=255)
                draw.text((x + 8, y + 8), Path(name).stem, fill=0)
        p = out / f"cards_{start // per_sheet + 1:02d}.jpg"
        canvas.save(p, "JPEG", quality=80)
        paths.append(p)
    return paths


def write_map(film: Film, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(film.draft_map(), ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return p
