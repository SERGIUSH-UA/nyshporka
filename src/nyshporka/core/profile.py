"""🎯 Профіль дослідження — «чий рід шукаємо» як файл, а не як константи в коді.

Інструмент пошуку по архівах зазвичай прив'язаний до роду, під який його писали:
цільове прізвище розсіяне константами по кількох модулях — таргети пошуку, ваги
генератора синтетики, відмінкова парадигма для підписів розмітки. Копії пишуться
окремо й неминуче розходяться між собою, а щоб шукати своє прізвище, треба
знайти й переписати їх усі.

Тут джерело одне — `config/research_profile.yaml` у робочому просторі, а форми
**породжуються** (`core.morph`). Формат: `defaults` + `extends` + `fallback`,
тобто нове дослідження заводиться новим профілем, а не правкою коду.

Профіль описує рід цілком: основи на кожну орфографію, парадигму, корені для
фаззі-пошуку, рід-специфічний шум (сусідні прізвища з тим самим хвостом),
куровані роки народження ключових предків і рецепт генератора синтетики.

🔴 Обмеження, свідомо закладене в дизайн: коли профіль підмінює собою наявні
таблиці, згенероване мусить збігатися з ними **літерально**. Синтетика годує
трен, трен дає модель, модель дає знахідки — зсув у вагах не впаде ніде, а
виявиться через тиждень як «модель стала гірша», коли причину вже не відновити.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from nyshporka.core import morph
from nyshporka.core.workspace import workspace

CONFIG_NAME = "research_profile.yaml"


class ProfileError(RuntimeError):
    """Профіль не знайдено або він не читається."""


# ── розбір слота синтетики ───────────────────────────────────────────────────
#: Рецепт синтетики — це впорядкований перелік «слот → вага». Слот описує, ЯК
#: дістати написання, а не саме написання: `gen_m@ru_prereform`, `lower(...)`,
#: `hyphen(..., 4)`. Літерал у лапках лишається для того, що правилом не
#: виводиться (описки писаря).
def render_slot(slot: str, stems: dict[str, str], par: morph.Paradigm) -> str:
    """Слот рецепта → конкретне написання."""
    s = slot.strip()
    if s.startswith(("'", '"')) and s.endswith(s[0]) and len(s) >= 2:
        return s[1:-1]

    for fn in ("lower", "hyphen_head", "hyphen_tail", "hyphen"):
        if s.startswith(fn + "(") and s.endswith(")"):
            inner = s[len(fn) + 1:-1]
            if fn == "lower":
                return render_slot(inner, stems, par).lower()
            base, _, cut_raw = inner.rpartition(",")
            if not base:
                raise ProfileError(f"слот «{slot}»: {fn}(…) потребує позицію розриву")
            word = render_slot(base.strip(), stems, par)
            try:
                cut = int(cut_raw)
            except ValueError:
                raise ProfileError(f"слот «{slot}»: «{cut_raw.strip()}» не число") from None
            full, head, tail = morph.hyphenate(word, cut)
            return {"hyphen": full, "hyphen_head": head, "hyphen_tail": tail}[fn]

    code, _, orth = s.partition("@")
    # 🔴 Замовчування залежить від САМОГО профілю, а не від константи. Слот без
    # «@» досі означав `bank`, і просто перевести його на `uk` означало б тихо
    # змінити написання, якими вже шукають, — у профілі з десятком слотів це
    # помітили б аж по зміні числа хітів. Тому: є в профілі основа `bank` —
    # поводимось як раніше; немає (а в нового дослідника її й не буде) — беремо
    # українську.
    orth = orth or ("bank" if stems.get("bank") else "uk")
    stem = stems.get(orth)
    if stem is None:
        raise ProfileError(
            f"слот «{slot}»: немає основи для орфографії «{orth}» "
            f"(є: {', '.join(sorted(stems))})")
    form = par.form(stem, code.strip(), orth)
    if form is None:
        raise ProfileError(
            f"слот «{slot}»: парадигма «{par.id}» не має форми «{code}» в «{orth}»")
    return form


# ── профіль ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ResearchProfile:
    """Розв'язаний профіль дослідження."""

    name: str
    display: str = ""
    paradigm_id: str = "adj_skyi"
    stems: dict[str, str] = field(default_factory=dict)
    #: Нормалізований корінь для драбини таргетів пошуку («сікорськ»).
    htr_root: str = ""
    #: Корені для фаззі-пошуку по нормалізованому тексту, з вагами.
    roots: tuple[tuple[str, float], ...] = ()
    #: Рецепт синтетики: впорядкований перелік (слот, вага).
    synth_recipe: tuple[tuple[str, float], ...] = ()
    #: Слоти написань, якими прізвище шукається в декоді (порядок значущий).
    search_slots: tuple[str, ...] = ()
    #: Написання, що не виводяться правилом (описки писаря, рідкі варіанти).
    extra_forms: tuple[str, ...] = ()
    #: Шум, специфічний для цього роду (сусідні прізвища на той самий хвіст).
    confusers: tuple[str, ...] = ()
    #: Підрядки, за якими прізвище впізнається в довільному тексті. Не форми:
    #: саме куски («ікорс», «sikor»), бо декод калічить і початок слова, і кінець.
    substrings: tuple[str, ...] = ()
    #: Правила зниження рангу: ім'я → regex. Не фільтр — саме ранг: слово, що
    #: може виявитись родом, зникати не має (пор. `confuser-kills-hit-use-rank`).
    rank_down: dict[str, str] = field(default_factory=dict)
    #: Курована таблиця років народження ключових предків: id → (рік, клас, підстава).
    #: Клас (запис / З віку / гіпотеза) вирішальний — розбіжність із гіпотезою
    #: нічого не спростовує, і саме тут найлегше хибно відкинути правильну знахідку.
    anchors: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    #: Приймачі самоперевірки пошуку — сторінки, знайдені оком і внесені в канон.
    selftest: dict[str, Any] = field(default_factory=dict)
    places: tuple[dict[str, Any], ...] = ()
    archives: tuple[dict[str, Any], ...] = ()

    # ── похідні таблиці ──────────────────────────────────────────────────────
    @property
    def paradigm(self) -> morph.Paradigm:
        return morph.paradigm(self.paradigm_id)

    def forms(self, orth: str = "bank") -> dict[str, str]:
        """Усі відмінкові форми в одній орфографії."""
        stem = self.stems.get(orth)
        if stem is None:
            raise ProfileError(f"немає основи для орфографії «{orth}»")
        return self.paradigm.forms(stem, orth)

    def form_examples(self) -> dict[str, str]:
        """Код форми → приклад-написання для підписів банку розмітки.

        ⚠ `bank` тут лише як історична таблиця: у профілі, заведеному формою,
        такої основи немає й не буде, а падати на прикладах — найгірший привід
        зупинити роботу.
        """
        return self.forms("bank" if self.stems.get("bank") else "uk")

    def htr_targets(self) -> tuple[tuple[str, float], ...]:
        """Драбина таргетів для `spotter.anchor.HTR_TARGETS`."""
        if not self.htr_root:
            raise ProfileError("у профілі немає `htr_root` — драбину таргетів нема з чого будувати")
        return morph.htr_targets(self.htr_root)

    def synth_variants(self) -> list[tuple[str, float]]:
        """Перелік написань із вагами для `spotter.synthesize.VARIANTS`.

        Порядок рецепта зберігається: він відтворює історичний порядок таблиці,
        а тест на дослівну тотожність звіряє саме список, не множину.
        """
        par = self.paradigm
        return [(render_slot(slot, self.stems, par), w) for slot, w in self.synth_recipe]

    def search_forms(self) -> list[str]:
        """Повні написання для пошуку в декоді (`htr_clan_scan.FULL_FORMS`).

        Свідомо вужче за `all_spellings()`: пороги фільтра калібровані саме на
        цьому наборі, і розширення до всіх відмінків × орфографій змінило б
        поведінку так, що перевірити нема на чому.
        """
        par = self.paradigm
        return [render_slot(s, self.stems, par) for s in self.search_slots]

    def uncovered_orthographies(self) -> list[str]:
        """Орфографії, де основа задана, а парадигма її не покриває.

        🔴 Це найтихіша втрата з усіх, які тут бувають. `Paradigm.forms()` на
        невідомій орфографії повертає порожньо БЕЗ помилки, а `all_spellings()`
        просто ітерує по заданих основах — тож профіль із польською основою і
        парадигмою, у якої польської таблиці немає, дає нуль польських написань
        і жодної ознаки, що щось загубилось. Людина бачить список написань,
        вважає його повним і закриває напрям, якого не шукали.

        Сусідній приймач (`stems_partial`) ловить зворотний випадок — основи
        немає. На цей — «основа є, а таблиці немає» — не було нічого.
        """
        par = self.paradigm
        return [orth for orth in self.stems
                if self.stems.get(orth) and not par.endings.get(orth)]

    def all_spellings(self) -> list[str]:
        """Усе, чим прізвище може виглядати в тексті — для пошукових ключів.

        Об'єднує повні форми в усіх орфографіях, додаткові написання й голови/
        хвости переносів із рецепта. Дублікати прибираються, порядок стабільний.
        """
        out: list[str] = []
        for orth in self.stems:
            out += list(self.forms(orth).values())
        out += list(self.extra_forms)
        out += [s for s, _ in self.synth_variants()]
        seen: set[str] = set()
        uniq: list[str] = []
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq


