"""Звірка двох середовищ рушіїв на тих самих кадрах — сегментація й тексти побайтово.

Навіщо. Кеш сегментації (`data/derived/htr_seg`) несе у ключі версію kraken:
інший kraken може дати інші полігони рядків, тобто інший текст, без жодного
сліду в лозі. Тому кеш, порахований однією версією, раннер іншої версії не
бере — і після оновлення kraken кожна справа пересегментовувалась би заново
(понад сто тисяч записів, 7–20 с на сторінку). Пару версій можна оголосити
одним родоводом сегментації (`runner.SEG_LINEAGE`) лише тоді, коли тотожність
ДОВЕДЕНО прогоном, а не виведено зі збігу файлів бібліотеки. Цей скрипт і є
такий прогін.

Що робить. Той самий `runner.py` (з усіма патчами, як у бою) читає ту саму теку
кадрів двічі: інтерпретатором середовища A і середовища B, кожен у свою теку
виходу й свою теку кешу. Потім звіряє побайтово:
- `seg` у кожному кеш-блобі (полігони, базові лінії, порядок рядків);
- `<стор>.lines.json` (рамки й полігони рядків, з яких ріжуться кропи);
- тексти основної моделі й кожного голосу (`<out>-<тег>`).
Ключ кешу НЕ звіряється — він законно різний (у ньому версія kraken), саме
тому й потрібен цей доказ.

Запуск — будь-яким Python ≥ 3.10, лише stdlib:

    python -m nyshporka.htr.patches.kraken_lineage_verify \\
        --py-a <python старого середовища> --py-b <python нового> \\
        --frames <тека кадрів> --model <модель> [--models <голоси через кому>] \\
        --out <тека звірки> [-- <додаткові аргументи раннера>]

Код виходу 0 — усе тотожне; 1 — є розбіжності (перелік у `report.json`).
Повторний запуск з тією ж `--out` не переганяє сторону, яка вже має прогін
(`--rerun` — переганяти).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "runner.py"


def _clean_env() -> dict[str, str]:
    """Середовище підпроцесу без чужого PYTHONHOME/PYTHONPATH.

    Раннер — самодостатній файл, але в чужому інтерпретаторі змінні сесії
    (VIRTUAL_ENV, PYTHONPATH застосунку) підсовують йому не ті пакети.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _versions(py: str) -> dict[str, str]:
    code = ("import importlib.metadata as m, json\n"
            "out = {}\n"
            "for d in ('kraken', 'torch', 'torchvision', 'numpy', 'pillow', "
            "'scikit-image', 'scipy', 'shapely'):\n"
            "    try: out[d] = m.version(d)\n"
            "    except Exception: out[d] = ''\n"
            "print(json.dumps(out))")
    r = subprocess.run([py, "-c", code], capture_output=True, text=True, env=_clean_env())
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": (r.stderr or r.stdout)[-400:]}


