"""✍️ Черга розмітки: що показати людині і в якому порядку.

Ручна мітка — найдорожче, що є в конвеєрі: хвилина ока на рядок. Тому черга
ранжується не «як лежить», а **розбіжністю голосів**: там, де рушії прочитали
по-різному, людина дає найбільше нового знання; там, де вони згодні, машина
вже вміє — і такі рядки чекають у хвості.

Дві поправки, без яких рейтинг брехав (виміряно в дослідницькому конвеєрі):
**вага довжини** — інакше «2 2» проти «2» дає 67 балів і однознакові уламки
очолюють чергу; **штраф за дегенерацію** — луп-рядки («~~~~~~») максимально
розходяться між моделями і теж лізли вгору.

Режими: `spread` (дефолт — ПО КОЛУ блоками по 6 із різних сторінок: модель,
навчена на одному писарі, вміє читати одного писаря), `useful` (сторінки за
середньою розбіжністю, всередині підряд), `page`, `sequential`, `names`
(лише рядки, що ймовірно несуть власну назву, — для валідаційного набору).

Порожні кропи сховані за замовчуванням: усі голоси мовчать або чорнила на
смужці менше `gate.INK_MIN`. Їх близько третини, і вони з'їли б час ока
задарма. Набір без жодного голосу дає чергу цілком — інакше свіжа нарізка
виглядала б як «нема чого розмічати».
"""
from __future__ import annotations

import base64
import io
import re
import statistics
from collections import Counter
from typing import Any

from rapidfuzz.distance import Levenshtein

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import gate as G
from nyshporka.train import sets as S
from nyshporka.utils.atomic import read_json, write_json

MIN_CHARS = 2          # коротші голоси не варті людського часу
SPREAD_BLOCK = 6
PAGEVIEW_DIR = "_pageview"
_CROP_RE = re.compile(r"^line_(\d+)\.png$")

#: Слова синодального формуляра. Рядок, що складається ПЕРЕВАЖНО з них, не
#: вартий людського часу: він повторюється на кожному аркуші, модель його і
#: так вивчила. 🔴 Рішення ухвалюється за ЧАСТКОЮ, а не «містить → відкинути».
_FORMULA = {
    "счетъ", "счет", "мѣсяцъ", "месяцъ", "день", "дня", "лѣта", "лета",
    "званіе", "звание", "имя", "отчество", "фамилія", "фамилия",
    "родившихся", "умершихъ", "умершаго", "бракомъ", "сочетавшихся",
    "воспріемники", "восприемники", "кто", "совершалъ", "таинство",
    "крещенія", "крещения", "погребенія", "погребения", "часть", "первая",
    "вторая", "третья", "третія", "поселяне", "домашніе", "домашние",
    "число", "людей", "показаніе", "дѣйства", "исповѣди", "причастія",
    "итого", "всего", "мужеска", "женска", "пола", "отъ", "чего", "умеръ",
    "исповѣдывалъ", "пріобщалъ", "гдѣ", "погребенъ", "книга", "метрическая",
    "метричная", "года", "годъ", "рожденія", "рождения", "и", "въ", "в",
    "на", "о", "а", "не", "его", "ея", "ихъ", "были", "былъ", "была",
    "данная", "губерніи", "губернии", "епархіи", "епархии", "консисторіи",
    "вѣдомость", "ведомость", "исповѣдная", "роспись", "метрической",
    "преставился", "преставилась", "преставися", "христіянской", "христіанской",
    "погребенна", "погребенная", "погребення", "покаяніи", "покаяній",
}

