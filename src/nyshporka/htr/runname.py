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


def _meta(out_dir: Path) -> dict:
    try:
        raw = read_json(out_dir / META_NAME, default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _belongs_elsewhere(meta: dict, frames_dir: Path, case_key: str) -> bool:
    """Чи довела мета, що теку зайняла ІНША справа. Немає доказу — `False`.

    Ключ справи вирішує, коли він є з обох боків. Без ключа судить тека кадрів
    з мети. 🔴 Якщо там стиснута копія (`…/cloud/frames/<ім'я>`), а не оригінал,
    судити нема з чого: така копія зветься за іменем справи, тобто теж могла
    збігтись у двох справ. Тоді лишаємо голе ім'я — краще один зайвий збіг, ніж
    друге читання справи, яку вже прочитано.
    """
    have = str(meta.get("case_key") or "").strip().lower()
    want = str(case_key or "").strip().lower()
    if have and want:
        return have != want
    mdir = str(meta.get("case_dir") or "").strip()
    if not mdir:
        return False
    norm = _norm(mdir)
    if "/cloud/frames/" in norm:
        return False
    return norm != _norm(frames_dir)


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
