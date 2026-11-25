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
from pathlib import Path
from typing import Any

FILE = "hmara.json"
DIR = "hmara"
ETAPY = ("storinky", "kropy", "druk")
#: Що вважається прочитаною сторінкою в теці результату етапу.
VYHID = {"storinky": "*.txt", "kropy": "*.txt", "druk": "*.md"}


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
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       check=False)
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
    """Поставити захід етапу. Повертає запис стану: `run_id`, `out_dir`, рішення, вилку.

    Відмова `cloud go` (немає плагіна оренди, ключа, балансу, понад стелю автозапуску) —
    `HmaraError` з його ж причиною: людина бачить, що зробити, а не «код 2»."""
    if etap not in ETAPY:
        raise ValueError(etap)
    teka = _podaty(d, etap, kadry, mitka)
    # теку етапу склали щойно й цілком — запобіжник «тека ще качається» (кадр молодший 5 хв) тут хибний
    args = [str(teka), "--allow-partial"]
    if etap == "druk":
        args += ["--print", "--not-an-edition", "--out-root", str(Path(d) / DIR / "vyhid")]
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
    if verdict not in ("detached", "ok"):
        why = str(res.get("why") or "") or khvist or f"код {kod}"
        if res.get("launch") == "needs_confirm":
            raise HmaraError(f"кошторис понад стелю автозапуску (до ${res.get('fork_high')}) — запустити "
                             f"може лише людина: та сама команда з `--confirm`. {why}", zghoda=True)
        raise HmaraError(why)
    zap = {"run_id": res.get("run_id") or "", "out_dir": res.get("out_dir") or "",
           "teka": str(teka), "kadriv": len(_kadry(teka)), "verdict": verdict, "mitka": mitka,
           "fork_high": res.get("fork_high"), "budget_usd": res.get("budget_usd"),
           "postavleno": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not zap["out_dir"] and res.get("cases"):
        zap["out_dir"] = res["cases"][0].get("out_dir") or ""
    _zapysaty(d, etap, zap)
    return zap


def gotovo(d: Path, etap: str) -> tuple[int, int]:
    """(прочитано, кадрів) етапу — за файлами в теці результату. Прочитана — є вихід АБО рушій
    записав сторінку в мету прогону: порожня сторінка чи кроп без числа тексту не мають, і без мети
    «прочитано N−1 з N» не минало б ніколи (так рахує й локальне читання)."""
    zap = stan(d).get(etap) or {}
    out = Path(zap.get("out_dir") or "")
    vsi = int(zap.get("kadriv") or 0)
    if not zap.get("out_dir") or not out.is_dir():
        return 0, vsi
    kadry = {p.stem for p in _kadry(Path(zap["teka"]))} if Path(zap.get("teka") or "").is_dir() else set()
    zrobleno = {p.name.split(".")[0] for p in out.glob(VYHID[etap])}
    meta = out / "_htr_meta.json"
    if etap != "druk" and meta.exists():
        with contextlib.suppress(ValueError, OSError, AttributeError):
            zrobleno |= {Path(k).stem for k in (json.loads(meta.read_text(encoding="utf-8"))
                                                .get("pages") or {})}
    return len(zrobleno & kadry) if kadry else len(zrobleno), vsi


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
    out = Path(zap.get("out_dir") or "")
    kudy = Path(kudy)
    kudy.mkdir(parents=True, exist_ok=True)
    n = 0
    if not zap.get("out_dir") or not out.is_dir():
        return 0
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