# ── читання конфігу ──────────────────────────────────────────────────────────
def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(
            out.get(k), dict) else v
    return out


def config_path() -> Path:
    return workspace().config / CONFIG_NAME


#: Порожній конфіг — і як «файла ще немає», і як форма відповіді.
EMPTY: dict[str, Any] = {"defaults": {}, "profiles": {}, "fallback": ""}


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    """Сирий конфіг. Файла немає — порожній; файл побитий — `ProfileError`.

    🔴 Розбір загорнутий навмисно. Доти `yaml.safe_load` летів винятком нагору,
    і одна зайва двокрапка у файлі валила виклик замість того, щоб дати чесну
    відповідь «конфіг не читається, ось де саме». Профіль секцій це вже робить
    правильно (`core.workspace._read_sections`), і розходитись їм нема причин —
    тим більше тепер, коли файл правлять із браузера, а не лише руками.
    """
    path = config_path()
    if not path.is_file():
        return dict(EMPTY)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"{path} не читається: {exc}") from None
    if raw is None:
        return dict(EMPTY)
    if not isinstance(raw, dict):
        raise ProfileError(f"{path}: очікувався словник, а там {type(raw).__name__}")
    return raw


def available() -> list[dict[str, Any]]:
    """Профілі, що є у файлі: ім'я, підпис, предок, чи він активний.

    ⚠ `display` береться ТАК САМО, як у `_build()`: спершу `surname.display`,
    і лише потім верхній рівень. Доти тут дивились лише на верхній, тож кожен
    профіль, зроблений заготовкою (вона пише `surname.display`), показувався в
    переліку безіменним — рівно ті профілі, для яких перелік і потрібен.
    """
    raw = _raw()
    fallback = str(raw.get("fallback") or "")
    out = []
    for n, b in (raw.get("profiles") or {}).items():
        body = b or {}
        sur = body.get("surname") or {}
        out.append({"name": n,
                    "display": str(sur.get("display") or body.get("display") or ""),
                    "extends": str(body.get("extends") or ""),
                    "active": n == fallback})
    return out


