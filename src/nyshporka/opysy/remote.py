"""🌐 Описи в Супрязі: залити `.nyshopys`, шукати по описах.

Той самий шлях, що в справ (`share.upload`): ключ і довірена адреса
(`_tok_i_dim`), запит із причинами відмови з тіла відповіді (`_request`),
підписаний PUT з `If-None-Match`, повторами й проксі (`_put`). Свого мережевого
коду тут немає — розходитись нічому.

🔴 Реєстрація йде маніфестом, прочитаним із ПАКЕТА, а не з робочої теки:
пакувальник дописує в маніфест `tool`, і сервер у `complete` звіряє маніфест
залитого пакета із заявленим побайтно (`manifest_mismatch`).

🔴 Перед заливкою пакет проходить ворота ще раз тут: людина не везе байти заради
відмови, яку видно на її боці.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from nyshporka.opysy import bundle as B
from nyshporka.share import catalog
from nyshporka.share import upload as U


def push(path: Path, *, base: str = "") -> dict[str, Any]:
    """Пакет → реєстрація → байти в сховище → `complete`. Відповідь пулу."""
    blob = Path(path).read_bytes()
    contents, verdict = B.verify(blob)
    if not verdict.passed:
        raise U.UploadError("пакет не проходить ворота: " + "; ".join(verdict.refusals))
    tok, home = U._tok_i_dim(base)
    reg = U._request("POST", f"{home}/opysy", body=contents.manifest, auth=tok)
    U._put(str(reg["upload"]), blob)
    done = U._request("POST", f"{home}/opysy/{int(reg['vnesok'])}/complete", auth=tok,
                      timeout=U.COMPLETE_TIMEOUT)
    return {"vnesok": done.get("vnesok", reg["vnesok"]), "opys": reg.get("opys"),
            "shyfra": reg.get("shyfra") or done.get("shyfra"),
            "duplicate": bool(done.get("duplicate")), "summary": done.get("summary") or {},
            "warnings": done.get("warnings") or [], "text": done.get("text", "")}


def search(q: str, *, repo: str = "", fond: str = "", limit: int = 50,
           base: str = "") -> dict[str, Any]:
    """Нечіткий пошук по описах. Без ключа пул віддає лише натяк: де є збіги."""
    home = catalog.base_url(base)
    tok = U.token() if catalog.may_send_key(home, explicit=False) else ""
    params = {"q": q, "limit": limit}
    if repo:
        params["repo"] = repo
    if fond:
        params["fond"] = fond
    return U._request("GET", f"{home}/opysy/search?{urlencode(params)}", auth=tok)


def policy(repo: str, fond: str, *, base: str = "") -> dict[str, Any]:
    """Політика сервера щодо фонду (з серверним переліком виключень)."""
    home = catalog.base_url(base)
    tok = U.token() if catalog.may_send_key(home, explicit=False) else ""
    return U._request("GET", f"{home}/opysy/polityka?{urlencode({'repo': repo, 'fond': fond})}",
                      auth=tok)
