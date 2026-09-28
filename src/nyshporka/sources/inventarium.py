"""🏚 Інвентаріум (`inventarium.org.ua`) — покажчик маєткових інвентарів.

Волонтерська база: один рядок — одне село всередині справи, разом зі сторінкою,
з якої в справі починається його інвентар. Відповідає на питання, якого не
ставить жоден опис фонду: «в якій книзі лежить інвентар мого села і на якому
аркуші». Опис фонду називає книгу («Актова книга Житомирського гродського суду
1794 р.»), а що всередині неї на с. 295 записано інвентар Яроповичів, знає лише
людина, яка книгу прогорнула, — і тут це записано.

🔑 **Головна користь — сторінка.** Інвентар у гродській книзі займає десяток
аркушів із шестисот; знаючи сторінку, книгу не треба читати рушієм цілком, досить
пачки кадрів навколо неї.

🪤 **Нуль тут про волонтера, а не про архів.** База розписана нерівно: у справі
ЛННБ 5-1-4145/III внесено Струцівку, Криве, Липки, а Яроповичів — які йшли з
ними одним ключем — окремого рядка немає. Відсутність села означає «ніхто не
розписав», а не «інвентаря немає».

Доступ: сайт читає базу напряму з Supabase (PostgREST) публічним ключем, який
лежить у його ж JavaScript. Пакет бере адресу й ключ ЗВІДТИ ж під час обходу, а
не тримає їх у коді: ключ ротується, і зашитий перестав би працювати мовчки —
обхід упав би з 401, який читався б як «база закрилась».

🔴 У базі є поле `email` — пошта волонтерів, що вносили рядки. Воно не
запитується взагалі (`select=` перелічує поля явно), тож у знімок не потрапляє.

Адресація (`ref`): `inv:<uuid рядка>`.
"""
from __future__ import annotations

import base64
import binascii
import csv
import datetime as _dt
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.sources.base import Hit, SourceAbout, SourceError, SourceScope
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline
from nyshporka.utils.atomic import atomic_write_bytes
from nyshporka.utils.translit import normalize_for_matching

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

HOST = "https://inventarium.org.ua"
TABLE = "records"

#: Поля, які беремо. 🔴 Перелік явний: `select=*` приніс би й `email`,
#: `created_by` — пошту й ідентифікатор волонтера.
FIELDS = ("id", "approved", "old_province", "old_district", "old_settlement_name",
          "current_region", "current_district", "current_settlement_name",
          "latitude", "longitude", "case_signature", "additional_case_signature",
          "case_date", "inventory_year", "pages_count", "inventory_start_page",
          "case_title", "inventory_type", "scans_url", "notes")

#: Рядків на запит. Сервер віддає й 10 000, але тисяча — це 17 запитів на всю
#: базу з паузою між ними, а не два важкі.
PAGE = 1000

_SUPA = re.compile(r"https://([a-z0-9]{8,})\.supabase\.co")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_CHUNK = re.compile(r"""["'](/_next/static/chunks/[^"']+?\.js)["']""")
#: «ЦДІАК 2-1-171», «ЛННБ ім. Стефаника 5-1-4145/III», «ЦДІАК-2227-1-158».
_SIG = re.compile(r"^(.*?)[\s-]+([^\s-]+-[^\s-]+-\S+)$")
_TOTAL = re.compile(r"/(\d+)\s*$")


def _flat(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def _fold(s: str) -> str:
    return s.casefold().replace("ё", "е").replace("’", "'").replace("ʼ", "'")


def _num(s: object) -> str | None:
    """Перше число поля без провідних нулів: «4145/III» → «4145»."""
    m = re.search(r"\d+", str(s or ""))
    return str(int(m.group())) if m else None


def _url(value: object) -> str:
    """Посилання з чужої бази — лише http(s): рядок іде в `href` консолі."""
    s = _flat(value)
    return s if s.lower().startswith(("http://", "https://")) else ""


def split_signature(sig: str) -> tuple[str, str, str, str]:
    """Шифра бази → (архів, фонд, опис, справа). Нерозбірна — архів порожній.

    🔴 Розбирається лише форма «<архів> Ф-О-С». Польські й угорські шифри
    («AGAD ASK 1/7/0/9/4», «HU MNL OL, C 59 - …») лишаються як є: вгадати в
    них фонд означало б завести в зведення фонд, якого не існує.
    """
    m = _SIG.match(_flat(sig))
    if not m:
        return "", "", "", ""
    parts = m.group(2).split("-", 2)
    return m.group(1).strip(" ,"), parts[0], parts[1], parts[2]


def jwt_role(token: str) -> tuple[str, str]:
    """(role, ref) з тіла JWT без перевірки підпису — лише щоб не взяти чужий токен."""
    try:
        body = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (IndexError, ValueError, binascii.Error):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("role") or ""), str(data.get("ref") or "")