#: Корені хрестильних імен — найдешевший непрямий сигнал «тут є власна назва».
#: Корені, а не повні форми: рушій калічить закінчення сильніше за основу.
_GIVEN = (
    "иван", "іоан", "иоан", "мар", "ѳеод", "феод", "григор", "васил",
    "никол", "петр", "павел", "анн", "параск", "евдок", "стеф", "симеон",
    "михаил", "александ", "андре", "димитр", "яков", "іаков", "ксен",
    "агаф", "татіан", "татьян", "елен", "екатерин", "софі", "анастас",
    "матрон", "ирин", "домник", "лаврент", "архип", "тимоф", "захар",
    "кирил", "даніил", "антон", "максим", "роман", "трифон", "филип",
    "гавр", "онисим", "евстаф", "марѳ", "марф", "пелаг", "уліан", "улиан",
    "мелан", "варвар", "наталі", "дарі", "иустин", "ефросин", "евфросин",
    "феврон", "агрипин", "христин", "лук", "серг", "прокоп", "игнат",
)
#: 🔴 Корінь шукається лише НА ПОЧАТКУ слова: без цього «Данная» у титулі
#: ловилось як ім'я через «анн» усередині, і титул ішов у чергу першим.
_GIVEN_RE = re.compile(r"\b(?:" + "|".join(_GIVEN) + r")", re.IGNORECASE)
_SURNAME_TAIL = re.compile(
    r"(ск|цк|шк|жк)(ій|ий|аго|ого|ая|ой)"
    r"|(ов|ев|ёв|инъ|ынъ|ин|ын)ъ?\b"
    r"|(енко|чукъ|чук|укъ|юкъ|ичъ|ича|ова|ева|ская|цкая|акъ|якъ)\b",
    re.IGNORECASE)
#: Коротше — графа лічильника, обрізок шапки або огризок сегментації.
NAME_MIN_LEN = 18
#: Сторінки з меншим числом рядків у режимі `names` пропускаються: титул,
#: порожній аркуш — актів там немає.
NAME_MIN_PAGE_LINES = 20
#: Скільки разів той самий за змістом рядок показати: причт підписується
#: під КОЖНИМ актом однаково. Два — другий дає перехресну перевірку.
NAME_DUP_LIMIT = 2
NAME_DUP_SIM = 82


def degenerate(s: str) -> bool:
    """Ознака зациклення декодера: «поряціI ~~~~~~~~~~~~»."""
    t = re.sub(r"\s+", "", s)
    if len(t) < 6:
        return False
    if re.search(r"(.)\1{5,}", t):
        return True
    return max(Counter(t).values()) / len(t) > 0.35


def usefulness(drafts: list[str]) -> float:
    """0..100 — наскільки рядок вартий людського часу (розбіжність × довжина)."""
    real = [d for d in drafts if d and len(d) >= MIN_CHARS]
    if not real:
        return 0.0
    longest = max(len(d) for d in real)
    weight = min(1.0, longest / 20.0)
    if any(degenerate(d) for d in real):
        weight *= 0.25
    if len(real) < 2:
        return round(50.0 * weight, 1)
    sims = [Levenshtein.normalized_similarity(real[0], d) * 100 for d in real[1:]]
    return round((100 - min(sims)) * weight, 1)


def name_score(drafts: list[str]) -> float:
    """0..100 — наскільки ймовірно, що рядок несе ВЛАСНУ НАЗВУ. Нуль = не показувати."""
    real = [d.strip() for d in drafts if d and d.strip()]
    if not real:
        return 0.0
    longest = max(real, key=len)
    n = len(longest)
    if n < NAME_MIN_LEN or sum(c.isdigit() for c in longest) / n > 0.4:
        return 0.0
    if any(degenerate(d) for d in real):
        return 0.0
    low = longest.lower()
    has_given = bool(_GIVEN_RE.search(low))
    # Формульність — по МАКСИМУМУ серед голосів: довший голос зазвичай
    # найспотвореніший і обходить стоп-словник. Якщо ХОЧ ОДНА модель бачить
    # тут формуляр, це формуляр.
    formulaic = 0.0
    for d in real:
        ws = [w for w in re.split(r"[^\wЀ-ӿѐ-џ]+", d.lower()) if w]
        if ws:
            formulaic = max(formulaic, sum(1 for w in ws if w in _FORMULA) / len(ws))
    # Ім'я скасовує вирок за формульність: «сынъ Григорій преставился…» —
    # формула, але ім'я СТОЇТЬ У НІЙ, і прочитати його — прочитати акт.
    if formulaic > 0.6 and not has_given:
        return 0.0
    score = 30.0
    if _SURNAME_TAIL.search(low):
        score += 25.0
    if has_given:
        score += 25.0
    score += 20.0 * min(1.0, max(0, n - NAME_MIN_LEN) / 30.0)
    return round(score, 1)


