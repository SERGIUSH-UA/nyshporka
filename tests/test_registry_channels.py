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
    """Ворота проти повторення: колонки, які збирач пише про ДЖЕРЕЛО справи,
    мусять бути відомі читалці реєстру.

    🔴 Тут стояв виняток на `duck_*` — «описують чужий покажчик і в реєстр
    опису не вливаються». Це було неправдою, і вона вимірна: 2954 з 2955 рядків
    ф.224 і 4261 з 4391 ф.904 несуть `duck_url`, а читалка їх мовчки відкидала.
    Виняток, обґрунтований неперевіреним фактом, гірший за відсутній тест: він
    зробив ваду законною й пережив би наступного читача.

    ⚠ Префікс `duck_` тут не означає каналу завантаження — покажчик сам нічого
    не віддає. Означає лише: якщо збирач це пише, читалка мусить це бачити.
    """
    # ⚠ МЕЖА, а не виняток: злиття переносить у реєстр три колонки покажчика з
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
