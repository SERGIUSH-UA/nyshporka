"""🏛 Канали завантаження в реєстрі опису: що збирач пише — читалка мусить бачити.

🔴 Вада, заради якої цей файл існує, прожила цілий реліз. Збирач ARCHIUM
з'явився й писав `archium_file`, а читалка реєстру в тій самій версії цих
колонок ще не знала — тобто одна половина пакета складала те, чого друга не
бачить. Наслідок вимірюваний: справа, скан якої лежить онлайн і береться за
секунди, показувалась станом «лише замовлення в архіві».

Обидві половини були «правильні» кожна окремо, і саме тому ніщо не падало.
"""
from __future__ import annotations

from nyshporka.fonds.collect.archium import FIELDS as ARCHIUM_FIELDS
from nyshporka.fonds.collect.commons import FIELDS as COMMONS_FIELDS
from nyshporka.fonds.collect.duck import FIELDS as DUCK_FIELDS
from nyshporka.fonds.registry import FIELDS as REGISTRY_FIELDS
from nyshporka.fonds.registry import row_status


def test_a_scan_in_the_viewer_is_something_you_can_take_yourself() -> None:
    """🔴 Поведінковий приймач: `todo` = «можна взяти самому», `order` = «лише
    замовлення в архіві». Плутанина тут коштує тижня очікування замовлення на
    документ, який лежить онлайн."""
    row = {"opys": "1", "spr_int": "1", "spr_letter": "",
           "archium_file": "51068",
           "archium_url": "https://архів/file-viewer/51068/"}
    assert row_status(row, live={}, conflicts={})["disk_state"] == "todo"


def test_a_case_with_no_channel_at_all_is_an_order() -> None:
    """Зворотний бік: без жодного каналу стан мусить лишитись замовленням,
    інакше черга завантаження наповниться тим, чого взяти не можна."""
    row = {"opys": "1", "spr_int": "2", "spr_letter": ""}
    assert row_status(row, live={}, conflicts={})["disk_state"] == "order"


def test_what_a_collector_writes_the_registry_can_read() -> None:
    """Ворота проти повторення: колонки, які збирач пише про джерело справи,
    мусять бути відомі читалці реєстру.

    🔴 Тут стояв виняток на `duck_*` — «описують чужий покажчик і в реєстр
    опису не вливаються». Це було неправдою, і вона вимірна: 2954 з 2955 рядків
    ф.224 і 4261 з 4391 ф.904 несуть `duck_url`, а читалка їх мовчки відкидала.
    Виняток, обґрунтований неперевіреним фактом, гірший за відсутній тест: він
    зробив ваду законною й пережив би наступного читача.

    ⚠ Префікс `duck_` тут не означає каналу завантаження — покажчик сам нічого
    не віддає. Означає лише: якщо збирач це пише, читалка мусить це бачити.
    """
    # ⚠ межа, а не виняток: злиття переносить у реєстр три колонки покажчика з
    # шести — `duck_id` і `duck_copies` лишаються у файлі збирача. Перевірено
    # на диску: у злитих реєстрах ф.224 і ф.904 стоять рівно `duck_url`,
    # `duck_online`, `duck_copy_url`. Записано тут, щоб наступний не вважав це
    # недоглядом і не «полагодив».
    # 🔜 Коли злиття переїде в пакет, цей перелік замінить прямий зшивач
    # `set(merge.COLUMNS) <= set(FIELDS)` — і межа стане перевіреною, а не
    # переказаною.
    not_carried = {"duck_id", "duck_copies"}
    written = {c for c in (*ARCHIUM_FIELDS, *COMMONS_FIELDS, *DUCK_FIELDS)
               if c.startswith(("archium_", "commons_", "mirror_", "duck_"))}
    unknown = sorted(written - not_carried - set(REGISTRY_FIELDS))
    assert not unknown, (
        f"збирач пише колонки, яких читалка реєстру не знає: {unknown} — "
        f"зібране доїде до реєстру й не потрапить у застосунок")


# ── ARCHIUM: номер фонду не мусить бути особистою проблемою користувача ──────
def test_the_pack_remembers_the_site_fond_number() -> None:
    """🔴 Знайдене одним користувачем однакове для всіх.

    Сайт архіву адресує фонд ВЛАСНИМ номером (ЦДІАК ф.224 значиться там фондом
    198), і без нього збирач узагалі не стартує. Доти це число жило лише в теці
    того простору, де його раз знайшли, — тобто кожен наступний користувач мусив
    шукати те саме заново. Це факт про САЙТ, а не про чиюсь машину.
    """
    from nyshporka.archives import active

    f = active().fonds.get(("CDIAK", "224"))
    assert f is not None, "фонду немає в паку"
    assert f.archium_fond == "198"
    assert f.archium_opys.get("3") == "1529", f.archium_opys


def test_a_case_link_is_enough_to_calibrate() -> None:
    """🔴 Людина не мусить знати, що таке «внутрішній номер фонду».

    Вона вміє показати пальцем: ось справа цього фонду. Номер зі сторінки дає
    САЙТ, а не наш здогад.

    ⚠ Голе число лишається НОМЕРОМ ФОНДУ: обидва числові, і вгадувати тут не
    можна — ознакою справи є саме адреса.
    """
    from nyshporka.fonds.collect.archium import _resolve_fond_id, _viewer_id

    assert _viewer_id("https://archium.cdiak.archives.gov.ua/file-viewer/51068/") == "51068"
    assert _viewer_id("/file-viewer/51068") == "51068"
    assert _viewer_id("51068") == "51068"
    assert _viewer_id("щось інше") == ""

    class _Collector:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def fond_id_from_case(self, viewer_id: str, repo: str = "") -> str:
            self.asked.append(viewer_id)
            return "198"

    class _T:
        repo = "CDIAK"

    c = _Collector()
    assert _resolve_fond_id("https://a/file-viewer/51068/", c, _T()) == "198"
    assert c.asked == ["51068"], "посилання на справу не спитало сайт"
    assert _resolve_fond_id("198", c, _T()) == "198"
    assert c.asked == ["51068"], "голе число сприйняли за справу"


def test_a_known_number_means_the_collector_can_start() -> None:
    """Наслідок, заради якого все й робилось: фонд із номером у паку більше не
    вимагає від людини нічого — план одразу «готовий»."""
    from nyshporka.fonds.collect.archium import ArchiumCollector

    class _T:
        repo, fond, fond_id, opys = "CDIAK", "224", "cdiak_224", ()

    got, invs = ArchiumCollector(workspace=None).known_fond_id(_T())
    assert got == "198", got
    assert sorted(invs) == ["1", "2", "3"], invs
