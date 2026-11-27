"""Хмарне читання опису: етапи `nysh opys read` через `nysh cloud go`, як для справ.

Опис читається трьома етапами, і кожен може їхати в хмару:
- `storinky` — цілі сторінки рукописного опису (Писар + Дяк), вихід — прогін `run`;
- `kropy` — кропи колонки № (`opysy.dochyt`) цілими рядками (`-p whole_line=1`);
- `druk` — машинописний опис рушієм друку (`--print --not-an-edition`), вихід — розмітка VL.

Транспорт — той самий, що в справ: `cloud go` сам везе кадри об'єктним сховищем, якщо воно
налаштоване, інакше просто на машину (`--transport auto`). Рішення про запуск — теж його: до
стелі автозапуску захід іде без людини, понад неї — лише з `--confirm` ЛЮДИНИ.

Захід відчеплений: `opys read` ставить його й виходить, а повтор тієї самої команди забирає
результат, коли диск каже, що все прочитано (повнота — за файлами, не за станом наглядача).

🔴 Ім'я теки, яку бачить `cloud go`, — це і тека результату, і ключ архіву кадрів у сховищі.
Тому кадри кожного етапу подаються під унікальним іменем (`<опис>-<етап>`), жорсткими
посиланнями на ті самі файли, без копії на диску.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

FILE = "hmara.json"
DIR = "hmara"
ETAPY = ("storinky", "kropy", "druk")
#: Що вважається прочитаною сторінкою в теці результату етапу.
VYHID = {"storinky": "*.txt", "kropy": "*.txt", "druk": "*.md"}


#: Збирач відкладених заходів: поки він стоїть (`nysh opys read` на кілька тек), етап не ставить
#: свого заходу, а лишає запит тут, і всі теки їдуть ОДНИМ `cloud go` — одна черга на одну машину.
#: 🔴 Без цього кожна тека орендувала свою машину: накладні заходу (від кількох центів на рукописі до
#: ~$0.2 на машинописі) — незалежно від обсягу (27.11.2026 — 110 заходів на 429 сторінок, $5.35).
ZBIR: ContextVar[list[dict[str, Any]] | None] = ContextVar("opysy_hmara_zbir", default=None)


class HmaraError(RuntimeError):
    """Захід не поставлено: причина людською мовою (відмова `cloud go`, немає плагіна оренди).
    `zghoda` — відмова лише за стелею автозапуску: потрібен `--confirm` людини, а не інше місце."""

    def __init__(self, why: str, *, zghoda: bool = False) -> None:
        super().__init__(why)
        self.zghoda = zghoda


def slug(d: Path) -> str:
    """Ім'я опису для теки результату й ключа сховища: латиниця, цифри, дефіси + відбиток шляху."""
    from nyshporka.opysy import workdir as W
    from nyshporka.utils.text import slugify

    pas = W.load(Path(d))
    base = slugify("-".join(str(pas.get(k) or "") for k in ("repo", "fond", "opys"))) or "opys"
    vidbytok = hashlib.sha1(str(Path(d).resolve()).encode("utf-8")).hexdigest()[:6]
    return f"opys-{base}-{vidbytok}"


def _stan_file(d: Path) -> Path:
    return Path(d) / FILE


def stan(d: Path) -> dict[str, Any]:
    """Стан хмарних етапів опису. Битий файл (обрив запису) — як порожній: етап поставиться
    знову, а не кожен `read` падатиме до ручного видалення."""
    p = _stan_file(d)
    if not p.exists():
        return {}
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return got if isinstance(got, dict) else {}


def zapysaty_stan(d: Path, s: dict[str, Any]) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(_stan_file(d), json.dumps(s, ensure_ascii=False, indent=1))


def _zapysaty(d: Path, etap: str, zap: dict[str, Any]) -> None:
    s = stan(d)
    s[etap] = zap
    zapysaty_stan(d, s)


def zabuty(d: Path, etap: str) -> None:
    """Зняти етап зі стану: наступний `read` поставить його знову."""
    s = stan(d)
    if s.pop(etap, None) is not None:
        zapysaty_stan(d, s)


