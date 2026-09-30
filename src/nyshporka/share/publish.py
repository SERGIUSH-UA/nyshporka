"""📤 Зібрати свій декод у пакет: від шифри до файлу й рядка каталогу.

Порядок тут не випадковий: спершу збираємо ЗАЯВУ (що це за справа, скільки
кадрів, чим читали), проганяємо її крізь ворота — і лише тоді пишемо файл.
Зворотний порядок (зібрати, потім перевірити) залишає на диску пакет, який не
можна віддавати, і рано чи пізно хтось його однаково віддасть.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from nyshporka.share import (
    align,
    bundle,
    catalog,
    fingerprint,
    gates,
    journal,
    opys,
    opys_check,
)
from nyshporka.share.bundle import Manifest


class PublishError(RuntimeError):
    """Пакет не зібрати — з названою причиною."""


def resolve_runs(scope: str, *,
                 skip: tuple[str, ...] | list[str] = ()) -> tuple[list[Path], dict[str, Any]]:
    """Теки прогонів для справи або для одного прогону, разом із голосами.

    🔴 Голоси добираються ЗАВЖДИ. Справу читають двома моделями, і пакет із
    однією з них виглядає повним: сторінки на місці, знаменник сходиться, а
    другого прочитання просто немає — і отримувач про це не дізнається.
    """
    from nyshporka import htr_store as S
    from nyshporka.cloud.verify import voice_dirs
    from nyshporka.core.workspace import workspace

    scope = (scope or "").strip()
    if not scope:
        raise PublishError("не названо, що пакувати: шифра справи або ім'я прогону")
    try:
        got = S.runs_for_scope(scope)
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    if got.get("kind") not in ("case", "run"):
        # 🔴 Серія фонду — не справа. Шифру, якої не розібрав резолвер,
        # пошук чесно розуміє як серію і збирає прогони за хвостом цифр:
        # «ДАВіО ф.792 оп.1 спр.25» так зібрало чужий прогін `25-1-182`, і
        # пакет поїхав би з чужим текстом під цією шифрою.
        keys = ", ".join(got.get("keys") or []) or "—"
        raise PublishError(
            f"«{scope}» не розпізнано як одну справу (знайдено серію: {keys}). "
            "Назвіть справу ключем, напр. DAVO/792/25")
    rows = got.get("rows") or []
    if not rows:
        raise PublishError(
            f"для «{scope}» прочитаного немає. Що є взагалі: nysh text state")
    root = workspace().htr_reports
    dirs: list[Path] = []
    for r in rows:
        d = root / str(r.get("name") or "")
        if not d.is_dir():
            continue
        if d not in dirs:
            dirs.append(d)
        for v in voice_dirs(d):
            # 🔴 Голос без мети — невідомо, якою моделлю читали, і ворота
            # відмовили б через нього ВСЬОМУ пакету. Такий голос не їде.
            if v not in dirs and (v / bundle.META_NAME).is_file():
                dirs.append(v)
    dirs, skipped = choose_voices(dirs, str(got.get("key") or ""), skip=skip,
                                  own=[str(r.get("name") or "") for r in rows])
    got["skipped_runs"] = skipped
    if not dirs:
        why = "; ".join(f"{s['run']}: {s['why']}" for s in skipped)
        raise PublishError(f"теки прогонів для «{scope}» немає на диску"
                           + (f" (відкинуто: {why})" if why else ""))
    return dirs, got


def _meta_of(d: Path) -> dict[str, Any]:
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(d / bundle.META_NAME, default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}


def choose_voices(dirs: list[Path], key: str, *,
                  skip: tuple[str, ...] | list[str] = (),
                  own: tuple[str, ...] | list[str] = ()) -> tuple[list[Path], list[dict[str, str]]]:
    """Які прогони справи — голоси пакета, а які лишаються вдома. І чому.

    🔴 «Усі теки з ключем справи» — не те саме, що «прочитання справи». На
    живому просторі серед них стояли:

    * **заміри** (`control_run`): латинська модель по кириличному аркушу,
      прогнана, щоб ДОВЕСТИ, що польських вставок немає, — 942 сторінки
      сміттєвого тексту, які в пакеті стали б рівноправним голосом;
    * **проби**: 15 і 40 кадрів тією самою моделлю, яка потім прочитала всі
      602 — їхні рядки вдруге лягали б у знаменник і в хеш змісту;
    * **сусіди за префіксом**: `voice_dirs` бере будь-яку теку `<прогін>-*`,
      і для короткого імені `010241` туди потрапляли прогони ІНШИХ справ;
    * **чужі прийняті** (`shared`): їх уже віддав автор, і перепакувати їх
      від свого імені не можна.

    Проба впізнається не за іменем, а за змістом: її сторінки цілком входять
    у повніший прогін ТІЄЇ САМОЇ моделі. Прогони однієї моделі по різних
    частинах справи (сторінки не вкладені) лишаються обидва.

    `skip` — імена прогонів, які людина чи агент прибрали явно.

    `own` — прогони, які відбір справи (`runs_for_scope`) уже визнав за цю
    справу: за прив'язкою `cases bind` чи за текою кадрів. 🔴 `case_key` у
    меті — шифра паспорта НА МИТЬ прогону, і після `nysh case --shifra` він
    застаріває. 29.09 сімнадцять справ Нікополя, переведених з оп. 1 на оп. 3,
    так відмовили цілком: «прогін іншої справи (ДАДнО 193-1-201)», а
    `cases bind` не допомагав, бо тут його ніхто не питав. Ключ мети лишається
    сторожем лише для решти — сусідів за префіксом (`voice_dirs`), і сусід, що
    читав ту саму теку кадрів або прив'язаний до справи, — теж свій.
    """
    from nyshporka import htr_store as S

    skipped: list[dict[str, str]] = []
    keep: list[tuple[Path, dict[str, Any], set[str]]] = []
    want = S._canon_case_key(key) if key else ""
    skip_set = {str(s).strip() for s in skip if str(s).strip()}
    own_set = {n for n in own if n}
    bound = S._bound_runs() if want else {}
    own_frames = {S.frames_dir_key(_meta_of(d).get("case_dir"))
                  for d in dirs if d.name in own_set} - {""}
    for d in dirs:
        meta = _meta_of(d)
        if d.name in skip_set:
            skipped.append({"run": d.name, "why": "прибрано явно (--skip-run)"})
            continue
        if meta.get("shared"):
            skipped.append({"run": d.name, "why": "чужий прийнятий прогін — його "
                                                  "віддає автор, не ви"})
            continue
        if meta.get("control_run"):
            skipped.append({"run": d.name, "why": "вимірювальний прогін "
                                                  "(control_run), а не прочитання"})
            continue
        its = str(meta.get("case_key") or "")
        if d.name in bound:
            ours = S._canon_case_key(bound[d.name] or "") == want
        else:
            ours = (d.name in own_set
                    or S.frames_dir_key(meta.get("case_dir")) in own_frames)
        if want and its and not ours and S._canon_case_key(its) != want:
            skipped.append({"run": d.name,
                            "why": f"прогін іншої справи ({its})"})
            continue
        pages = {p.name for p in d.glob(bundle.PACKED_TEXT)}
        keep.append((d, meta, pages))

    out: list[Path] = []
    for i, (d, meta, pages) in enumerate(keep):
        model = str(meta.get("model") or "")
        wider = next((o for j, (o, m, p) in enumerate(keep)
                      if j != i and str(m.get("model") or "") == model and model
                      and pages <= p and (len(p) > len(pages) or j < i)), None)
        if wider is not None and pages:
            skipped.append({"run": d.name,
                            "why": f"пробний: усі його {len(pages)} стор. є в "
                                   f"повнішому прогоні {wider.name} тієї самої моделі"})
            continue
        out.append(d)
    return out, skipped


def _case_block(scope_info: dict[str, Any], case_dir: Path | None) -> dict[str, Any]:
    """Шифра й опис справи — з паспорта теки, а не з нашого ключа.

    🔴 `key_local` їде довідково й ніколи як ідентичність: він збирається з
    імені теки й версії паку, тож в іншого дослідника та сама справа дістане
    інший ключ (`align` пояснює, чому).
    """
    from nyshporka.cases.register import parse_shifra, read_sidecar

    key = str(scope_info.get("key") or "")
    shifra = str(scope_info.get("shifra") or "")
    side = read_sidecar(case_dir) if case_dir else {}
    shifra = str(side.get("shifra") or shifra)
    out: dict[str, Any] = {"shifra": shifra, "key_local": key}
    if shifra:
        try:
            s = parse_shifra(shifra)
            out.update(repo=s.repo, fond=s.fond, opys=s.opys, spr=s.spr)
        except Exception:
            pass
    for src, dst in (("title", "title"), ("place", "place")):
        if side.get(src):
            out[dst] = side[src]
    # Жанр — кодом зі словника пакета, а не вільним текстом паспорта: картка
    # фільтрує каталог за ним, а в дослідницьких паспортах поле зветься
    # `record_type` і пишеться як завгодно («Ревізькі казки причту…»).
    code, types = opys.genre(side, str(out.get("title") or ""))
    if code:
        out["doc_type"] = code
    if types:
        out["record_types"] = types
    out.update(opys.sidecar_extras(side))
    raw_years = ([] if opys.sidecar_years_from_fs(side)
                 else [side.get("year_from"), side.get("year_to")])
    years = [int(y) for y in raw_years
             if isinstance(y, (int, str)) and str(y).isdigit()]
    if years:
        out["years"] = [min(years), max(years)]
    places = side.get("villages_from_index") or side.get("covers")
    if isinstance(places, list) and places:
        out["places"] = [str(p) for p in places][:20]
    elif side.get("place"):
        out["places"] = [str(side["place"])]
    return out


def _normalize_shifra(case: dict[str, Any], key: str) -> dict[str, Any]:
    """Шифра, яку розбирає резолвер, — навіть коли паспорт записав її інакше.

    🔴 Паспорти тримають шифру як завгодно: «ДАВіО ф.726 оп.1 спр.26»,
    «Р-93-3-19» без архіву, «ДАЖО 178-51-418 (арк. сільської секції)».
    Резолвер таких не розбирає, і справа йшла б у каталог під шифрою, за
    якою її ніхто не знайде. Ключ справи відомий — тоді в маніфест іде його
    канонічна шифра, а запис паспорта лишається поруч довідково.
    """
    from nyshporka.pagestore import resolve_case

    raw = str(case.get("shifra") or "")
    try:
        resolve_case(raw)
        return case
    except Exception:
        pass
    try:
        ref = resolve_case(key) if key else None
    except Exception:
        ref = None
    if ref is None or not ref.opys:
        return case
    from nyshporka.library import _shifra

    canon = _shifra(ref.repo, ref.fond, ref.opys, ref.spr)
    try:
        if resolve_case(canon).key != ref.key:
            return case
    except Exception:
        return case
    out = {**case, "shifra": canon, "repo": ref.repo, "fond": ref.fond,
           "opys": ref.opys, "spr": ref.spr}
    if raw and raw != canon:
        out["shifra_pasport"] = raw
    return out


_EXPLICIT_OPYS = re.compile(r"^[^/]+/([^/-]+)-([^/]+)/")


def _opys_z_progoniv(case: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """Опис справи — з прогонів, коли вони називають його явно.

    🔴 У фондах, де опис не входить до ключа (ЦДІАК 127), справи різних
    описів з тим самим номером мають ОДИН ключ: «127-1076-1664» і
    «127-1078-1664» — обидві `CDIAK/127/1664`. Резолвер за ключем вгадує
    опис, і прогін з опису 1078 поїхав би в каталог під шифрою 1076, тобто
    під чужою справою. Прогін же пам'ятає опис явно — у своїй меті чи в
    прив'язці («CDIAK/127-1078/1664»). Паспорт теки сильніший: якщо він
    називає інший опис, нічого не міняється, а розбіжність ловить засів.
    """
    from nyshporka import htr_store as S

    bound = S._bound_runs()
    fond = str(case.get("fond") or "")
    found: set[str] = set()
    for r in info.get("rows") or []:
        raw = str(bound.get(str(r.get("name")), None) or r.get("case_key") or "")
        m = _EXPLICIT_OPYS.match(raw)
        if m and m.group(1) == fond:
            found.add(m.group(2))
    if len(found) != 1:
        return case
    opys = found.pop()
    if str(case.get("opys") or "") == opys or case.get("shifra_pasport"):
        return case
    from nyshporka.library import _shifra

    out = {**case, "opys": opys,
           "shifra": _shifra(case.get("repo"), case.get("fond"), opys, case.get("spr"))}
    if case.get("shifra") and case["shifra"] != out["shifra"]:
        out["shifra_rezolver"] = case["shifra"]
    return out


def _teky_pasportu(case_dir: Path | None) -> list[Path]:
    """Тека справи й теки, з яких її сторінки відрендерено (`rendered_from`).

    🔴 Справу, читану з PDF, рушій бачить як теку відрендерених сторінок, і
    паспорт цієї теки каже лише «рендер із PDF для HTR-черги». Звідки PDF —
    знає паспорт теки ПОРУЧ із самим PDF. Заміряно 28.09.2026: у пулі стояло
    822 книги без посилання на скани, і для 298 з них посилання лежало саме
    там — у паспорті теки-джерела або в її `meta.json`.
    """
    from nyshporka.cases.register import read_sidecar

    if case_dir is None:
        return []
    out = [Path(case_dir)]
    try:
        from nyshporka.core.workspace import workspace

        root: Path | None = workspace().root
    except Exception:
        root = None
    for rel in read_sidecar(Path(case_dir)).get("rendered_from") or []:
        p = Path(str(rel))
        bazy = [x for x in (root, Path(case_dir)) if x is not None]
        for cand in ([p] if p.is_absolute() else [b / p for b in bazy]):
            if cand.parent.is_dir() and cand.parent not in out:
                out.append(cand.parent)
                break
    return out


def _ref_z_adresy(url: str) -> dict[str, str] | None:
    """Ідентифікатор зйомки з адреси сканів — або None для чужого хоста.

    Одне правило на `--link` і на паспорт: розійдуться — і та сама адреса
    Commons із прапорця стане посиланням, а з паспорта ні. Так і було:
    `source_url` паспорта їхав як `url`, якого пул не приймає, і скани
    губились дорогою.
    """
    import re
    from urllib.parse import unquote, urlparse

    url = str(url or "").strip()
    if not url:
        return None
    commons = re.search(r"commons\.wikimedia\.org/wiki/(?:File|Файл):([^?#]+)",
                        unquote(url), re.IGNORECASE)
    if commons:
        return {"source": "commons", "ref": f"file:{commons.group(1)}", "url": url}
    if urlparse(url).netloc.lower() == "upload.wikimedia.org":
        # Пряма адреса файлу: останній сегмент шляху і є назвою в Commons.
        imia = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        if imia:
            return {"source": "commons", "ref": f"file:{imia}", "url": url}
    dgs = re.search(r"familysearch\.org/.*?(?:imageGroupNumbers=|/film/|dgs[:=])"
                    r"(\d{6,9})", url, re.IGNORECASE)
    if dgs:
        return {"source": "fs", "ref": f"dgs:{dgs.group(1)}", "url": url}
    # Та сама форма, що пише сайдкар (`viewer_id` → `file:<id>`).
    archium = re.search(r"archium\.[\w.-]+/file-viewer/(\d+)", url, re.IGNORECASE)
    if archium:
        return {"source": "archium", "ref": f"file:{archium.group(1)}", "url": url}
    return None


def _commons_nazvy(raw: Any) -> list[str]:
    """Назви файлів Commons: багатотомна справа пише їх через «;»."""
    out = []
    for chast in str(raw or "").split(";"):
        imia = chast.strip().removeprefix("File:").removeprefix("Файл:").strip()
        if imia:
            out.append(imia)
    return out


def _refs_from_sidecar(case_dir: Path | None) -> list[dict[str, str]]:
    """Стабільні посилання на джерело зйомки — єдине, що не залежить від нас.

    Ключ справи в кожного свій, а `File:…` у Commons або DGS у FamilySearch
    однакові для всіх. Саме за ними отримувач знайде ті самі аркуші.

    Паспорт шукається й у теці, з якої сторінки відрендерено
    (`_teky_pasportu`), і читається в усіх формах, у яких посилання в
    паспортах справді лежить: поля `dgs`/`commons_title`/`viewer_id`, назва
    Commons у мітці чистки бінарників, адреси файлів у старому `meta.json`.
    """
    from nyshporka.cases.register import read_sidecar

    out: list[dict[str, str]] = []

    def add(source: str, ref: str, url: str = "") -> None:
        if ref and not any(r["source"] == source and r["ref"] == ref for r in out):
            row = {"source": source, "ref": ref}
            if url:
                row["url"] = url
            out.append(row)

    def z_adresy(url: Any) -> bool:
        got = _ref_z_adresy(str(url or ""))
        if got:
            add(got["source"], got["ref"], got.get("url", ""))
        return got is not None

    for teka in _teky_pasportu(case_dir):
        side = read_sidecar(teka)
        if side.get("dgs") or side.get("fs_film") or side.get("film"):
            ident = side.get("dgs") or side.get("fs_film") or side.get("film")
            add("fs", f"dgs:{ident}" if side.get("dgs") else f"film:{ident}",
                str(side.get("fsfiles_url") or side.get("base_url") or ""))
        for imia in _commons_nazvy(side.get("commons_title")):
            add("commons", f"file:{imia}", str(side.get("commons_url") or ""))
        # Бінарники Commons прибрано після звірки — назва лишилась у мітці.
        pcv = side.get("purged_commons_verified")
        if isinstance(pcv, dict):
            for imia in _commons_nazvy(pcv.get("commons_title")):
                add("commons", f"file:{imia}")
        if side.get("viewer_id"):
            add("archium", f"file:{side['viewer_id']}",
                str(side.get("viewer_url") or ""))
        if side.get("babynyar_case"):
            add("babynyar", f"case:{side['babynyar_case']}",
                str(side.get("babynyar_url") or ""))
        # Старий паспорт завантажувача (`meta.json`): адреса в кожного файлу.
        for f in side.get("files") or []:
            if isinstance(f, dict):
                z_adresy(f.get("source_url"))
        for key in ("source_url", "duck_url"):
            if side.get(key) and not z_adresy(side[key]):
                add("url", str(side[key]), str(side[key]))
                break
    return out


def _refs_from_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ідентифікатори зйомки з посилань, які людина дала сама (`--link`).

    🔴 Лише користувацькі посилання й лише відомі хости сканів. Реєстрові
    лишаються в `links` (див. `_links_from_registry`): вони кажуть «справа
    там є», а не «знімали звідти». А людина, яка дала `--link` на файл
    Commons, називає саме джерело своїх сканів — і ворота досі казали їй
    `no_refs` з порадою додати той самий `--link`, який вона вже додала.
    """
    out: list[dict[str, str]] = []
    for link in links:
        got = _ref_z_adresy(str(link.get("url") or ""))
        if got:
            out.append(got)
    return out


