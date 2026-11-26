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
            "warnings": done.get("warnings") or [], "text": done.get("text", ""),
            "obmin": bool(done.get("obmin"))}


def navchannia(vnesok: int, blob: bytes, *, base: str = "") -> dict[str, Any]:
    """Матеріал для навчання до прийнятого внеску: реєстрація → байти в сховище → `complete`.

    Той самий двоходовий шлях, що в пакета: великі байти не йдуть через сервер (там стеля 1 МБ).
    Сервер перевіряє архів тим самим `navchannia.perevirka`; лежить він у сховищі, доки власник
    Нишпорки його не забере."""
    from nyshporka.opysy import navchannia as NV

    NV.perevirka(blob)  # не везти байти заради відмови, яку видно тут
    tok, home = U._tok_i_dim(base)
    reg = U._request("POST", f"{home}/opysy/{int(vnesok)}/navchannia", auth=tok,
                     body={"bytes": len(blob)})
    if reg.get("vzhe"):
        return reg
    U._put(str(reg["upload"]), blob)
    return U._request("POST", f"{home}/opysy/navchannia/{int(reg['peredacha'])}/complete",
                      auth=tok, timeout=U.COMPLETE_TIMEOUT)


def skan_viddaty(path: Path, *, sha256: str, meta: dict[str, Any], vnesok: int | None = None,
                 base: str = "") -> dict[str, Any]:
    """Скан опису, якого немає онлайн, — власнику Нишпорки для Commons (тимчасово в сховище), до
    прийнятого внеску. Сервер звіряє відбиток залитого з `sha256` джерела; коли власник опублікує
    скан на Commons, посилання справ цього внеску сервер допише сам."""
    blob = Path(path).read_bytes()
    tok, home = U._tok_i_dim(base)
    reg = U._request("POST", f"{home}/opysy/skany", auth=tok,
                     body={"sha256": sha256, "bytes": len(blob), "imia": Path(path).name,
                           "vnesok": vnesok, **meta})
    if "upload" not in reg:
        return reg  # той самий скан уже передано чи вже на Commons
    U._put(str(reg["upload"]), blob)
    return U._request("POST", f"{home}/opysy/skany/{int(reg['peredacha'])}/complete", auth=tok,
                      timeout=U.COMPLETE_TIMEOUT)


def skan_stan(sha256: str, *, base: str = "") -> dict[str, Any]:
    """Що з переданим сканом: `gotovo` — чекає власника, `na_commons` — є адреса Commons."""
    tok, home = U._tok_i_dim(base)
    return U._request("GET", f"{home}/opysy/skany?{urlencode({'sha256': sha256})}", auth=tok)


# ── власник: забрати передачі з R2, скан на Commons ─────────────────────────


def peredachi(*, vyd: str = "", status: str = "gotovo", after: int = 0,
              base: str = "") -> dict[str, Any]:
    """Що лежить у сховищі для власника (адмін; іншим сервер відповідає 404)."""
    tok, home = U._tok_i_dim(base)
    params = {"vyd": vyd, "status": status, "after": after}
    return U._request("GET", f"{home}/opysy/admin/peredachi?{urlencode(params)}", auth=tok)


def peredachu_zavantazhyty(url: str, kudy: Path, sha256: str) -> int:
    """Байти передачі за підписаним посиланням — у файл, потоком; відбиток мусить збігтися з тим,
    що прийняв сервер, інакше файл геть і `UploadError`."""
    import hashlib

    import httpx

    from nyshporka.sources.http import proxy_url, transport

    kudy = Path(kudy)
    kudy.parent.mkdir(parents=True, exist_ok=True)
    part = kudy.with_name(kudy.name + ".part")
    h = hashlib.sha256()
    n = 0
    try:
        with httpx.Client(transport=transport(proxy_url()), timeout=600.0) as c, \
                c.stream("GET", url) as r:
            if r.status_code >= 400:
                raise U.UploadError(f"сховище відповіло {r.status_code}", status=r.status_code)
            with part.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise U.UploadError(f"не завантажилось: {exc}") from exc
    if h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise U.UploadError("відбиток завантаженого не збігся з прийнятим сервером")
    part.replace(kudy)
    return n