def _kadry(teka: Path) -> list[Path]:
    return sorted(p for p in Path(teka).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def _podaty(d: Path, etap: str, kadry: Path, mitka: str = "") -> Path:
    """Тека кадрів етапу під унікальним іменем — жорсткі посилання (інакше копії).

    Тека складається наново щоразу: кропи, перерізані після зміни метаданих, мають ті самі імена, і
    старе посилання тримало б старий вміст. `mitka` (відбиток метаданих) дає новому заходу нове ім'я —
    отже й нову теку результату, без чужого старого тексту в ній."""
    teka = Path(d) / DIR / (f"{slug(d)}-{etap}" + (f"-{mitka}" if mitka else ""))
    if teka.exists():
        shutil.rmtree(teka)
    teka.mkdir(parents=True, exist_ok=True)
    for k in _kadry(kadry):
        dest = teka / k.name
        try:
            os.link(k, dest)
        except OSError:
            shutil.copy2(k, dest)
    return teka


def _cloud_go(args: list[str]) -> tuple[int, dict[str, Any], str]:
    """`nysh cloud go … --json` тим самим інтерпретатором: (код, підсумок, хвіст виводу)."""
    cmd = [sys.executable, "-m", "nyshporka", "cloud", "go", *args, "--json"]
    # 🔴 Дитина пише в трубу кодуванням консолі (cp1251, cp1252), а читається підсумок як UTF-8:
    # кирилиця в `out_dir` ставала «?», і результат заходу не знаходився (відгук №28, 27.11.2026).
    # Лише `PYTHONIOENCODING`: `PYTHONUTF8` змінив би й кодування файлів, а його успадкує наглядач.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       check=False, env=env)
    pidsumok: dict[str, Any] = {}
    for line in reversed((p.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                pidsumok = json.loads(line)
                break
            except ValueError:
                continue
    khvist = "\n".join(((p.stderr or "") + "\n" + (p.stdout or "")).strip().splitlines()[-6:])
    return p.returncode, pidsumok, khvist


def postavyty(d: Path, etap: str, kadry: Path, *, script: str = "", params: list[str] | None = None,
              confirm: bool = False, mitka: str = "") -> dict[str, Any]:
    """Поставити захід етапу однієї теки. Повертає запис стану: `run_id`, `out_dir`, рішення, вилку.

    Відмова `cloud go` (немає плагіна оренди, ключа, балансу, понад стелю автозапуску) —
    `HmaraError` з його ж причиною: людина бачить, що зробити, а не «код 2»."""
    got = postavyty_razom([{"d": d, "etap": etap, "kadry": kadry, "script": script, "mitka": mitka}],
                          params=params, confirm=confirm)[str(Path(d))]
    if isinstance(got, HmaraError):
        raise got
    return got


def _toi_samyi_shliakh(a: str | Path, b: str | Path) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except (OSError, ValueError):
        return False


def _korin_druku(teky: list[Path]) -> Path:
    """Куди рушій друку кладе результат спільного заходу кількох описів.

    Одна тека — як і досі, `<тека>/hmara/vyhid`. Кілька — не в теку одного з описів (платний вихід
    чужих описів не має жити там, де його знесуть разом з одним), а в простір, `data/derived/opysy`.
    Кожна тека однаково забирає свій результат копією (`zabraty`)."""
    if len(teky) == 1:
        return Path(teky[0]) / DIR / "vyhid"
    try:
        from nyshporka.core.workspace import workspace

        return workspace().derived / "opysy" / "hmara-vyhid"
    except Exception:
        return Path(teky[0]) / DIR / "vyhid"


def postavyty_razom(zapyty: list[dict[str, Any]], *, params: list[str] | None = None,
                    confirm: bool = False) -> dict[str, dict[str, Any] | HmaraError]:
    """Один захід `cloud go` на кілька тек того самого етапу й письма: одна черга, одна машина.

    `zapyty` — `{"d", "etap", "kadry", "script", "mitka"}` на теку. Повертає на кожну теку
    (`str(d)`) або записаний стан етапу, або `HmaraError`. Відмова всього заходу (понад стелю,
    немає оренди) — та сама помилка всім: 🔴 жодного заходу «по одному» замість відмови.
    Справу черги зіставляється з текою за шляхом (`cases[].case_dir`), не за порядком; тека, якої
    захід не взяв (`dropped`) чи не назвав, дістає помилку й не дістає стану."""
    if not zapyty:
        return {}
    etap = zapyty[0]["etap"]
    script = zapyty[0].get("script") or ""
    if etap not in ETAPY or any(z["etap"] != etap or (z.get("script") or "") != script for z in zapyty):
        raise ValueError("один захід — один етап і одне письмо")
    teky = [_podaty(z["d"], etap, z["kadry"], z.get("mitka") or "") for z in zapyty]
    # теку етапу склали щойно й цілком — запобіжник «тека ще качається» (кадр молодший 5 хв) тут хибний
    args = [*map(str, teky), "--allow-partial"]
    if etap == "druk":
        args += ["--print", "--not-an-edition", "--out-root",
                 str(_korin_druku([Path(z["d"]) for z in zapyty]))]
    elif script:
        args += ["--script", script]
    for p in (params or []):
        args += ["-p", p]
    if etap == "kropy":
        args += ["-p", "whole_line=1"]
    if confirm:
        args.append("--confirm")
    kod, res, khvist = _cloud_go(args)
    verdict = str(res.get("verdict") or "")
    out: dict[str, dict[str, Any] | HmaraError] = {}
    if verdict not in ("detached", "ok"):
        why = str(res.get("why") or "") or khvist or f"код {kod}"
        if res.get("launch") == "needs_confirm":
            err = HmaraError(f"кошторис понад стелю автозапуску (до ${res.get('fork_high')}) — запустити "
                             f"може лише людина: та сама команда з `--confirm`. {why}", zghoda=True)
        else:
            err = HmaraError(why)
        return {str(Path(z["d"])): err for z in zapyty}
    cases = [c for c in (res.get("cases") or []) if isinstance(c, dict)]
    teper = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for z, teka in zip(zapyty, teky, strict=True):
        if len(zapyty) == 1:
            # одна тека — рівно як до 0.49.7: верхні поля відповіді, `cases[0]` — запасом
            c0 = cases[0] if cases else {}
            case: dict[str, Any] | None = {"run_id": res.get("run_id") or c0.get("run_id"),
                                           "out_dir": res.get("out_dir") or c0.get("out_dir")}
        else:
            # за шляхом теки або за `run_id`, що починається з імені теки етапу (у ньому відбиток
            # шляху опису, тож воно не повторюється між описами); за порядком — ніколи
            case = next((c for c in cases
                         if _toi_samyi_shliakh(c.get("case_dir") or "", teka)
                         or str(c.get("run_id") or "").split("__", 1)[0] == teka.name), None)
        if case is None or not case.get("run_id"):
            vypalo = next((x for x in (res.get("dropped") or [])
                           if isinstance(x, dict) and _toi_samyi_shliakh(x.get("case") or "", teka)), None)
            out[str(Path(z["d"]))] = HmaraError(
                "захід не взяв цю теку" + (f": {vypalo.get('why')}" if vypalo and vypalo.get("why") else ""))
            continue
        zap = {"run_id": case.get("run_id") or "", "out_dir": case.get("out_dir") or "",
               "teka": str(teka), "kadriv": len(_kadry(teka)), "verdict": verdict,
               "mitka": z.get("mitka") or "", "fork_high": res.get("fork_high"),
               "budget_usd": res.get("budget_usd"), "postavleno": teper}
        if len(zapyty) > 1:
            zap["razom"] = len(zapyty)   # скільки тек поїхало цим заходом
        st = _reiestr(str(zap["run_id"] or ""))
        if st is not None and st.out_dir:
            zap["out_dir"] = st.out_dir   # реєстр пише наглядач у UTF-8 — адреса з нього надійніша
        _zapysaty(z["d"], etap, zap)
        out[str(Path(z["d"]))] = zap
    return out


def _reiestr(run_id: str) -> Any:
    """Запис заходу в реєстрі хмари (`cloud.state`) — або None."""
    if not run_id:
        return None
    try:
        from nyshporka.cloud import state as ST

        return ST.load(run_id)
    except Exception:
        return None


def teka_vyhodu(zap: dict[str, Any]) -> Path | None:
    """Тека результату етапу: записана в стані, якщо вона є на диску, інакше — з реєстру хмари.

    🔴 Стан пише `out_dir` з виводу дочірнього `cloud go`, а реєстр — сам наглядач у файл UTF-8.
    До 0.49.6 вивід дитини губив кирилицю («?»), і записана адреса не існувала, хоча результат
    лежав на диску (відгук №28)."""
    p = str(zap.get("out_dir") or "")
    if p and Path(p).is_dir():
        return Path(p)
    st = _reiestr(str(zap.get("run_id") or ""))
    if st is not None and st.out_dir and Path(st.out_dir).is_dir():
        return Path(st.out_dir)
    return None


def uspikh(zap: dict[str, Any]) -> bool:
    """Реєстр хмари каже, що захід скінчився успішно (`done` · `ok`)."""
    st = _reiestr(str(zap.get("run_id") or ""))
    return st is not None and st.phase == "done" and st.verdict == "ok"


def _zrobleno(out: Path, etap: str) -> set[str]:
    """Прочитані кадри в теці результату. Прочитана — є вихід АБО рушій записав сторінку в мету
    прогону: порожня сторінка чи кроп без числа тексту не мають, і без мети «прочитано N−1 з N» не
    минало б ніколи (так рахує й локальне читання)."""
    zrobleno = {p.name.split(".")[0] for p in out.glob(VYHID[etap])}
    meta = out / "_htr_meta.json"
    if etap != "druk" and meta.exists():
        with contextlib.suppress(ValueError, OSError, AttributeError):
            zrobleno |= {Path(k).stem for k in (json.loads(meta.read_text(encoding="utf-8"))
                                                .get("pages") or {})}
    return zrobleno


def gotovo(d: Path, etap: str) -> tuple[int, int]:
    """(прочитано, кадрів) етапу — за файлами в теці результату (`_zrobleno`)."""
    zap = stan(d).get(etap) or {}
    vsi = int(zap.get("kadriv") or 0)
    out = teka_vyhodu(zap)
    if out is None:
        return 0, vsi
    kadry = {p.stem for p in _kadry(Path(zap["teka"]))} if Path(zap.get("teka") or "").is_dir() else set()
    zrobleno = _zrobleno(out, etap)
    return len(zrobleno & kadry) if kadry else len(zrobleno), vsi


def _toi_samyi(a: str | Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (OSError, ValueError):
        return False


def pidkhopyty(d: Path, etap: str, mitka: str = "") -> dict[str, Any] | None:
    """Готовий захід етапу з реєстру хмари, коли стан теки його не пам'ятає.

    0.49.5 стирав стан етапу, не знайшовши результату за зіпсованою адресою (відгук №28), і
    наступний `read` поставив би платний захід удруге. Тут береться останній захід, що прочитав
    саме цю теку кадрів (та сама мітка метаданих — те саме ім'я теки) успішно й повністю: кожен
    її кадр має вихід. Неповний чи чужий не береться — тоді захід ставиться, як і раніше."""
    teka = Path(d) / DIR / (f"{slug(d)}-{etap}" + (f"-{mitka}" if mitka else ""))
    if not teka.is_dir():
        return None
    kadry = {p.stem for p in _kadry(teka)}
    if not kadry:
        return None
    try:
        from nyshporka.cloud import state as ST

        runs = ST.all_runs()
    except Exception:
        return None
    best: Any = None
    for st in runs:
        if st.phase != "done" or st.verdict != "ok" or not st.case_dir or not st.out_dir:
            continue
        if not _toi_samyi(st.case_dir, teka) or not Path(st.out_dir).is_dir():
            continue
        if not kadry <= _zrobleno(Path(st.out_dir), etap):
            continue
        if best is None or st.updated > best.updated:
            best = st
    if best is None:
        return None
    zap = {"run_id": best.run_id, "out_dir": best.out_dir, "teka": str(teka), "kadriv": len(kadry),
           "verdict": "ok", "mitka": mitka, "pidkhopleno": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                         time.gmtime())}
    _zapysaty(d, etap, zap)
    return zap


def prychyna(zap: dict[str, Any]) -> str:
    """Чим скінчився захід етапу — людською мовою зі стану (`market_empty`, причина наглядача)."""
    try:
        from nyshporka.cloud import state as ST

        st = ST.load(str(zap.get("run_id") or ""))
    except Exception:
        return ""
    if st is None:
        return ""
    return " · ".join(x for x in (st.verdict, st.why) if x)


def skinchyvsia(zap: dict[str, Any]) -> bool:
    """Захід етапу вже не читає: наглядач записав кінець (`done` / `failed`). Відчеплений запис, що
    ще стоїть «читає», спершу звіряється з наглядачем (`settle_open`). Невідомо — False: краще
    почекати ще один повтор, ніж забрати недочитане."""
    run_id = str(zap.get("run_id") or "")
    if not run_id:
        return False
    try:
        from nyshporka.cloud import state as ST
        from nyshporka.cloud import supervised as SUP

        st = ST.load(run_id)
        if st is None:
            return False
        if st.phase not in ("done", "failed"):
            SUP.settle_open([st])
            st = ST.load(run_id) or st
        return st.phase in ("done", "failed")
    except Exception:
        return False


def zabraty(d: Path, etap: str, kudy: Path) -> int:
    """Результат етапу — у `kudy` (копія: тека результату лишається за наглядачем)."""
    zap = stan(d).get(etap) or {}
    out = teka_vyhodu(zap)
    kudy = Path(kudy)
    kudy.mkdir(parents=True, exist_ok=True)
    n = 0
    if out is None:
        return 0
    zap["out_dir"] = str(out)   # адреса з реєстру заступає зіпсовану з виводу дитини
    for f in out.iterdir():
        if f.is_file():
            shutil.copy2(f, kudy / f.name)
            n += 1
    zap["zabrano"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _zapysaty(d, etap, zap)
    return n


def zabraty_tekou(vid: Path, kudy: Path) -> int:
    """Уся тека результату (сестринський голос) — у `kudy`."""
    kudy = Path(kudy)
    kudy.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in Path(vid).iterdir():
        if f.is_file():
            shutil.copy2(f, kudy / f.name)
            n += 1
    return n


def vl_do_run(vl: Path, run: Path, pages: Path) -> int:
    """Розмітка рушія друку → прогін `run`, який бачать таблиця, пакет і пошук.

    Текст сторінки — `NNNN.txt` рушія; мета прогону — модель друку; геометрія — лише розмір
    сторінки (пакет рахує місце справи в частках сторінки, а VL дає одну рамку на таблицю)."""
    from PIL import Image

    from nyshporka.htr.layout import write_geometry

    run = Path(run)
    run.mkdir(parents=True, exist_ok=True)
    n = 0
    for md in sorted(Path(vl).glob("*.md")):
        stem = md.stem
        src = next((p for p in (Path(pages) / f"{stem}.jpg", Path(pages) / f"{stem}.png") if p.exists()), None)
        if src is None:
            continue
        txt = Path(vl) / f"{stem}.txt"
        (run / f"{stem}.txt").write_text(txt.read_text(encoding="utf-8") if txt.exists()
                                         else md.read_text(encoding="utf-8"), encoding="utf-8")
        w, h = Image.open(src).size
        write_geometry(run, stem, {"boxes": [], "size": [w, h]})
        n += 1
    (run / "_htr_meta.json").write_text(json.dumps({"model": "paddleocr_vl", "engine": "print"}),
                                        encoding="utf-8")
    return n