def _merge_refs(pershi: list[dict[str, str]],
                dodatkovi: list[dict[str, str]]) -> list[dict[str, str]]:
    """Сайдкар важить більше: джерело, яке він уже назвав, не перебивається."""
    out = list(pershi)
    for r in dodatkovi:
        if not any(x.get("source") == r["source"] for x in out):
            out.append(r)
    return out


def _letter_variants(letter: str) -> list[str]:
    """Літерний індекс справи обома письмами: `a` → `["a", "а"]`.

    ⚠ Зворотний бік таблиці будується З НЕЇ САМОЇ, а не пишеться вдруге:
    `_norm_spr` зводить кириличну літеру до латинської, і другий перелік
    розійшовся б із першим при першому ж доданому рядку.
    """
    from nyshporka.library import _LETTER_TO_LAT

    if not letter:
        return [""]
    out = [letter]
    out += [cyr for cyr, lat in _LETTER_TO_LAT.items()
            if lat == letter and cyr != letter]
    return out


def _links_from_registry(shifra: str) -> list[dict[str, str]]:
    """Куди піти по ці скани — з реєстру опису фонду.

    🔴 Саме `links`, а НЕ `refs`, і це не косметика. `refs` на боці пулу
    означає «та сама ЗЙОМКА» і склеює зйомки між собою; реєстр опису знає
    лише, що СПРАВА є на FamilySearch чи в Commons — а качали її, може,
    зовсім не звідти. Реєстрове посилання в `refs` склеїло б дві різні
    зйомки однієї справи в одну, тобто приписало б чужі координати рядків
    чужим пікселям. `links` цього не роблять: вони для ока, не для добору.

    Навіщо взагалі: ворота попереджають `no_refs` — «звірити знахідку з
    зображенням отримувачу буде нікуди піти». На десятьох засіяних справах
    сайдкари джерела не мали (`spr-6940` прямо каже «DGS не зафіксовано на
    момент завантаження»), а реєстр опису його знає — просто пакувальник
    туди не заглядав.

    Мовчить у будь-якій халепі: пакування не має падати через те, що
    реєстру фонду немає або простір ще не зібраний.
    """
    row = opys.registry_row(shifra)
    if not row:
        return []

    out: list[dict[str, str]] = []
    dgs = str(row.get("fs_dgs") or row.get("fs_film") or "").strip()
    if dgs:
        out.append({
            "label": f"FamilySearch, DGS {dgs}",
            "url": "https://www.familysearch.org/records/images/"
                   f"search-results?imageGroupNumbers={dgs}",
        })
    commons = str(row.get("commons_title") or "").strip()
    if commons:
        out.append({"label": f"Wikimedia Commons: {commons}",
                    "url": str(row.get("commons_url") or "").strip()})
    archium = str(row.get("archium_url") or "").strip()
    if archium:
        out.append({"label": "ARCHIUM, посторінкові скани", "url": archium})
    return [x for x in out if x["url"]]