def _run_side(side: str, py: str, args: argparse.Namespace, extra: list[str]) -> dict:
    root = args.out / side
    run_dir = root / "run"
    seg_dir = root / "seg"
    log = root / "runner.log"
    if run_dir.exists() and not args.rerun:
        print(f"[{side}] прогін уже є — не переганяю ({run_dir})", flush=True)
        prev = root / "side.json"
        return json.loads(prev.read_text(encoding="utf-8")) if prev.is_file() else {}
    root.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(RUNNER), "--case-dir", str(args.frames), "--out-dir", str(run_dir),
           "--model", args.model, "--seg-cache-dir", str(seg_dir),
           "--device", args.device, "--script", args.script,
           # раннер на непідтримуваній версії kraken не стартує — а звірка
           # якраз і порівнює стару версію з новою
           "--allow-any-kraken"]
    if args.models:
        cmd += ["--models", args.models]
    cmd += extra
    print(f"[{side}] {' '.join(cmd)}", flush=True)
    t0 = time.time()
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=_clean_env()).returncode
    info = {"side": side, "python": py, "rc": rc, "wall_s": round(time.time() - t0, 1),
            "versions": _versions(py), "cmd": cmd}
    (root / "side.json").write_text(json.dumps(info, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"[{side}] rc={rc} за {info['wall_s']} с · лог {log}", flush=True)
    return info


def _load_gz(p: Path) -> dict:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


#: Випадкові ідентифікатори kraken: кожен рядок і регіон отримує новий UUID
#: (`_c2fe25be-f8a5-…`) на кожному запуску, а рядок посилається на регіон саме
#: ним. Без нормалізації два тотожні прогони ТОГО САМОГО середовища теж
#: «розходились» би на кожному файлі (перший прогін 04.10.2026: 15 із 15, і всі
#: — лише id). Викидати їх не можна: тоді випала б і належність рядка регіону.
#: Тому кожен UUID замінюється порядковим номером першої появи.
_UUID = re.compile(r"^_?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _geometry(obj, ids: dict[str, str] | None = None):
    """Сегментація з UUID, заміненими на порядкові номери, — те, що визначає кропи."""
    ids = {} if ids is None else ids
    if isinstance(obj, dict):
        return {k: _geometry(obj[k], ids) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_geometry(v, ids) for v in obj]
    if isinstance(obj, str) and _UUID.match(obj):
        return ids.setdefault(obj, f"#{len(ids)}")
    return obj


def _first_diff(a, b, path: str = "") -> str:
    """Перше місце, де два JSON-дерева розходяться — для читабельного звіту."""
    if type(a) is not type(b):
        return f"{path}: тип {type(a).__name__} ≠ {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                return f"{path}/{k}: ключ лише з одного боку"
            if a[k] != b[k]:
                return _first_diff(a[k], b[k], f"{path}/{k}")
        return path
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: довжина {len(a)} ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_diff(x, y, f"{path}[{i}]")
        return path
    return f"{path}: {str(a)[:80]} ≠ {str(b)[:80]}"


def _compare(out: Path) -> dict:
    a_root, b_root = out / "a", out / "b"
    rep: dict = {"seg": {}, "lines": {}, "text": {}}

    # ── сегментація: кеш-блоби з однаковим іменем (сторінка + кут + стеля) ──
    a_seg = {p.name: p for p in (a_root / "seg").rglob("*.seg.json.gz")}
    b_seg = {p.name: p for p in (b_root / "seg").rglob("*.seg.json.gz")}
    same = diff = 0
    diffs = []
    for name in sorted(set(a_seg) | set(b_seg)):
        if name not in a_seg or name not in b_seg:
            diff += 1
            diffs.append({"file": name, "why": "кеш лише з одного боку"})
            continue
        sa = _geometry(_load_gz(a_seg[name]).get("seg"))
        sb = _geometry(_load_gz(b_seg[name]).get("seg"))
        if sa == sb:
            same += 1
        else:
            diff += 1
            diffs.append({"file": name, "why": _first_diff(sa, sb, "seg")})
    keys = sorted({json.dumps(_load_gz(p).get("key"), sort_keys=True)
                   for p in list(a_seg.values())[:1] + list(b_seg.values())[:1]})
    rep["seg"] = {"same": same, "diff": diff, "diffs": diffs[:50], "keys_seen": keys}

    # ── рамки рядків ──
    same = diff = 0
    diffs = []
    a_run, b_run = a_root / "run", b_root / "run"
    for pa in sorted(a_run.glob("*.lines.json")):
        pb = b_run / pa.name
        if not pb.is_file():
            diff += 1
            diffs.append({"file": pa.name, "why": "лише в A"})
            continue
        ja = json.loads(pa.read_text(encoding="utf-8"))
        jb = json.loads(pb.read_text(encoding="utf-8"))
        if ja == jb:
            same += 1
        else:
            diff += 1
            diffs.append({"file": pa.name, "why": _first_diff(ja, jb)})
    for pb in sorted(b_run.glob("*.lines.json")):
        if not (a_run / pb.name).is_file():
            diff += 1
            diffs.append({"file": pb.name, "why": "лише в B"})
    rep["lines"] = {"same": same, "diff": diff, "diffs": diffs[:50]}

    # ── тексти: основна тека й кожна тека голосу ──
    dirs = [("main", a_run, b_run)]
    for da in sorted(a_root.glob("run-*")):
        dirs.append((da.name[len("run-"):], da, b_root / da.name))
    for tag, da, db in dirs:
        same = diff = 0
        lines_total = lines_diff = 0
        diffs = []
        for pa in sorted(da.glob("*.txt")):
            pb = db / pa.name
            ta = pa.read_text(encoding="utf-8").splitlines()
            tb = pb.read_text(encoding="utf-8").splitlines() if pb.is_file() else []
            lines_total += len(ta)
            if ta == tb:
                same += 1
                continue
            diff += 1
            nd = sum(1 for x, y in zip(ta, tb) if x != y) + abs(len(ta) - len(tb))
            lines_diff += nd
            first = next((i for i, (x, y) in enumerate(zip(ta, tb)) if x != y),
                         min(len(ta), len(tb)))
            diffs.append({"file": pa.name, "lines_differ": nd, "n_a": len(ta), "n_b": len(tb),
                          "first": first,
                          "a": ta[first][:120] if first < len(ta) else None,
                          "b": tb[first][:120] if first < len(tb) else None})
        rep["text"][tag] = {"same": same, "diff": diff, "lines": lines_total,
                            "lines_differ": lines_diff, "diffs": diffs[:50]}
    return rep


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--py-a", required=True, help="інтерпретатор середовища A (еталон)")
    ap.add_argument("--py-b", required=True, help="інтерпретатор середовища B (кандидат)")
    ap.add_argument("--frames", required=True, type=Path, help="тека кадрів")
    ap.add_argument("--model", required=True, help="основна модель (шлях)")
    ap.add_argument("--models", default="", help="голоси через кому (шляхи)")
    ap.add_argument("--out", required=True, type=Path, help="тека звірки")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--script", default="auto")
    ap.add_argument("--rerun", action="store_true", help="переганяти обидві сторони")
    ap.add_argument("--compare-only", action="store_true")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    sides = {}
    if not args.compare_only:
        sides["a"] = _run_side("a", args.py_a, args, extra)
        sides["b"] = _run_side("b", args.py_b, args, extra)
    rep = _compare(args.out)
    rep["sides"] = sides
    (args.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                          encoding="utf-8")

    ok = rep["seg"]["diff"] == 0 and rep["lines"]["diff"] == 0 and all(
        t["diff"] == 0 for t in rep["text"].values())
    print(f"сегментація: {rep['seg']['same']} тотожних, {rep['seg']['diff']} розбіжних")
    print(f"рамки рядків: {rep['lines']['same']} тотожних, {rep['lines']['diff']} розбіжних")
    for tag, t in rep["text"].items():
        print(f"текст [{tag}]: сторінок {t['same']} тотожних, {t['diff']} розбіжних · "
              f"рядків {t['lines']}, розбіжних {t['lines_differ']}")
    for side, info in sides.items():
        if info:
            v = info.get("versions", {})
            print(f"  {side}: rc={info.get('rc')} {info.get('wall_s')} с · kraken {v.get('kraken')} "
                  f"torch {v.get('torch')} pillow {v.get('pillow')} numpy {v.get('numpy')}")
    print("✓ ТОТОЖНО" if ok else f"✗ Є РОЗБІЖНОСТІ — {args.out / 'report.json'}")
    if any(info and info.get("rc") for info in sides.values()):
        print("⚠ раннер повернув ненульовий код — дивись runner.log сторони")
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
