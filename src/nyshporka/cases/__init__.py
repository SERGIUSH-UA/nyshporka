r"""Центральний реєстр справ — один рядок на справу з усіма шарами обробки.

Зводить п'ять сховищ, які досі жили окремо:

  1. `data/derived/case_library.json` — опис (шифра, назва, роки, місце, тип, кадри);
  2. `reports/htr/*/_htr_meta.json`   — декод: рушій, модель, скільки сторінок;
  3. `data/clan_hunt/state.json`      — fuzzy-пошук роду й вердикти по сторінках;
  4. `data/derived/nyshporka.sqlite`      — скільки фактів канону спирається на справу;
  5. `data/pages/**`                  — що прочитано оком.

Опис НЕ дублюється: `nyshporka.library` лишається джерелом назв і шифр, тут вони лише
збагачуються. Вихід — `data/derived/case_index.sqlite` (derived, перебудовується).
"""
from nyshporka.cases.collect import collect_rows
from nyshporka.cases.db import build_index, query_rows
from nyshporka.cases.model import CaseRow, RunLink
from nyshporka.cases.resolve import resolve_run

__all__ = ["CaseRow", "RunLink", "build_index", "collect_rows", "query_rows", "resolve_run"]
