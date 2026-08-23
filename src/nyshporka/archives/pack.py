"""🏛 Пак архівів — знання про фонди як дані.

Правила, які залежать від конкретного архіву чи фонду, довго жили словниками в
коді: скорочення архіву, опис за замовчуванням для сканованих тек, фонди де
опис ОБОВ'ЯЗКОВО входить у ключ справи, губернія за визначенням фонду, теки що
справами не є. Наслідок — новий архів можна було додати лише правкою коду, і
чужий дослідник із власним фондом упирався в це першим.

Тепер джерело одне — `data/archives.yaml`, а код лише читає.

🔴 Що НЕ переїхало в дані й чому. Розбір конкретних каталогів (TSV краулу
ARCHIUM, курованих `CATALOG.md`, покажчика опису ф.315) лишається кодом: це
формат, а не знання. У пак іде декларація «такий каталог існує й лежить отут»,
а як його читати — вирішує парсер. Спроба описати ще й формат перетворила б
YAML на мову програмування.

Пак розширюваний: користувач може підкласти свій файл поверх вбудованого
(`NYSHPORKA_ARCHIVES_PACK` або `<простір>/config/archives.yaml`), і його записи
переб'ють вбудовані по ключу. Саме так додається архів, якого ми не знаємо.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: Вбудований пак — їде разом із кодом.
BUILTIN = Path(__file__).resolve().parent / "data" / "archives.yaml"
#: Ескейп-хетч: шлях до власного паку.
ENV_PACK = "NYSHPORKA_ARCHIVES_PACK"
#: Ім'я файлу, який шукається в конфігу робочого простору.
WORKSPACE_PACK = "archives.yaml"


@dataclass(frozen=True)
class Site:
    """Майданчик архіву: де саме лежить його переглядач.

    🔴 Адреса — знання про АРХІВ, а не формат, тому їй місце в паку. Рушій
    переглядача (`archium`) спільний для кількох архівів, а хости різні; доки
    хост був константою модуля, джерело вміло рівно один архів, і другий
    додавався тільки правкою коду.
    """

    engine: str                     # який парсер це читає: "archium"
    url: str
    source_id: str = ""             # id джерела; порожньо — рахується з коду архіву
    fond_groups: bool = True        # чи є в цього майданчика дерево груп фондів
    groups: tuple[tuple[str, str], ...] = ()   # (id, назва) — лише якщо є
    bundled: str = ""               # ім'я вкладеного зрізу каталогу, якщо він є


@dataclass(frozen=True)
class Repository:
    code: str
    label: str
    name: str = ""
    country: str = ""
    note: str = ""
    #: Майданчики за рушієм переглядача.
    sites: dict[str, Site] = field(default_factory=dict)
    #: Як цей архів зветься в ЧУЖИХ системах. Списком, бо буває кілька написань:
    #: файли ДАВіО лежать на Commons і під «ДАВіО», і під «ДАВО», і пошук лише за
    #: одним написанням мовчки втрачає половину.
    codes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Код ТОГО САМОГО архіву, під яким він теж трапляється в обліку.
    #: 🔴 Знання про це вже було — примітою для людини, — і саме тому «на диску»
    #: рахувалось лише за номером фонду: розділити архіви машина не вміла.
    #: Наслідок мовчазний в обидва боки: одеська справа ф.904 позначала наявною
    #: вінницьку, а десять вінницьких під другим кодом випали б із обліку, якби
    #: код звіряли строго.
    same_as: str = ""


@dataclass(frozen=True)
class OpysBound:
    """Останній номер справи в описі — ЗНАМЕННИК покриття фонду.

    🔴 Саме число тут неповне без `basis`. «1515, звірено з офіційним переліком
    архіву» і «231, максимум того, що встигли транскрибувати» — різні за силою
    твердження: друге є НИЖНЬОЮ оцінкою, тож покриття по ньому завищене й
    зростатиме лише вниз. Доки підстава жила в коментарі коду, обидві межі
    подавались однаково впевнено, і читач не мав як їх розрізнити.
    """

    opys: str
    last: int
    basis: str = ""      # official | guide | header | transcript | manual | ""
    note: str = ""

    @property
    def is_lower_estimate(self) -> bool:
        """Межа з транскрипції — покриття по ній ЗАВИЩЕНЕ."""
        return self.basis in ("", "transcript")


@dataclass(frozen=True)
class Fond:
    repo: str
    fond: str
    name: str = ""
    guberniya: str = ""
    default_opys: str | None = None
    opys_in_key: bool = False
    note: str = ""
    #: Межі описів — знання про КОНКРЕТНИЙ фонд конкретного архіву, тому тут, а
    #: не в коді: номери фондів між архівами колізують, і ключ `(repo, fond)`
    #: знімає це за побудовою.
    opys_last: dict[str, OpysBound] = field(default_factory=dict)
    #: Од.зб. за офіційним путівником архіву — для звірки з розрахунком.
    guide_total: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.repo, self.fond)


@dataclass(frozen=True)
class ArchivesPack:
    repositories: dict[str, Repository] = field(default_factory=dict)
    fonds: dict[tuple[str, str], Fond] = field(default_factory=dict)
    skip_slugs: frozenset[str] = frozenset()
    record_type_labels: dict[str, str] = field(default_factory=dict)
    sources: tuple[Path, ...] = ()

    def sites(self, engine: str) -> tuple[tuple[str, Site], ...]:
        """Усі майданчики цього рушія: `(код архіву, майданчик)`."""
        return tuple((code, r.sites[engine]) for code, r in
                     sorted(self.repositories.items()) if engine in r.sites)

    def site(self, repo: str | None, engine: str) -> Site | None:
        r = self.repositories.get(str(repo or "").upper())
        return r.sites.get(engine) if r else None

    def opys_bounds(self, repo: str | None, fond: str | None) -> dict[str, OpysBound]:
        """Межі описів фонду. Порожньо — знаменника НЕМАЄ.

        🔴 І це не те саме, що «нуль». Покриття без знаменника не рахується
        взагалі: частка була б вигадана, а «0/0 · немає 0» читається як «усе на
        місці». Порожній словник тут мусить звучати як прогалина.
        """
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return dict(f.opys_last) if f else {}

    def guide_total(self, repo: str | None, fond: str | None) -> int | None:
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return f.guide_total if f else None

    def canon_repo(self, repo: str | None) -> str:
        """Код архіву, зведений до канонічного: `DAVIO` → `DAVO`.

        Невідомий код повертається як є — здогадуватись тут нема з чого, а
        порожній рядок зробив би з невідомого архіву «будь-який».
        """
        code = str(repo or "").upper()
        r = self.repositories.get(code)
        return r.same_as if r and r.same_as else code

    def same_archive(self, a: str | None, b: str | None) -> bool:
        """Чи це той самий архів, хай і під різними кодами."""
        return self.canon_repo(a) == self.canon_repo(b)

    def codes_for(self, repo: str | None, system: str) -> tuple[str, ...]:
        """Як архів зветься в чужій системі (`duck`, `commons`).

        Порожньо означає «не знаємо» — і це чесніше за здогад: код, вигаданий
        за нашим власним, дав би запит про архів, якого в тій системі немає, а
        нуль у відповідь читався б як «там нічого немає».
        """
        r = self.repositories.get(str(repo or "").upper())
        return r.codes.get(system, ()) if r else ()

    # ── те, чим користується решта коду ──────────────────────────────────────
    def repo_label(self, repo: str | None) -> str:
        """Скорочення архіву; невідомий код повертається як є.

        Повертати код замість порожнього рядка тут принципово: у шифрі справи
        краще побачити «XYZ 315-1-8433», ніж « 315-1-8433» і гадати, чий він.
        """
        code = str(repo or "")
        r = self.repositories.get(code.upper())
        return r.label if r else code

    def default_opys(self, repo: str | None, fond: str | None) -> str | None:
        """Опис, який мають скановані теки фонду, коли їхнє ім'я його не несе."""
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return f.default_opys if f else None

    def opys_in_key(self, repo: str | None, fond: str | None) -> bool:
        """Чи опис ОБОВ'ЯЗКОВО входить у ключ справи цього фонду."""
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return bool(f and f.opys_in_key)

    def guberniya(self, repo: str | None, fond: str | None) -> str:
        """Губернія, задана самим фондом. Порожньо, якщо фонд не з відомих.

        Запасний варіант: розбір тексту опису сильніший і йде першим. Потрібно
        там, де поле місця порожнє за побудовою — напр. сповідки консисторії
        описані переліком сіл, і зріз «по губернії» без цього недораховує.
        """
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return f.guberniya if f else ""

    def rtype_label(self, rtype: str | None) -> str:
        return self.record_type_labels.get(str(rtype or ""), str(rtype or ""))

    def is_skipped_slug(self, slug: str) -> bool:
        return slug in self.skip_slugs


