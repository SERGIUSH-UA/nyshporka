"""🎯 Профіль дослідження — «чий рід шукаємо» як файл, а не як константи в коді.

Інструмент пошуку по архівах зазвичай прив'язаний до роду, під який його писали:
цільове прізвище розсіяне константами по кількох модулях — таргети пошуку, ваги
генератора синтетики, відмінкова парадигма для підписів розмітки. Копії пишуться
окремо й неминуче розходяться між собою, а щоб шукати СВОЄ прізвище, треба
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
    orth = orth or "bank"
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
    #: Шум, специфічний для ЦЬОГО роду (сусідні прізвища на той самий хвіст).
    confusers: tuple[str, ...] = ()
    #: Підрядки, за якими прізвище впізнається в довільному тексті. Не форми:
    #: саме куски («ікорс», «sikor»), бо декод калічить і початок слова, і кінець.
    substrings: tuple[str, ...] = ()
    #: Правила ЗНИЖЕННЯ РАНГУ: ім'я → regex. Не фільтр — саме ранг: слово, що
    #: може виявитись родом, зникати не має (пор. `confuser-kills-hit-use-rank`).
    rank_down: dict[str, str] = field(default_factory=dict)
    #: Курована таблиця років народження ключових предків: id → (рік, клас, підстава).
    #: Клас (ЗАПИС / З ВІКУ / ГІПОТЕЗА) вирішальний — розбіжність із гіпотезою
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
        """Код форми → приклад-написання для підписів банку розмітки."""
        return self.forms("bank")

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


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {"defaults": {}, "profiles": {}, "fallback": ""}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def available() -> list[dict[str, Any]]:
    raw = _raw()
    return [{"name": n, "display": (b or {}).get("display", ""),
             "extends": (b or {}).get("extends", "")}
            for n, b in (raw.get("profiles") or {}).items()]


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
    raw = _raw()
    profiles = raw.get("profiles") or {}
    target = name or raw.get("fallback") or ""
    if not target:
        # 🔴 Повідомлення мусить називати ВИХІД. Доти воно казало, чого немає, і
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
    return _build(target, body)


@lru_cache(maxsize=1)
def active() -> ResearchProfile:
    """Профіль за замовчуванням для процесу."""
    return resolve()


def reset() -> None:
    """Скинути кеші — для тестів і після правки конфігу."""
    _raw.cache_clear()
    active.cache_clear()


# ── заведення профілю ────────────────────────────────────────────────────────
#: Заготовка конфігу. Основи на РЕШТУ орфографій лишаються порожніми навмисно:
#: докстрінг `core.morph` пояснює, чому їх не виводять правилом («рос. Сикор- →
#: укр. Сікор-: позиція залежить від історії слова, не від правила»). Порожнє
#: поле з підписом чесніше за вгадане: воно видно, а хибна основа мовчки
#: викидає половину написань із пошуку.
_TEMPLATE = """\
# Чий рід шукаємо. Один файл на простір; профілів у ньому може бути кілька,
# `fallback` каже, який брати без імені.
#
# 🔴 Основа (`stems`) задається НА КОЖНУ орфографію окремо і руками. Вивести її
# правилом не можна: рос. «Сикор-» → укр. «Сікор-» міняє першу «и», але не «и»
# в закінченні, і позиція залежить від історії слова. Заповнені основи дають
# форми (відмінки, роди, множину) самі — виписувати їх не треба.
#
# Орфографії: ru_modern · ru_prereform · uk · pl · bank (історична таблиця
# підписів розмітки, може бути внутрішньо непослідовною — так і лишати).
fallback: {name}

profiles:
  {name}:
    surname:
      display: {display}
      paradigm: {paradigm}      # {paradigm_label}
      stems:
        {orth}: {stem}
{other_stems}
      # Корені для фаззі-пошуку: рушій калічить саме СЕРЕДИНУ слова, тож корінь
      # береться коротким. Вага — від 0 до 1.
      roots:
        - [{stem}, 1.0]
      # Написання, які правилом не виводяться: описки писаря, чужі традиції.
      extra_forms: []
      # Сусідні прізвища з тим самим хвостом, які дають хибні хіти.
      confusers: []
"""


def write_config(name: str, display: str, *, paradigm: str = "adj_skyi",
                 orth: str = "uk", force: bool = False) -> Path:
    """Створити `config/research_profile.yaml` із заготовкою під це прізвище.

    Повертає шлях. Наявний файл не чіпається без `force`: у ньому вже може
    лежати робота, а мовчазний перезапис профілю означав би, що пошук назавтра
    шукає інше прізвище й ніде про це не каже.

    🔴 Основа відсікається за таблицею САМОЇ парадигми, а не здогадом. Це не та
    згортка, яку `core.morph` забороняє: там ідеться про перенесення основи між
    орфографіями, тут — про зняття відомого закінчення в межах однієї.
    """
    if orth not in morph.ORTHOGRAPHIES:
        raise ProfileError(
            f"невідома орфографія «{orth}». Є: {', '.join(morph.ORTHOGRAPHIES)}")
    try:
        par = morph.paradigm(paradigm)
    except KeyError as exc:
        raise ProfileError(str(exc)) from None

    display = display.strip()
    if not display:
        raise ProfileError("порожнє прізвище")
    ending = (par.endings.get(orth) or {}).get("nom_m", "")
    stem = display
    if ending and display.lower().endswith(ending.lower()):
        stem = display[: -len(ending)]

    path = config_path()
    if path.exists() and not force:
        raise ProfileError(
            f"{path} вже є — правити руками або `nysh profile init --force`")

    others = "\n".join(
        f"        # {o}:  # ← заповнити, якщо шукати й цією орфографією"
        for o in morph.ORTHOGRAPHIES if o != orth)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _TEMPLATE.format(name=name, display=display, paradigm=paradigm,
                         paradigm_label=par.label, orth=orth, stem=stem,
                         other_stems=others),
        encoding="utf-8")
    # 🔴 Обидва кеші, а не лише сирий конфіг: `active()` тримає зібраний
    # профіль окремо, і без цього перший же показ у тому самому процесі віддав
    # би стан «профілю немає» на щойно створений файл.
    reset()
    return path
