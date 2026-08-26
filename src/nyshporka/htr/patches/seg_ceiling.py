"""Стеля кількості рядків у сегментації Kraken — керована й помітна.

`kraken.lib.segmentation.vectorize_lines(max_endpoints=400)` — захист від
O(n²) MCP-шляхів між кінцями скелета. Кожен baseline дає 2 кінці, тож стеля
насправді читається як **200 рядків на сторінку**. При перевищенні kraken
сортує скелетні компоненти за розміром і викидає найдрібніші, поки бюджет не
вичерпано, — тобто губиться саме дрібне: номери актів, дати, короткі рядки на
кінцях граф.

🔴 Найгірше в цьому — мовчазність. Помилки в лозі немає, декод виглядає повним,
а в меті лишається рівне `lines: 200` серед сусідів 190-199. На ДАЖО 178-51-418
(шлюбна метрика 1839, розворот 3 графи × 2 сторінки) у стелю впирається 141 з
244 сторінок; підняття до 1600 дає +20 рядків на сторінку за +1.6 с.

Тому тут дві речі, яких немає в самому kraken:

1. **Стеля — параметр прогону** (`--max-endpoints`), а не константа бібліотеки.
2. **Спрацювання стелі видно**: `hit()` каже, чи фільтр різав на цій сторінці,
   і раннер за цим сам перепускає сторінку з піднятою стелею. Детектор
   подвійний — лог kraken (точний) або кількість рядків на самій межі
   (запасний, якщо текст повідомлення зміниться при апгрейді). Пін
   `kraken==7.0.2` тримає перше, друге переживе й зміну версії.

Прикладати після `gpu_sato`/`fast_geom` не обов'язково — патчі незалежні:
ці підміняють `skimage.filters.sato` і геометрію, цей — саму `vectorize_lines`.
"""
from __future__ import annotations

import logging

DEFAULT_CEILING = 400

_STATE: dict = {
    "ceiling": DEFAULT_CEILING,
    "hit": False,
    "orig": None,
    "installed": False,
}


class _FilterWatcher(logging.Handler):
    """Ловить `Filtered N endpoints from M skeleton components` з kraken.

    Kraken пише це рівно тоді, коли фільтр справді щось викинув, тож це
    найточніший наявний сигнал. Рівень логера піднімаємо до INFO, але записи
    нікуди не виводяться: root за замовчуванням без хендлерів, а `lastResort`
    показує лише WARNING+.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.getMessage().lstrip().startswith("Filtered"):
                _STATE["hit"] = True
        except Exception:
            pass


def install(max_endpoints: int = DEFAULT_CEILING, verbose: bool = True) -> int:
    """Підмінити `vectorize_lines` версією з керованою стелею. Ідемпотентно."""
    from kraken.lib import segmentation as kseg

    _STATE["ceiling"] = int(max_endpoints)

    if not _STATE["installed"]:
        _STATE["orig"] = kseg.vectorize_lines

        def patched(im, threshold: float = 0.17, min_length=5,
                    text_direction: str = "horizontal",
                    max_endpoints: int = DEFAULT_CEILING):
            # стеля береться зі стану модуля, а не з аргументу: kraken кличе
            # функцію без нього, і підміна дефолту і є весь патч
            return _STATE["orig"](im, threshold, min_length, text_direction,
                                  _STATE["ceiling"])

        kseg.vectorize_lines = patched
        # blla імпортував ім'я напряму (`from ... import vectorize_lines`),
        # тож підміни лише в модулі-джерелі мало — вона б його не зачепила
        try:
            import kraken.blla as blla
            blla.vectorize_lines = patched
        except Exception:
            pass

        log = logging.getLogger("kraken.lib.segmentation")
        if log.level > logging.INFO or log.level == logging.NOTSET:
            log.setLevel(logging.INFO)
        log.addHandler(_FilterWatcher())

        _STATE["installed"] = True

    if verbose:
        print(f"[seg-ceiling] стеля рядків {_STATE['ceiling'] // 2} "
              f"(max_endpoints={_STATE['ceiling']})", flush=True)
    return _STATE["ceiling"]


def set_ceiling(max_endpoints: int) -> None:
    """Змінити стелю на льоту — для перепуску однієї сторінки."""
    _STATE["ceiling"] = int(max_endpoints)


def ceiling() -> int:
    return _STATE["ceiling"]


def reset() -> None:
    """Забути слід спрацювання. Кликати перед кожною сторінкою."""
    _STATE["hit"] = False


def hit(n_lines: int | None = None) -> bool:
    """Чи різала стеля? `n_lines` — запасний детектор за кількістю рядків.

    Кожна проста лінія дає 2 кінці, тож сторінка, яка вперлась, віддає рівно
    `ceiling // 2` рядків (буває на 1-2 менше, коли якась компонента має
    непарне число кінців) — звідси допуск.
    """
    if _STATE["hit"]:
        return True
    if n_lines is None:
        return False
    return n_lines >= (_STATE["ceiling"] // 2) - 2
