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
    """Ворота проти повторення: колонки збирачів, які описують КАНАЛ, мусять
    бути відомі читалці реєстру.

    ⚠ Не всі колонки збирача сюди належать: `duck_*` описують чужий покажчик і
    в реєстр опису не вливаються — його заповнює окремий крок злиття. Тому
    перевіряються саме ті, за якими вирішують, чи можна завантажити.
    """
    channel_columns = {c for c in (*ARCHIUM_FIELDS, *COMMONS_FIELDS)
                       if c.startswith(("archium_", "commons_", "mirror_"))}
    unknown = sorted(channel_columns - set(REGISTRY_FIELDS))
    assert not unknown, (
        f"збирач пише колонки каналу, яких читалка реєстру не знає: {unknown} — "
        f"справа зі сканом виглядатиме як «лише замовлення в архіві»")