def _pairs(value: Any) -> tuple[tuple[str, float], ...]:
    """`[{value: x, weight: 1.0}]` або `[[x, 1.0]]` → кортеж пар."""
    out = []
    for item in value or []:
        if isinstance(item, dict):
            key = item.get("value", item.get("slot", item.get("text")))
            out.append((str(key), float(item.get("weight", 1.0))))
        else:
            out.append((str(item[0]), float(item[1])))
    return tuple(out)


def _build(name: str, body: dict[str, Any]) -> ResearchProfile:
    sur = body.get("surname") or {}
    return ResearchProfile(
        name=name,
        display=str(sur.get("display") or body.get("display") or ""),
        paradigm_id=str(sur.get("paradigm") or "adj_skyi"),
        stems={str(k): str(v) for k, v in (sur.get("stems") or {}).items()},
        htr_root=str(sur.get("htr_root") or ""),
        roots=_pairs(sur.get("roots")),
        synth_recipe=_pairs(body.get("synth")),
        search_slots=tuple(str(x) for x in (sur.get("search_forms") or [])),
        extra_forms=tuple(str(x) for x in (sur.get("extra_forms") or [])),
        confusers=tuple(str(x) for x in (sur.get("confusers") or [])),
        substrings=tuple(str(x) for x in (sur.get("substrings") or [])),
        rank_down={str(k): str(v) for k, v in (sur.get("rank_down") or {}).items()},
        anchors={str(k): (int(v[0]), str(v[1]), str(v[2]))
                 for k, v in (body.get("anchors") or {}).items()},
        selftest=body.get("selftest") or {},
        places=tuple(body.get("places") or []),
        archives=tuple(body.get("archives") or []),
    )


