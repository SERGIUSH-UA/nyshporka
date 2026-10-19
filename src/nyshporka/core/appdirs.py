"""Де лежать дані й кеш застосунку (каталоги архівів, ваги моделей).

🔴 Одна точка, а не `platformdirs` у кожному модулі. Людина обирає в інсталяторі
теку на D:, бо на C: мало місця, — і каталоги (49 МБ) з вагами (~215 МБ) мусять
лягти туди ж, а не мовчки в `%LOCALAPPDATA%` (відеоурок, 16.10.2026).

Порядок:

1. змінна `NYSHPORKA_DATA_DIR` — свідомий вибір людини;
2. `data_dir=` у `install-info.ini` — розкладка «одна тека» з інсталятора;
3. `platformdirs` — як було досі.

Кеш живе в `<дані>/Cache`, тобто так само, як `platformdirs` розкладає його на
Windows, — щоб шлях читався однаково з будь-якого з трьох джерел.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Свідомо обрана тека даних застосунку.
ENV_DATA_DIR = "NYSHPORKA_DATA_DIR"

APP = "Nyshporka"


def _chosen() -> Path | None:
    env = os.environ.get(ENV_DATA_DIR, "").strip()
    if env:
        return Path(env)
    from nyshporka.setup.update import install_info

    got = install_info().get("data_dir", "").strip()
    return Path(got) if got else None


def data_dir() -> Path:
    """Тека даних: те, чия втрата тиха (каталоги)."""
    own = _chosen()
    if own is not None:
        return own
    from platformdirs import user_data_dir

    return Path(user_data_dir(APP, appauthor=False))


def cache_dir() -> Path:
    """Тека кешу: відтворюване (ваги моделей)."""
    own = _chosen()
    if own is not None:
        return own / "Cache"
    from platformdirs import user_cache_dir

    return Path(user_cache_dir(APP, appauthor=False))


#: Змінна, якою наглядач оренди (`gpuhire`, модуль `gpurunner`) бере свою теку.
ENV_GPURUNNER_DATA_DIR = "GPURUNNER_DATA_DIR"


def gpurunner_data_dir() -> Path | None:
    """Куди наглядачеві оренди класти свій стан — або `None`, якщо не чіпати.

    🔴 Без змінної наглядач кладе реєстр прогонів, витрати й чекпоінти боксів у
    `%LOCALAPPDATA%\\gpurunner` — гігабайти на C: тому, хто в інсталяторі обрав
    D: (19.10.2026: 4.4 ГБ). Тому з обраною текою даних — `<дані>/gpurunner`.

    `None`, коли:
    * змінну вже задано — це чийсь свідомий вибір;
    * теку даних ніхто не обирав — тоді й наглядач лишається, де був;
    * стара тека в профілі вже існує. 🔴 Переїзд мовчки осиротив би живі сесії й
      історію прогонів: новий наглядач не знайшов би ні орендованих машин, ні
      витрат. Переносить її людина, не перший-ліпший виклик.
    """
    if os.environ.get(ENV_GPURUNNER_DATA_DIR, "").strip():
        return None
    own = _chosen()
    if own is None:
        return None
    from platformdirs import user_data_dir

    if Path(user_data_dir("gpurunner", appauthor=False)).exists():
        return None
    return own / "gpurunner"


def gpurunner_env() -> dict[str, str]:
    """Доповнення оточення для виклику наглядача оренди окремим процесом."""
    got = gpurunner_data_dir()
    return {ENV_GPURUNNER_DATA_DIR: str(got)} if got is not None else {}