def _with_registry(own: list[dict[str, str]], shifra: str) -> list[dict[str, str]]:
    """Свої посилання плюс реєстрові, без повторів.

    🔴 Назване людиною йде першим і не витісняється: вона знає, звідки
    качала САМЕ ЦЮ зйомку, а реєстр знає лише, де справа є взагалі.
    """
    out = list(own)
    seen = {x.get("url", "").strip().rstrip("/") for x in out}
    for link in _links_from_registry(shifra):
        if link["url"].rstrip("/") not in seen:
            out.append(link)
            seen.add(link["url"].rstrip("/"))
    return out


def _znamennyk(frames_block: dict[str, Any],
               row: dict[str, Any] | None) -> dict[str, Any]:
    """Знаменник покриття — кадри КОПІЇ справи, а не теки на диску.

    🔴 Тека тримає рівно те, що скачали: з дзеркала взяли 5 кадрів із 824 — і
    маніфест казав «5 із 5», каталог Супряги малював повну смугу, а ворота
    20 % такий уривок пропускали. Реєстр опису знає, скільки кадрів має
    копія. Поріг той самий, що в «partial» бібліотеки: завантажувач пропускає
    технічні кадри, і дрібний недобір — не уривок.
    """
    from nyshporka.fonds.registry import _PARTIAL_RATIO, expected_frames

    want = expected_frames(row) if row else 0
    have = int(frames_block.get("total") or 0)
    if want and have < want * _PARTIAL_RATIO:
        # `listed` лишається кадрами на диску: за ним іде прив'язка тексту.
        return {**frames_block, "total": want, "on_disk": have}
    return frames_block


