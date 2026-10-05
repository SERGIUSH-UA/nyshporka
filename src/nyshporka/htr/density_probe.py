"""Щільність справи наперед: рядків на сторінку з вибірки кадрів — лише сегментація.

Гість середовища рушіїв (як `runner.py`): пакета `nyshporka` тут немає, відповідь
— останній рядок stdout у JSON.

Навіщо. Темп читання (і отже вибір машини, стеля часу, ціна тисячі сторінок)
рахується від рядків на сторінку: час сторінки ≈ стала + рядки, і більше від
матеріалу майже нічого не залежить (заміри 01.10.2026: 6 справ, 4 типи
документів). Перший захід справи щільності не знав і брав припущені 60 рядків,
а реальна буває від 18 (сповідки) до 250 (щільні формуляри) — помилка вдвічі-
втричі в обидва боки. Вибірка з 40 кадрів дає ±4–7 % на рівномірних книгах і
±30 % на збірних, де щільні блоки йдуть підряд; ~1 хв на карті.

Як. Лише мережа сегментації й векторизація базових ліній: контури (найдорожча
частина сегментації) для лічби рядків не потрібні. Ті самі патчі, що в
раннері. Кадри-смуги (етикетка плівки, корінець; ш/в > 2.5) не сторінки — не
рахуються. Перші й останні три кадри — обкладинки — теж.

    <інтерпретатор рушіїв> density_probe.py <тека кадрів> [--sample 40] [--device cuda:0]
    <інтерпретатор рушіїв> density_probe.py --serve      # запити JSON-рядками зі stdin

⚡ Заміри 05.10.2026 (GTX 1650, ДАЖО 1-78, 40 кадрів): сегментація на карті —
23–32 с, векторизація ліній на процесорі — 52–64 с, тобто дві третини часу
йшли в ОДИН потік процесора, поки карта стояла (зайнятість ~20 %). Тому
векторизація йде пулом потоків паралельно з сегментацією наступного кадру
(4 потоки — ×1.8 на векторизації), а `--serve` тримає імпорти й модель
(9 с) на всю партію: справи міряються одна за одною тим самим процесом.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

FRAME_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
#: Ширше за висоту більше ніж стільки — не сторінка (етикетка, смуга).
MAX_ASPECT = 2.5
#: Скільки кадрів брати без карти: сегментація на процесорі в рази повільніша.
CPU_SAMPLE = 12
#: Стеля кінців скелета — як у перепуску раннера: густа сторінка рахується
#: повністю, а не обрізаною на 200 рядках.
MAX_ENDPOINTS = 1600
#: Скільки потоків векторизують лінії, поки карта сегментує наступний кадр.
VECTOR_JOBS = 4

#: Масштаби ridge-фільтра — як `--sato-sigmas` раннера. Рідні kraken'івські
#: (1,3,5,7,9) дають ІНШЕ число рядків: 02.10.2026 на 127-1016-247 кадр 0040 —
#: 158 проти 114, кадр 0080 — 376 проти 421. Без карти замір їх і брав, тож
#: щільність розходилась із тим, що потім рахує раннер.
SATO_SIGMAS = (1, 3)


def install_sato(skf: Any, device: str, *, install_gpu: Any) -> None:
    """Sato з масштабами раннера: на карті — `gpu_sato`, без неї — skimage."""
    if device.startswith("cuda"):
        install_gpu(SATO_SIGMAS, device=device)
        return
    orig = skf.sato

    def patched(image: Any, sigmas: tuple[int, ...] = SATO_SIGMAS, black_ridges: bool = True,
                mode: str | None = None, cval: float = 0) -> Any:
        return orig(image, sigmas=sigmas, black_ridges=black_ridges, mode=mode, cval=cval)

    skf.sato = patched


def sample_frames(case_dir: Path, n: int) -> list[Path]:
    """Рівномірна вибірка без обкладинок, у порядку справи."""
    files = sorted(p for p in case_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in FRAME_EXT)
    body = files[3:-3] if len(files) > 20 else files
    if len(body) <= n:
        return body
    step = len(body) / n
    return [body[int(i * step)] for i in range(n)]


def count_lines(frames: list[Path], model: Any, device: str, *, blla: Any, kseg: Any,
                release: Any, open_image: Any, jobs: int = 1) -> list[int]:
    """Рядків на кожному кадрі-сторінці; після кожного кадру пам'ять карти віддається.

    🔴 Без `release` кеш алокатора torch тримає блоки під КОЖНУ нову форму
    входу, а форма тут своя на кожному розвороті (ширина 3905…4111 при висоті
    3100). 02.10.2026, ЦДІАК 127-1016-247 на GTX 1650 (4 ГБ): за шість кадрів
    зарезервовано 5.7 ГБ, тобто більше за саму карту. Windows (WDDM) кладе
    надлишок у RAM процесу, і замір ріс до 8–12 ГБ, поки не клав систему. З
    віддачею після кожного кадру ті самі кадри тримаються в 1.4 ГБ.

    `jobs` > 1 — векторизація пулом потоків, поки карта сегментує наступний
    кадр. Теплокарта вже в пам'яті процесора (numpy), тож карта віддається так
    само після кожного кадру; у черзі лежить не більше `2·jobs` кадрів.
    """
    def vectorize(parts: list[Any]) -> int:
        return sum(len(kseg.vectorize_lines(part, text_direction="horizontal",
                                            max_endpoints=MAX_ENDPOINTS))
                   for part in parts)

    pool = None
    if jobs > 1:
        from concurrent.futures import ThreadPoolExecutor

        pool = ThreadPoolExecutor(max_workers=jobs)
    counts: list[Any] = []
    try:
        for f in frames:
            with open_image(f) as raw:
                w, h = raw.size
                if not h or w / h > MAX_ASPECT:
                    continue
                im = raw.convert("RGB")
            rets = blla.compute_segmentation_map(im, None, model, device)
            cls = rets["cls_map"]
            st_sep = cls["aux"]["_start_separator"]
            end_sep = cls["aux"]["_end_separator"]
            parts = [rets["heatmap"][(st_sep, end_sep, idx), :, :]
                     for idx in cls["baselines"].values()]
            del rets, cls, im
            release()
            if pool is None:
                counts.append(vectorize(parts))
                continue
            counts.append(pool.submit(vectorize, parts))
            pending = [c for c in counts if not isinstance(c, int) and not c.done()]
            if len(pending) > 2 * jobs:
                pending[0].result()
        return [c if isinstance(c, int) else c.result() for c in counts]
    finally:
        if pool is not None:
            pool.shutdown(wait=True)


def _engine(device_arg: str = "") -> dict[str, Any]:
    """Імпорти, патчі раннера й модель сегментації — один раз на процес."""
    from importlib import resources

    import torch
    from kraken import blla
    from kraken.lib import segmentation as kseg
    from kraken.lib import vgsl
    from PIL import Image
    from skimage import filters as skf

    sys.path.insert(0, str(Path(__file__).resolve().parent / "patches"))
    import fast_geom
    import seg_resize
    from gpu_sato import install_gpu_sato

    fast_geom.install()
    seg_resize.install()
    cuda = torch.cuda.is_available()
    device = device_arg or ("cuda:0" if cuda else "cpu")
    install_sato(skf, device, install_gpu=install_gpu_sato)
    model = vgsl.TorchVGSLModel.load_model(resources.files("kraken").joinpath("blla.mlmodel"))

    def release() -> None:
        if device.startswith("cuda"):
            torch.cuda.empty_cache()

    return {"blla": blla, "kseg": kseg, "model": model, "device": device,
            "release": release, "open_image": Image.open}


def measure(eng: dict[str, Any], case_dir: Path, sample: int) -> dict[str, Any]:
    """Одна справа: відповідь у тій самій формі, що й одноразовий виклик."""
    t0 = time.perf_counter()
    device = eng["device"]
    n = sample if device.startswith("cuda") else min(sample, CPU_SAMPLE)
    try:
        counts = count_lines(sample_frames(case_dir, n), eng["model"], device,
                             blla=eng["blla"], kseg=eng["kseg"], release=eng["release"],
                             open_image=eng["open_image"], jobs=VECTOR_JOBS)
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"[:300]}
    if not counts:
        return {"ok": False, "why": "у вибірці немає сторінок"}
    return {"ok": True, "n": len(counts), "sample": sample,
            "lines_mean": round(statistics.mean(counts), 1),
            "lines_median": float(statistics.median(counts)),
            "device": device, "sec": round(time.perf_counter() - t0, 1)}


def serve(device_arg: str = "") -> int:
    """Запити `{"dir": …, "sample": N}` рядками зі stdin, відповідь — рядком у stdout.

    Відповідь несе `dir` запиту: хост відкидає все інше, що процес друкує в
    stdout (kraken і torch бувають балакучі). Перший рядок — `{"ready": …}`
    або відмова середовища.
    """
    t0 = time.perf_counter()
    try:
        eng = _engine(device_arg)
    except Exception as exc:
        print(json.dumps({"ready": False, "why": f"{type(exc).__name__}: {exc}"[:300]}),
              flush=True)
        return 1
    print(json.dumps({"ready": True, "device": eng["device"],
                      "sec": round(time.perf_counter() - t0, 1)}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req: dict[str, Any] = {}
        try:
            req = json.loads(line)
            got = measure(eng, Path(req["dir"]), int(req.get("sample") or 40))
        except Exception as exc:
            got = {"ok": False, "why": f"{type(exc).__name__}: {exc}"[:300]}
        print(json.dumps({**got, "dir": str(req.get("dir") or "")}, ensure_ascii=True),
              flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("case_dir", nargs="?", default="")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--device", default="")
    ap.add_argument("--serve", action="store_true",
                    help="тримати модель і міряти справи з запитів у stdin")
    a = ap.parse_args()
    if a.serve:
        return serve(a.device)
    t0 = time.perf_counter()
    try:
        eng = _engine(a.device)
    except Exception as exc:  # відповідь мусить бути завжди — хост чекає JSON
        print(json.dumps({"ok": False, "why": f"{type(exc).__name__}: {exc}"[:300]}))
        return 1
    got = measure(eng, Path(a.case_dir), a.sample)
    if got.get("ok"):
        got["sec"] = round(time.perf_counter() - t0, 1)
    print(json.dumps(got))
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