# ── читання ──────────────────────────────────────────────────────────────────
def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Верхній пак перебиває нижній ПО КЛЮЧУ, а не заміщає секцію цілком.

    Інакше користувач, який додав один свій архів, мовчки втратив би всі
    вбудовані — і це виглядало б як «програма забула половину фондів».
    """
    out = dict(base)
    # 🔴 Репозиторії зливаються ВГЛИБ, а не цілим записом. Інакше людина, що
    # дописала архіву одну назву в чужій системі, мовчки втратила б його
    # майданчики — тобто той самий клас вади, від якого захищає злиття по
    # ключу, лише поверхом нижче.
    merged_repos = dict(base.get("repositories") or {})
    for code, body in (over.get("repositories") or {}).items():
        old_body = merged_repos.get(code) or {}
        add = body or {}
        new_body = dict(old_body, **add)
        for nested in ("sites", "codes"):
            was, now = old_body.get(nested) or {}, add.get(nested) or {}
            if was or now:
                new_body[nested] = {**was, **now}
        merged_repos[code] = new_body
    out["repositories"] = merged_repos
    out["record_type_labels"] = {**(base.get("record_type_labels") or {}),
                                 **(over.get("record_type_labels") or {})}
    # 🔴 Записи фонду зливаються ВГЛИБ, як і репозиторії. Доки в них була сама
    # губернія, ціна заміщення була низька; щойно туди їдуть ЗНАМЕННИКИ
    # покриття, вона стає такою: дослідник, що дописав своєму фонду межу одного
    # опису, мовчки втрачає `default_opys` — і кожна сканована тека дістає чужий
    # опис у ключі справи.
    by_key = {(str(f.get("repo", "")).upper(), str(f.get("fond", ""))): f
              for f in (base.get("fonds") or [])}
    for f in over.get("fonds") or []:
        k = (str(f.get("repo", "")).upper(), str(f.get("fond", "")))
        was = by_key.get(k) or {}
        merged = dict(was, **f)
        # Межі описів — по номеру опису: додати одну межу можна, не
        # переписуючи решту.
        old_b, new_b = was.get("opys_last") or {}, f.get("opys_last") or {}
        if old_b or new_b:
            merged["opys_last"] = {**old_b, **new_b}
        by_key[k] = merged
    out["fonds"] = list(by_key.values())
    out["skip_slugs"] = sorted({*(base.get("skip_slugs") or []),
                                *(over.get("skip_slugs") or [])})
    return out


def _read(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _overlay_paths() -> list[Path]:
    """Де шукати пак користувача, від найявнішого."""
    out: list[Path] = []
    env = os.environ.get(ENV_PACK)
    if env:
        out.append(Path(env))
    try:
        from nyshporka.core.workspace import workspace
        out.append(workspace().config / WORKSPACE_PACK)
    except Exception:  # простір ще не визначено — це не привід падати
        pass
    return [p for p in out if p.is_file()]


def _build(raw: dict[str, Any], sources: tuple[Path, ...]) -> ArchivesPack:
    repos = {}
    for code, body in (raw.get("repositories") or {}).items():
        b = body or {}
        sites = {}
        for engine, sb in (b.get("sites") or {}).items():
            sb = sb or {}
            sites[str(engine)] = Site(
                engine=str(engine), url=str(sb.get("url") or "").rstrip("/"),
                source_id=str(sb.get("source_id") or ""),
                fond_groups=bool(sb.get("fond_groups", True)),
                groups=tuple((str(g.get("id")), str(g.get("label") or ""))
                             for g in (sb.get("groups") or [])),
                bundled=str(sb.get("bundled") or ""))
        codes = {}
        for system, val in (b.get("codes") or {}).items():
            listed = val if isinstance(val, list) else [val]
            codes[str(system)] = tuple(str(v) for v in listed if v)
        repos[str(code).upper()] = Repository(
            code=str(code).upper(), label=str(b.get("label") or code),
            name=str(b.get("name") or ""), country=str(b.get("country") or ""),
            note=str(b.get("note") or ""), sites=sites, codes=codes,
            same_as=str(b.get("same_as") or "").upper())
    fonds = {}
    for body in raw.get("fonds") or []:
        b = body or {}
        bounds: dict[str, OpysBound] = {}
        # 🔴 Порядок ключів зберігається як у файлі: покриття пишеться в порядку
        # ітерації описів, тож перестановка міняє байти `coverage.json`.
        for opys, val in (b.get("opys_last") or {}).items():
            body = val if isinstance(val, dict) else {"last": val}
            raw_last = body.get("last")
            if not str(raw_last or "").strip().isdigit():
                continue
            last = int(str(raw_last).strip())
            bounds[str(opys)] = OpysBound(
                opys=str(opys), last=last, basis=str(body.get("basis") or ""),
                note=str(body.get("note") or ""))
        guide = b.get("guide_total")
        f = Fond(
            repo=str(b.get("repo") or "").upper(), fond=str(b.get("fond") or ""),
            name=str(b.get("name") or ""), guberniya=str(b.get("guberniya") or ""),
            default_opys=(str(b["default_opys"]) if b.get("default_opys") is not None
                          else None),
            opys_in_key=bool(b.get("opys_in_key")), note=str(b.get("note") or ""),
            opys_last=bounds,
            guide_total=int(str(guide)) if str(guide or "").isdigit() else None)
        fonds[f.key] = f
    return ArchivesPack(
        repositories=repos, fonds=fonds,
        skip_slugs=frozenset(str(s) for s in (raw.get("skip_slugs") or [])),
        record_type_labels={str(k): str(v) for k, v in
                            (raw.get("record_type_labels") or {}).items()},
        sources=sources,
    )


def load(extra: Path | None = None) -> ArchivesPack:
    """Вбудований пак + накладки користувача (без кешу — для тестів)."""
    raw = _read(BUILTIN)
    used = [BUILTIN]
    for p in [*_overlay_paths(), *( [extra] if extra else [] )]:
        raw = _merge(raw, _read(p))
        used.append(p)
    return _build(raw, tuple(used))


@lru_cache(maxsize=1)
def active() -> ArchivesPack:
    return load()


def reset() -> None:
    active.cache_clear()
