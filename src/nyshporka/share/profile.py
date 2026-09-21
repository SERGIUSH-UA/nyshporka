"""⚙️ Профіль Супряги: хто ви й на що згодні.

Заповнюється один раз (`nysh share setup`) і більше не питається. Причина в
тому, як люди читають справи: прогін триває годинами, і питання «віддати?»
після кожного дратує на третій раз, а на пʼятий його клацають не читаючи —
тобто згода перестає бути згодою.

🔴 Типово — НЕ ділитись. Серед аудиторії є люди, які платили за зйомку, і
автоматична роздача відштовхнула б їх назавжди. Режим `zavzhdy` вмикає
людина сама й свідомо.

Де лежить і чому саме там
-------------------------

Профіль — у `config/supriaha.yaml`, тобто ЇДЕ РАЗОМ ІЗ ПРОСТОРОМ. Це
навмисно: спакував простір на інший свій компʼютер — псевдонім, контакт і
режим згоди поїхали з ним.

🔴 Токен тут НЕ лежить і лежати не буде (`upload.py` пояснює докладно):
простір пересилають одне одному, і токен поїхав би разом із ним.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Ім'я файлу в теці конфігів простору.
CONFIG_NAME = "supriaha.yaml"

#: Режими згоди.
NIKOLY = "nikoly"      # мовчати назавжди
ZAVZHDY = "zavzhdy"    # пакувати й віддавати самому
PYTATY = "pytaty"      # вести список і нагадувати раз на тиждень
CONSENT = (NIKOLY, ZAVZHDY, PYTATY)

CONSENT_TEXT = {
    NIKOLY: "ніколи не ділитись",
    ZAVZHDY: "віддавати одразу після прогону",
    PYTATY: "вести список і нагадувати",
}

HEADER = """\
# Профіль Супряги — спільного банку прочитаних архівних справ.
#
# Заповнюється командою `nysh share setup`. Правити руками можна, але
# коментарі при наступному записі команди не збережуться.
#
# 🔴 Токена тут немає й не буде: простір пересилають одне одному, і токен
# поїхав би разом із ним. Він живе в NYSHPORKA_SUPRIAHA_TOKEN або в сховищі
# ключів операційної системи.
"""


@dataclass
class Profile:
    """Те, що людина сказала про себе один раз."""

    #: Псевдонім у каталозі. Порожній — «без імені»; це законний вибір.
    handle: str = ""
    #: Як зв'язатись. 🔴 Публічні дані, тож лише на явну згоду.
    contact: str = ""
    site: str = ""
    #: Ліцензія тексту за замовчуванням.
    license: str = "CC0-1.0"
    #: Умови джерела сканів — окремим полем від ліцензії тексту.
    source_terms: str = ""
    #: `nikoly` | `zavzhdy` | `pytaty`
    consent: str = PYTATY
    #: Питати пул перед прогоном, чи справу вже прочитали.
    lookup: bool = True
    #: Геометрія рядків — в ОБИДВА боки одним перемикачем.
    #:
    #: Тягнути її, коли прив'язка дала `exact`, і віддавати разом зі своїм
    #: текстом у режимі «завжди». Два окремі поля тут були б удаваним
    #: вибором: людина, яка не хоче мати справи з рамками, не хоче її ні
    #: качати, ні розсилати, а важить геометрія ×10 від тексту — тобто
    #: автоматична віддача без перемикача клала б цю ціну на того, хто
    #: вмикав зовсім інше.
    geometry: bool = True
    #: Поля, яких ця версія не знає, — зберігаються недоторканими.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def shares(self) -> bool:
        return self.consent != NIKOLY

    @property
    def auto(self) -> bool:
        return self.consent == ZAVZHDY

    def as_json(self) -> dict[str, Any]:
        out = {k: v for k, v in asdict(self).items() if k != "extra"}
        out.update(self.extra)
        return out


def config_path() -> Any:
    from nyshporka.core.workspace import workspace

    return workspace().config / CONFIG_NAME


def load() -> Profile:
    """Профіль або типовий, якщо його ще не заповнювали.

    Ніколи не кидає: побитий файл — це привід узяти дефолти й дати людині
    працювати далі, а не зупинити прогін через конфіг, у який вона, може,
    і не заглядала.
    """
    import yaml

    path = config_path()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        # 🔴 Саме `Exception`, а не `ValueError`: `yaml` кидає власну
        # ієрархію (`YAMLError`), яка від `ValueError` не походить, і
        # вузький перехоплювач пропустив би падіння на биту кому в конфігу.
        # Вартість помилки несиметрична: тут це зупинений прогін, а плата
        # за широкий перехоплювач — дефолтний профіль.
        return Profile()
    if not isinstance(raw, dict):
        return Profile()

    known = {f for f in Profile.__dataclass_fields__ if f != "extra"}
    got = Profile(**{k: v for k, v in raw.items() if k in known and v is not None})
    got.extra = {k: v for k, v in raw.items() if k not in known}
    if got.consent not in CONSENT:
        got.consent = PYTATY
    return got


def save(profile: Profile) -> Any:
    """Записати профіль. Повертає шлях.

    ⚠️ Коментарі, дописані рукою, не переживають запис: `yaml.safe_dump`
    їх не бачить. Для цього файлу це прийнятно — він короткий і машинний, —
    а от профіль дослідника (`core/profile.py`) саме через це пишеться
    інакше: там у коментарях записані заміри.
    """
    import yaml

    from nyshporka.utils.atomic import atomic_write_text

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(profile.as_json(), allow_unicode=True, sort_keys=False)
    atomic_write_text(path, HEADER + body)
    return path


def pack_defaults(profile: Profile | None = None) -> dict[str, str]:
    """Значення для `share.pack`, узяті з профілю.

    Доти ліцензія була захардкоджена у двох місцях — у CLI й в описі
    операції, — і розійтись вони могли мовчки.
    """
    p = profile or load()
    return {
        "publisher": p.handle,
        "contact": p.contact,
        "site": p.site,
        "license": p.license or "CC0-1.0",
        "source_terms": p.source_terms,
    }
