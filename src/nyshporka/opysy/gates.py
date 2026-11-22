"""🚦 Ворота опису-внеску: що не пускаємо в пул і чому.

Ворота спільні з сервером Супряги, як `share.gates`: пакувальник не збирає
брак, приймач проганяє ті самі перевірки ще раз, бо чужому «все гаразд» вірити
підстав немає.

🔴 Описи суворіші за справи. За рядком опису людина замовляє справу в архіві:
рядок, що не веде на сторінку джерела, не можна звірити, і хибний номер
коштує їй грошей і місяців очікування. Тому відмова тут — за:

1. фонд, закритий для заливки (`excluded`, окремо від решти воріт);
2. рядок без прив'язки до сторінки джерела;
3. сторінку джерела, якої рушій не пройшов (без явного `--partial`);
4. погану якість без нормалізації назв;
5. нормалізацію, що вигадує власні назви.

Непідтверджений номер справи, розрив ланцюга номерів, приватне джерело —
позначка, а не відмова: інакше скоропис не пройшов би ніколи, а саме там
опис потрібен найбільше.

🔴 Причина відмови завжди названа поштучно (`Verdict.refuse` з кодом правила).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from nyshporka.opysy import names as N
from nyshporka.opysy.schema import SCHEMA, Manifest, Page, Row, page_ref, row_key
from nyshporka.share import gates as _share_gates

#: Номер правил воріт описів. Піднімається, коли змінюється те, що ворота
#: ПУСКАЮТЬ: нова відмова, інший поріг, інший словник чи межа схожості в `names`.
POLICY = 1

#: Частка нормалізованих рядків із власною назвою без відповідника в сирому,
#: понад яку пакет не пускається. Калібрування 22.11.2026 (вибірка A/B і Б2,
#: зі словником): B ≤ 5 %, Б2 0,3 %, вільна нормалізація на скорописі 31,7 %.
#: Підібрано на тій самій вибірці; перша перевірка поза нею — пілот ДАОО ф.445.
#: Діє лише для мови зі словником (`names.LEXICONS`).
INVENTED_MAX_SHARE = 0.12
#: Менше стількох таких рядків — лише позначки, навіть понад частку: на
#: короткому описі три рядки — це шум вибірки, а не вигадування.
INVENTED_MIN_ROWS = 5
#: Опис класу `low` має бути нормалізований майже весь. Поріг попередній.
NORM_MIN_SHARE_LOW = 0.95
#: Понад таку частку порожніх сторінок — радше рушій не взяв письмо, ніж
#: опис складався з обкладинок. Поріг попередній.
MAX_BLANK_PAGES = 0.5
#: Форми опису, які читає HTR рукопису: клас `high` їм поки не дається.
HAND_FORMS = frozenset({"hand_form", "hand_ruled", "mixed"})

#: Фонди, закриті для заливки, з причиною. Сервер тримає свій перелік
#: (`/v1/opysy/polityka`), цей — для роботи без мережі.
#: Причина в пакеті навмисно нейтральна; повна — у сервера й у Майстерні.
EXCLUDED: dict[tuple[str, str], str] = {
    ("CDIAK", "442"): "описи цього фонду Супряга не приймає",
}

#: Шлях машини у вільному тексті: диск Windows, UNC, домашні теки, file://.
_LOCAL_PATH = re.compile(r"(?:^|[\s\"'(])(?:[A-Za-z]:[\\/]|\\\\[\w.-]+\\|/home/|/Users/|~/|file://)")


class Verdict(_share_gates.Verdict):
    """Той самий вердикт, що у справ, але з номером правил описів."""

    def as_json(self) -> dict[str, Any]:
        out = super().as_json()
        out["policy"] = POLICY
        out["kind"] = "opys"
        return out


def repo_fond(repo: str, fond: str) -> tuple[str, str]:
    """Код архіву й фонд, як у ключах пакета: `ЦДІАК`, `0442` → `CDIAK`, `442`.

    Розбір — той самий, що в реєстрі фонду (`fonds.registry.parse_key`): власна
    копія таблиці кодів архівів уже раз розійшлася з паком.

    ⚠ `parse_key` зводить до коду лише частину кириличних назв («ЦДІАК», «ДАХмО»),
    а «ДАОО» лишає як є — і той самий фонд розходився на два ключі (`ДАОО` і `DAOO`).
    Тому назву ще раз зводимо зворотною таблицею підписів того самого реєстру
    (`REPO_LABEL`), а не новою копією.
    """
    from nyshporka.fonds.registry import REPO_LABEL, parse_key

    try:
        repo_k, fond_k = parse_key(f"{repo.strip()}/{fond.strip()}/1/1")[:2]
    except ValueError:
        repo_k, fond_k = repo.strip().upper(), fond.strip().lower()
    za_pidpysom = {label.upper(): code for code, label in REPO_LABEL.items()}
    # Канонічний код, коли кілька кодів мають той самий підпис (DAVO/DAVIO).
    za_pidpysom["ДАВІО"] = "DAVIO"
    return za_pidpysom.get(repo_k.upper(), repo_k), fond_k


def repo_code(repo: str) -> str:
    """Код архіву як у ключах пакета: `ЦДІАК` → `CDIAK`."""
    return repo_fond(repo, "1")[0]


def excluded(repo: str, fond: str,
             extra: dict[tuple[str, str], str] | None = None) -> str:
    """Причина, з якої фонд закритий для заливки, або порожньо.

    Окремо від решти воріт: її питають ДО прогону (щоб не читати даремно) і
    проганяють на рядках закритого фонду без збирання пакета.
    """
    key = repo_fond(repo, fond)
    table = {**EXCLUDED, **(extra or {})}
    return table.get(key, "")


# ── Розбір ────────────────────────────────────────────────────────────────


def parse(manifest: dict[str, Any], pages: Iterable[dict[str, Any]],
          rows: Iterable[dict[str, Any]]) -> tuple[Manifest | None, list[Page], list[Row], Verdict]:
    """Сирі словники пакета → моделі. Помилка схеми — відмова з файлом і рядком.

    🔴 Номер схеми звіряється ДО розбору: новіший клієнт приносить поля, яких
    цей бік не знає, і замість сирої помилки pydantic людина має почути, що
    сторона застаріла.
    """
    v = Verdict()
    got = manifest.get("schema")
    if not isinstance(got, int):
        v.refuse("у manifest.json немає номера схеми", rule="schema", field="schema")
        return None, [], [], v
    if got > SCHEMA:
        v.refuse(f"схема пакета {got} новіша, ніж знає цей бік ({SCHEMA}): "
                 "онови Нишпорку (або сервер ще не оновлено)", rule="schema_newer", field="schema")
        return None, [], [], v
    try:
        m = Manifest.model_validate(manifest)
    except ValidationError as exc:
        v.refuse(f"manifest.json: {_first_error(exc)}", rule="schema", field="manifest")
        return None, [], [], v
    out_pages: list[Page] = []
    for i, p in enumerate(pages, 1):
        try:
            out_pages.append(Page.model_validate(p))
        except ValidationError as exc:
            v.refuse(f"pages.jsonl, рядок {i}: {_first_error(exc)}", rule="schema", field="pages")
    out_rows: list[Row] = []
    for i, r in enumerate(rows, 1):
        try:
            out_rows.append(Row.model_validate(r))
        except ValidationError as exc:
            v.refuse(f"rows.jsonl, рядок {i}: {_first_error(exc)}", rule="schema", field="rows")
    return m, out_pages, out_rows, v


def _first_error(exc: ValidationError) -> str:
    errs = exc.errors()
    if not errs:
        return str(exc)
    e = errs[0]
    loc = ".".join(str(x) for x in e.get("loc", ()))
    more = f" (і ще {len(errs) - 1})" if len(errs) > 1 else ""
    return f"{loc}: {e.get('msg', '')}{more}"


# ── Ворота ────────────────────────────────────────────────────────────────


def check(m: Manifest, pages: list[Page], rows: list[Row], *,
          excluded_extra: dict[tuple[str, str], str] | None = None) -> Verdict:
    """Проганяє опис крізь усі ворота. Вердикт + позначки поштучно."""
    v = Verdict()
    why = excluded(m.repo, m.fond, excluded_extra)
    if why:
        v.refuse(f"{m.repo} ф.{m.fond}: {why}", rule="excluded_fond", field="fond")
    _gate_text_fields(m, v)
    _gate_meta(m, v)
    _gate_binding(m, rows, v)
    _gate_coverage(m, pages, v)
    _gate_quality(m, rows, v)
    _gate_invented(m, rows, v)
    _warn_numbers(rows, v)
    if any(s.kind == "private" for s in m.sources):
        v.warn("private_source", "скан лише в автора: звірити рядок можна через автора "
                                 "чи в читальній залі; у видачі такий опис стоїть нижче")
    return v


def _gate_text_fields(m: Manifest, v: Verdict) -> None:
    """Шлях машини у вільному тексті маніфесту — слід чужого диска в пулі."""
    fields: list[tuple[str, str]] = [("title", m.title), ("tool", m.tool),
                                     ("quality.note", m.quality.note)]
    if m.partial:
        fields.append(("partial.why", m.partial.why))
    for i, s in enumerate(m.sources):
        fields.append((f"sources[{i}].label", s.label))
    leaked = [name for name, text in fields if text and _LOCAL_PATH.search(text)]
    if leaked:
        v.refuse("у маніфесті шлях машини, на якій збирали пакет: " + ", ".join(leaked),
                 rule="machine_path", field=leaked[0])


def _gate_meta(m: Manifest, v: Verdict) -> None:
    if not m.engines:
        v.refuse("не названо рушія й моделі: без них отримувач не оцінить читання "
                 "(engines у маніфесті)", rule="no_engine", field="engines")
    if not m.license.strip():
        v.refuse("не вказано ліцензію тексту (license у маніфесті)", rule="no_license",
                 field="license")


def _gate_binding(m: Manifest, rows: list[Row], v: Verdict) -> None:
    """Кожен рядок веде на сторінку джерела; ключ рядка — свій, без дублів."""
    if not rows:
        return
    unbound: list[str] = []
    bad_ref: list[str] = []
    bad_half: list[str] = []
    bad_rk: list[str] = []
    seen: dict[str, str] = {}
    dups: list[str] = []
    for i, r in enumerate(rows, 1):
        label = _row_label(i, r)
        if not r.regions:
            unbound.append(label)
            continue
        for g in r.regions:
            if not (0 <= g.src < len(m.sources)) or not (1 <= g.page <= m.sources[g.src].pages):
                bad_ref.append(f"{label} → {page_ref(g.src, g.page, g.half)}")
            elif g.half is not None and not m.sources[g.src].spread:
                bad_half.append(label)
        rk = row_key(m.sources, r)
        if not rk:
            continue
        if r.rk and r.rk != rk:
            bad_rk.append(label)
        if rk in seen:
            dups.append(f"{seen[rk]} і {label}")
        else:
            seen[rk] = label
    if unbound:
        v.refuse(f"{len(unbound)} рядків без прив'язки до сторінки джерела: {_few(unbound)}",
                 rule="row_unbound", field="rows.regions")
    if bad_ref:
        v.refuse(f"{len(bad_ref)} рядків ведуть на сторінку, якої в джерелі немає: {_few(bad_ref)}",
                 rule="row_bad_page", field="rows.regions")
    if bad_half:
        v.refuse(f"{len(bad_half)} рядків мають половину розвороту, а джерело не розворот: "
                 f"{_few(bad_half)}", rule="row_bad_half", field="rows.regions.half")
    if bad_rk:
        v.refuse(f"{len(bad_rk)} рядків несуть чужий ключ (rk не збігається з місцем): "
                 f"{_few(bad_rk)}", rule="row_bad_key", field="rows.rk")
    if dups:
        v.refuse(f"{len(dups)} пар рядків на тому самому місці: {_few(dups)}",
                 rule="row_dup", field="rows.regions")


@dataclass
class Coverage:
    """Покриття опису в одній одиниці — СТОРІНКА ДЖЕРЕЛА.

    Сторінка пройдена, якщо є запис цілої сторінки або обох половин розвороту.
    Порожня — якщо пройдена й тексту немає ні в цілій, ні в жодній половині
    (обкладинка, чистий аркуш). Ту саму одиницю бачать ворота й звіт людині.
    """

    total: int = 0
    read: list[tuple[int, int]] = field(default_factory=list)
    blank: list[tuple[int, int]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    stray: list[str] = field(default_factory=list)


def coverage(m: Manifest, pages: list[Page]) -> Coverage:
    cov = Coverage()
    halves: dict[tuple[int, int], set[int | None]] = {}
    texted: set[tuple[int, int]] = set()
    for p in pages:
        ref = page_ref(p.src, p.page, p.half)
        if not (0 <= p.src < len(m.sources)) or not (1 <= p.page <= m.sources[p.src].pages):
            cov.stray.append(ref)
            continue
        has_text = any(t.strip() for t in p.voices.values())
        if not has_text and not p.blank:
            cov.empty.append(ref)
            continue
        halves.setdefault((p.src, p.page), set()).add(p.half)
        if has_text:
            texted.add((p.src, p.page))
    for si, s in enumerate(m.sources):
        for page in range(1, s.pages + 1):
            cov.total += 1
            got = halves.get((si, page), set())
            if None in got or {0, 1} <= got:
                cov.read.append((si, page))
                if (si, page) not in texted:
                    cov.blank.append((si, page))
            else:
                cov.missing.append(page_ref(si, page))
    return cov


def _gate_coverage(m: Manifest, pages: list[Page], v: Verdict) -> None:
    """Кожна сторінка джерела пройдена рушієм (`coverage`).

    Знаменник — сторінки ДЖЕРЕЛА, а не те, що виробник вирішив прочитати.
    Порожня сторінка рахується пройденою, якщо позначена `blank`; сторінка без
    тексту й без позначки — ні.
    """
    cov = coverage(m, pages)
    if cov.stray:
        v.refuse(f"{len(cov.stray)} сторінок поза джерелом: {_few(cov.stray)}",
                 rule="page_bad_ref", field="pages")
    if cov.empty:
        v.refuse(f"{len(cov.empty)} сторінок без тексту й без позначки blank: {_few(cov.empty)}",
                 rule="page_empty", field="pages")
    if cov.missing:
        if m.partial and m.partial.why.strip():
            v.warn("partial", f"неповний опис ({m.partial.why.strip()}): бракує "
                              f"{len(cov.missing)} з {cov.total} сторінок джерела")
        else:
            v.refuse(f"рушій не пройшов {len(cov.missing)} з {cov.total} сторінок джерела: "
                     f"{_few(cov.missing)}. Неповний опис — лише з полем partial у manifest.json (причина й перелік сторінок)",
                     rule="coverage", field="pages")
    if cov.read and len(cov.blank) / len(cov.read) > MAX_BLANK_PAGES:
        v.refuse(f"порожніх сторінок {len(cov.blank)} з {len(cov.read)}: радше рушій не взяв "
                 "письмо, ніж опис складається з обкладинок", rule="pages_blank",
                 field="pages.blank")


def _gate_quality(m: Manifest, rows: list[Row], v: Verdict) -> None:
    """Клас якості й нормалізація.

    ⚠ Клас оголошує виробник пакета (з форми опису й упевненості рушія), ворота
    його не виводять самі: у пакеті немає еталону. Звіряється лише те, що
    звірити можна: рукопис не буває `high`, а `low` має бути нормалізований.
    """
    q = m.quality
    if q.klass == "high" and q.form in HAND_FORMS:  # form обов'язкова в схемі
        v.refuse(f"рукописний опис ({q.form}) не може мати клас high: рукопис читає HTR, "
                 "і назви без нормалізації шукаються погано", rule="quality_hand_high",
                 field="quality.klass")
    normed = sum(1 for r in rows if r.title_norm.strip())
    if normed and m.normalization is None:
        v.refuse("назви нормалізовано, але не сказано чим (normalization: prompt, version, "
                 "model)", rule="norm_unnamed", field="normalization")
    if q.klass == "low" and rows:
        share = normed / len(rows)
        if share < NORM_MIN_SHARE_LOW:
            v.refuse(f"опис низької якості нормалізований на {share:.0%} рядків (треба "
                     f"≥ {NORM_MIN_SHARE_LOW:.0%}): без нормалізації назви не шукаються",
                     rule="norm_missing", field="rows.title_norm")


def _gate_invented(m: Manifest, rows: list[Row], v: Verdict) -> None:
    """Нормалізація, що вигадує власні назви (`names.invented`).

    🔴 Відмова — лише для мови зі словником загальних слів. Без словника чини й
    установи з великої йдуть за «вигадані прізвища» (заміряно: чесна
    нормалізація скоропису — 16,7 % рядків), і ворота відкидали б чесне. Там —
    лише позначки рядків.
    """
    normed = [(i, r) for i, r in enumerate(rows, 1) if r.title_norm.strip()]
    if not normed:
        return
    common = N.lexicon_for(m.language)
    flagged: list[str] = []
    for i, r in normed:
        bad = N.invented(r.title_raw, r.title_norm, common=common or frozenset())
        if bad:
            flagged.append(f"{_row_label(i, r)}: {', '.join(bad[:3])}")
    if not flagged:
        return
    share = len(flagged) / len(normed)
    v.warn("invented_names", f"{len(flagged)} з {len(normed)} нормалізованих рядків мають "
                             f"власну назву, якої немає в сирому: {_few(flagged)}")
    if common is None:
        v.warn("invented_names_no_lexicon",
               f"для мови «{m.language}» словника загальних слів немає: власні назви "
               "звірено лише позначками, відмови за ними немає")
        return
    if len(flagged) >= INVENTED_MIN_ROWS and share > INVENTED_MAX_SHARE:
        v.refuse(f"нормалізація вигадує власні назви: {len(flagged)} з {len(normed)} рядків "
                 f"({share:.0%}, межа {INVENTED_MAX_SHARE:.0%}). Прізвища й місця "
                 "нормалізація переписує буквально, зіпсоване позначає ⟨?…⟩; виправити "
                 "прізвище можна лише правилом підстановки з доказом. Приклади: "
                 f"{_few(flagged)}", rule="norm_invents", field="rows.title_norm")


def _warn_numbers(rows: list[Row], v: Verdict) -> None:
    """Номери справ: непідтверджені, розриви й повтори ланцюга."""
    if not rows:
        return
    unconf = [r for r in rows if r.no_status == "unconfirmed"]
    if unconf:
        v.warn("no_unconfirmed", f"{len(unconf)} з {len(rows)} номерів справ не підтверджено "
                                 "ні ланцюгом, ні оком — у видачі вони з позначкою «звірити»")
    ordered = sorted((r for r in rows if r.regions and r.no is not None),
                     key=lambda r: (r.regions[0].src, r.regions[0].page,
                                    -1 if r.regions[0].half is None else r.regions[0].half,
                                    r.regions[0].y0))
    seen: set[tuple[int, str]] = set()
    dups: list[str] = []
    back: list[str] = []
    prev: int | None = None
    for r in ordered:
        assert r.no is not None
        key = (r.no, r.letter)
        if key in seen:
            dups.append(f"№{r.no}{r.letter}")
        seen.add(key)
        if prev is not None and r.no < prev:
            back.append(f"№{prev}→{r.no}")
        prev = r.no
    if dups:
        v.warn("no_dup", f"номер справи повторюється {len(dups)} разів: {_few(dups)}")
    if back:
        v.warn("no_back", f"номер іде назад {len(back)} разів (новий розділ опису чи "
                          f"хибне читання): {_few(back)}")


def _row_label(i: int, r: Row) -> str:
    return f"рядок {i}" + (f" (№{r.no}{r.letter})" if r.no is not None else "")


def _few(items: list[str], k: int = 5) -> str:
    head = "; ".join(items[:k])
    return head + (f" … ще {len(items) - k}" if len(items) > k else "")


def summary(m: Manifest, pages: list[Page], rows: list[Row]) -> dict[str, Any]:
    """Знаменник опису: перше число — покриття текстом, потім таблиця."""
    cov = coverage(m, pages)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.no_status] = by_status.get(r.no_status, 0) + 1
    return {"pages_total": cov.total, "pages_read": len(cov.read),
            "pages_blank": len(cov.blank), "rows": len(rows),
            "rows_normalized": sum(1 for r in rows if r.title_norm.strip()),
            "no_status": by_status}


def dumps_verdict(v: Verdict) -> str:
    return json.dumps(v.as_json(), ensure_ascii=False, indent=2)