def dedupe_similar(items: list[dict[str, Any]], limit: int = NAME_DUP_LIMIT,
                   thresh: int = NAME_DUP_SIM) -> list[dict[str, Any]]:
    """Не більше `limit` рядків одного змісту; порівняння нечітке по голосах."""
    kept: list[tuple[str, list[int]]] = []
    out: list[dict[str, Any]] = []
    for it in items:
        cand = max((d for d in it.get("drafts", []) if d), key=len, default="")
        if not cand:
            continue
        hit = None
        for k, (ref, _) in enumerate(kept):
            if Levenshtein.normalized_similarity(ref.lower(), cand.lower()) * 100 >= thresh:
                hit = k
                break
        if hit is None:
            kept.append((cand, [len(out)]))
            out.append(it)
        elif len(kept[hit][1]) < limit:
            kept[hit][1].append(len(out))
            out.append(it)
    return out


def draft_label(draft_id: str) -> str:
    """Людська назва голосу; злиття арбітрів підписується окремо."""
    if draft_id == S.MERGE_ID:
        return "Злиття"
    return draft_id.replace("draft_", "")


class Store:
    """Один набір: кропи, голоси, мітки — усе, що потрібно вкладці."""

    def __init__(self, name: str, *, ws: Workspace | None = None) -> None:
        self.ws = ws if ws is not None else workspace()
        self.reg = S.registry(self.ws)
        self.name = name
        self.spec = self.reg.load(name)
        self._pages: dict[str, list[int]] | None = None
        self._drafts: dict[str, dict[int, list[str]]] = {}
        self._ink: dict[str, float] | None = None

    # -- кропи --
    def pages(self) -> dict[str, list[int]]:
        """{сторінка: [індекси кропів]} — з диска."""
        if self._pages is None:
            root = self.reg.crops_of(self.spec)
            out: dict[str, list[int]] = {}
            if root.is_dir():
                for d in sorted(p for p in root.iterdir() if p.is_dir()
                                and not p.name.startswith("_")):
                    idxs = [int(m.group(1)) for f in d.iterdir()
                            if (m := _CROP_RE.match(f.name))]
                    if idxs:
                        out[d.name] = sorted(idxs)
            self._pages = out
        return self._pages

    # -- голоси --
    def draft_ids(self) -> list[str]:
        return [d.id for d in self.spec.drafts]

    def draft_labels(self) -> list[str]:
        return [draft_label(d.id) for d in self.spec.drafts]

    def drafts(self, page: str) -> dict[int, list[str]]:
        """{idx: [голос_1, голос_2, …]} — позиція = номер джерела в `drafts`.

        🔴 Відсутнє джерело лишає на своєму місці порожній рядок: інакше
        підписи з'їжджали б на сторінках, де є не всі голоси (нормальний
        стан набору, бо злиття робиться батчами по кілька сторінок).
        """
        if page in self._drafts:
            return self._drafts[page]
        srcs = self.spec.drafts
        out: dict[int, list[str]] = {}
        for pos, d in enumerate(srcs):
            lines = self.reg.draft_lines(self.spec, d, page) or []
            for i, line in enumerate(lines):
                row = out.setdefault(i, [""] * len(srcs))
                row[pos] = line.strip()
        self._drafts[page] = out
        return out

    def has_drafts(self) -> bool:
        return any(self.reg.draft_lines(self.spec, d, pg) is not None
                   for d in self.spec.drafts for pg in list(self.pages())[:3])

    # -- чорнило --
    def _ink_cache(self) -> dict[str, float]:
        if self._ink is None:
            got = read_json(self.reg.set_dir(self.name) / PAGEVIEW_DIR / "_ink.json",
                            default={})
            self._ink = dict(got) if isinstance(got, dict) else {}
        return self._ink

    def ink(self, page: str, idx: int) -> float | None:
        key = f"{page}:{idx}"
        cache = self._ink_cache()
        if key in cache:
            return float(cache[key])
        p = self.reg.crop_path(self.spec, page, idx)
        if p is None:
            return None
        v = G.ink_fraction(p)
        cache[key] = v
        return v

    def _flush_ink(self) -> None:
        if self._ink:
            write_json(self.reg.set_dir(self.name) / PAGEVIEW_DIR / "_ink.json", self._ink)

    # -- черга --
    def queue(self, mode: str = "spread", page: str = "", limit: int = 400,
              include_blank: bool = False) -> dict[str, Any]:
        pages = self.pages()
        if not pages:
            raise S.SetError(f"у наборі «{self.name}» немає кропів — спершу `nysh train cut`")
        done = self.reg.marks(self.name)
        no_drafts = not self.spec.drafts or not self.has_drafts()

        def items_of(pg: str) -> list[dict[str, Any]]:
            drafts = self.drafts(pg)
            out = []
            for i in pages[pg]:
                if (pg, i) in done:
                    continue
                d = drafts.get(i, [""] * len(self.spec.drafts))
                best = next((x for x in d if x), "")
                if not include_blank and not no_drafts:
                    if not any(len(x.strip()) >= MIN_CHARS for x in d):
                        continue
                    ink = self.ink(pg, i)
                    if ink is not None and ink < G.INK_MIN:
                        continue
                out.append({"page": pg, "idx": i, "draft": best, "drafts": d,
                            "score": usefulness(d)})
            return out

        items: list[dict[str, Any]]
        if mode == "names":
            buckets = []
            for pg in sorted(pages):
                if len(pages[pg]) < NAME_MIN_PAGE_LINES:
                    continue
                b = []
                for it in items_of(pg):
                    ns = name_score(it["drafts"])
                    if ns <= 0:
                        continue
                    it["score"] = ns
                    b.append(it)
                if b:
                    b.sort(key=lambda x: -x["score"])
                    buckets.append(b)
            items, off = [], 0
            # Усередині аркуша — за балом, але МІЖ аркушами по колу: глобальне
            # сортування витісняє незручні почерки, а їх вимірювач не пробачає.
            while buckets:
                for b in list(buckets):
                    if off >= len(b):
                        buckets.remove(b)
                        continue
                    items.append(b[off])
                off += 1
            items = dedupe_similar(items)
        elif mode == "spread":
            buckets = [b for b in (items_of(pg) for pg in sorted(pages)) if b]
            buckets.sort(key=lambda b: -sum(x["score"] for x in b) / len(b))
            items, off = [], 0
            while buckets and len(items) < limit:
                for b in list(buckets):
                    chunk = b[off:off + SPREAD_BLOCK]
                    if not chunk:
                        buckets.remove(b)
                        continue
                    items.extend(chunk)
                off += SPREAD_BLOCK
        elif mode == "page" and page:
            items = items_of(page)
        else:
            order = sorted(pages)
            if mode == "useful":
                scored = []
                for pg in order:
                    its = items_of(pg)
                    if its:
                        scored.append((sum(x["score"] for x in its) / len(its), pg))
                order = [pg for _, pg in sorted(scored, key=lambda t: -t[0])]
            items = []
            for pg in order:
                items.extend(items_of(pg))
                if len(items) >= limit:
                    break
        self._flush_ink()
        return {"items": items[:limit], "mode": mode,
                "draft_srcs": self.draft_labels(), "draft_ids": self.draft_ids(),
                "n_pages": len(pages),
                "n_total": sum(len(v) for v in pages.values()),
                "n_queue": len(items), "n_done": len(done)}

    # -- один рядок --
    def context(self, page: str, idx: int, span: int = 2) -> list[dict[str, Any]]:
        pages = self.pages()
        if page not in pages:
            return []
        done = self.reg.marks(self.name)
        drafts = self.drafts(page)
        avail = pages[page]
        try:
            pos = avail.index(int(idx))
        except ValueError:
            return []
        out = []
        for j in range(max(0, pos - span), min(len(avail), pos + span + 1)):
            i = avail[j]
            rec = done.get((page, i))
            d = drafts.get(i, [])
            out.append({"idx": i, "cur": i == int(idx),
                        "text": (rec or {}).get("text", ""),
                        "status": (rec or {}).get("status", ""),
                        "draft": next((x for x in d if x), "")})
        return out

    def line(self, page: str, idx: int, span: int = 2) -> dict[str, Any]:
        p = self.reg.crop_path(self.spec, page, idx)
        if p is None:
            raise S.SetError(f"кропа {page}:{idx} немає в наборі «{self.name}»")
        png = p.read_bytes()
        d = self.drafts(page).get(idx, [""] * len(self.spec.drafts))
        saved = self.reg.marks(self.name).get((page, int(idx)))
        return {"page": page, "idx": int(idx),
                "image": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
                "context": self.context(page, idx, span),
                "drafts": d, "draft_srcs": self.draft_labels(),
                "draft_ids": self.draft_ids(), "saved": saved}

    # -- сторінка --
    def page_image(self, page: str, max_px: int = 1800) -> dict[str, Any]:
        """Зменшена сторінка з рамками рядків.

        Скани — 4000×3000 і мегабайти; віддавати як є означає секунди на
        кожен рядок, а розмітка живе на швидкості. Зменшене кешується під
        набором (`_pageview/`) — регенерований кеш, не незамінне.
        """
        from PIL import Image

        pg_meta = (self.reg.cut_meta(self.spec).get("pages") or {}).get(page) or {}
        boxes = {str(i): [int(v) for v in b[:4]]
                 for i, b in enumerate(pg_meta.get("boxes") or []) if b}
        max_px = max(600, min(4000, int(max_px)))
        cache = self.reg.set_dir(self.name) / PAGEVIEW_DIR / f"{page}_{max_px}.jpg"
        size = pg_meta.get("size")
        if not cache.is_file():
            from nyshporka.htr import view as V
            from nyshporka.train.cut import image_key

            im = V._page_image(self.spec.source_run, image_key(pg_meta, page)).convert("RGB")
            size = size or [im.width, im.height]
            if max(im.size) > max_px:
                k = max_px / max(im.size)
                im = im.resize((int(im.width * k), int(im.height * k)),
                               Image.Resampling.LANCZOS)
            cache.parent.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82, optimize=True)
            cache.write_bytes(buf.getvalue())
        data = cache.read_bytes()
        return {"page": page, "size": size, "boxes": boxes,
                "image": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")}

    # -- мітки --
    def save(self, page: str, idx: int, text: str, status: str, *, kind: str = "hand",
             draft: str = "", secs: float = 0.0) -> dict[str, Any]:
        return self.reg.append_mark(self.name, page, idx, text, status, kind=kind,
                                    draft=draft, secs=secs, by="eye")

    def suggest(self, prefix: str, limit: int = 6) -> list[str]:
        """Автодоповнення з УЖЕ введених фраз — у метриці рядки повторюються."""
        prefix = prefix.strip().lower()
        if len(prefix) < 2:
            return []
        freq: Counter[str] = Counter()
        for rec in self.reg.marks(self.name).values():
            t = (rec.get("text") or "").strip()
            if t and rec.get("status") == "ok":
                freq[t] += 1
        hits = [(t, c) for t, c in freq.items() if t.lower().startswith(prefix)]
        hits.sort(key=lambda kv: (-kv[1], len(kv[0])))
        return [t for t, _ in hits[:limit]]

    def stats(self) -> dict[str, Any]:
        """Прогрес, темп і CER першого голосу проти ручних міток.

        `cer_draft` — найдешевший вимірювач якості злиття/голосу: символьна
        відстань між тим, що рушій (або арбітри) дали, і тим, що написала
        людина, по рядках зі статусом `ok`.
        """
        pages = self.pages()
        done = self.reg.marks(self.name)
        by_status = Counter(str(m.get("status")) for m in done.values())
        by_kind = Counter(str(m.get("kind") or "hand") for m in done.values()
                          if m.get("status") != "skip")
        secs = [float(m.get("secs") or 0) for m in done.values() if float(m.get("secs") or 0) > 0]
        med = statistics.median(secs) if secs else 0.0
        total = sum(len(v) for v in pages.values())
        left = total - len(done)
        dist = chars = 0
        for (pg, i), m in done.items():
            if m.get("status") != "ok" or not m.get("text"):
                continue
            d = self.drafts(pg).get(i, [])
            first = next((x for x in d if x), "")
            if not first:
                continue
            dist += Levenshtein.distance(first, str(m["text"]))
            chars += len(str(m["text"]))
        return {"name": self.name, "n_total": total, "n_pages": len(pages),
                "n_done": len(done), "n_left": left,
                "by_status": dict(by_status), "by_kind": dict(by_kind),
                "median_secs": round(med, 1),
                "eta_min": round(left * med / 60) if med else None,
                "chars": sum(len(m.get("text") or "") for m in done.values()
                             if m.get("status") == "ok"),
                "cer_draft": round(dist / chars, 3) if chars else None,
                "cer_lines": sum(1 for m in done.values() if m.get("status") == "ok")}


def tokens_of(s: str) -> list[str]:
    """Слова рядка — для перевірок і підсвітки."""
    return [w for w in re.split(r"[^\wЀ-ӿѐ-џ]+", s) if w]


__all__ = ["Store", "dedupe_similar", "degenerate", "draft_label", "name_score",
           "tokens_of", "usefulness"]