def resolve(name: str | None = None) -> ResearchProfile:
    """Профіль за іменем; без імені — `fallback` із конфігу."""
    return resolve_in(_raw(), name)


def resolve_in(raw: dict[str, Any], name: str | None = None) -> ResearchProfile:
    """Те саме, але на переданому конфігу — щоб перевірити текст до запису.

    Винесено з `resolve()` саме заради редактора: текст, який щойно набрали,
    треба зарезолвити, не підмінюючи ним справжній файл і не чіпаючи кешів.
    """
    profiles = raw.get("profiles") or {}
    target = name or raw.get("fallback") or ""
    if not target:
        # 🔴 Повідомлення мусить називати вихід. Доти воно казало, чого немає, і
        # мовчало про те, що завести профіль нічим: файл не створює ні `init`,
        # ні майстер, а команди запису не існувало — тобто людина лишалась
        # перед налаштуванням, до якого немає дверей.
        raise ProfileError(
            f"профіль дослідження не задано і немає `fallback` у {config_path()}"
            "\nзавести: `nysh profile init <Прізвище>`")
    if target not in profiles:
        raise ProfileError(
            f"немає профілю «{target}». Є: {', '.join(sorted(profiles)) or '(жодного)'}")

    # `extends` — ланцюжком, як у village-профілях; захист від циклу обов'язковий,
    # бо конфіг редагують руками.
    chain: list[str] = []
    cur = target
    while cur:
        if cur in chain:
            raise ProfileError(f"цикл у extends: {' → '.join([*chain, cur])}")
        chain.append(cur)
        cur = str((profiles.get(cur) or {}).get("extends") or "")
        if cur and cur not in profiles:
            raise ProfileError(f"«{chain[-1]}» успадковує невідомий профіль «{cur}»")

    body: dict[str, Any] = dict(raw.get("defaults") or {})
    for nm in reversed(chain):
        body = _deep_merge(body, profiles.get(nm) or {})
    prof = _build(target, body)
    # 🔴 Парадигма перевіряється ТУТ. Властивість `paradigm` резолвить її ліниво,
    # тож описка у файлі («adj_sky») пролізала через резолв мовчки й падала
    # `KeyError` аж на першому побудованому написанні — тобто не там, де її
    # зробили, і не тим типом, який ловлять усі виклики.
    try:
        morph.paradigm(prof.paradigm_id)
    except KeyError as exc:
        raise ProfileError(f"профіль «{target}»: {exc.args[0]}") from None
    return prof


@lru_cache(maxsize=1)
def active() -> ResearchProfile:
    """Профіль за замовчуванням для процесу."""
    return resolve()


def reset() -> None:
    """Скинути кеші — для тестів і після правки конфігу."""
    _raw.cache_clear()
    active.cache_clear()


