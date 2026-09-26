"""Зібрати індекс фондів «Бабиного Яру» — для постачання з пакетом.

🔴 Навіщо. 26.09.2026 майданчик прибрав JSON-API, а сторінка архіву показує
лише частину фондів (ДАМО: 25). Решта живе за прямою адресою
`/archive/fund/<id>` — зокрема ДАМО ф.484, найбільша колекція метричних книг
майданчика. Без індексу збирач казав би про неї «немає».

Перебираються id підряд через саме джерело (`BabynYarSource.page`), тобто з
тим самим темпом і пережиданням викликів Cloudflare. Кінець — коли за
найбільшим id, видимим на сторінках архівів, іде `--stop-after` порожніх
адрес поспіль. Поступ зберігається кожні 25 id: обрив не починає наново.

    python tools/babynyar_funds.py              # продовжити з місця зупинки
    python tools/babynyar_funds.py --fresh      # наново
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from nyshporka.sources.babynyar import (
    BASE,
    KNOWN_FUNDS,
    BabynYarSource,
    fund_page,
    table_rows,
)
from nyshporka.sources.base import SourceError


class _Prostyi:
    """Системний `curl` із чесним User-Agent і трьома секундами між запитами.

    🔴 Не шлях за замовчуванням. 27.09.2026 `curl_cffi`, що вдає Chrome,
    упирався в сторінку-виклик Cloudflare на `/archive/`, `httpx` отримував
    403 (відсіч за TLS-відбитком), а системний `curl` із назвою застосунку —
    200. HAR сесії браузера того дня підтвердив, що сайт віддає звичайні
    HTML-сторінки без жодного API. Переждання викликів лишається (`CfClient`).
    Пауза тут, бо підставлений клієнт джерело вважає двійником і не чекає.
    """

    def __init__(self) -> None:
        import shutil
        import subprocess
        import tempfile

        from nyshporka.sources.cfclient import CfClient
        from nyshporka.sources.http import app_ua

        # ⚠ Явний шлях: Windows шукає програму в System32 РАНІШЕ за PATH, а
        # тамтешній `curl` 27.09.2026 стабільно діставав від сайту 403, тоді як
        # `curl` із Git for Windows — 200. `NYSHPORKA_CURL` перекриває вибір.
        exe = (os.environ.get("NYSHPORKA_CURL")
               or next((p for p in (r"C:\Program Files\Git\mingw64\bin\curl.exe",)
                        if Path(p).exists()), None)
               or shutil.which("curl") or "curl")
        spravzhnii = subprocess.run

        def _run(cmd: Any, *args: Any, **kw: Any) -> Any:
            if isinstance(cmd, list) and cmd and cmd[0] == "curl":
                cmd = [exe, *cmd[1:]]
            return spravzhnii(cmd, *args, **kw)

        import nyshporka.sources.cfclient as cfm

        cfm.subprocess.run = _run  # type: ignore[assignment]
        print(f"curl: {exe}", flush=True)

        class _Curl(CfClient):
            def __post_init__(self) -> None:
                self.via = "curl"
                self._tmp = tempfile.TemporaryDirectory(prefix="nysh-cf-")
                self._jar = Path(self._tmp.name) / "cookies.txt"

        self._c = _Curl(headers={"User-Agent": app_ua()})

    def get(self, url: str) -> Any:
        import time

        time.sleep(3.0)
        return self._c.get(url)


def _zapysaty(out: Path, funds: dict[int, dict[str, Any]], scanned_to: int) -> None:
    data = {"source": BASE, "taken": dt.date.today().isoformat(),
            "scanned_to": scanned_to,
            "funds": [funds[k] for k in sorted(funds)]}
    tmp = out.with_suffix(".json.tmp")
    tmp.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    tmp.replace(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(KNOWN_FUNDS))
    ap.add_argument("--stop-after", type=int, default=80,
                    help="скільки порожніх id поспіль за видимими означає кінець")
    ap.add_argument("--fresh", action="store_true", help="почати наново")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    funds: dict[int, dict[str, Any]] = {}
    start = 1
    if out.exists() and not a.fresh:
        old = json.loads(out.read_text(encoding="utf-8"))
        funds = {int(f["id"]): f for f in old.get("funds") or []}
        start = int(old.get("scanned_to") or 0) + 1

    src = BabynYarSource(client=_Prostyi())
    # Найбільший id, видимий на сторінках архівів: до нього діри не означають
    # кінця (фонди прибирають і з середини).
    vydymi = 0
    for arch in src.archives():
        for fid, _cells in table_rows(src.page(f"/archive/{arch['id']}"), "fond"):
            vydymi = max(vydymi, int(fid))
    print(f"видимий максимум id: {vydymi}; починаю з {start}", flush=True)

    fid, porozhni = start - 1, 0
    while True:
        fid += 1
        try:
            html = src.page(f"/archive/fund/{fid}")
        except SourceError as exc:
            if "404" not in str(exc):
                # Виклик Cloudflare чи збій — зберегти поступ і вийти: наступний
                # запуск продовжить із цього id.
                _zapysaty(out, funds, fid - 1)
                print(f"зупинка на id {fid}: {exc}", file=sys.stderr)
                return 1
            porozhni += 1
        else:
            got = fund_page(html)
            if got is None:
                porozhni += 1
            else:
                porozhni = 0
                funds[fid] = {"id": fid, **got}
        if fid % 25 == 0:
            _zapysaty(out, funds, fid)
            print(f"id {fid} · фондів {len(funds)}", flush=True)
        if fid > vydymi and porozhni >= a.stop_after:
            break
    _zapysaty(out, funds, fid)
    print(f"✓ фондів {len(funds)} (перебрано id 1…{fid}) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
