"""Іменовані операції, які пул виконує на сервері: перелік, запуск, стан, скасування.

Клієнт нічого не знає про самі операції: назви, описи, підказки й причини
відмов приходять від сервера як є. Тут лише транспорт — запит, ключ
повторності й розбір відмови.

🔴 Номери незакритих викликів лежать у стані користувача, щоб хук старту сесії міг сказати про
них БЕЗ мережі: `PRIVACY.md` обіцяє, що `nysh` сам у мережу не ходить. Дізнається, що готове,
агент уже явним запитом `nysh share hotove`.

🔴 `pasport` у результаті — непрозорий словник від сервера. Клієнт пише його
цілком у `_supriaha_vyklyk.json` і не читає жодного поля, крім `pidkazka`
(текст для людини).
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from nyshporka.share import catalog as C
from nyshporka.utils.atomic import atomic_write_text

#: Тека скіла в агента. Ім'я нейтральне: текст приходить від сервера лише людині, якій він є.
SKIL = "supriaha-operatsii"
OPYS_MAKS = 1000
TEKST_MAKS = 4000
#: Причини, за яких новий запит не змінить відповіді: повтор лише стукає в сервер.
PAUZA_PRYCHYNY = ("odnochasno", "chasto")


class Vidmova(C.PoolError):
    """Відмова сервера з текстом для людини (`povidomlennia`) і паузою (`retry_after`)."""

    def __init__(self, message: str, *, status: int | None = None,
                 retry_after: int | None = None, prychyna: str = "",
                 vycherpano: bool = False) -> None:
        super().__init__(message, status=status)
        self.retry_after = retry_after
        self.prychyna = prychyna
        #: Вікно заповнене до краю. Неповне не тримає паузи: менший обсяг ще може пройти.
        self.vycherpano = vycherpano


def _vidmova(exc: Exception) -> Vidmova:
    """Відмова з тіла відповіді: `detail.povidomlennia`, `detail.retry_after`."""
    status = getattr(exc, "status", None)
    detail: Any = None
    try:
        detail = json.loads(str(getattr(exc, "body", "") or "")).get("detail")
    except (ValueError, AttributeError):
        detail = None
    tekst, pauza, prychyna, vycherpano = "", None, "", False
    if isinstance(detail, dict):
        tekst = str(detail.get("povidomlennia") or "")
        prychyna = str(detail.get("prychyna") or "")
        if str(detail.get("retry_after") or "").isdigit():
            pauza = int(detail["retry_after"])
        vikna = detail.get("vikna")
        vycherpano = isinstance(vikna, dict) and any(
            isinstance(v, dict) and int(v.get("vykorystano") or 0) >= int(v.get("mezha") or 0) > 0
            for v in vikna.values())
    elif isinstance(detail, str):
        tekst = detail
    return Vidmova(tekst or C.reason(exc), status=status, retry_after=pauza, prychyna=prychyna,
                   vycherpano=vycherpano)


def _rozibraty(resp: Any) -> dict[str, Any]:
    try:
        got = json.loads(resp.text)
    except ValueError:
        raise C.PoolError("пул відповів не JSON") from None
    if not isinstance(got, dict):
        raise C.PoolError("пул відповів не тим, чого чекали")
    return got


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    from nyshporka.sources.http import HttpError

    try:
        resp = C._fetcher(url, accept_json=True).post(url, json_body=body)
    except HttpError as exc:
        if exc.status == 401:
            raise C.PotribenKliuch(C.KLIUCH_TEXT, status=401) from exc
        raise _vidmova(exc) from exc
    return _rozibraty(resp)


def _get(url: str) -> dict[str, Any]:
    """Як `catalog._get`, але відмова несе текст сервера."""
    from nyshporka.sources.http import HttpError

    try:
        resp = C._fetcher(url, accept_json=True).get(url)
    except HttpError as exc:
        if exc.status == 401:
            raise C.PotribenKliuch(C.KLIUCH_TEXT, status=401) from exc
        raise _vidmova(exc) from exc
    return _rozibraty(resp)


def novyi_kliuch() -> str:
    return secrets.token_hex(16)


def perelik(base: str = "") -> dict[str, Any]:
    return _get(f"{C.base_url(base)}/m/perelik")


def dovidka(base: str = "") -> dict[str, Any]:
    return _get(f"{C.base_url(base)}/m/dovidka")


def zapustyty(operatsiia: str, parametry: dict[str, str], kliuch: str = "",
              base: str = "") -> dict[str, Any]:
    """Новий виклик (201) або повтор за ключем (200). Ключ без вказівки — свій.

    Поки сервер велів чекати, запит не йде: відмову дає сам клієнт, і ця стриманість не залежить
    від того, що вирішить агент."""
    _pereviryty_pauzu(operatsiia)
    try:
        return _post(f"{C.base_url(base)}/m/vyklyky",
                     {"operatsiia": operatsiia, "parametry": parametry,
                      "kliuch": kliuch or novyi_kliuch()})
    except Vidmova as exc:
        _zapamiataty_pauzu(operatsiia, exc)
        raise


def _pauzy() -> dict[str, Any]:
    from nyshporka.core import workspace as W

    got = W.state_all().get(W.KEY_SUPRIAHA_PAUZY)
    return dict(got) if isinstance(got, dict) else {}


def _pereviryty_pauzu(operatsiia: str) -> None:
    zapys = _pauzy().get(operatsiia)
    if not isinstance(zapys, dict):
        return
    zalyshok = int(float(zapys.get("do") or 0) - time.time()) + 1
    if zalyshok > 1:
        raise Vidmova(str(zapys.get("tekst") or "сервер велів зачекати"), status=429,
                      retry_after=zalyshok, prychyna=str(zapys.get("prychyna") or ""))


def _zapamiataty_pauzu(operatsiia: str, exc: Vidmova) -> None:
    if not exc.retry_after or not (exc.prychyna in PAUZA_PRYCHYNY or exc.vycherpano):
        return
    from nyshporka.core import workspace as W

    W.state_set(**{W.KEY_SUPRIAHA_PAUZY: {**_pauzy(), operatsiia: {
        "do": time.time() + exc.retry_after, "tekst": str(exc), "prychyna": exc.prychyna}}})


def zniaty_pauzy() -> None:
    """Забране чи скасоване звільнило місце: чекати більше нема чого."""
    from nyshporka.core import workspace as W

    if _pauzy():
        W.state_set(**{W.KEY_SUPRIAHA_PAUZY: {}})


def _vidkryti() -> list[int]:
    from nyshporka.core import workspace as W

    got = W.state_all().get(W.KEY_SUPRIAHA_VYKLYKY)
    return [int(x) for x in got if isinstance(x, int)] if isinstance(got, list) else []


def _zapysaty(vidkryti: list[int]) -> None:
    from nyshporka.core import workspace as W

    W.state_set(**{W.KEY_SUPRIAHA_VYKLYKY: sorted(set(vidkryti))})


def zapamiataty(vid: int) -> None:
    _zapysaty([*_vidkryti(), vid])


def zabuty(vid: int) -> None:
    _zapysaty([v for v in _vidkryti() if v != vid])


def _teky_skila() -> list[Path]:
    """Лише теки наявних агентів: тек, яких людина не заводила, ми не створюємо."""
    from nyshporka import skills as S

    out = []
    if (Path.home() / ".claude").is_dir():
        out.append(Path.home() / S.AGENT_DIRS["claude"] / SKIL)
    if S.codex_present():
        out.append(Path.home() / S.AGENT_DIRS["codex"] / SKIL)
    return out


def polozhyty_skil(skil: Any) -> list[str]:
    """Скіл від сервера — у теки агентів: нова сесія знатиме про операції сама, без підказки людини.

    Сервер дає лише опис і текст; ім'я й місце тут. Файл належить клієнту й оновлюється з кожною
    довідкою. Пише його лише явна команда `share dovidka`, а не встановлення пакета.
    """
    if not isinstance(skil, dict) or not skil.get("opys") or not skil.get("tekst"):
        return []
    opys = " ".join(str(skil["opys"]).split())[:OPYS_MAKS]
    tekst = str(skil["tekst"])[:TEKST_MAKS]
    karta = (f"---\nname: {SKIL}\ndescription: {json.dumps(opys, ensure_ascii=False)}\n---\n\n"
             f"{tekst.rstrip()}\n")
    out = []
    for teka in _teky_skila():
        try:
            teka.mkdir(parents=True, exist_ok=True)
            atomic_write_text(teka / "SKILL.md", karta, newline="\n")
        except OSError:
            continue                      # нагадування хука лишається, це лише зручність
        out.append(str(teka))
    return out


def prybraty_skil() -> None:
    """Людину вивели з кола: двері зачинено, агентові нема чого їх шукати."""
    for teka in _teky_skila():
        try:
            (teka / "SKILL.md").unlink(missing_ok=True)
            teka.rmdir()
        except OSError:
            pass


def hotove(base: str = "") -> dict[str, Any]:
    """Що чекає на людину: скачане й те, що ще в роботі. Відповідь сервера правдивіша за локальний
    запис, тож він оновлюється з неї: виклик, закритий з іншої машини, більше не нагадає про себе."""
    d = _get(f"{C.base_url(base)}/m/hotove")
    _zapysaty([int(r["id"]) for r in [*d.get("hotovo", []), *d.get("zhyvi", [])]])
    return d


def pochaty(vid: int, base: str = "") -> dict[str, Any]:
    """Згода людини на роботу, що чекала на перегляд."""
    return _post(f"{C.base_url(base)}/m/vyklyky/{vid}/pochaty", {})


def stan(vid: int, base: str = "") -> dict[str, Any]:
    return _get(f"{C.base_url(base)}/m/vyklyky/{vid}")


def skasuvaty(vid: int, base: str = "") -> dict[str, Any]:
    return _post(f"{C.base_url(base)}/m/vyklyky/{vid}/skasuvaty", {})


def rezultat(vid: int, base: str = "") -> dict[str, Any]:
    """Повний результат готового виклику — у тому вигляді, який дає сервер."""
    return _get(f"{C.base_url(base)}/m/vyklyky/{vid}/rezultat")


def dia(vid: int, tilo: dict[str, Any], base: str = "") -> dict[str, Any]:
    """Дія людини над результатом свого виклику (вердикт рядкові, закрити). Що вміє виклик,
    вирішує сервер: виклик без дій відповідає 404."""
    return _post(f"{C.base_url(base)}/m/vyklyky/{vid}/dia", tilo)
