"""📤 Зібрати свій декод у пакет: від шифри до файлу й рядка каталогу.

Порядок тут не випадковий: спершу збираємо ЗАЯВУ (що це за справа, скільки
кадрів, чим читали), проганяємо її крізь ворота — і лише тоді пишемо файл.
Зворотний порядок (зібрати, потім перевірити) залишає на диску пакет, який не
можна віддавати, і рано чи пізно хтось його однаково віддасть.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from nyshporka.share import align, bundle, catalog, fingerprint, gates, journal, opys
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
    dirs, skipped = choose_voices(dirs, str(got.get("key") or ""), skip=skip)
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
                  skip: tuple[str, ...] | list[str] = ()) -> tuple[list[Path], list[dict[str, str]]]:
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
    """
    from nyshporka import htr_store as S

    skipped: list[dict[str, str]] = []
    keep: list[tuple[Path, dict[str, Any], set[str]]] = []
    want = S._canon_case_key(key) if key else ""
    skip_set = {str(s).strip() for s in skip if str(s).strip()}
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
        own = str(meta.get("case_key") or "")
        if want and own and S._canon_case_key(own) != want:
            skipped.append({"run": d.name,
                            "why": f"прогін іншої справи ({own})"})
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
    raw_years = [side.get("year_from"), side.get("year_to")]
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


def _refs_from_sidecar(case_dir: Path | None) -> list[dict[str, str]]:
    """Стабільні посилання на джерело зйомки — єдине, що не залежить від нас.

    Ключ справи в кожного свій, а `File:…` у Commons або DGS у FamilySearch
    однакові для всіх. Саме за ними отримувач знайде ті самі аркуші.
    """
    from nyshporka.cases.register import read_sidecar

    if case_dir is None:
        return []
    side = read_sidecar(case_dir)
    out: list[dict[str, str]] = []

    def add(source: str, ref: str, url: str = "") -> None:
        if ref and not any(r["source"] == source for r in out):
            row = {"source": source, "ref": ref}
            if url:
                row["url"] = url
            out.append(row)

    if side.get("dgs") or side.get("fs_film") or side.get("film"):
        ident = side.get("dgs") or side.get("fs_film") or side.get("film")
        add("fs", f"dgs:{ident}" if side.get("dgs") else f"film:{ident}",
            str(side.get("fsfiles_url") or side.get("base_url") or ""))
    if side.get("commons_title"):
        add("commons", f"file:{side['commons_title']}",
            str(side.get("commons_url") or ""))
    if side.get("viewer_id"):
        add("archium", f"file:{side['viewer_id']}",
            str(side.get("viewer_url") or ""))
    if side.get("babynyar_case"):
        add("babynyar", f"case:{side['babynyar_case']}",
            str(side.get("babynyar_url") or ""))
    for key in ("source_url", "duck_url"):
        if side.get(key):
            add("url", str(side[key]), str(side[key]))
            break
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
    case = _normalize_shifra(_case_block(info, case_dir), key)
    if archive_name.strip():
        # Архіву немає в довіднику — назву дає людина. Сервер покаже її на
        # картці, доки архів не з'явиться в довіднику пакета.
        case["repo_name"] = archive_name.strip()[:120]
    row = opys.registry_row(str(case.get("shifra") or ""))
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
    if row and not case.get("years"):
        ry = [int(row[k]) for k in ("year_from", "year_to")
              if str(row.get(k) or "").isdigit()]
        if ry:
            case["years"] = [min(ry), max(ry)]
    # 🔴 Картка людини — ОСТАННЬОЮ, поверх усього зібраного: паспорт і
    # реєстр — здогад пакувальника, а задане руками — рішення.
    kartka = {**K.get(key), **(card_fields or {})}
    if kartka:
        case = K.apply(case, kartka)
        nazva = str(case.get("title") or "")
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
        case=case, refs=_refs_from_sidecar(case_dir),
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
    }
    if dry_run:
        out["files_list"] = [f["arc"] for f in sketch["files"]]
        if geometry and geom_sketch:
            out["geom_files_list"] = [f["arc"] for f in geom_sketch["files"]]
            out["geom_bytes_raw"] = geom_sketch["bytes"]
        out["dry_run"] = True
        return out
    if not verdict.passed:
        raise PublishError("ворота не пропустили пакет:\n" + gates.describe(verdict))

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
