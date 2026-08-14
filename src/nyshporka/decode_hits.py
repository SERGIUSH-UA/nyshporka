"""👁 Реєстр хітів декоду — які саме скани справи варто передивитись оком.

Навіщо: агентний декод справи дає 2-3 кандидати на сотні аркушів, і єдиний спосіб
закрити питання «щ чи ц», «-скій чи -укъ» — подивитись оком у повній роздільності.
Досі це робилось ad-hoc сервером на ngrok, який помирав разом із сесією; вердикт
губився в листуванні. Тут він зберігається поруч із хітом.

Формат `data/spotter/decode_hits.json`:

    {"version": 1, "cases": {
       "<key>": {"path": "data/raw/...", "shifra": "ДАВО 337-1-4", "title": "...",
                 "hits": [{"scan": "0030.JPG", "sheet": "31", "row": "413",
                           "kind": "clan", "label": "...", "conf": 85,
                           "note": "...", "verdict": null, "verdict_note": "",
                           "verdict_date": ""}]}}}

`kind` розділяє те, що шукали, від того, з чим його плутають:
  clan     — цільовий рід (цільове прізвище й варіанти)
  side     — побічна ціль проєкту (Фисюк, Дудник, Григоришен, Шендеровський)
  confuser — еталон для порівняння (Пастухъ, Долищукъ, Дрогобецкій)

`verdict` ставить ЛЮДИНА з мобільного: confirmed / refuted / unclear. Він не
застаріває від зміни моделі й не переписується новим декодом — агент може лише
додати хіт, зняти чужий вердикт не може (див. `set_verdict`).

Пов'язано: memory `decode-agents-invent-d-surnames` — саме через хибні хіти
агентів (3/3 спростовано оком) цей реєстр і знадобився.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from nyshporka.core.workspace import workspace

ROOT = workspace().root
HITS_PATH = workspace().spotter / "decode_hits.json"

KINDS = {
    "clan": {"emoji": "🔥", "label": "рід"},
    "side": {"emoji": "🎯", "label": "побічна ціль"},
    "confuser": {"emoji": "🪤", "label": "конфузер-еталон"},
}

VERDICTS = {
    "confirmed": {"emoji": "✅", "label": "підтверджено оком"},
    "refuted": {"emoji": "❌", "label": "спростовано оком"},
    "unclear": {"emoji": "🤷", "label": "нерозбірливо"},
}


def load() -> dict:
    """Увесь реєстр. Порожній скелет, якщо файлу ще немає."""
    if not HITS_PATH.exists():
        return {"version": 1, "cases": {}}
    try:
        data = json.loads(HITS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "cases": {}}
    data.setdefault("cases", {})
    return data


def save(data: dict) -> Path:
    HITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    HITS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return HITS_PATH


def cases() -> list[dict]:
    """Справи з хітами + лічильники — для списку у вкладці «👁 Гортач»."""
    out = []
    for key, case in load()["cases"].items():
        hits = case.get("hits") or []
        out.append({
            "key": key,
            "path": case.get("path") or "",
            "shifra": case.get("shifra") or "",
            "title": case.get("title") or "",
            "n_hits": len(hits),
            "n_clan": sum(1 for h in hits if h.get("kind") == "clan"),
            "n_open": sum(1 for h in hits if not h.get("verdict")),
            "n_confirmed": sum(1 for h in hits if h.get("verdict") == "confirmed"),
            "n_refuted": sum(1 for h in hits if h.get("verdict") == "refuted"),
        })
    # спершу ті, де лишились неперевірені хіти роду
    out.sort(key=lambda c: (-c["n_open"], -c["n_clan"], c["shifra"]))
    return out


def case_hits(key: str) -> dict | None:
    """Справа з хітами. `scan_index` — позиція скана у теці, для гортання контексту."""
    case = load()["cases"].get(key)
    if not case:
        return None
    scans = list_scans(case.get("path") or "")
    pos = {name: i for i, name in enumerate(scans)}
    hits = []
    for h in case.get("hits") or []:
        hits.append({**h, "scan_index": pos.get(h.get("scan"), -1)})
    hits.sort(key=lambda h: h.get("scan") or "")
    return {**case, "key": key, "hits": hits, "n_scans": len(scans)}


def list_scans(rel_path: str) -> list[str]:
    """Імена файлів-сканів теки справи, відсортовані. Порожньо, якщо теки нема."""
    if not rel_path:
        return []
    d = (ROOT / rel_path).resolve()
    if not _inside_repo(d) or not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def scan_path(key: str, scan: str) -> Path | None:
    """Абсолютний шлях скана — з перевіркою, що він у теці саме цієї справи.

    Захист від path traversal: `scan` мусить бути голим іменем файлу, а результат —
    лежати всередині оголошеної теки справи, яка сама лежить у репозиторії.
    """
    case = load()["cases"].get(key)
    if not case or not scan or "/" in scan or "\\" in scan or scan.startswith("."):
        return None
    base = _inside_repo(case.get("path") or "")
    if base is None:
        return None
    target = Path(os.path.abspath(base / scan))
    if target.parent != base or not target.is_file():
        return None
    return target


def _inside_repo(path: str | Path) -> Path | None:
    """Абсолютний шлях теки справи, якщо вона під `data/raw`; інакше None.

    🐞 Було `.resolve()` + докстрінг «junction'и на T: — теж, вони туди лінковані».
    Це припущення ХИБНЕ: `resolve()` розкриває junction, шлях стає `T:\\…`, і гард
    відкидав справу. Тобто скани всього ф.196 (він видний у репо саме через
    junction — memory `disk-layout-t-drive-junctions`) не віддавались. Спільний
    нормалізатор — `htr_store.under_raw`: `abspath` прибирає `..`, посилань не
    розкриває.
    """
    from nyshporka.htr_store import under_raw
    return under_raw(path)


def set_verdict(key: str, scan: str, verdict: str | None, note: str = "") -> dict:
    """Вердикт людини по конкретному скану. verdict=None — зняти (повернути в чергу)."""
    if verdict and verdict not in VERDICTS:
        raise ValueError(f"невідомий вердикт: {verdict} (треба {', '.join(VERDICTS)})")
    data = load()
    case = data["cases"].get(key)
    if not case:
        raise ValueError(f"справи «{key}» немає в реєстрі хітів")
    for h in case.get("hits") or []:
        if h.get("scan") == scan:
            h["verdict"] = verdict or None
            h["verdict_note"] = note
            h["verdict_date"] = date.today().isoformat() if verdict else ""
            save(data)
            return h
    raise ValueError(f"скана «{scan}» немає серед хітів справи «{key}»")


def add_case(key: str, path: str, shifra: str = "", title: str = "",
             hits: list[dict] | None = None, replace: bool = False) -> dict:
    """Внести справу з хітами. За замовчуванням ДОПИСУЄ, зберігаючи чужі вердикти.

    Вердикт людини — дорожчий за будь-який машинний результат, тож повторний декод
    оновлює опис хіта, але поле `verdict` лишає як є. `replace=True` стирає все —
    лише для явного «перезаписати з нуля».
    """
    data = load()
    case = data["cases"].setdefault(key, {"path": path, "hits": []})
    case["path"] = path or case.get("path") or ""
    if shifra:
        case["shifra"] = shifra
    if title:
        case["title"] = title
    if replace:
        case["hits"] = []
    existing = {h.get("scan"): h for h in case.get("hits") or []}
    for h in hits or []:
        scan = h.get("scan")
        if not scan:
            continue
        old = existing.get(scan) or {}
        merged = {
            "scan": scan,
            "sheet": h.get("sheet") or "",
            "row": h.get("row") or "",
            "kind": h.get("kind") or "clan",
            "label": h.get("label") or "",
            "conf": h.get("conf"),
            "note": h.get("note") or "",
            # вердикт людини переживає повторний декод
            "verdict": old.get("verdict"),
            "verdict_note": old.get("verdict_note", ""),
            "verdict_date": old.get("verdict_date", ""),
        }
        existing[scan] = merged
    case["hits"] = sorted(existing.values(), key=lambda h: h["scan"])
    save(data)
    return case