def find_credentials(scripts: list[str]) -> tuple[str, str] | None:
    """(адреса Supabase, anon-ключ) з тексту скриптів сайту.

    🔴 Береться лише ключ з `role=anon` і того самого проєкту, що й адреса.
    Скрипт може нести кілька токенів, і сервісний, взятий першим, був би вже
    не читанням публічних даних.
    """
    for text in scripts:
        for m in _SUPA.finditer(text):
            ref = m.group(1)
            for tok in _JWT.findall(text):
                role, tok_ref = jwt_role(tok)
                if role == "anon" and tok_ref == ref:
                    return f"https://{ref}.supabase.co", tok
    return None


def row_of(rec: dict[str, Any]) -> dict[str, str]:
    """Запис бази → рядок знімка. Список додаткових шифр — через « | »."""
    out: dict[str, str] = {}
    for f in FIELDS:
        v = rec.get(f)
        if isinstance(v, list):
            v = " | ".join(_flat(x) for x in v if _flat(x))
        elif isinstance(v, bool):
            v = "1" if v else "0"
        out[f] = _flat(v)
    return out


@lru_cache(maxsize=2)
def _load(path: Path, mtime_ns: int, size: int) -> tuple[tuple[dict[str, str], str, str], ...]:
    """Рядки знімка з двома формами назв для збігу. Ключ — штамп файлу."""
    _ = (mtime_ns, size)
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    out = []
    for r in rows:
        hay = " ".join((r.get("old_settlement_name", ""), r.get("current_settlement_name", ""),
                        r.get("case_title", "")))
        out.append((r, _fold(hay), normalize_for_matching(hay)))
    return tuple(out)