def _opys_hint(info: dict[str, Any]) -> str:
    """Опис справи з `case_key` прогонів — коли ключ бібліотеки його не несе."""
    from nyshporka.library import split_fond_opys

    for r in info.get("rows") or []:
        parts = str(r.get("case_key") or "").split("/")
        if len(parts) == 3:
            # Літерний фонд (`R-6129`) — один сегмент, а не фонд із описом.
            _fond, opys = split_fond_opys(parts[1])
            if opys:
                return opys
    return ""


def _znamennyk_z_pasporta(frames_block: dict[str, Any],
                          home: Path | None) -> dict[str, Any]:
    """Скільки кадрів мала справа, коли самих кадрів на диску вже немає.

    🔴 Лише знаменник: `listed` лишається нулем, бо прив'язувати текст нема
    до чого, і відбитка теж не буде. Але «кадрів не названо» там, де паспорт
    знає число, змушувало картку мовчати про повноту прочитаного.
    """
    from nyshporka.cases.register import read_sidecar

    if home is None or frames_block.get("total"):
        return frames_block
    for teka in _teky_pasportu(home):
        side = read_sidecar(teka)
        removed: dict[str, Any] = {}
        f = teka / "_frames_removed.json"
        if f.is_file():
            try:
                import json

                got = json.loads(f.read_text(encoding="utf-8"))
                removed = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                removed = {}
        # Старий `meta.json`: сторінки кожного PDF справи.
        storinok_pdf = 0
        for fl in side.get("files") or []:
            try:
                storinok_pdf += int((fl or {}).get("pagecount") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
        for value in (removed.get("frames_was"), side.get("frames"),
                      side.get("frames_got"), side.get("n_pages"), storinok_pdf):
            try:
                n = int(value or 0)
            except (TypeError, ValueError):
                continue
            if n > 0:
                return {**frames_block, "total": n, "on_disk": 0}
    return frames_block


def znamennyk_spravy(key: str, shifra: str = "") -> dict[str, Any]:
    """Скільки кадрів має справа і ЗВІДКИ це число — те саме, що візьме пакування.

    🔴 Одна відповідь на три місця. Пакувальник шукає число в п'яти джерелах,
    а перелік неподіленого дивився лише в бібліотеку: справа з числом у
    паспорті чи в картці стояла там «без кадрів», хоча пакувалась, і навпаки —
    картка не казала, чи число взагалі є, доки пакування не відмовляло.

    `total` — 0, коли числа немає ніде; `unknown` — причина з картки, якщо
    людина її назвала.
    """
    from nyshporka.fonds.registry import _PARTIAL_RATIO, expected_frames
    from nyshporka.share import card as K

    out: dict[str, Any] = {"total": 0, "source": "", "unknown": ""}
    if not key:
        return out
    kartka = K.get(key)
    out["unknown"] = str(kartka.get("frames_unknown") or "")
    case_dir = align.case_dir_for(key)
    na_dysku = len(align.frames_sorted(case_dir)) if case_dir else 0
    total, source = na_dysku, ("кадри на диску" if na_dysku else "")
    if not total:
        home = align.case_home_for(key)
        total = int(_znamennyk_z_pasporta({"total": 0}, home).get("total") or 0)
        source = "паспорт теки" if total else ""
    if not total:
        total = align.library_frames(key)
        source = "бібліотека" if total else ""
    row = opys.registry_row(shifra) if shifra else None
    want = expected_frames(row) if row else 0
    if want and total < want * _PARTIAL_RATIO:
        total, source = want, "реєстр опису"
    try:
        z_kartky = int(kartka.get("frames") or 0)
    except (TypeError, ValueError):
        z_kartky = 0
    if z_kartky and z_kartky >= na_dysku:
        total, source = z_kartky, "картка"
    out.update(total=total, source=source)
    return out


def build_manifest(scope: str, *,
                   hash_frames: bool = False,
                   publisher: str = "", contact: str = "", site: str = "",
                   note: str = "", links: list[dict[str, str]] | None = None,
                   extra: dict[str, Any] | None = None,
                   license_text: str = "CC0-1.0",
                   source_terms: str = "",
                   archive_name: str = "",
                   skip_runs: tuple[str, ...] | list[str] = (),
                   card_fields: dict[str, Any] | None = None,
                   ) -> tuple[Manifest, list[Path], list[dict[str, Any]], dict[str, Any]]:
    """Скласти заяву пакета. Файл ще не пишеться — спершу ворота.

    `card_fields` — поля картки поверх запам'ятованої (`share/card.py`):
    назва, роки, місця, жанр, які людина чи агент задали самі.
    """
    from nyshporka.share import card as K

    run_dirs, info = resolve_runs(scope, skip=skip_runs)
    key = str(info.get("key") or "")
    case_dir = align.case_dir_for(key) if key else None
    frames = align.frames_of(case_dir, hash_frames=hash_frames) if case_dir else []
    # Тека справи — паспорт — буває й без кадрів (прибрані після читання).
    # Кадри й відбиток — лише з `case_dir`; опис, посилання й знаменник — звідси.
    home = align.case_home_for(key, _opys_hint(info)) if key else None
    voices = [bundle.voice_of(d) for d in run_dirs]
    voices = [v for v in voices if v.pages]
    if not voices:
        raise PublishError(
            f"у теках прогонів немає жодної сторінки тексту: {', '.join(d.name for d in run_dirs)}")

    counted = bundle.tally(
        {d.name: {p.name: p.read_text(encoding="utf-8", errors="replace")
                  for p in sorted(d.glob(bundle.PACKED_TEXT))} for d in run_dirs},
        {v.run: v.model for v in voices})
    decode = {
        "pages": counted["pages"],
        "lines": counted["lines"],
        "chars": counted["chars"],
        "blank_pages": counted["blank_pages"],
        "voices": [v.as_json() for v in voices],
        # 🔴 Хеш ЗМІСТУ пакета — не той самий, що sha256 файла. Файл того
        # самого прогону, спакований двічі, має різні байти (час у маніфесті,
        # mtime у tar, час у gzip), тож за ним «це вже віддавали» не
        # впізнати. Зведений по всіх голосах, у порядку імен прогонів, щоб
        # порядок обходу тек на нього не впливав.
        "content_sha256": _content_of(voices),
    }
    frames_block: dict[str, Any] = (
        align.summary(frames) if frames
        else {"total": 0, "listed": 0, "with_sha256": 0, "with_apid": 0})
    # Відбиток зйомки: п'ять кадрів і два хеші на кожен. Коштує частку
    # секунди й ~30 МБ читання — на відміну від хешування всієї справи, від
    # якого відмовились саме через ціну. Саме він робить мітку `exact`
    # можливою для того, хто качав ту саму зйомку, але розбирав її своїм
    # інструментом.
    if case_dir is not None:
        got = fingerprint.fingerprint(case_dir)
        if fingerprint.checked(got):
            frames_block["fingerprint"] = got
    pub: dict[str, str] = {}
    if publisher:
        pub["handle"] = publisher
    if contact:
        pub["contact"] = contact
    if site:
        pub["url"] = site
    lic = {"text": license_text, "images": "не входять"}
    if source_terms:
        lic["source_terms"] = source_terms
    if not frames:
        frames_block = _znamennyk_z_pasporta(frames_block, home)
    if not frames_block.get("total") and key:
        # Паспорт мовчить, а бібліотека знає сторінки PDF — це й є кадри
        # справи, читаної з PDF. `listed` лишається нулем: зображень, до яких
        # прив'язувати текст, на диску немає.
        n = align.library_frames(key)
        if n > 0:
            frames_block = {**frames_block, "total": n, "on_disk": 0}
    case = _opys_z_progoniv(_normalize_shifra(_case_block(info, home), key), info)
    if archive_name.strip():
        # Архіву немає в довіднику — назву дає людина. Сервер покаже її на
        # картці, доки архів не з'явиться в довіднику пакета.
        case["repo_name"] = archive_name.strip()[:120]
    row = opys.registry_row(str(case.get("shifra") or ""))
    frames_block = _znamennyk(frames_block, row)
    # Паспорт мовчить або тримає робочу нотатку — назву й роки дає реєстр
    # опису: він вичитаний з друкованого опису фонду, а не складений нами.
    library = next((str(r.get("title") or "") for r in info.get("rows") or []
                    if r.get("title")), "")
    nazva = opys.title(str(case.get("title") or ""), row, library)
    if nazva:
        case["title"] = nazva
    else:
        case.pop("title", None)
    if not case.get("doc_type"):
        code, types = opys.genre(case, nazva)
        if code:
            case["doc_type"] = code
        if types:
            case["record_types"] = types
    if not nazva:
        # Опис фонду назви не має: краще «Сповідні розписи · Iampol'
        # (каталог FamilySearch)», ніж картка «без назви» — але лише з полів
        # цієї справи й з назвою джерела.
        from nyshporka.cases.register import read_sidecar

        side = read_sidecar(home) if home else {}
        nazva = (opys.catalog_title(row)
                 or opys.passport_title(side, str(case.get("doc_type") or "")))
        if nazva:
            case["title"] = nazva
            case["title_src"] = "catalog" if opys.catalog_title(row) else "pasport"
    if row and not case.get("years"):
        ry = opys.trusted_registry_years(row)
        if ry:
            case["years"] = ry
    # 🔴 Картка людини — ОСТАННЬОЮ, поверх усього зібраного: паспорт і
    # реєстр — здогад пакувальника, а задане руками — рішення.
    kartka = {**K.get(key), **(card_fields or {})}
    if kartka:
        case = K.apply(case, kartka)
        nazva = str(case.get("title") or "")
    if kartka.get("frames"):
        # Число, назване людиною, — з каталогу чи опису, — сильніше за будь-який
        # здогад. Але не менше, ніж кадрів справді лежить: тоді воно хибне.
        n = int(kartka["frames"])
        listed = int(frames_block.get("listed") or 0)
        if n >= listed:
            frames_block = {**frames_block, "total": n, "on_disk": listed}
    # Причина, з якої числа кадрів немає, живе в картці — щоб її бачило кожне
    # пакування цієї справи (пачкою, автовіддача), а не лише те, де її назвали.
    extra = dict(extra or {})
    if kartka.get("frames_unknown") and not extra.get(FRAMES_UNKNOWN):
        extra[FRAMES_UNKNOWN] = str(kartka["frames_unknown"])
    # Робочий запис паспорта про жанр (`record_type`) — вільний текст
    # дослідника, і в картку він іде лише очищеним, як і назва.
    if case.get("record_type"):
        clean_type = opys.clean_text(str(case["record_type"]))
        if clean_type:
            case["record_type"] = clean_type
        else:
            case.pop("record_type", None)
    described = opys.build(
        str(case.get("shifra") or ""), row=row,
        frames_total=int(frames_block.get("total") or 0),
        geometry_pages=_geometry_pages(run_dirs),
        text_pages=counted["pages"])
    if described:
        case["details"] = described
    m = Manifest(
        case=case,
        refs=_merge_refs(_refs_from_sidecar(home), _refs_from_links(list(links or []))),
        frames=frames_block, decode=decode, publisher=pub, note=note,
        links=_with_registry(list(links or []), str(case.get("shifra") or "")),
        extra=dict(extra or {}), license=lic,
        tool=bundle._tool_version(), created=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    details = {"skipped_runs": list(info.get("skipped_runs") or []),
               "card": kartka, "key": key}
    return m, run_dirs, frames, details


def _content_of(voices: list[bundle.Voice]) -> str:
    """Один хеш змісту на весь пакет — зведення хешів голосів.

    Голос без свого хеша (старий прогін, перепакований новим клієнтом)
    просто не бере участі: краще віддати хеш меншого набору, ніж вигадати
    його й отримати тихий «дубль» там, де його немає.
    """
    parts = sorted(v.content_sha256 for v in voices if v.content_sha256)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _geometry_pages(run_dirs: list[Path]) -> int:
    """Скільки сторінок має рамки рядків — у найповнішому голосі."""
    return max((sum(1 for _ in d.glob(bundle.PACKED_GEOMETRY)) for d in run_dirs),
               default=0)


#: Поле `extra` маніфесту: чому число кадрів справи невідоме.
FRAMES_UNKNOWN = "frames_unknown"


def _zbirna_teka(key: str, run_dirs: list[Path]) -> str:
    """Чому цю теку не можна спакувати однією справою; порожньо — можна."""
    from nyshporka.cases import span as SP

    names = [d.name for d in run_dirs]
    case_dir = align.case_dir_for(key) if key else None
    got = (SP.of_dir(case_dir, *names) if case_dir is not None
           else SP.of_passport({}, *names))
    if got is None:
        return ""
    return f"збірна тека: {got.why}. {SP.fix(str(case_dir or names[0]))}"


def pack(scope: str, dest: Path | None = None, *, geometry: bool = True,
         hash_frames: bool = False, partial_why: str = "",
         dry_run: bool = False, **meta: Any) -> dict[str, Any]:
    """Зібрати пакет справи. `dry_run` — показати, що поїде, і нічого не писати.

    Пишеться ДВА файли, коли геометрія є на диску: текстовий пакет і пакет
    геометрії поруч із ним. Це не два заходи для людини — вона й далі каже
    «спакуй справу», — а два об'єкти для пулу: текст качають усі, геометрію
    лише ті, у кого ті самі кадри.

    `geometry=False` лишає другий файл незібраним. Текстовий від цього не
    змінюється ні на байт, тож хеш змісту той самий і повторним внеском він
    не стане.
    """
    card_fields = meta.pop("card_fields", None) or {}
    remember = bool(meta.pop("remember_card", True))
    m, run_dirs, frames, details = build_manifest(
        scope, hash_frames=hash_frames, card_fields=card_fields, **meta)
    verdict = gates.check(m, partial_why=partial_why)
    sketch = bundle.plan(run_dirs)
    geom_dirs = [d for d in run_dirs if bundle.has_geometry(d)]
    geom_sketch = bundle.plan(geom_dirs, patterns=bundle.PACKED_GEOM) if geom_dirs else None
    out: dict[str, Any] = {
        "manifest": m.as_json(),
        "gates": verdict.as_json(),
        "runs": [d.name for d in run_dirs],
        # 🔴 Що лишилось удома і чому — завжди видно: проба чи замір, мовчки
        # викинуті з пакета, виглядали б як загублений голос.
        "skipped_runs": details["skipped_runs"],
        "card": details["card"],
        "files": len(sketch["files"]),
        "bytes_raw": sketch["bytes"],
        "frames_listed": len(frames),
        "geometry_on_disk": bool(geom_dirs),
        # Чи названо той опис: пул — завжди (офлайн), покажчик — лише в пробі,
        # бо це запит у мережу. Лише підказки, заливку вони не зупиняють.
        "opys_check": opys_check.check(m.case, network=dry_run),
    }
    # 🔴 Пакет без числа кадрів справи не збирається мовчки. Ворота його
    # пускають із попередженням (і пускатимуть: ними судить і пул, а старі
    # клієнти мусять заливати далі) — але отримувач такого пакета не відрізнить
    # прочитану справу від уривка. Тож той, хто пакує ЗАРАЗ, мусить або назвати
    # число, або сказати вголос, що його немає й чому (звіт користувача
    # 29.09.2026).
    bez_znamennyka = ""
    if m.frames_total <= 0 and not str(m.extra.get(FRAMES_UNKNOWN) or "").strip():
        bez_znamennyka = (
            "кадрів справи не названо — без цього числа отримувач не відрізнить "
            "прочитану справу від уривка. Назвіть його з каталогу чи опису: "
            "--frames N (або `nysh share card <справа> --frames N`). Якщо числа "
            "справді взяти нізвідки: --frames-unknown \"чому\"")
        out["pack_refusals"] = [bez_znamennyka]
    # 🔴 Збірна тека не пакується як одна справа: у каталог пулу поїхала б
    # шифра першої з кадрами й текстом усіх. Відмова тут, а не у воротах —
    # ворота імпортує пул, і теки на диску він не бачить.
    zbirna = _zbirna_teka(details.get("key") or "", run_dirs)
    if zbirna:
        out.setdefault("pack_refusals", []).append(zbirna)
    if dry_run:
        out["files_list"] = [f["arc"] for f in sketch["files"]]
        if geometry and geom_sketch:
            out["geom_files_list"] = [f["arc"] for f in geom_sketch["files"]]
            out["geom_bytes_raw"] = geom_sketch["bytes"]
        out["dry_run"] = True
        return out
    if not verdict.passed:
        raise PublishError("ворота не пропустили пакет:\n" + gates.describe(verdict))
    if bez_znamennyka:
        raise PublishError(bez_znamennyka)
    if zbirna:
        raise PublishError(zbirna)

    if card_fields and remember and details["key"]:
        # Задане на пакуванні живе й далі: наступне пакування (автовіддача,
        # `suggest --all`, дочитування новою моделлю) візьме ту саму картку.
        from nyshporka.share import card as K

        out["card_saved"] = K.set_fields(details["key"], card_fields)

    name = bundle.suggest_name(m)
    dest = Path(dest) if dest else (journal.share_dir() / journal.OUTBOX / name)
    if dest.is_dir():
        dest = dest / name
    wrote = bundle.write(dest, m, run_dirs, frames=frames)
    out.update(wrote)

    geom: dict[str, Any] | None = None
    if geometry and geom_dirs:
        # Той самий маніфест і той самий перелік кадрів: geom-пакет мусить
        # називати ту саму справу, інакше приймач не знає, до чого його класти.
        geom = bundle.write(bundle.geom_path(dest), m, geom_dirs, frames=frames,
                            patterns=bundle.PACKED_GEOM)
        out["geom"] = geom
    else:
        # 🔴 Geom-файл від ПОПЕРЕДНЬОГО пакування цієї справи лежить під тим
        # самим іменем і належить іншому тексту. Лишений тут, він поїхав би
        # у пул разом із новим текстом, і кроп різав би не ті рядки.
        stale = bundle.geom_path(dest)
        if stale.is_file():
            stale.unlink()
            out["geom_removed"] = str(stale)

    row = catalog.row_for(m, sha256=wrote["sha256"], nbytes=wrote["bytes"])
    out["catalog_row"] = row.as_tsv()
    out["catalog"] = row.as_json()
    journal.record(journal.PACKED, shifra=m.shifra,
                   case_key=str(m.case.get("key_local") or ""),
                   pages=m.pages, bytes=wrote["bytes"], sha256=wrote["sha256"],
                   path=wrote["path"], models=", ".join(m.models()),
                   geom_bytes=int(geom["bytes"]) if geom else 0)
    return out
