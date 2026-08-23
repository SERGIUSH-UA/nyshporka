"""🧬 Зведення джерел опису в один реєстр фонду.

Сусід `collect/`, а не його частина, і це не формальність: збирач відповідає на
«що існує у фонді» й пише `registry/<джерело>.tsv`, а злиття споживає ВСІ ці
файли й пише файл самого фонду. Покласти його в `collect/` означало б, що воно
з'явиться серед збирачів, і людина шукатиме `merge.tsv`.
"""
from nyshporka.fonds.merge.scans import aggregate_commons, is_volume
from nyshporka.fonds.merge.text import (
    key_of,
    letter_cyr,
    names_settlement,
    norm_title,
    opys_sort,
    token_set_ratio,
    village_matches,
    village_of,
)

__all__ = ["aggregate_commons", "is_volume", "key_of", "letter_cyr",
           "names_settlement", "norm_title", "opys_sort", "token_set_ratio",
           "village_matches", "village_of"]
