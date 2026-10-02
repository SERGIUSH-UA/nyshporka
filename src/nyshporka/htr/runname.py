"""Ім'я прогону: тека результату справи в `reports/htr`.

🔴 Доти воно було ім'ям останньої теки кадрів. Справи лежать як
`<архів>/spr-N`, тож `CDIAK/2/145` і `CDIAK/224/145` обидві давали `spr-145`, і
друга пройшла б поверх текстів першої без жодної помилки (73 імені `spr-N` у
реєстрі мають по 2-3 справи). Тепер ім'я лишається голим, поки теку не займає
ІНША справа; тоді до нього дописується тека архіву: `cdiak_2-spr-145`.

Правило навмисно спирається на диск, а не на реєстр: голе ім'я в справ, що вже
прочитані, лишається тим самим, тож `already_read`, реєстр і всі чинні посилання
їх знаходять, а перейменовувати нічого не треба.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from nyshporka.utils.atomic import CorruptFileError, read_json

META_NAME = "_htr_meta.json"


def base_name(frames_dir: str | Path) -> str:
    """Ім'я справи за текою кадрів: для `…/pages` — батьківська тека."""
    d = Path(frames_dir)
    return d.parent.name if d.name == "pages" else d.name


def _case_root(frames_dir: str | Path) -> Path:
    d = Path(frames_dir)
    return d.parent if d.name == "pages" else d


def _norm(path: str | Path) -> str:
    s = str(path).replace("\\", "/").rstrip("/").lower()
    return s[:-len("/pages")] if s.endswith("/pages") else s


def _meta(out_dir: Path) -> dict[str, Any]:
    try:
        raw = read_json(out_dir / META_NAME, default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _belongs_elsewhere(meta: dict[str, Any], frames_dir: Path, case_key: str) -> bool:
    """Чи довела мета, що теку зайняла ІНША справа. Немає доказу — `False`.

    Ключ справи вирішує, коли він є з обох боків. Без ключа судить тека кадрів
    з мети. 🔴 Якщо там стиснута копія (`…/cloud/frames/<ім'я>`), а не оригінал,
    судити нема з чого: така копія зветься за іменем справи, тобто теж могла
    збігтись у двох справ. Тоді лишаємо голе ім'я — краще один зайвий збіг, ніж
    друге читання справи, яку вже прочитано.
    """
    mdir = str(meta.get("case_dir") or "").strip()
    norm = _norm(mdir) if mdir else ""
    # Та сама тека кадрів — та сама справа, хоч би як записано ключ.
    if norm and "/cloud/frames/" not in norm and norm == _norm(frames_dir):
        return False
    have = _canon(str(meta.get("case_key") or ""))
    want = _canon(str(case_key or ""))
    if have and want:
        from nyshporka.core.casekey import compatible

        return not compatible(have, want)
    if not norm or "/cloud/frames/" in norm:
        return False
    return norm != _norm(frames_dir)


def _canon(key: str) -> str:
    """Ключ у канонічній формі. 🔴 Рядком не порівнювати: раннер пише в мету
    шифру паспорта («ЦДІАК 2-1-169»), а `cloud go` і старі мети — ключ
    бібліотеки («CDIAK/2/169»). Порівняння рядків бачило в цьому дві справи й
    давало 318 з 755 прочитаних справ нове ім'я — тобто повторне читання."""
    key = key.strip()
    if not key:
        return ""
    from nyshporka.htr_store import _canon_case_key

    return _canon_case_key(key).strip().lower()


def run_name(frames_dir: str | Path, case_key: str = "", *,
             reports: Path | None = None) -> str:
    """Ім'я теки результату: голе, а коли зайняте чужою справою — з архівом."""
    if reports is None:
        from nyshporka.core.workspace import workspace

        reports = workspace().htr_reports
    d = Path(frames_dir)
    base = base_name(d)
    meta = _meta(Path(reports) / base)
    if not meta or not _belongs_elsewhere(meta, d, case_key):
        return base
    archive = _case_root(d).parent.name
    return f"{archive}-{base}" if archive else base
