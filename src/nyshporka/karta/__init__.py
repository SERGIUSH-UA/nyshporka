"""🗺 Карта: книга → сучасні поселення з координатами. Один рушій для клієнта й Супряги.

Чи ляже книга на карту покриття Супряги, вирішує цей модуль — і пакувальник
клієнта (`share pack` показує точку до заливки), і сервер (`app.heo`
перераховує пул). Так само, як ворота `share.gates`: правила однієї копії не
розходяться між кінцями. Перенесено з `nyshporka-online/app/heo.py` 28.10.2026.

Звідки точки — з офлайн-паків каталогу (`NYSHPORKA_CATALOG`): `places`
(поселення Wikidata з координатами й усіма адмінодиницями P131, зокрема
районами до 2020) і газетир ЦДІАК `geog` (історичне село → район і область
«нині»). Немає паків — немає й точок, і це не помилка. Сучасна область точки —
з контурів `oblasti.json` (Natural Earth; та сама геометрія, що на карті).

🔴 Губернія чи повіт на картці — це РАЙОН ПОШУКУ, а не покриття (рішення
дослідника 19.10.2026): справа «про вбивство в містечку Мястківка» з шапкою
«Подільська губ.» покриває Мястківку, а не губернію.

🔴 Повіт — жорсткий фільтр. Замір 19.10.2026 на 8203 книгах: без нього
єдиний однойменний у паку бравсь з іншого кінця країни («Васьківці
Летичівського повіту» лягли на Чернігівщину, бо справжніх у паку немає).

🔴 Дві ролі точки — і вони не змішуються на карті:
- `tytul` — село з назви книги чи з місця на картці: покриття справи.
  Точність на вибірці ~95 %.
- `tekst` — згадка з тексту (`places` після збагачення): у метриках це
  здебільшого «звідки люди», у судовій справі — сам предмет. Точність помітно
  нижча, тож карта бере її лише на вимогу.

Слабкі способи (`nechitko` — одна літера різниці; `kvalifikator` —
«Радуляны» → «Старые Радуляны»; `latynka_slabko`) позначені низькою певністю:
на вибірці ~90 %.

Ручний довідник зниклих і перейменованих сіл (`heo_ruchni.yaml`) веде сервер;
сюди він приходить параметром `dovidnyk(ruchni=…)`.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("nyshporka.karta")

#: Номер правил прив'язки. Сервер додає його до відбитка книги (`app.heo.vidbytok`):
#: зміна правил тут перераховує весь пул без окремого кроку на сервері.
PRAVYLA = 11

POD = ["вінниц", "хмельниц", "одес"]
VOL = ["волин", "рівнен", "житомир", "тернопіл", "хмельниц"]

#: Архів → області його губернії. Не сучасна область архіву: ДАЖО зберігає
#: усю Волинську губернію (Малий Жолудськ — нині Рівненщина), ДАХмО — Поділля.
ARKHIV: dict[str, list[str]] = {
    "DAHMO": POD, "DAVIO": POD, "DAZHO": VOL, "DAVOO": ["волин", "рівнен"],
    "DARO": ["рівнен", "волин"], "DAPO": ["полтав", "черкас", "сум"],
    "DAOO": ["одес", "миколаїв", "херсон", "кіровоград", "молдова"],
    "IZMAIL": ["одес", "молдова"], "DAZPO": ["запоріз"], "DADNO": ["дніпропетров"],
    "DACHO": ["чернігів"], "DASO": ["сум", "харків"], "DAHO": ["харків", "сум"],
    "DAKO": ["київ", "черкас", "житомир"], "DAK": ["київ"], "DAKRO": ["кіровоград"],
    "DACHKO": ["черкас"], "DACHVO": ["чернівец"], "DAHEO": ["херсон"],
    "ANRM": ["молдова", "одес", "чернівец"], "GAKO": ["київ"],
    # Галичина й південь — архіви, яких таблиця не знала (28.10.2026): їхні книги
    # прив'язувались без звуження областю, і однойменні села йшли «двозначно».
    "CDIAL": ["львів", "тернопіл", "івано-франків"], "DAIFO": ["івано-франків"],
    "DATO": ["тернопіл"], "DALO": ["львів"], "DAMO": ["миколаїв"],
}
#: Губернія (корінь, як пишуть у назвах справ) → сучасні області. З запасом:
#: це звуження пошуку, а не відповідь.
@functools.lru_cache(maxsize=256)
def oblasti_arkhivu(repo: str) -> tuple[str, ...]:
    """Області архіву за будь-яким його кодом — через довідник архівів ядра.

    🔴 Код ДАВіО в маніфесті буває двома: канонічний `DAVIO` і давній `DAVO`
    (`archives.yaml`, `same_as`), а простір може перевернути канон накладкою —
    простір із накладкою пише `DAVO`, сервер без неї — `DAVIO`. Тож таблиця `ARKHIV` тримає
    один код на архів, а відповідність шукається `same_archive`, не дублем кодів.
    Волинський ДАВоО (`DAVOO`) — окремий архів: «ДАВО» йому навмисно не синонім.
    """
    if repo in ARKHIV:
        return tuple(ARKHIV[repo])
    try:
        from nyshporka.archives import active

        pak = active()
        for kod, obl in ARKHIV.items():
            if pak.same_archive(kod, repo):
                return tuple(obl)
    except Exception:   # довідник архівів не прочитався — лише без звуження областю
        pass
    return ()


HUBERNIIA: dict[str, list[str]] = {
    "поділ": POD, "подол": POD, "волин": VOL, "волын": VOL,
    "київ": ["київ", "черкас", "житомир", "вінниц", "кіровоград"],
    "киев": ["київ", "черкас", "житомир", "вінниц", "кіровоград"],
    "херсон": ["херсон", "миколаїв", "одес", "кіровоград", "дніпропетров"],
    "таврій": ["херсон", "запоріз", "крим"], "таврич": ["херсон", "запоріз", "крим"],
    "катеринослав": ["дніпропетров", "запоріз", "донец", "луган"],
    "екатеринослав": ["дніпропетров", "запоріз", "донец", "луган"],
    "полтав": ["полтав", "черкас", "сум"],
    "чернігів": ["чернігів", "сум", "київ"], "чернигов": ["чернігів", "сум", "київ"],
    "харків": ["харків", "сум", "донец", "луган"], "харьков": ["харків", "сум", "донец", "луган"],
    "бессараб": ["молдова", "одес", "чернівец"],
    # Курщина й північ Чернігівщини — нині Росія: області в паку немає,
    # тож губернія лише впізнається (ручні записи Бочківки, Лопазни).
    "курськ": ["курськ"], "курск": ["курськ"],
}
ADMIN_RE = re.compile(
    r"(губ\b|губ\.|губерн|пов\.|повіт|уезд|уѣзд|волост|район|р-н|обл\.|област|окру[гж]|"
    r"деканат|намісництв|воєводств|імперія|союз|щина$|^поділля$|^волинь$|^україна$|"
    r"^украина$|^молдова$|^бессарабія$|^румунія$|^польща$|^russia|^ukraine|podolia|сільрад|"
    r"міськрад|\bполк\b|канцеляр|протопоп|колоні[їй]\b|сотн[яі]\b)", re.I)
PREFIKS_RE = re.compile(
    r"^(?:с\.|c\.|м\.|смт\.?|сел\.|сл\.|х\.|д\.|м-ко|м-ка|мст\.|село|містечко|місто|деревня|"
    r"деревні|хутір|хутора|слобода|кол\.|колонія|selo|sat(?:ul)?|com\.)\s*", re.I)
#: Дореформений правопис і ru/uk-літери → одна форма для порівняння.
STARE = str.maketrans({"ѣ": "е", "ѳ": "ф", "і": "и", "ї": "и", "ы": "и", "ъ": "", "є": "е",
                       "э": "е", "ь": "", "ґ": "г"})
#: «Большая Бѣлозерка» → «Великая Белозерка»: норма ru у паку — сучасна.
KVAL_ZAMINA = [(r"\bбольш(ая|ой|ое|ие)\b", "велик\\1"), (r"\bбольша\b", "велика")]
KVALIFIKATORY = {
    "велика", "великий", "велике", "великі", "мала", "малий", "мале", "малі", "стара", "старий",
    "старе", "старі", "нова", "новий", "нове", "нові", "верхня", "верхній", "нижня", "нижній",
    "великая", "малая", "малый", "старая", "старый", "новая", "новый", "старые",
    "новые", "верхняя", "нижняя", "veche", "noua", "mare", "mic", "vechi", "noi",
}
#: Відмінки й старі закінчення: «Полонномъ», «Каплинецъ», «Килій», «Луцкѣ».
KINTSI = [("ого", "е"), ("ом", "е"), ("ом", "ое"), ("ой", "а"), ("ки", "ка"),
          ("ец", "ци"), ("ок", "ки"), ("ий", "ия"), ("ий", "ія"), ("ій", "ія"),
          ("ева", "ив"), ("ова", "ив"), ("ова", "ов"), ("ева", "ев"), ("ина", "ин"),
          ("ци", "ця"), ("и", "а"), ("а", "о"), ("а", ""), ("е", "а"),
          ("у", "а"), ("ах", "и"), ("ов", "и"), ("ев", "и"), ("е", ""), ("и", ""),
          ("у", ""), ("ах", ""), ("ня", "ни"), ("ни", "ня"),
          # орудний: «благочиння з Клокушною, Окницею, Єдинцями»
          ("ями", "і"), ("ами", "и"), ("ею", "я"), ("ою", "а")]
SLOVO = r"[А-ЯІЇЄҐ][а-яіїєґ'’ʼ]+(?:-[А-ЯІЇЄҐа-яіїєґ][а-яіїєґ'’ʼ]+)*"
#: «… с. Сивороги Ушицького повіту», «села Біловоди», «м-ка Джурин (Журилов)».
TYTUL_SELO = re.compile(
    r"(?:\bс\.|\bc\.|\bм\.|м-ка|м-ко|\bсмт|\bсела|\bсело|містечка|\bміста|селища|слободи|хутора|"
    r"\bсел\.|\bд\.|села\b)\s*(" + SLOVO + r"(?: " + SLOVO + r"){0,2})")
#: «по церквах сіл: Половенкове, Пряжів» і «Лебединський повіт, 1906 р. (Будилки, Буймер)».
#: «сіл», «селах», «селеній», «сільради», «сельсовета» — за ними перелік поселень.
TYTUL_PERELIK = re.compile(r"(?:\bсіл\b:?|\bсел\w*:?|\bсільрад\w*:?|\bсельсовет\w*:?|"
                           r"\(\s*(?=[А-ЯІЇЄҐ][^)]*,))\s*([^.;)]+)")
#: Роздільники переліку сіл: кома й сполучник.
SPOLUCH_RE = re.compile(r",|\s(?:й|і|та)\s")
#: «Іванівка й Благовіщенка»: друге село після сполучника.
DRUHE_RE = re.compile(r"(" + SLOVO + r"(?: " + SLOVO + r")?)\s+(?:й|і|та)\s+(?:с\.\s*|села\s+)?("
                      + SLOVO + r"(?: " + SLOVO + r")?)")
#: «(тепер Шевченкове)», «(Владичень)», «(с. Переможне)» — назва в дужках.
DUZHKY_RE = re.compile(r"\((?:тепер|нині|суч\.)?\s*(?:с\.|м\.|смт)?\s*(" + SLOVO + r"(?:[ -]"
                       + SLOVO + r")?)\)")
DUZHKY_KOMA_RE = re.compile(r",\s*(?:с\.|м\.|смт)?\s*(" + SLOVO + r"(?: " + SLOVO + r")?)\)")
#: «Рені й села», «Сквира та інші» — хвіст переліку не частина назви.
I_SELA_RE = re.compile(r"\s+(?:й|і|та|и)\s+(?:села|сіл|селища|околиці|інші|ін\.|"
                       r"[\w-]*\s*колоні\w*).*$")
#: «передмістя Чернівців-Ленківці», «передмістя Нікополь-Довгалівка»: частина міста.
PEREDMISTIA_RE = re.compile(r"^передмістя\s+(" + SLOVO + r")$")
TEPER_RE = re.compile(r"^(?:тепер|нині|суч\.)\s*(?:с\.|м\.|смт)?\s*")
#: Місце прикметником при установі, яка стоїть у самому місці. Церкви тут
#: немає свідомо: «Миколаївська церква» — присвята, а не Миколаїв.
_PRYKM = r"[А-ЯІЇЄҐа-яіїєґ][\w'’ʼ]+(?:ськ|цьк|зьк)(?:ого|ої|ий|а|ій|і|ому)"
USTANOVA_RE = re.compile(
    r"((?:" + _PRYKM + r"\s*(?:,|-|\bй\b|\bі\b|\bта\b)\s*)*" + _PRYKM + r")\s+"
    r"(?:(?:міськ|римо-католицьк|парафіяльн|гродськ|земськ|повітов|магістратськ)\w*\s+)*"
    r"(?:костел|сільрад|примар|громад|виконком|волост|гродськ\w* суд|духовн\w* суд|"
    r"земськ\w* суд|магістрат|ратуш|кагал|синагог|общин)")
PRYKM_OSNOVA_RE = re.compile(r"([\w'’ʼ]+?)(янськ|анськ|ськ|цьк|зьк)(?:ого|ої|ий|а|ій|і|ому)$")
#: FamilySearch: «Церковні записи · Pylyava, Litin (каталог FamilySearch)».
TYTUL_FS = re.compile(r"·\s*([A-Za-z'’ -]+?),\s*([A-Za-z'’ -]+?)\s*(?:,|\(|$)")
TYTUL_POVIT = re.compile(r"([А-ЯІЇЄҐ][а-яіїєґ'’ʼ-]+?)"
                         r"(?:ського|ський|цького|цький|зького|зький|ского|скаго|ский|цкого|зкого)\s+"
                         r"(?:пов|уезд|уѣзд|р-н|район|округ)", re.I)
#: «Ямпільського пов. Подільської губ.» → корінь повіту й губернія.
POVIT_HUB_RE = re.compile(
    r"([А-ЯІЇЄҐ][а-яіїєґ'’ʼ-]+?)(?:ського|цького|зького|ского|цкого|зкого)\s+пов.*?"
    r"([А-ЯІЇЄҐ][а-яіїєґ'’ʼ-]+?)(?:ської|ськой|ской)\s+губ")
PRYKM = re.compile(r"(ського|цького|зького|ского|скаго|цкого|зкого|ської|ской|ський|зький|ский"
                   r"|ська|цька|зька|ская)$")

#: Як далеко від повітового міста ще «в повіті». Повіти XIX ст. — до 100 км.
POVIT_KM = 100
#: Сусіди однієї книги: однойменних розводить відстань до вже поставлених.
SUSID_KM = 40
#: Види поселень, де стоїть повітова установа, костел, примарія.
MISTA = frozenset({"місто", "смт", "селище міського типу"})
#: Однойменні ближче за це — один населений пункт, записаний двічі.
DUBL_KM = 5

#: Способи з низькою певністю (на вибірці ~90 %).
NYZKA = frozenset({"nechitko", "kvalifikator", "prykmetnyk", "latynka_slabko"})


#: Контури сучасних областей (Natural Earth) — та сама геометрія, що на карті.
KONTURY = Path(__file__).resolve().parent / "oblasti.json"


@functools.cache
def _kontury() -> list[tuple[str, tuple[float, float, float, float], list[list[list[float]]]]]:
    """Сучасні області з `oblasti.json`: (назва, рамка, кільця)."""
    dani = json.loads(KONTURY.read_text(encoding="utf-8"))
    out = []
    for o in dani["oblasti"]:
        xs = [x for k in o["kiltsia"] for x, _ in k]
        ys = [y for k in o["kiltsia"] for _, y in k]
        out.append((o["nazva"], (min(xs), min(ys), max(xs), max(ys)), o["kiltsia"]))
    return out


def v_kiltsi(lng: float, lat: float, kiltse: list[list[float]]) -> bool:
    vseredyni = False
    j = len(kiltse) - 1
    for i in range(len(kiltse)):
        xi, yi = kiltse[i]
        xj, yj = kiltse[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            vseredyni = not vseredyni
        j = i
    return vseredyni


def oblast_tochky(lat: float, lng: float, zapasna: str) -> str:
    """Сучасна область за геометрією, а не за P131 Wikidata.

    P131 несе й колишні області: Ярмолинці (Хмельниччина) мали серед них
    Вінницьку, і фільтр «Вінницька область» малював їх за межею області.
    Контури ті самі, що на карті, тож фільтр і малюнок збігаються. Точка поза
    всіма контурами (узбережжя, спрощене до ~1 км) — перша область з паку.
    """
    for nazva, (x0, y0, x1, y1), kiltsia in _kontury():
        if x0 <= lng <= x1 and y0 <= lat <= y1 and any(v_kiltsi(lng, lat, k) for k in kiltsia):
            return nazva
    return zapasna.split("|")[0].strip()


def _km(a: dict[str, Any], b: dict[str, Any]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def _norm(s: str) -> str:
    from nyshporka.geog.gazetteer import norm_name

    return norm_name(s)


def _lat(s: str) -> str:
    """Латинка й кирилиця → одна форма: «Pylyava» і «Пилява» → «pilava».

    `normalize_for_matching` клієнта їх не зводить (`piliava` проти `pilava`,
    `kh` проти `h`), а назви FamilySearch пишуть саме так.
    """
    from nyshporka.utils.translit import normalize_for_matching

    t = normalize_for_matching(s)
    for a, b in (("kh", "h"), ("'", ""), ("’", ""), ("ʼ", ""), ("ia", "a"), ("iu", "u"),
                 ("io", "o"), ("ie", "e"), ("yo", "o"), ("ya", "a"), ("yu", "u"), ("y", "i"),
                 ("-", ""), (" ", ""), ("w", "v"), ("ă", "e"), ("î", "i"), ("â", "i")):
        t = t.replace(a, b)
    return t


@dataclass
class Dovidnyk:
    """Поселення паку з індексами під усі способи пошуку."""

    idx: dict[str, dict[str, dict[str, Any]]] = field(default_factory=lambda: defaultdict(dict))
    trl: dict[str, dict[str, dict[str, Any]]] = field(default_factory=lambda: defaultdict(dict))
    kval: dict[str, dict[str, dict[str, Any]]] = field(default_factory=lambda: defaultdict(dict))
    vsi: list[dict[str, Any]] = field(default_factory=list)
    mista: list[dict[str, Any]] = field(default_factory=list)
    haz: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    #: Корінь повіту → губернії, де такий повіт був (з карток газетира).
    povit_hub: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    #: Латинка (`z_latynky`): пул поселень на повіт чи область і вибір на пару
    #: «село + пул». Книг обходу FS — тисячі, а пар «село, повіт» — сотні: без
    #: пам'яті кожна книга заново перебирала 33 тис. поселень.
    lat_pul: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = field(default_factory=dict)
    lat_vybir: dict[tuple[str, str, tuple[str, ...]], Any] = field(default_factory=dict)

    def dodaty(self, d: dict[str, Any]) -> None:
        d["obl"] = ((d["top"] or "") + " " + ("молдова" if d["country"] == "MD" else "")).lower()
        d["adm"] = (d["admin"] or "").lower().translate(STARE)
        kliuchi = {d["norm_uk"], d["norm_ru"], *(d["norm_alias"] or "").split(" | ")} - {None, ""}
        d["kl"] = {k.translate(STARE) for k in kliuchi}
        for k in kliuchi:
            self.idx[k][d["qid"]] = d
            self.idx[k.translate(STARE)][d["qid"]] = d
            self.trl[_lat(k)][d["qid"]] = d
            slova = k.replace("-", " ").split()
            if len(slova) == 2 and (slova[0] in KVALIFIKATORY) != (slova[1] in KVALIFIKATORY):
                osnova = slova[1] if slova[0] in KVALIFIKATORY else slova[0]
                self.kval[osnova.translate(STARE)][d["qid"]] = d
        for t in (d["translit"] or "").split():
            self.trl[_lat(t)][d["qid"]] = d
        self.vsi.append(d)
        if d["kind"] in MISTA:
            self.mista.append(d)

    def dodaty_nazvy(self, d: dict[str, Any], nazvy: list[str], povit: str) -> None:
        """Старі назви поселення паку (ручний довідник, запис з `qid`)."""
        for nazva in nazvy:
            k = _norm(str(nazva))
            if not k:
                continue
            d["kl"].add(k.translate(STARE))
            self.idx[k][d["qid"]] = d
            self.idx[k.translate(STARE)][d["qid"]] = d
            self.trl[_lat(k)][d["qid"]] = d
        # Повіт — у адмінодиницю: за ним `_vybraty` розводить однойменні.
        if povit:
            d["adm"] += " | " + f"{povit} повіт".lower().translate(STARE)

    def dodaty_hazetyr(self, d: dict[str, Any]) -> None:
        m_o = re.search(r"([\w'’-]+)\s+обл", d["modern_place"])
        m_r = re.search(r"([\w'’-]+)\s+р-н", d["modern_place"])
        d["o"] = _norm(m_o.group(1))[:6] if m_o else ""
        # корінь коротший за прикметник: «Барського» → «барск» ловить і «Барський»
        d["r"] = _norm(m_r.group(1)).translate(STARE)[:5] if m_r else ""
        for k in {d["norm_uk"], d["norm_ru"]}:
            if k:
                self.haz[k.translate(STARE)].append(d)
        m = POVIT_HUB_RE.search(d.get("uezd_gub") or "")
        if m:
            hub = _norm(m.group(2))
            for kluch in HUBERNIIA:
                if hub.startswith(kluch):
                    self.povit_hub[_norm(m.group(1)).translate(STARE)[:6]].add(kluch)


_STANY = {"зникле", "злите", "перейменоване", "існує"}
_TOCHNIST = {"точно", "приблизно"}


def pereviryty_ruchni(sela: list[dict[str, Any]]) -> list[str]:
    """Вади ручного довідника — порожньо, якщо все гаразд.

    Тест (`tests/test_heo.py`) ганяє це по справжньому файлу: помилка в
    записі має валити CI, а не тихо випадати з карти.
    """
    vady: list[str] = []
    bachyly: set[str] = set()
    for i, s in enumerate(sela, 1):
        imia = f"запис {i} ({s.get('id') or s.get('nazva') or '?'})"
        id_ = str(s.get("id") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,37}", id_):
            vady.append(f"{imia}: id — латинка a-z, цифри, дефіс, 3–38 знаків")
        elif id_ in bachyly:
            vady.append(f"{imia}: id повторюється")
        bachyly.add(id_)
        if not str(s.get("nazva") or "").strip():
            vady.append(f"{imia}: немає назви")
        if s.get("qid"):
            # Стара назва села, яке є в паку під сучасною: точка — з паку.
            if not re.fullmatch(r"Q\d+", str(s["qid"])):
                vady.append(f"{imia}: qid — Q-ідентифікатор Wikidata")
            if "lat" in s or "lng" in s:
                vady.append(f"{imia}: з qid координати беруться з паку — lat/lng зайві")
        else:
            try:
                lat, lng = float(s["lat"]), float(s["lng"])
                # Україна й Молдова з запасом (і північ Чернігівської губернії, нині
                # Брянщина); поза цим — переплутані lat/lng
                if not (44.0 <= lat <= 53.5 and 22.0 <= lng <= 40.5):
                    vady.append(f"{imia}: координати поза Україною й Молдовою — "
                                "lat/lng переплутані?")
            except (KeyError, TypeError, ValueError):
                vady.append(f"{imia}: немає координат lat/lng числами")
            if s.get("tochnist") not in _TOCHNIST:
                vady.append(f"{imia}: tochnist — {' | '.join(sorted(_TOCHNIST))}")
        if s.get("qid") and s.get("tochnist") and s["tochnist"] not in _TOCHNIST:
            vady.append(f"{imia}: tochnist — {' | '.join(sorted(_TOCHNIST))}")
        if s.get("stan") not in _STANY:
            vady.append(f"{imia}: stan — {' | '.join(sorted(_STANY))}")
        if not str(s.get("dzherelo") or "").strip():
            vady.append(f"{imia}: без джерела точка на карту не йде")
        if s.get("zlyte_z") and not re.fullmatch(r"Q\d+", str(s["zlyte_z"])):
            vady.append(f"{imia}: zlyte_z — Q-ідентифікатор Wikidata")
        if not isinstance(s.get("inshi_nazvy") or [], list):
            vady.append(f"{imia}: inshi_nazvy — перелік у квадратних дужках")
    return vady


def _ruchnyi_zapys(s: dict[str, Any]) -> dict[str, Any]:
    """Запис довідника → рядок того самого виду, що й поселення паку."""
    lat, lng = float(s["lat"]), float(s["lng"])
    oblast = oblast_tochky(lat, lng, "")
    inshi = [str(x) for x in (s.get("inshi_nazvy") or []) if str(x).strip()]
    # Повіт — у адмінодиниці: за ним `_vybraty` розводить однойменні.
    admin = " | ".join(x for x in (f"{s['povit']} повіт" if s.get("povit") else "",
                                   f"{s['huberniia']} губернія" if s.get("huberniia") else "")
                       if x)
    return {"qid": f"r:{s['id']}", "name_uk": str(s["nazva"]), "kind": str(s["stan"]),
            "top": oblast, "admin": admin, "country": "MD" if oblast == "Молдова" else "UA",
            "lat": lat, "lng": lng, "norm_uk": _norm(str(s["nazva"])), "norm_ru": "",
            "norm_alias": " | ".join(_norm(x) for x in inshi), "translit": ""}


#: Зібрані довідники: (тека каталогу, відбиток ручних записів) → довідник.
_DOVIDNYKY: dict[tuple[str, str], Dovidnyk] = {}


def dovidnyk(ruchni: list[dict[str, Any]] | None = None, *,
             pamiat: bool = True) -> Dovidnyk | None:
    """Довідник із паків каталогу; None — паку поселень немає.

    `ruchni` — записи ручного довідника сервера (`app.heo.ruchni()`); клієнт
    живе без них. Збирання — секунди (33 тис. поселень), тож довідник один на
    процес для тієї самої теки каталогу й тих самих записів; `pamiat=False` —
    зібрати наново (сервер тримає свою пам'ять, тести міняють каталог).
    """
    sela_vkhid = [dict(x) for x in (ruchni or [])]
    kliuch = (os.environ.get("NYSHPORKA_CATALOG", ""),
              hashlib.sha256(json.dumps(sela_vkhid, ensure_ascii=False, sort_keys=True,
                                        default=str).encode()).hexdigest()[:16])
    if pamiat and kliuch in _DOVIDNYKY:
        return _DOVIDNYKY[kliuch]
    from nyshporka.catalog.store import CatalogMissing, close_all, open_packs

    dov = Dovidnyk()
    try:
        paky = open_packs("places", with_own=False)
    except CatalogMissing:
        return None
    try:
        for _pid, con in paky:
            for r in con.execute("SELECT qid, name_uk, kind, top, admin, country, lat, lng, "
                                 "norm_uk, norm_ru, norm_alias, translit FROM modern "
                                 "WHERE lat IS NOT NULL"):
                dov.dodaty(dict(r))
    finally:
        close_all(paky)
    # газетир — підмога для перейменованих; без нього розбір просто слабший
    try:
        haz = open_packs("geog", with_own=False)
    except CatalogMissing:
        haz = []
    try:
        for _pid, con in haz:
            try:
                for r in con.execute("SELECT norm_uk, norm_ru, uezd_gub, modern_place FROM places "
                                     "WHERE modern_place <> ''"):
                    dov.dodaty_hazetyr(dict(r))
            except sqlite3.Error:
                log.warning("газетир %s не читається", _pid)
    finally:
        close_all(haz)
    # Ручні записи — після паку: запис із вадою йде в журнал і пропускається,
    # а не гасить усю карту (тест сервера ловить вади раніше).
    sela = sela_vkhid
    za_qid = {d["qid"]: d for d in dov.vsi}
    for s in sela:
        if pereviryty_ruchni([s]):
            log.warning("ручний запис пропущено: %s", "; ".join(pereviryty_ruchni([s])))
            continue
        if not s.get("qid"):
            d = _ruchnyi_zapys(s)
            dov.dodaty(d)
        elif s["qid"] in za_qid:
            d = za_qid[s["qid"]]
            dov.dodaty_nazvy(d, [str(s["nazva"]), *(s.get("inshi_nazvy") or [])],
                             str(s.get("povit") or ""))
        else:
            log.warning("ручний запис %s: %s немає в паку", s["id"], s["qid"])
            continue
        # Губернія запису — теж «область» для фільтра: Лопазна нині в Брянській
        # області, якої пак не знає, а Молокіш — у Молдові, хоч книга подільська.
        hub = _norm(str(s.get("huberniia") or "")).translate(STARE)
        d["obl"] += "".join(" " + " ".join([k, *v]) for k, v in HUBERNIIA.items()
                            if hub.startswith(k.translate(STARE)))
    if pamiat:
        _DOVIDNYKY[kliuch] = dov
    return dov


# ── розбір однієї книги ─────────────────────────────────────────────────────

@dataclass
class Tochka:
    qid: str
    nazva: str
    oblast: str
    lat: float
    lng: float
    rol: str          # tytul | tekst
    sposib: str       # odnoznachno | oblast | povit | vidstan | seriia | varianty | hazetyr |
    #                   nechitko | kvalifikator | prykmetnyk | latynka | latynka_slabko
    dzherelo: str     # як місце стоїть у книзі

    @property
    def pevnist(self) -> str:
        return "nyzka" if self.sposib in NYZKA else "vysoka"


def _chystyty(nazva: str) -> str:
    n = _norm(PREFIKS_RE.sub("", nazva.strip()))
    for a, b in KVAL_ZAMINA:
        n = re.sub(a, b, n)
    return n


def _kandydaty(dov: Dovidnyk, nazva: str) -> dict[str, dict[str, Any]]:
    n = _chystyty(nazva)
    if not n:
        return {}
    if re.fullmatch(r"[a-zăâîșțşţąćęłńóśźżüéöő' -]+", n):
        return dov.trl.get(_lat(n), {})
    slova = n.replace("-", " ").split()
    dod = ([" ".join(reversed(slova)), "-".join(slova), "-".join(reversed(slova))]
           if len(slova) == 2 else [])
    for k in (n, n.translate(STARE), *dod):
        if k in dov.idx:
            return dov.idx[k]
    for k in (n, n.translate(STARE)):
        for suf, zam in KINTSI:
            if k.endswith(suf) and len(k) - len(suf) >= 3 and k[: -len(suf)] + zam in dov.idx:
                return dov.idx[k[: -len(suf)] + zam]
    return {}


def _varianty(s: str) -> list[str]:
    """«Мінжир (Mingir), Бессарабія» → [«Мінжир», «Mingir»]; «суч. Bulboaca» теж."""
    # Пробіл зрізати ДО перевірки: « Бессарабія» з «Аккерманський повіт, Бессарабія»
    # не ловилась `^бессарабія$` і йшла назвою села (13 книг ДАОО, 25.10.2026).
    # Частина з самих прикметників («Бендерський») — повіт, а не село;
    # «Варшава / Краків / Львів» — де засідала канцелярія, а не одне місце.
    nazva = [c for c in (I_SELA_RE.sub("", x.strip()) for x in s.split(","))
             if c and not ADMIN_RE.search(c) and _obrizaty(c) and " / " not in c]
    if not nazva:
        return []
    v = nazva[0]
    # «Рені й села (за користувачем…)» — 95 книг ДАОО 914 не лягали, бо назвою
    # села бралось «Рені й села», а другою — «за користувачем» (25.10.2026).
    out = [I_SELA_RE.sub("", re.sub(r"\(.*?\)|\(.*$", "", v)).strip()]
    dodatkovi = [TEPER_RE.sub("", x).strip() for x in re.findall(r"\(([^);]*)", v)]
    # «Дракула (Ізмаїльщина)»: край у дужках — не друга назва села.
    out += [x for x in dodatkovi if PREFIKS_RE.sub("", x)[:1].isupper() and not ADMIN_RE.search(x)]
    out += [x.strip() for x in re.findall(r"суч\.\s*([^);,]+)", v)]
    return [x for x in dict.fromkeys(y for x in out for y in _peredmistia(x)) if x]


def _peredmistia(x: str) -> list[str]:
    """«передмістя Чернівців-Ленківці» → [частина, місто]: пак знає місто, а
    передмістя — не завжди. Решта назв — як є."""
    m = PEREDMISTIA_RE.match(x)
    if not m or "-" not in m.group(1):
        return [x]
    misto, chastyna = m.group(1).split("-", 1)
    # «Чернівців» — родовий: місто в називному (Чернівці).
    return [m.group(1), chastyna, re.sub(r"ів$", "і", misto)]


def _obrizaty(s: str) -> str:
    """«Пирятина Пирятинського» → «Пирятина»: повіт не частина назви села."""
    slova = s.strip().split()
    # «м. Літин Державний архів Хмельницької області» — назва архіву за селом.
    if "Державний" in slova:
        slova = slova[: slova.index("Державний")]
    while slova and PRYKM.search(slova[-1]):
        slova.pop()
    return " ".join(slova)


def _selo(x: str) -> bool:
    """Схоже на назву поселення, а не на повіт чи присвяту храму."""
    return (bool(re.fullmatch(SLOVO + r"(?: " + SLOVO + r")?", x)) and not ADMIN_RE.search(x)
            and not PRYKM.search(x))


def z_nazvy(title: str) -> list[str]:
    """Села, названі в назві книги."""
    out = [_obrizaty(m) for m in TYTUL_SELO.findall(title)]
    for perelik in TYTUL_PERELIK.findall(title):
        for x in SPOLUCH_RE.split(perelik):
            x = _obrizaty(x.strip())
            if re.fullmatch(SLOVO + r"(?: " + SLOVO + r")?", x) and not ADMIN_RE.search(x):
                out.append(x)
    # «с. Іванівка й Благовіщенка», «по селах Лапинка і Довгалівка»: друге
    # село після сполучника (25.10.2026 — такі книги лягали лише першим).
    for m in DRUHE_RE.finditer(title):
        if _obrizaty(m.group(1)) in out and _selo(_obrizaty(m.group(2))):
            out.append(_obrizaty(m.group(2)))
    # «Карамахмет (тепер Шевченкове)», «Імпуцита (Владичень)»: сучасна чи друга
    # назва в дужках — пак знає саме її.
    for m in DUZHKY_RE.finditer(title):
        if _selo(m.group(1)):
            out.append(m.group(1))
    # «(нотаріус Калужський, Новоархангельськ)» — місце останнім у дужках.
    for m in DUZHKY_KOMA_RE.finditer(title):
        if _selo(m.group(1)):
            out.append(m.group(1))
    fs = TYTUL_FS.search(title)
    if fs:
        out.append(fs.group(1))
    return [x for x in dict.fromkeys(out) if x]


def z_prykmetnyka(title: str) -> list[tuple[str, list[str]]]:
    """Місця, названі прикметником при установі: «Деражнянського костелу»,
    «Саксаганська й Новочигринівська сільради», «Ізмаїльської міської примарії».

    Повертає (прикметник, можливі назви): прикметник однозначно назву не
    відновлює (Деражня, Славута, Острожець, Іллінці), тож пробуються кілька.
    """
    out: list[tuple[str, list[str]]] = []
    for m in USTANOVA_RE.finditer(title):
        for x in re.split(r"\s*(?:,|-|\bй\b|\bі\b|\bта\b)\s*", m.group(1)):
            o = PRYKM_OSNOVA_RE.match(x.strip())
            if not o or len(o.group(1)) < 3:
                continue
            os_, suf = o.group(1), o.group(2)
            if suf == "цьк":
                formy = [os_ + "ць", os_[:-1] + "ці", os_ + "ці", os_ + "ця", os_]
            elif suf == "янськ":
                formy = [os_ + "я", os_ + "яни", os_ + "янка", os_ + "ян"]
            elif suf == "анськ":
                formy = [os_ + "а", os_ + "ани", os_ + "анка"]
            else:
                formy = [os_, os_ + "а", os_ + "я", os_ + "е", os_ + "и", os_ + "о", os_ + "ь",
                         os_ + "ка"]
                if os_.endswith("й"):
                    formy.append(os_[:-1] + "я")
            out.append((x.strip(), formy))
    return out


def _z_prykmetnyka(dov: Dovidnyk, formy: list[str], kt: _Kontekst) -> dict[str, Any] | None:
    """Поселення за можливими назвами — лише в області справи й лише єдине."""
    c: dict[str, dict[str, Any]] = {}
    for f in formy:
        n = _norm(f)
        c.update(dov.idx.get(n, {}))
        c.update(dov.idx.get(n.translate(STARE), {}))
    if not c:
        return None
    # Консисторія чи деканат могли сягати за губернію архіву (римо-католицька
    # консисторія в ДАЖО — і Тетіїв, і Кодима): одне поселення на весь пак — воно.
    if len({d["qid"] for d in c.values()}) == 1:
        return next(iter(c.values()))
    if not kt.obl:
        return None
    d, rez = _vybraty(c, kt)
    if d is None and rez == "dvoznachno":
        # Костел, примарія, суд стоять у місті: Славутський костел — місто
        # Славута, а не однойменне село Віньковеччини.
        mista = {q: x for q, x in c.items() if x["kind"] in MISTA
                 and (not kt.obl or any(o in x["obl"] for o in kt.obl))}
        if len(mista) == 1:
            return next(iter(mista.values()))
    return d


@dataclass
class _Kontekst:
    obl: list[str]
    povit: list[str]
    tsentry: list[dict[str, Any]]
    tochky: list[dict[str, Any]] = field(default_factory=list)
    #: Точки сусідніх книг того самого опису — останній доказ для однойменних.
    seriia: list[dict[str, Any]] = field(default_factory=list)
    _pul: list[dict[str, Any]] | None = None


def _kontekst(dov: Dovidnyk, repo: str, title: str, place: str, places: list[str]) -> _Kontekst:
    tekst = " ".join([title, place, *places])
    low = tekst.lower()
    obl = list(oblasti_arkhivu(repo))
    for k, v in HUBERNIIA.items():
        if (re.search(k + r"\w*\s*(губ|намісн|воєв|епарх|єпарх|$)", low)
                or k + "ськ" in low or k + "ская" in low):
            obl += v
    for m in re.findall(r"([а-яіїєґ'’-]+?)(?:ська|ской|ської)\s+обл", low):
        obl.append(m[:6])
    povit = []
    # Повна основа («катеринослав», «проскурів») — щоб знайти саме повітове
    # місто, а не перше з тим самим початком: «катери…» вело на Кипуче
    # Луганщини замість Катеринослава (нині Дніпро).
    povit_povni = []
    #: Основа міста на «-ець» — першою: «Липовецького» ліниво ріжеться на
    #: «Липове» + «цького», і точна назва знаходила село Липове, а не Липовець
    #: (25.10.2026: Іллінці, Гуменці, Гринчук «поза повітом»).
    povit_ts = []
    for m in TYTUL_POVIT.finditer(tekst):
        povne = _norm(m.group(1)).translate(STARE)
        if len(povne) >= 3:
            povit.append(povne[:6])
            povit_povni.append(povne)
            if tekst[m.end(1)] in "цЦ":
                povit_ts.append(povne + "ц")
    # FamilySearch: повіт латинкою («Litin») → повітове місто → корінь кирилицею
    fs = TYTUL_FS.search(title)
    if fs:
        shukane = _lat(fs.group(2))
        for m in dov.mista:
            formy = {_lat(k) for k in m["kl"]} | {_lat(t) for t in (m["translit"] or "").split()}
            if shukane in formy:
                povit.append(sorted(m["kl"])[0][:6])
    obl_povitu = [o for p in povit for h in dov.povit_hub.get(p, ()) for o in HUBERNIIA[h]]
    zvuzhennia = obl_povitu or obl

    def v_zoni(m: dict[str, Any]) -> bool:
        return not zvuzhennia or any(o in m["obl"] for o in zvuzhennia)

    # Спершу — точна назва серед усіх поселень (Ольгопіль нині село, і серед
    # міст його немає), лише в губернії повіту; немає — початок назви серед міст.
    # Точну назву звужує лише губернія повіту, не архів: Катеринославський
    # повіт у справі Запорізького архіву — повітове місто в Дніпрі.
    def tochno(osnovy: list[str]) -> list[dict[str, Any]]:
        # Без повіту перебір усіх поселень коштував ~1 с на книгу (замір 25.10.2026).
        if not osnovy:
            return []
        return [m for m in dov.vsi
                if (not obl_povitu or any(o in m["obl"] for o in obl_povitu)) and any(
                    k == p or k.startswith(p + "-") or k.startswith(p + " ")
                    for k in m["kl"] for p in osnovy)]

    tsentry = (povit_ts and tochno(povit_ts)) or tochno(povit_povni)
    if not tsentry and povit:
        tsentry = [m for m in dov.mista if any(k.startswith(p) for k in m["kl"] for p in povit)]
        # Повітове місто — лише в губернії, де такий повіт був: Ямпільський
        # повіт — Поділля, а Ямпіль із Ямпільським районом є й на Сумщині
        # («Антонівка Ямпільського повіту» лягала туди). Губернію повіту знає
        # газетир; не знає — звужує область архіву чи губернії з назви.
        if zvuzhennia:
            tsentry = [m for m in tsentry if v_zoni(m)] or tsentry
    # Справа ЦДІАК без губернії в назві: губернія повіту з газетира звужує й
    # самі села («Демівка Ольгопільського повіту» — не Львівщина).
    return _Kontekst(obl=obl or obl_povitu, povit=povit, tsentry=tsentry)


def _pul(dov: Dovidnyk, kt: _Kontekst) -> list[dict[str, Any]]:
    """Поселення в межах повіту — простір для слабких способів."""
    if kt._pul is None:
        kt._pul = ([d for d in dov.vsi if min(_km(d, t) for t in kt.tsentry) <= POVIT_KM]
                   if kt.tsentry else [])
    return kt._pul


def _vybraty(c: dict[str, dict[str, Any]], kt: _Kontekst) -> tuple[dict[str, Any] | None, str]:
    """Один кандидат або (None, причина). Порядок: область → повіт → сусіди."""
    rows = list(c.values())
    if not rows:
        return None, "nema"
    if kt.obl:
        v = [d for d in rows if any(o in d["obl"] for o in kt.obl)]
        if len(rows) == 1 and not v:
            return None, "poza_oblastiu"
        if v:
            rows = v
    if kt.tsentry:
        # Межа повіту — відстань, а не назва району: Ямпільський район є й на
        # Сумщині, і за назвою туди йшли села Ямпільського повіту Поділля.
        v = [d for d in rows if min(_km(d, t) for t in kt.tsentry) <= POVIT_KM]
        if not v:
            return None, "poza_povitom"
        rows = v
    if len(rows) == 1:
        return rows[0], "odnoznachno" if len(c) == 1 else "oblast"
    # Дубль Wikidata: те саме місто двома записами за кілька кілометрів (Славута).
    if _odne(rows):
        return rows[0], "oblast"
    if kt.povit:
        v = [d for d in rows if any(p in d["adm"] for p in kt.povit)]
        if len(v) == 1 or _odne(v):
            return v[0], "povit"
        v2 = [d for d in (v or rows)
              if kt.tsentry and min(_km(d, t) for t in kt.tsentry) <= 60]
        if len(v2) == 1 or _odne(v2):
            return v2[0], "povit"
    if kt.tochky:
        v = [d for d in rows if min(_km(d, t) for t in kt.tochky) <= SUSID_KM]
        if len(v) == 1 or _odne(v):
            return v[0], "vidstan"
    # Сусіди за описом: опис архіву — одна парафія, повіт чи благочиння, тож із
    # кількох однойменних справжнє те, що поруч із уже прив'язаними справами
    # серії (25.10.2026: Фузовка, Томай, Здовбиця, Василівка — 351 книга).
    if kt.seriia:
        v = [d for d in rows if min(_km(d, t) for t in kt.seriia) <= SUSID_KM]
        if len(v) == 1 or _odne(v):
            return v[0], "seriia"
    return None, "dvoznachno"


def _odne(rows: list[dict[str, Any]]) -> bool:
    """Кілька записів — одне поселення: та сама назва в межах `DUBL_KM`.

    🔴 На кожному кроці вибору, а не лише першому: Яланець Бершадського району
    стоїть у паку двічі за 2 км, а третій Яланець — за 77 км. Перший крок дублі
    не зводив (три записи), а крок «до 60 км від повітового міста» лишав два
    записи того самого села й казав «двозначно» (28.10.2026).
    """
    return (len(rows) > 1 and len({d["name_uk"] for d in rows}) == 1
            and max(_km(rows[0], d) for d in rows) <= DUBL_KM)


def _z_hazetyra(dov: Dovidnyk, nazva: str, kt: _Kontekst) -> dict[str, Any] | None:
    """Історична назва → район і область «нині» → поселення там зі спільним коренем.

    Ловить перейменування: «Чемериси Волоські» Могилівського повіту — нині
    Чемериси-Барські Барського району.
    """
    n = _chystyty(nazva).translate(STARE)
    karty = dov.haz.get(n, [])
    if kt.povit:
        # Картка іншого повіту — інше село («Кам'яне Лебединського» не Савранське).
        karty = [k for k in karty if any(p in _norm(k["uezd_gub"]).translate(STARE)
                                         for p in kt.povit)]
    rai = {(k["o"], k["r"]) for k in karty if k["r"]}
    if len(rai) != 1 or not n:
        return None
    o, r = rai.pop()
    korin = n.split()[0][:5]
    # Корінь — на початку слова: «янів» усередині «мар'янівки» — інше село
    # (Янів Вінницького повіту — нині Іванів, а лягав на Мар'янівку, 21.10.2026).
    v = [d for d in dov.vsi if o in d["obl"] and r in d["adm"]
         and any(w.startswith(korin) for k in d["kl"] for w in re.split(r"[\s-]+", k))]
    return v[0] if len(v) == 1 else None


def _z_kvalifikatorom(dov: Dovidnyk, nazva: str, kt: _Kontekst) -> dict[str, Any] | None:
    """«Радуляны» → «Старые Радуляны», лише якщо в повіті такий один."""
    n = _chystyty(nazva).translate(STARE)
    c = dov.kval.get(n) or {}
    if not c:
        for suf, zam in KINTSI:
            if n.endswith(suf) and n[: -len(suf)] + zam in dov.kval:
                c = dov.kval[n[: -len(suf)] + zam]
                break
    pul = _pul(dov, kt)
    if not c or not pul:
        return None
    qid = {d["qid"] for d in pul}
    v = [d for d in c.values() if d["qid"] in qid]
    return v[0] if len(v) == 1 else None


def _nechitko(dov: Dovidnyk, nazva: str, kt: _Kontekst) -> dict[str, Any] | None:
    """Одна літера різниці (шум читання) — лише в повіті й лише єдиний.

    По кількох областях одна літера вже дає чуже село: «Юльківка Сумського
    повіту» без повіту лягала на донецьку Юрківку.
    """
    from rapidfuzz.distance import Levenshtein

    n = _chystyty(nazva).translate(STARE)
    pul = _pul(dov, kt)
    if len(n) < 6 or not re.fullmatch(r"[а-яґ' -]+", n) or not pul:
        return None
    # «Мечетна Велика» — у паку «Велика Мечетня»: порядок слів і літера.
    slova = n.split()
    formy = [n, " ".join(reversed(slova))] if len(slova) == 2 else [n]
    naikrashchi: dict[str, tuple[int, dict[str, Any]]] = {}
    for d in pul:
        for k, f in ((k, f) for k in d["kl"] for f in formy):
            if abs(len(k) - len(f)) <= 1:
                dist = Levenshtein.distance(f, k, score_cutoff=1)
                if dist <= 1 and (d["qid"] not in naikrashchi or dist < naikrashchi[d["qid"]][0]):
                    naikrashchi[d["qid"]] = (dist, d)
    if not naikrashchi:
        return None
    best = min(x[0] for x in naikrashchi.values())
    v = [d for dist, d in naikrashchi.values() if dist == best]
    return v[0] if len(v) == 1 else None


# ── латинка: села FamilySearch і польські назви костелів ────────────────────
#
# Пак знає поселення кирилицею, а книги з обходу FamilySearch несуть село
# латинкою: «Religious Records — taujna, Balta, Podolia», місце
# «rudnytske, Olgopol, Podolia, Russian Empire». FS пише то з української
# транслітерації, то з російської (`taujna` — Таужне, `romanovka` — Романівка),
# і `_lat` такі форми не зводить. Метрики костелів — польською:
# «Метрична книга костелу (Pohrebyszcze)». Звідси — порівняння «скелетів»
# назв у межах повіту (чи областей архіву, коли повіту немає) і лише
# однозначне. Перевірено 28.10.2026 на обході ДАХмО: 5 563 точки з 9 083
# записів FS, що доти не лягали жодним.

#: Поріг схожості скелетів і відрив від наступної назви.
LAT_MIN = 0.90
LAT_VIDRYV = 0.06
#: Штраф збігу з псевдонімом Wikidata («Мала Багачівка» має псевдонім «Багачівка»)
#: і з «серцевиною» назви (без кінцевих голосних, о=і: `Puzhaykiv` — Пужайкове).
LAT_SHTRAF_PSEVDO = 0.08
LAT_SHTRAF_SERTSE = 0.04

_SK_KYR = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "є": "e",
    "ё": "o", "ж": "z", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "c", "ч": "c", "ш": "s", "щ": "s", "ь": "",
    "ъ": "", "ы": "i", "э": "e", "ю": "u", "я": "a", "ѣ": "e", "ѳ": "f",
})
_SK_LAT = [("shch", "s"), ("sch", "s"), ("zh", "z"), ("kh", "x"), ("ch", "c"), ("sh", "s"),
           ("ts", "c"), ("tz", "c"), ("ya", "a"), ("ia", "a"), ("yu", "u"), ("iu", "u"),
           ("ye", "e"), ("ie", "e"), ("yo", "o"), ("io", "o"), ("yi", "i"), ("ii", "i"),
           ("j", "z"), ("y", "i"), ("h", "g"), ("w", "v"), ("ă", "a"), ("â", "i"),
           ("î", "i"), ("ş", "s"), ("ș", "s"), ("ţ", "c"), ("ț", "c")]
#: Польська графіка: «ch» тут — х, а не ч, як у транслітерації FS.
_SK_POL = [("szcz", "s"), ("rz", "z"), ("sz", "s"), ("cz", "c"), ("ch", "x"), ("ł", "l"),
           ("ń", "n"), ("ś", "s"), ("ć", "c"), ("ź", "z"), ("ż", "z"), ("ó", "o"),
           ("ę", "e"), ("ą", "a"), ("w", "v")]
_KYRYLYTSIA = re.compile(r"[а-яіїєґёѣѳ]")

#: Місце FS: «село, Повіт, Губернія[, Russian Empire]» латинкою.
FS_MISTSE = re.compile(r"^\s*([^,А-Яа-яІіЇїЄєҐґ]+?),\s*([^,А-Яа-яІіЇїЄєҐґ]+?),\s*[A-Za-z][^,]*"
                       r"(?:,\s*Russian Empire)?\s*$")
#: Назва з обходу FS: «Religious Records — taujna, Balta, Podolia».
TYTUL_FS_TYRE = re.compile(r"—\s*([^,—А-Яа-яІіЇїЄєҐґ]+?),\s*([^,—А-Яа-яІіЇїЄєҐґ]+?),\s*[A-Za-z]")
#: Польська чи латинська назва в дужках: «костелу (Pohrebyszcze)».
LAT_DUZHKY = re.compile(r"\(([A-ZŁŚŻŹĆ][A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ'’-]{2,}"
                        r"(?:[ -][A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ'’-]+)?)\)")


@functools.lru_cache(maxsize=1 << 16)
def skeleton(nazva: str) -> str:
    """Назва латинкою чи кирилицею → одна форма для порівняння."""
    s = re.sub(r"['’ʼ`\-\s.]", "", nazva.lower().strip())
    if _KYRYLYTSIA.search(s):
        s = s.translate(_SK_KYR)
    else:
        if re.search(r"[łńśćźżóęą]|sz|cz|rz|w", s):
            for a, b in _SK_POL:
                s = s.replace(a, b)
        for a, b in _SK_LAT:
            s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def _sertse(s: str) -> str:
    return re.sub(r"[aeiou]+$", "", s).replace("o", "i")


def _skeleti(d: dict[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """(назва, псевдоніми) поселення скелетами; рахується раз на поселення."""
    got = d.get("_sk")
    if got is None:
        holovni = frozenset(skeleton(d.get(k) or "")
                            for k in ("name_uk", "norm_uk", "norm_ru")) - {""}
        psevdo = frozenset(skeleton(k) for k in d["kl"] if k) - holovni - {""}
        got = d["_sk"] = (holovni, psevdo)
    return got


def _lat_otsinka(shukane: str, d: dict[str, Any]) -> tuple[float, bool]:
    """Схожість і чи це збіг із самою назвою (а не псевдонімом чи серцевиною).

    ⚡ Повна схожість — лише там, де дешева верхня межа (`real_quick_ratio`,
    `quick_ratio`) дотягує до порогу: нижче за `LAT_MIN - LAT_VIDRYV` оцінка
    на вибір не впливає, а пул повіту — тисяча-дві поселень (0,44 с на пару
    без відсікання, замір 28.10.2026).
    """
    holovni, psevdo = _skeleti(d)
    naikr, nazva = 0.0, False
    for k in holovni:
        r = _shozhist(shukane, k)
        if r > naikr:
            naikr, nazva = r, True
    for k in psevdo:
        r = _shozhist(shukane, k) - LAT_SHTRAF_PSEVDO
        if r > naikr:
            naikr, nazva = r, False
    sertse = _sertse(shukane)
    for k in holovni:
        r = _shozhist(sertse, _sertse(k)) - LAT_SHTRAF_SERTSE
        if r > naikr:
            naikr, nazva = r, False
    return naikr, nazva


def _shozhist(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    porih = LAT_MIN - LAT_VIDRYV
    sm = SequenceMatcher(None, a, b)
    if sm.real_quick_ratio() < porih or sm.quick_ratio() < porih:
        return 0.0
    return sm.ratio()


def _bez_utochnennia(nazva: str) -> str:
    """«Будей (Оргіївський район)» → «Будей»: уточнення Wikidata — не назва."""
    return re.sub(r"\s*\(.*?\)\s*$", "", nazva or "").strip()


def _lat_vybraty(selo: str, pul: list[dict[str, Any]],
                 chomu: list[tuple[str, list[str]]] | None = None,
                 ) -> tuple[dict[str, Any], str] | None:
    """Одне поселення пулу під назву латинкою — або None, коли непевно чи двозначно.

    `chomu` отримує (причина, кандидати), коли поселення не вибрано.
    """
    def ni(prychyna: str, kand: list[str] | None = None) -> None:
        if chomu is not None:
            chomu.append((prychyna, kand or []))

    shukane = skeleton(selo)
    if len(shukane) < 3 or not pul:
        ni("poza_povitom" if not pul else "nema")
        return None
    ots = sorted(((*_lat_otsinka(shukane, d), d) for d in pul), key=lambda x: -x[0])
    r1 = ots[0][0]
    if r1 < LAT_MIN:
        ni("nema")
        return None
    blyzki = [x for x in ots if x[0] >= r1 - LAT_VIDRYV]
    # Точний збіг назви одного села перемагає серцевини й псевдоніми інших.
    tochni = [x for x in blyzki if x[0] >= 0.999 and x[1]]
    if tochni and len({_bez_utochnennia(d["name_uk"]) for _, _, d in tochni}) == 1:
        blyzki = tochni
    if len({_bez_utochnennia(d["name_uk"]) for _, _, d in blyzki}) > 1:
        ni("dvoznachno", sorted({_z_raionom(d) for _, _, d in blyzki})[:6])
        return None
    sela = [d for _, _, d in blyzki]
    # Однойменні села в пулі за межами дубля — двозначно, а не «перше-ліпше».
    if len(sela) > 1 and not _odne(sela):
        ni("dvoznachno", sorted({_z_raionom(d) for d in sela})[:6])
        return None
    sposib = "latynka" if r1 >= 0.999 and blyzki[0][1] else "latynka_slabko"
    return sela[0], sposib


def _tsentry_lat(dov: Dovidnyk, povit: str, obl: list[str]) -> list[dict[str, Any]]:
    """Повітове місто за назвою повіту латинкою («Balta», «Olgopol»).

    Не лише серед міст: Ольгопіль нині село. Однойменні — звужує область архіву.
    """
    shukane = skeleton(povit)
    if len(shukane) < 3:
        return []
    v = [d for d in dov.vsi if shukane in _skeleti(d)[0]]
    if obl:
        v = [d for d in v if any(o in d["obl"] for o in obl)] or ([] if v else v)
    mista = [d for d in v if d["kind"] in MISTA]
    return mista or v


def z_latynky(dov: Dovidnyk, kt: _Kontekst, title: str, place: str,
              places: list[str], chomu: list[dict[str, Any]] | None = None,
              ) -> list[tuple[dict[str, Any], str, str]]:
    """Села латинкою з назви й місць книги → (поселення, спосіб, як стоїть у книзі)."""
    out: list[tuple[dict[str, Any], str, str]] = []
    pary: list[tuple[str, str, str]] = []
    for s in (place, *places):
        m = FS_MISTSE.match(s or "")
        if m:
            pary.append((m.group(1).strip(), m.group(2).strip(), s))
    for m in TYTUL_FS_TYRE.finditer(title or ""):
        pary.append((m.group(1).strip(), m.group(2).strip(), m.group(0)))
    fs = TYTUL_FS.search(title or "")
    if fs:
        pary.append((fs.group(1).strip(), fs.group(2).strip(), fs.group(0)))
    obl = tuple(kt.obl)
    for selo, povit, dzherelo in dict.fromkeys(pary):
        kp = (skeleton(povit), obl)
        if kp not in dov.lat_pul:
            tsentry = _tsentry_lat(dov, povit, kt.obl)
            dov.lat_pul[kp] = ([d for d in dov.vsi if min(_km(d, t) for t in tsentry) <= POVIT_KM]
                               if tsentry else [])
        got = _lat_z_pamiati(dov, selo, kp, chomu, dzherelo)
        if got:
            out.append((got[0], got[1], dzherelo))
    if obl:
        kp = ("", obl)
        if kp not in dov.lat_pul:
            dov.lat_pul[kp] = [d for d in dov.vsi if any(o in d["obl"] for o in obl)]
        for m in LAT_DUZHKY.finditer(title or ""):
            got = _lat_z_pamiati(dov, m.group(1), kp, chomu, m.group(0))
            if got:
                out.append((got[0], got[1], m.group(0)))
    return out


def _lat_z_pamiati(dov: Dovidnyk, selo: str, kp: tuple[str, tuple[str, ...]],
                   chomu: list[dict[str, Any]] | None = None,
                   dzherelo: str = "") -> tuple[dict[str, Any], str] | None:
    kv = (skeleton(selo), *kp)
    if kv not in dov.lat_vybir:
        prychyny: list[tuple[str, list[str]]] = []
        dov.lat_vybir[kv] = (_lat_vybraty(selo, dov.lat_pul[kp], prychyny), prychyny)
    got: tuple[dict[str, Any], str] | None
    got, prychyny = dov.lat_vybir[kv]
    if got is None and chomu is not None:
        for prychyna, kand in prychyny or [("nema", [])]:
            chomu.append({"dzherelo": dzherelo[:160], "chomu": prychyna, "kandydaty": kand})
    return got


def pryviazaty(dov: Dovidnyk, *, repo: str, title: str, place: str,
               places: list[str], seriia: list[dict[str, Any]] | None = None,
               chomu: list[dict[str, Any]] | None = None,
               selo_lyudyny: str = "") -> list[Tochka]:
    """Точки однієї книги. Не знайдене чи двозначне — просто без точки.

    `seriia` — точки (lat, lng) інших книг того самого опису.

    `selo_lyudyny` — `qid` поселення, яке назвала людина (`nysh share card
    --selo`): воно й є покриттям справи (`tytul`, спосіб `lyudyna`), а розбір
    назви лишає лише згадки з тексту. Невідомий довіднику `qid` — звичайний розбір.

    `chomu` — куди дописати, чому точки з назви чи місця немає (для людини перед
    заливкою): `{"dzherelo", "chomu", "kandydaty"}`, де `chomu` — `nema` (такого
    поселення в довіднику немає), `dvoznachno` (кілька однойменних; `kandydaty` —
    які), `poza_povitom` / `poza_oblastiu`, або `bez_sela` — у назві й місці села
    не названо зовсім (лише губернія чи повіт).
    """
    lyudyna = poselennia(dov, selo_lyudyny) if selo_lyudyny else None
    if lyudyna is not None:
        zvychaini = pryviazaty(dov, repo=repo, title=title, place=place, places=places,
                               seriia=seriia)
        return [_tochka(lyudyna, "tytul", "lyudyna", "людина"),
                *[t for t in zvychaini if t.rol == "tekst" and t.qid != lyudyna["qid"]]]
    kt = _kontekst(dov, repo, title, place, places)
    kt.seriia = list(seriia or [])
    tyt = z_nazvy(title)
    # Друга назва місця з дужок («Фузовка (Fuzăuca)») — запасний варіант того
    # самого села: розводить однойменних, яких перша назва не розводить.
    var_mistsia = _varianty(place) if place else []
    if var_mistsia:
        tyt.append(var_mistsia[0])
    zapysy: list[dict[str, Any]] = [
        {"s": s, "rol": "tytul", "var": var_mistsia if var_mistsia and s == var_mistsia[0] else [s]}
        for s in dict.fromkeys(tyt)]
    zapysy += [{"s": s, "rol": "tytul", "var": [], "prykm": formy}
               for s, formy in z_prykmetnyka(title) if s not in tyt]
    for s in places:
        var = _varianty(s)
        if var and s != place:
            # «Вінниця, Подільська губ.» без головного місця — перелік парафій, який
            # видавець склав сам (збірні книги деканату), а не слово з тексту рушія.
            # Як згадка такі книги не видно на мапі без галочки (21.10.2026: ~70
            # книг Вінницького деканату, у Вінниці показувало три).
            rol = "tytul" if not place and "," in s and ADMIN_RE.search(s) else "tekst"
            zapysy.append({"s": s, "rol": rol, "var": var})
    # Три проходи: другий бачить точки першого (сусіди), слабкі способи —
    # лише в останньому, щоб не перебити сильніший доказ.
    for prokhid in (0, 1, 2):
        for z in zapysy:
            if z.get("d"):
                continue
            d: dict[str, Any] | None = None
            rez = "nema"
            if z.get("prykm"):
                d = _z_prykmetnyka(dov, z["prykm"], kt)
                if d:
                    z["d"], z["rez"] = d, "prykmetnyk"
                    kt.tochky.append(d)
                continue
            # Газетир ЦДІАК знає село разом із повітом і сучасний район — це
            # сильніше за будь-яке правило вибору серед однойменних паку
            # (аудит 19.10: «Бобрик Лебединського повіту» — Лебединий Бобрик).
            if kt.povit:
                for v in z["var"]:
                    dh = _z_hazetyra(dov, v, kt)
                    if dh:
                        d, rez = dh, "hazetyr"
                        break
            for v in z["var"] if d is None else []:
                c = _kandydaty(dov, v)
                if c:
                    d, rez = _vybraty(c, kt)
                    if d is None and rez == "dvoznachno":
                        z["kand"] = sorted({_z_raionom(x) for x in c.values()})[:6]
                    if d is not None or rez != "dvoznachno":
                        break
                    # Двозначно — наступний варіант назви може розвести:
                    # спільний кандидат обох назв або єдиний у другої.
                    for v2 in z["var"][z["var"].index(v) + 1:]:
                        c2 = _kandydaty(dov, v2)
                        spilni = {q: c[q] for q in c if q in c2}
                        d2, _rez2 = _vybraty(spilni or c2, kt) if (spilni or c2) else (None, "")
                        if d2 is not None:
                            d, rez = d2, "varianty"
                            break
                    break
            if d is None and rez in ("nema", "dvoznachno"):
                for v in z["var"]:
                    dh = _z_hazetyra(dov, v, kt)
                    if dh:
                        d, rez = dh, "hazetyr"
                        break
            if d is None and rez == "nema" and prokhid == 2:
                for v in z["var"]:
                    dk = _z_kvalifikatorom(dov, v, kt)
                    if dk:
                        d, rez = dk, "kvalifikator"
                        break
                    dn = _nechitko(dov, v, kt)
                    if dn:
                        d, rez = dn, "nechitko"
                        break
            if d:
                z["d"], z["rez"] = d, rez
                kt.tochky.append(d)
            else:
                z["chomu"] = rez
    out: dict[tuple[str, str], Tochka] = {}
    for z in zapysy:
        d = z.get("d")
        if d and (d["qid"], z["rol"]) not in out:
            out[(d["qid"], z["rol"])] = Tochka(
                qid=d["qid"], nazva=(d["name_uk"] or "")[:160],
                oblast=oblast_tochky(float(d["lat"]), float(d["lng"]), d["top"] or "")[:80],
                lat=float(d["lat"]), lng=float(d["lng"]), rol=z["rol"], sposib=z["rez"],
                dzherelo=z["s"][:160])
    # Латинка — лише коли кирилицею села з назви й місця не знайшлось: FS-місце
    # чи польська назва в дужках тоді єдине, що каже, де книга.
    chomu_lat: list[dict[str, Any]] = []
    if not any(r == "tytul" for _, r in out):
        for d, sposib, dzherelo in z_latynky(dov, kt, title, place, places, chomu_lat):
            if (d["qid"], "tytul") not in out:
                out[(d["qid"], "tytul")] = Tochka(
                    qid=d["qid"], nazva=(d["name_uk"] or "")[:160],
                    oblast=oblast_tochky(float(d["lat"]), float(d["lng"]), d["top"] or "")[:80],
                    lat=float(d["lat"]), lng=float(d["lng"]), rol="tytul", sposib=sposib,
                    dzherelo=dzherelo[:160])
    # село з назви не дублюється згадкою з тексту
    tyt_qid = {q for q, r in out if r == "tytul"}
    if chomu is not None and not tyt_qid:
        bez = [z for z in zapysy if z["rol"] == "tytul" and not z.get("d")]
        for z in bez:
            chomu.append({"dzherelo": str(z["s"])[:160], "chomu": z.get("chomu") or "nema",
                          "kandydaty": list(z.get("kand") or [])})
        chomu.extend(chomu_lat)
        if not bez and not chomu_lat:
            chomu.append({"dzherelo": "", "chomu": "bez_sela", "kandydaty": []})
    return [t for (q, r), t in out.items() if r == "tytul" or q not in tyt_qid]


def _z_raionom(d: dict[str, Any]) -> str:
    """«Капітанка (Голованівський район)» — щоб людина могла назвати, яке з однойменних."""
    adm = str(d.get("admin") or "").split(" | ")[0].strip()
    return f"{d.get('name_uk') or '?'} ({adm})" if adm else str(d.get("name_uk") or "?")


def dlia_spravy(repo: str, title: str, place: str, places: list[str],
                selo_lyudyny: str = "") -> dict[str, Any]:
    """Куди ляже книга на карті Супряги — для людини до заливки.

    `{"tochky": [...], "chomu": [...]}` або `{"bez_kataloga": True}`, коли паку
    поселень немає. Точки — лише роль `tytul` (покриття справи): згадки з тексту
    картка не показує.
    """
    dov = dovidnyk()
    if dov is None:
        return {"bez_kataloga": True}
    chomu: list[dict[str, Any]] = []
    tochky = [t for t in pryviazaty(dov, repo=repo, title=title, place=place,
                                    places=list(places), chomu=chomu,
                                    selo_lyudyny=selo_lyudyny) if t.rol == "tytul"]
    return {"tochky": [{"qid": t.qid, "nazva": t.nazva, "oblast": t.oblast,
                        "sposib": t.sposib, "pevnist": t.pevnist,
                        "dzherelo": t.dzherelo} for t in tochky],
            "chomu": [] if tochky else chomu}


def poiasnennia(info: dict[str, Any]) -> str:
    """Рядок для людини: де книга на карті, або чому її там не буде й що зробити."""
    if info.get("bez_kataloga"):
        return ("карту не перевірено: паку поселень немає в каталозі — "
                "`nysh catalog update`")
    tochky = info.get("tochky") or []
    if tochky:
        return "на карті: " + "; ".join(
            f"{t['nazva']} ({t['oblast']}"
            + (", непевно" if t.get("pevnist") == "nyzka" else "")
            + (", назвали ви" if t.get("sposib") == "lyudyna" else "") + ")" for t in tochky)
    prychyny = []
    for c in info.get("chomu") or []:
        dzh = f"«{c['dzherelo']}» " if c.get("dzherelo") else ""
        kod = c.get("chomu")
        if kod == "bez_sela":
            prychyny.append("у назві й місці села не названо — лише губернія чи повіт")
        elif kod == "dvoznachno":
            kand = "; ".join(c.get("kandydaty") or [])
            prychyny.append(f"{dzh}— кілька однойменних ({kand}); назвіть район у місці")
        elif kod in ("poza_povitom", "poza_oblastiu"):
            prychyny.append(f"{dzh}— таке село є лише за межами повіту чи області архіву")
        else:
            prychyny.append(f"{dzh}— такого поселення в довіднику немає (написання?)")
    return ("на карту не ляже: " + "; ".join(dict.fromkeys(prychyny))
            + ". Назвіть село: `nysh share card <справа> --selo \"Назва, район\"`")


def _tochka(d: dict[str, Any], rol: str, sposib: str, dzherelo: str) -> Tochka:
    return Tochka(qid=d["qid"], nazva=(d["name_uk"] or "")[:160],
                  oblast=oblast_tochky(float(d["lat"]), float(d["lng"]), d["top"] or "")[:80],
                  lat=float(d["lat"]), lng=float(d["lng"]), rol=rol, sposib=sposib,
                  dzherelo=dzherelo[:160])


def poselennia(dov: Dovidnyk, qid: str) -> dict[str, Any] | None:
    """Поселення довідника за `qid` (Wikidata чи `r:` ручного довідника)."""
    za_qid = getattr(dov, "_za_qid", None)
    if za_qid is None:
        za_qid = {d["qid"]: d for d in dov.vsi}
        dov._za_qid = za_qid  # type: ignore[attr-defined]
    got: dict[str, Any] | None = za_qid.get(str(qid or "").strip())
    return got


class KartaError(ValueError):
    """Село не знайдено або назване неоднозначно — з переліком, що є."""


#: «Голованівський р-н», «Кіровоградська обл.», «громада» — підказка, де шукати.
_PIDKAZKA_SLUZHBOVI = re.compile(r"\b(р-н|район|районі|обл\.?|область|області|громада|"
                                 r"сільська|селищна|міська|рада)\b", re.IGNORECASE)


def znaity_selo(tekst: str, *, repo: str = "") -> dict[str, Any]:
    """«Капітанка, Голованівський р-н» → одне поселення довідника.

    Перше — назва (кирилицею, у називному відмінку); далі — підказка: район,
    громада, область (досить кореня: «Голованівськ»). Без підказки — серед
    областей архіву справи. Двозначно чи нічого — `KartaError` з переліком
    кандидатів і їхніх районів, щоб людина могла уточнити.
    """
    dov = dovidnyk()
    if dov is None:
        raise KartaError("паку поселень немає в каталозі — `nysh catalog update`")
    chastyny = [c.strip() for c in str(tekst or "").split(",") if c.strip()]
    if not chastyny:
        raise KartaError("не названо села")
    nazva = chastyny[0]
    kand = list(_kandydaty(dov, nazva).values())
    if not kand:
        raise KartaError(f"«{nazva}» немає в довіднику поселень — перевірте написання "
                         "(сучасна назва, називний відмінок)")
    pidkazky = [_norm(_PIDKAZKA_SLUZHBOVI.sub(" ", c)).translate(STARE)[:6]
                for c in chastyny[1:]]
    pidkazky = [p for p in pidkazky if len(p) >= 3]
    if pidkazky:
        kand = [d for d in kand
                if all(p in (d["adm"] + " " + d["obl"]).translate(STARE) for p in pidkazky)]
    else:
        obl = oblasti_arkhivu(repo) if repo else ()
        v = [d for d in kand if any(o in d["obl"] for o in obl)]
        kand = v or kand
    if len(kand) > 1 and _odne(kand):
        kand = kand[:1]
    if len(kand) != 1:
        if not kand:
            raise KartaError(f"«{nazva}» з такою підказкою не знайдено")
        perelik = "; ".join(sorted({_z_raionom(d) for d in kand})[:8])
        raise KartaError(f"«{nazva}» — кілька однойменних: {perelik}. Додайте район: "
                         f"«{nazva}, <район> р-н»")
    d = kand[0]
    return {"qid": d["qid"], "nazva": d["name_uk"],
            "oblast": oblast_tochky(float(d["lat"]), float(d["lng"]), d["top"] or "")}