class InventariumSource:
    """Покажчик маєткових інвентарів за селом і за шифрою справи."""

    id = "inventarium"
    label = "Інвентаріум (маєткові інвентарі за селом)"
    caps = frozenset({"search", "address"})
    about = SourceAbout(
        answers="в якій справі лежить інвентар мого села і з якої сторінки",
        gives="село (стара й сучасна назва), шифру справи, рік, сторінку початку "
              "інвентаря, обсяг справи, тип документа й посилання на скани",
        not_gives="тексту інвентаря; сіл, яких волонтер не розписав; справ без інвентарів",
        where_class="маєткові інвентарі",
        # Заміряно по знімку 28.09.2026: 16 355 рядків, роки 1494-1916; інвентарі
        # 12 220, фасії 2 868, люстрації 803, урбарії 463.
        scope=SourceScope(years=(1494, 1916),
                          note="переважно ЦДІАЛ, ЛННБ, ЦДІАК, AGAD, ANK, MNL; "
                               "інвентарі, фасії, люстрації, урбарії"),
        match_on=("settlement", "title"), match_how="normalized",
        zero_means="у знімку (дата в `basis`) немає рядка з цією назвою села ні в "
                   "старій, ні в сучасній формі, ні в заголовку справи; справа може "
                   "містити інвентар села без окремого рядка",
        pitfalls=("без знімка відмовляє: зібрати `nysh crawl inventarium`",
                  "маєтковий ключ названо за власником або головним селом — "
                  "шукати й за сусідами по ключу",
                  "сторінка — з розпису волонтера, з кадром не звірена",
                  "рік буває століттям («XVIII ст.»)"))

    SNAP_REL = Path("data") / "raw" / "inventarium" / "_crawl" / "records.tsv"
    STATE_REL = Path("data") / "raw" / "inventarium" / "_crawl" / "state.json"

    NO_CATALOG = (
        "знімка Інвентаріуму в просторі немає — нуль звідси нічого б не означав. "
        "Зібрати: `nysh crawl inventarium` (≈17 запитів, уся база).")

    def __init__(self, workspace: Path | None = None, *,
                 site: Fetcher | None = None, api: Fetcher | None = None) -> None:
        """`site` і `api` — два хости: сторінки сайту й PostgREST бази. Обидва
        підставляються в тестах."""
        self.workspace = Path(workspace) if workspace else None
        self._site = site
        self._api = api

    # ── знімок ───────────────────────────────────────────────────────────────

    @property
    def snap_path(self) -> Path | None:
        return (self.workspace / self.SNAP_REL) if self.workspace else None

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        path = self.snap_path
        if path is None or not path.is_file():
            return "none", {}
        st = path.stat()
        state = self._read_state()
        return "workspace", {
            "path": str(path),
            "rows": len(_load(path, st.st_mtime_ns, st.st_size)),
            "taken": state.get("taken") or _dt.date.fromtimestamp(st.st_mtime).isoformat(),
            "scope": "маєткові інвентарі за селом"}

    def _rows(self) -> tuple[tuple[dict[str, str], str, str], ...]:
        kind, info = self.catalog_source()
        if kind == "none":
            raise SourceError(self.NO_CATALOG)
        path = Path(info["path"])
        st = path.stat()
        return _load(path, st.st_mtime_ns, st.st_size)

    def _read_state(self) -> dict[str, Any]:
        if self.workspace is None:
            return {}
        try:
            data = json.loads((self.workspace / self.STATE_REL).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    # ── пошук ────────────────────────────────────────────────────────────────

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Рядки, де є ВСІ слова запиту — у старій чи сучасній назві села або в
        заголовку справи. Збіг — підрядок, як є або після нормалізації («Яроповичи»
        знаходить «Яроповичі»). ⚠ Латинку з кирилицею нормалізація не зводить
        («Jaropowicze» → нуль): польську назву шукати й українською.

        🔴 Кількість збігів їде в примітку, коли видачу обрізано.
        """
        words = _flat(q).split()
        if not words:
            return []
        rows = self._rows()
        folded = [_fold(w) for w in words]
        normed = [normalize_for_matching(w) for w in words]
        found = [r for r, t_fold, t_norm in rows
                 if all(f in t_fold or (n and n in t_norm)
                        for f, n in zip(folded, normed, strict=True))]
        taken = self.catalog_source()[1].get("taken") or ""
        tail = f" · з {len(found)} за запитом" if len(found) > limit else ""
        return [self._hit(r, taken, tail) for r in found[:limit]]

    def find_case(self, fond: str, opys: str, spr: str, *, repo: str = "") -> list[Hit]:
        """Усі розписані інвентарі справи — за основною й додатковими шифрами,
        за сторінкою. Відповідь на «які села лежать у цій книзі і з якого аркуша».

        ⚠ Номер справи порівнюється числом: «4145/III» і «4145/II» — різні
        томи, тож суфікс після числа мусить збігтися, якщо його задано.
        """
        want = (_num(fond), _num(opys), _num(spr))
        if None in want:
            return []
        want_tail = str(spr).strip().casefold()
        taken = self.catalog_source()[1].get("taken") or ""
        out: list[tuple[int, Hit]] = []
        for r, _f, _n in self._rows():
            sigs = [r.get("case_signature", "")] + \
                   [s for s in (r.get("additional_case_signature") or "").split(" | ") if s]
            for sig in sigs:
                arch, f, o, s = split_signature(sig)
                if not arch or (_num(f), _num(o), _num(s)) != want:
                    continue
                if not want_tail.isdigit() and s.casefold() != want_tail:
                    continue
                if repo and self._our_repo(arch) != repo.upper():
                    continue
                page = _num(r.get("inventory_start_page"))
                out.append((int(page) if page else 10**9, self._hit(r, taken, "")))
                break
        out.sort(key=lambda p: p[0])
        return [h for _p, h in out]

    @staticmethod
    def _our_repo(archive: str) -> str:
        """«ЦДІАК» → `CDIAK` через пак; незнайомий архів — порожньо, не здогад."""
        from nyshporka.archives import active

        pk = active()
        code = pk.resolve_code(_flat(archive))
        return pk.canon_repo(code) if code else ""

    def _hit(self, r: dict[str, str], taken: str, tail: str) -> Hit:
        sig = r.get("case_signature", "")
        arch, fond, _o, _s = split_signature(sig)
        old = r.get("old_settlement_name", "")
        cur = r.get("current_settlement_name", "")
        place = " · ".join(x for x in (
            old, f"тепер {cur}" if cur and _fold(cur) != _fold(old) else "",
            r.get("current_district", ""), r.get("current_region", "")) if x)
        page = _num(r.get("inventory_start_page"))
        years = r.get("inventory_year") or r.get("case_date", "")
        note = " · ".join(x for x in (
            r.get("inventory_type", ""),
            f"с. {r.get('inventory_start_page')}" if r.get("inventory_start_page") else "",
            f"у справі {r.get('pages_count')} с." if r.get("pages_count") else "",
            "⚠ не затверджено модератором" if r.get("approved") == "0" else "",
            f"знімок від {taken}" if taken else "") if x)
        return Hit(
            source=self.id, ref=f"inv:{r.get('id', '')}",
            title=(r.get("case_title") or "")[:200], years=years, place=place,
            shifra=sig, repo=self._our_repo(arch) if arch else "", archive=arch,
            fond=fond, page=int(page) if page else None,
            # Скани лежать у FamilySearch, szukajwarchiwach тощо — качає інше
            # джерело; тут лише адреса.
            acquirable=False, url=_url(r.get("scans_url")), note=(note + tail).strip(" ·"))

    # ── обхід ────────────────────────────────────────────────────────────────

    def _site_http(self) -> Fetcher:
        return self._site or Fetcher(base=HOST, headers={"User-Agent": app_ua()})

    def credentials(self) -> tuple[str, str]:
        """Адреса й публічний ключ бази — зі скриптів самого сайту."""
        http = self._site_http()
        try:
            home = str(http.get("/").text)
            chunks = sorted(set(_CHUNK.findall(home)))
            texts = [home]
            for path in chunks:
                texts.append(str(http.get(path).text))
                got = find_credentials(texts)
                if got:
                    return got
        except (HttpError, OSError) as exc:
            raise SourceError(f"сайт Інвентаріуму не відповів: {exc}") from exc
        raise SourceError(
            f"у скриптах сайту ({len(chunks)} файлів) не знайшлось адреси Supabase з "
            f"публічним ключем — сайт змінив спосіб доступу до бази, обхід треба "
            f"переписати")

    def crawl(self, groups: tuple[str, ...] | None = None, *,
              on_progress: ProgressFn | None = None,
              resume: bool = True) -> dict[str, Any]:
        """Забрати базу цілком у знімок простору.

        `groups` і `resume` не мають сенсу: база — 17 запитів, і обірваний обхід
        дешевше повторити, ніж зшивати (порядок рядків між запусками може
        змінитись, коли волонтери додають нові).

        🔴 Приймач — число рядків проти `Content-Range` самого сервера. Якщо не
        зійшлось, знімок НЕ пишеться: неповна база виглядала б як повна, і нуль
        пошуку по ній читався б як «волонтери не розписали».
        """
        _ = (groups, resume)
        if self.workspace is None:
            raise SourceError("для обходу потрібен робочий простір — знімок лягає в нього")
        if offline() and self._api is None:
            raise SourceError("мережу вимкнено в цьому середовищі — базу не опитано")
        base, key = self.credentials()
        api = self._api or Fetcher(base=f"{base}/rest/v1", headers={
            "User-Agent": app_ua(), "apikey": key, "Authorization": f"Bearer {key}",
            "Prefer": "count=exact"})
        select = ",".join(FIELDS)
        recs: list[dict[str, Any]] = []
        total: int | None = None
        offset = 0
        while True:
            try:
                r = api.get(f"/{TABLE}?select={select}&order=id&limit={PAGE}&offset={offset}")
                batch = json.loads(str(r.text or "[]"))
            except (HttpError, OSError) as exc:
                raise SourceError(f"база Інвентаріуму не відповіла: {exc}") from exc
            except ValueError:
                raise SourceError("база відповіла не JSON — адреса запиту змінилась") from None
            m = _TOTAL.search(str(r.headers.get("content-range") or ""))
            if m:
                total = int(m.group(1))
            if not isinstance(batch, list) or not batch:
                break
            recs += [x for x in batch if isinstance(x, dict)]
            offset += len(batch)
            if on_progress:
                on_progress(done=len(recs), total=total or 0, unit="рядок")
            if total is not None and offset >= total:
                break
        if total is None:
            raise SourceError("сервер не назвав загальне число рядків (Content-Range) — "
                              "повноту знімка довести нічим, знімок не записано")
        ids = {str(x.get("id")) for x in recs}
        if len(recs) != total or len(ids) != total:
            raise SourceError(
                f"зібрано {len(recs)} рядків ({len(ids)} різних), а сервер каже {total} — "
                f"база змінилась під час обходу або обрізає видачу; знімок не записано")
        rows = sorted((row_of(x) for x in recs), key=lambda d: d["id"])
        import io

        buf = io.StringIO(newline="")
        w = csv.DictWriter(buf, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        atomic_write_bytes(self.workspace / self.SNAP_REL, buf.getvalue().encode("utf-8"))
        taken = _dt.date.today().isoformat()
        atomic_write_bytes(self.workspace / self.STATE_REL, json.dumps(
            {"taken": taken, "rows": total, "api": base}, ensure_ascii=False).encode("utf-8"))
        cases = {r["case_signature"] for r in rows if r["case_signature"]}
        return {"summary": f"рядків {total} · справ {len(cases)} · знімок від {taken}",
                "rows": total, "cases": len(cases)}