# ── правка профілю ───────────────────────────────────────────────────────────
#: Поля, які вміє форма. Решта (`confusers`, `rank_down`, `synth`, `anchors`,
#: `search_forms`) калібрується замірами, а не набором у полі, тож живе в тексті.
FORM_FIELDS: tuple[str, ...] = ("display", "paradigm", "stems", "roots", "substrings")


def paradigm_choices() -> list[dict[str, Any]]:
    """Парадигми для вибору у формі — разом із тим, чи вони перевірені.

    🔴 `verified` віддається назовні саме тому, що досі його не читав НІХТО
    (`core.morph`: «перший, хто візьме їх у роботу, має підняти прапорець»).
    Неперевірена парадигма віддає цілком правдоподібні форми, і людина не має
    жодного способу здогадатись, що на живому матеріалі їх не звіряли.
    """
    return [{"id": p.id, "label": p.label, "verified": p.verified}
            for p in morph.PARADIGMS.values()]


def stem_of(display: str, paradigm: str = "adj_skyi", orth: str = "uk") -> str:
    """Основа з прізвища: зняти відоме закінчення цієї парадигми.

    🔴 Це НЕ та згортка, яку забороняє `core.morph`: там ідеться про
    перенесення основи МІЖ орфографіями («Сикор-» → «Сікор-»), і воно
    заборонене. Тут закінчення знімається за таблицею самої парадигми в межах
    ОДНІЄЇ орфографії — тобто за даними, а не здогадом.
    """
    par = morph.PARADIGMS.get(paradigm)
    if par is None:
        return display.strip()
    ending = (par.endings.get(orth) or {}).get("nom_m", "")
    text = display.strip()
    if ending and text.lower().endswith(ending.lower()):
        return text[: -len(ending)]
    return text


def _slug(display: str) -> str:
    """Ключ профілю з прізвища. Порожній — «rid», щоб файл не лишився без імені."""
    return "".join(ch for ch in display.lower() if ch.isalnum()) or "rid"


def _body_of(display: str, paradigm: str, stems: dict[str, str],
             roots: list[str], substrings: list[str]) -> dict[str, Any]:
    """Тіло профілю так, як його читає `_build()`."""
    sur: dict[str, Any] = {"display": display, "paradigm": paradigm,
                           "stems": {k: v for k, v in stems.items() if v}}
    if roots:
        sur["roots"] = [_Flow([r, 1.0]) for r in roots]
    if substrings:
        sur["substrings"] = list(substrings)
    return {"surname": sur}


def _block(text: str, key: str, indent: int) -> tuple[int, int] | None:
    """Рядки блока `key:` на заданому відступі — (початок, кінець), напіввідкрито.

    Кінець — перший рядок із відступом ≤ `indent`, який не порожній і не
    коментар. Порожні рядки й коментарі всередині блока лишаються в ньому: вони
    належать саме йому, і відрізавши їх, ми переставили б чужі пояснення.
    """
    lines = text.splitlines()
    head = " " * indent + key + ":"
    start = -1
    for i, ln in enumerate(lines):
        if ln == head or ln.startswith(head + " ") or ln.startswith(head + "\t"):
            start = i
            break
    if start < 0:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if len(ln) - len(ln.lstrip()) <= indent:
            end = i
            break
    return start, end


class _Flow(list[Any]):
    """Список, який дампиться в рядок: `[лищинськ, 1.0]`, а не два рядки."""