def peredacha_zabrano(peredacha: int, sha256: str, *, base: str = "") -> dict[str, Any]:
    """Власник забрав і звірив: сервер прибирає об'єкт зі сховища (рядок лишається слідом)."""
    tok, home = U._tok_i_dim(base)
    return U._request("POST", f"{home}/opysy/admin/peredachi/{int(peredacha)}/zabrano",
                      body={"sha256": sha256}, auth=tok)


def skan_na_commons(peredacha: int, url: str, *, base: str = "") -> dict[str, Any]:
    """Скан опубліковано на Commons: сервер звіряє SHA-1 файлу там і дописує адресу в джерела."""
    tok, home = U._tok_i_dim(base)
    return U._request("POST", f"{home}/opysy/admin/skany/{int(peredacha)}/commons",
                      body={"url": url}, auth=tok)


def umovy(*, base: str = "") -> dict[str, Any]:
    """Чи прийняла людина чинні умови Засік і де їх прочитати."""
    tok, home = U._tok_i_dim(base)
    return U._request("GET", f"{home}/opysy/umovy", auth=tok)


def search(q: str, *, repo: str = "", fond: str = "", limit: int = 50,
           base: str = "") -> dict[str, Any]:
    """Нечіткий пошук по описах. Хто має доступ, вирішує сервер (бета-тест, вхід, норми) і сам
    пояснює відмову: клієнт не відмовляє за нього — перемкнути доступ можна без нового релізу."""
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


def _z_kliuchem(base: str) -> tuple[str, str]:
    """Словник і правила — лише людині з ключем: без нього пул відповідає 401/404."""
    tok, home = U._tok_i_dim(base)
    return tok, home


def names(repo: str, fond: str, *, opys: str = "", q: str = "", page: int = 1,
          base: str = "") -> dict[str, Any]:
    """Кластери власних назв фонду: написання з частотами, сусіди, правило, приклади (rk)."""
    tok, home = _z_kliuchem(base)
    params: dict[str, Any] = {"repo": repo, "fond": fond, "storinka": page}
    if opys:
        params["opys"] = opys
    if q:
        params["q"] = q
    return U._request("GET", f"{home}/opysy/nazvy?{urlencode(params)}", auth=tok)


def rules(repo: str, *, fond: str = "", state: str = "", base: str = "") -> dict[str, Any]:
    tok, home = _z_kliuchem(base)
    params = {"repo": repo, "fond": fond, "stan": state}
    return U._request("GET", f"{home}/opysy/pravyla?{urlencode(params)}", auth=tok)


def rule_add(repo: str, fond: str, variants: list[str], to: str, *, evidence: str,
             opys: str = "", kind: str = "prizvyshche", reason: str = "",
             base: str = "") -> dict[str, Any]:
    """Правило «варіанти → форма». Без права на всі внески межі пул ставить його в чергу."""
    tok, home = _z_kliuchem(base)
    body = {"repo": repo, "fond": fond, "opys": opys, "z": variants, "na": to, "vyd": kind,
            "dokaz": evidence, "prychyna": reason}
    return U._request("POST", f"{home}/opysy/pravyla", body=body, auth=tok)


def rule_undo(rule_id: int, *, reason: str = "", base: str = "") -> dict[str, Any]:
    tok, home = _z_kliuchem(base)
    return U._request("POST", f"{home}/opysy/pravyla/{int(rule_id)}/vidkotyty",
                      body={"prychyna": reason}, auth=tok)


# ── обмін нормалізацією (рішення дослідника 25.11.2026) ──────────────────────


def obmin_cherha(*, base: str = "") -> dict[str, Any]:
    tok, home = _z_kliuchem(base)
    return U._request("GET", f"{home}/opysy/obmin", auth=tok)


def obmin_vziaty(*, vnesok: int | None = None, base: str = "") -> dict[str, Any]:
    tok, home = _z_kliuchem(base)
    return U._request("POST", f"{home}/opysy/obmin/take",
                      body={} if vnesok is None else {"vnesok": int(vnesok)}, auth=tok)


def obmin_viddaty(obmin_id: int, *, model: str, vidpovidi: list[dict[str, str]],
                  base: str = "") -> dict[str, Any]:
    tok, home = _z_kliuchem(base)
    return U._request("POST", f"{home}/opysy/obmin/{int(obmin_id)}/give",
                      body={"model": model, "vidpovidi": vidpovidi}, auth=tok)