# `yaml` їде без стабів (ignore_missing_imports), тож базовий клас має тип
# `Any` — успадкування від нього перевірити нічим.
class _Dumper(yaml.SafeDumper):  # type: ignore[misc]
    """Вкладені послідовності з відступом — так їх пише людина й так у скілі."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


_Dumper.add_representer(
    _Flow, lambda d, data: d.represent_sequence(
        "tag:yaml.org,2002:seq", data, flow_style=True))


def _render(body: dict[str, Any], indent: int) -> str:
    """Тіло профілю → YAML із потрібним відступом, без сортування ключів."""
    text = yaml.dump(body, Dumper=_Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=100)
    pad = " " * indent
    return "".join(pad + ln + "\n" for ln in text.splitlines())


def _profiles_indent(text: str) -> int:
    """Відступ, на якому в цьому файлі лежать імена профілів (зазвичай 2)."""
    span = _block(text, "profiles", 0)
    if span is None:
        return 2
    lines = text.splitlines()
    for ln in lines[span[0] + 1:span[1]]:
        if ln.strip() and not ln.lstrip().startswith("#"):
            return len(ln) - len(ln.lstrip())
    return 2


def save(name: str, display: str, *, paradigm: str = "adj_skyi",
         orth: str = "uk", stems: dict[str, str] | None = None,
         roots: list[str] | None = None,
         substrings: list[str] | None = None) -> dict[str, Any]:
    """Завести або оновити профіль. Повертає `{name, path, mode}`.

    Три режими, і плутати їх дорого:

    * `created` — файла ще немає, пишеться заготовка з поясненнями;
    * `added`   — файл є, профілю з таким іменем немає: блок дописується
      всередину `profiles:`, решта файла не чіпається;
    * `updated` — профіль є, поля форми переписуються на МІСЦІ.

    🔴 **Написане рукою не переписується дампом.** Профіль дослідника — це до
    сотні рядків, у яких коментарями записані заміри («668 хітів → 662, тобто
    мовчазна зміна»). Прохід через `yaml.safe_dump` зітер би їх усі, і жоден
    приймач цього не помітив би: файл лишився б валідним. Тому правка — це
    заміна саме того блока, який форма показувала, а перед записом результат
    **перечитується** і звіряється з наміром. Не зійшлось — відмова з порадою
    правити текстом, а не запис «як вийшло».
    """
    display = (display or "").strip()
    if not display:
        raise ProfileError("порожнє прізвище — нема чого шукати")
    # ⚠ Приймаються Й історичні шари: профіль, заведений колись із `orth: bank`,
    # мусить лишитись збережуваним. Питати `bank` у людини перестали (див.
    # `morph.LEGACY_ORTHOGRAPHIES`), але відмовлятись правити те, що вже є, —
    # інша річ.
    if orth not in morph.ALL_ORTHOGRAPHIES:
        raise ProfileError(
            f"невідома орфографія «{orth}». Є: {', '.join(morph.ORTHOGRAPHIES)}")
    try:
        morph.paradigm(paradigm)
    except KeyError as exc:
        raise ProfileError(str(exc.args[0])) from None

    name = (name or "").strip() or _slug(display)
    # 🔴🔴 `ALL_`, а не `ORTHOGRAPHIES`. Форма «Рід» історичних шарів не показує,
    # тож у `stems` вони не приходять — але фільтр по ПИТАНИХ шарах викидав би
    # їх із того, що вже записано. Ціна тиха й дорога: слот без «@орфографія»
    # означає `bank`, доки основа `bank` у профілі є (`render_slot`), а щойно
    # збереження форми її зітре — усі такі слоти мовчки перемикаються на `uk`,
    # тобто міняються самі написання, якими шукають. Помітили б це аж по зміні
    # числа хітів, тобто ніколи.
    keep = {k: str(v).strip() for k, v in (stems or {}).items()
            if k in morph.ALL_ORTHOGRAPHIES and str(v).strip()}
    # 🔴 Основи шарів, ЯКИХ ФОРМА НЕ ПОКАЗУЄ, переносяться з наявного профілю.
    #
    # Форма надсилає рівно ті орфографії, які питає (`morph.ORTHOGRAPHIES`), і
    # `_patch` замінює блок `surname:` цілком — тобто одне збереження стирало б
    # історичну основу `bank`, якої форма не бачить. Ціна тиха: слот без
    # «@орфографія» означає `bank`, доки ця основа є (`render_slot`), а щойно
    # вона зникне — усі такі слоти мовчки перемикаються на `uk`, і міняються
    # самі написання, якими шукають. Помітно це аж по зміні числа хітів.
    # ⚠ Переносяться ТІЛЬКИ непитані шари: питані лишаються під контролем форми,
    # інакше очищене поле не можна було б очистити.
    was_stems = (((_raw().get("profiles") or {}).get(name) or {})
                 .get("surname") or {}).get("stems") or {}
    for k, v in was_stems.items():
        if k not in morph.ORTHOGRAPHIES and str(v).strip():
            keep.setdefault(k, str(v).strip())
    keep.setdefault(orth, stem_of(display, paradigm, orth))
    body = _body_of(display, paradigm, keep,
                    [r for r in (roots or []) if r],
                    [x for x in (substrings or []) if x])

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(_HEAD.format(name=name) + f"  {name}:\n" + _render(body, 4),
                        encoding="utf-8")
        reset()
        return {"name": name, "path": str(path), "mode": "created"}

    text = path.read_text(encoding="utf-8")
    raw = _raw()          # побитий файл кине ProfileError — і добре
    indent = _profiles_indent(text)
    if name in (raw.get("profiles") or {}):
        out, mode = _patch(text, name, indent, body), "updated"
    else:
        out = _append(text, name, indent, body,
                      set_fallback=not raw.get("fallback"))
        mode = "added"

    # 🔴 Приймач ПЕРЕД записом. Патч працює з текстом, тож незвична розкладка
    # (профіль у потоковому стилі, ключ у лапках, якірець) може дати не те, що
    # задумано. Перечитуємо результат і звіряємо ті поля, які міняли: не
    # зійшлось — файл лишається недоторканим.
    _verify(text, out, path, name, body)
    path.write_text(out, encoding="utf-8")
    reset()
    return {"name": name, "path": str(path), "mode": mode}


def _verify(before: str, after: str, path: Path, name: str,
            body: dict[str, Any]) -> None:
    """Пустити правку на диск лише тоді, коли вона зачепила РІВНО задумане.

    🔴 Звіряється весь документ, а не поля форми. Перша редакція перевіряла
    лише те, що змінювала, — і мовчки проходила правка, яка разом із основою
    зносила `confusers` і рядок «звірено оком: full=85.7» поруч. Файл лишався
    валідним, числа у формі — правильними, а півдня роботи зникало без сліду.
    Тому очікуваний результат будується з НАЯВНОГО документа, у якому підмінено
    рівно ті ключі, що показувала форма; будь-яка інша різниця — відмова.

    🔴 І окремо — коментарі. Дані можуть зійтися, а пояснення в замінюваному
    блоці все одно зникнуть: у YAML вони не дані. Тому блок із коментарями
    формою не правиться взагалі, хоч би як гарно сходився дамп.
    """
    try:
        was = yaml.safe_load(before) or {}
        got = yaml.safe_load(after) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"правка зробила б {path.name} нечитабельним ({exc}) — "
                           f"виправте текстом") from None

    want = _deep_merge(was, {"profiles": {name: body}})
    # 🔴 Основи ЗАМІЩУЮТЬСЯ, а не зливаються. Глибоке злиття лишало б у
    # `want` основу, яку людина щойно очистила у формі, — і звірка падала з
    # порадою «правте текстом» на цілком законній дії. Тобто поле, яке форма
    # показує й дозволяє стерти, стерти було неможливо, а відмова говорила про
    # щось інше. Непитані шари сюди не потрапляють: їх переносить `save()`
    # у сам `body`, тож заміщення їх не втрачає.
    sur = ((want.get("profiles") or {}).get(name) or {}).get("surname")
    if isinstance(sur, dict) and isinstance(body.get("surname"), dict)             and "stems" in body["surname"]:
        sur["stems"] = body["surname"]["stems"]
    if got != want:
        raise ProfileError(
            f"правка формою зачепила б у {path.name} не лише те, що показано. "
            f"Так буває з файлом, писаним рукою: у ньому є поля, яких форма не "
            f"знає. Правте текстом — розділ «весь файл»")


def _has_comment(text: str, span: tuple[int, int]) -> bool:
    """Чи є коментар у рядках, які буде замінено."""
    lines = text.splitlines()[span[0]:span[1]]
    return any("#" in ln for ln in lines)


def _patch(text: str, name: str, indent: int, body: dict[str, Any]) -> str:
    """Переписати блок `surname:` профілю, лишивши все довкола як було."""
    span = _block(text, name, indent)
    if span is None:
        raise ProfileError(
            f"профіль «{name}» є в конфігу, але його блока не видно в тексті — "
            f"правте текстом")
    lines = text.splitlines(keepends=True)
    start, end = span
    inner = "".join(lines[start + 1:end])
    sub = _block(inner, "surname", indent + 2)
    rendered = _render(body, indent + 2)
    if sub is None:
        return "".join([*lines[:start + 1], rendered, *lines[end:]])
    if _has_comment(inner, sub):
        raise ProfileError(
            "у цьому профілі коментарі стоять там, де форма пише поля. "
            "Дамп їх не переносить, а в них тут і лежать заміри — "
            "правте текстом: розділ «весь файл»")
    sl = inner.splitlines(keepends=True)
    return "".join([*lines[:start + 1], *sl[:sub[0]], rendered,
                    *sl[sub[1]:], *lines[end:]])


def _append(text: str, name: str, indent: int, body: dict[str, Any],
            *, set_fallback: bool) -> str:
    """Дописати профіль усередину `profiles:`, не чіпаючи наявних."""
    block = " " * indent + name + ":\n" + _render(body, indent + 2)
    span = _block(text, "profiles", 0)
    if span is None:
        out = text.rstrip("\n") + "\n\nprofiles:\n" + block
    else:
        lines = text.splitlines(keepends=True)
        out = "".join([*lines[:span[1]], block, *lines[span[1]:]])
    # Перший профіль у файлі без `fallback` лишився б невидимим: резолв бере
    # саме його, і без цього рядка щойно заведений рід нічим не активувати.
    return f"fallback: {name}\n" + out if set_fallback else out


#: Заготовка. Пояснення в ній не косметика: вони кажуть те, чого форма сказати
#: не може, — чому основи задаються руками й чому корінь береться коротким.
_HEAD = """\
# Чий рід шукаємо. Один файл на простір; профілів у ньому може бути кілька,
# `fallback` каже, який брати без імені.
#
# 🔴 Основа (`stems`) задається на кожну орфографію окремо і руками. Вивести її
# правилом не можна: рос. «Сикор-» → укр. «Сікор-» міняє першу «и», але не «и»
# в закінченні, і позиція залежить від історії слова. Заповнені основи дають
# форми (відмінки, роди, множину) самі — виписувати їх не треба.
#
# Орфографії: uk · ru_modern · ru_prereform · pl.
#
# Поля, яких тут немає (confusers, rank_down, synth, search_forms, anchors),
# калібруються замірами на власному матеріалі. Дописувати їх — сюди ж, руками.
fallback: {name}

profiles:
"""


# ── сирий текст ──────────────────────────────────────────────────────────────
def read_source() -> dict[str, Any]:
    """Текст конфігу як є — для редактора. Файла немає → порожньо, не відмова."""
    path = config_path()
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError as exc:
        raise ProfileError(f"{path} не читається: {exc}") from None
    return {"path": str(path), "exists": path.is_file(), "text": text}


def write_source(text: str) -> dict[str, Any]:
    """Записати сирий конфіг — після того, як він розібрався Й зарезолвився.

    🔴 Дві перевірки, а не одна. Валідний YAML ще нічого не означає: файл, у
    якому `fallback` показує в нікуди або парадигма названа з описки, читається
    без помилки й ламається аж у пошуку. Тому текст резолвиться `resolve_in()`
    ще до того, як торкнеться диска.

    Попередня версія лишається поруч у `.bak`: редактор у браузері — це те
    саме місце, де одним Ctrl+A зносять сотню рядків із замірами.
    """
    path = config_path()
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"це не читається як YAML: {exc}") from None
    if raw is not None and not isinstance(raw, dict):
        raise ProfileError(f"очікувався словник, а там {type(raw).__name__}")
    resolve_in(dict(raw or EMPTY))

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.with_name(path.name + ".bak").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    reset()
    return {"path": str(path), "bytes": len(text.encode("utf-8"))}
