"""HTR-прогін однієї справи: Kraken АБО PARSeq → грепабельний текст посторінково.

⚠ Виконується python-ом СЕРЕДОВИЩА РУШІЇВ (
yshporka.htr.env), не тим, у якому
стоїть пакет — тому тут НЕМАЄ імпортів `nyshporka`. Префікс прогрес-каналу
продубльовано літерально (дзеркало `nyshporka/core/progress.py`): злити їх
означало б імпортувати пакет там, де його немає.

## Два рушії, одна обв'язка (2026-07-30)

Рушій визначається РОЗШИРЕННЯМ моделі, окремого прапорця не треба:

  · `.mlmodel` → **kraken/CTC** («Скриба», McCATMuS) — латинка ф.792;
  · `.pt`      → **PARSeq** («Писар») — кирилиця (ревізії, метрики, судові справи).

Сегментація в обох випадках ТА САМА (`kraken.blla`), різниться лише крок
розпізнавання: kraken веде його сам через `rpred`, для PARSeq ми ріжемо рядки
`extract_polygons` і гонимо батчем. Саме тому Писар отримав усе, що доти мала
лише Скриба: детект орієнтації, resume, карантин, шардинг, sato-прискорення,
вотчдог консолі. Раніше для нього був лише двокроковий ручний шлях
(`kraken_lines_cut.py` + `pysar_lines_infer.py`) без жодного з цих запобіжників —
і на пробі ф.474 одна патологічна сторінка з'їла 602 с із 664.

🔴 **Пороги conf НЕ спільні між рушіями.** У kraken conf калібрований (справжня
сторінка 0.87–0.90, перевернута ~0.76 — звідси 180°-гард). PARSeq автогресивний:
він упевнений і в маренні, тож його conf НЕ є сигналом якості й гардити ним
сторінку не можна. Тому для parseq 180°-гард за conf вимкнено (`sure_conf=0`), а
орієнтацію вирішують детектор профілю і CNN — вони працюють на пікселях. Хто
захоче ризикнути — `--sure-conf` задається вручну.

🔴 **Рушії не затирають одне одного.** Обидва пишуть `<stem>.txt` у теку прогону,
тож прогін Писаря по теці Скриби змішав би два різні декоди в один корпус, і
жоден пошук уже не сказав би, що чим прочитане. Тому мета несе `engine`, і
невідповідність = відмова на старті з підказкою (`--force` щоб свідомо
перезаписати). Правильний спосіб мати обидва — ОКРЕМІ теки прогонів на одну
справу: `htr_store.runs_by_case_dir()` і так тримає список, а `search()` без
`name` ходить по всіх — тобто тримовна справа читається двома рушіями, і хіт
знаходиться незалежно від того, яким письмом написаний аркуш.

Що робить по кожній сторінці (jpg/jpeg/png, сортовані):
  1. resume: якщо `<out>/<stem>.txt` вже є і сторінка в меті — скіп;
  2. детект орієнтації (осциляція похідної ink-профілю: рядки тексту дають
     періодичність поперек себе; поля/бліди — ні). Валідовано на ф.792-1-55;
  3. OCR з retry за конфіденсом: детектор лише пропонує порядок кандидатів
     повороту (0/90/270 CCW), фінальне слово за avg_conf розпізнавання — бо
     детектор евристичний (~9/100 хибних на bleed-through сторінках);
  4. NFC-нормалізація (McCATMuS = NFD-модель, combining diacritics ламали б
     fuzzy-пошук і показ);
  5. `<stem>.txt` + інкрементальний `_htr_meta.json` (tmp+replace — не рветься).

Одна проблемна сторінка (OOM/крах сегментера) не валить прогін — пишеться у
`failed`, йдемо далі. Моделі (розпізнавання + сегментація) вантажаться ОДИН раз.
Сторінка, яка не падає, а ВІШАЄ процес, виняток не кине — її ловить вотчдог
консолі й пише у `<out>/_htr_quarantine.json`; звідти ми її читаємо на старті й
пропускаємо як збій (інакше нічний прогін бився б у неї до ранку).

🔴 **Третій, найгірший клас відмови: сторінка вбиває ПРОЦЕС.** Ні виняток, ні
вотчдог тут не спрацьовують — інтерпретатор помирає нативно, лог обривається
без traceback, `failed` лишається порожнім, і прогін виглядає завершеним.
Виміряно на ДАХмО 241-1-886 (2026-08-11): 14 сторінок із 18, `rc=1` без жодного
рядка діагностики, у мозаїці не видно нічого підозрілого. Тому:
  • **приймач повноти — ДИСК** (`missing_pages`: кадр ↔ `<stem>.txt`, і в
    побічних теках голосів теж), а не лічильники `done/skipped/failed`;
  • неповний прогін виходить із **rc=3** і рядком «⚠ НЕПОВНО: …» — мовчазний
    успіх при втрачених сторінках заборонений за побудовою;
  • `--supervise N` (дефолт 2) вмикає **наглядача**: він сам нічого не вантажить,
    лише перезапускає воркер, поки на диску є кадри без тексту; кадр, який двічі
    не дав прогресу при ненульовому rc, іде в карантин із причиною — так справа
    дочитується без нього, замість помирати на ньому щоразу.
  🔴 Фінальну подію `done` для консолі емітить наглядач із чисел ДИСКА: у
  дитини останньої спроби майже все — resume-скіп, і `HtrManager`, який тримає
  один результат на воркер, показав би «0 сторінок» на повністю прочитаній справі.

⚡ ПРОФІЛЬ ВУЗЬКОГО МІСЦЯ (py-spy на живому прогоні, 2026-07-24): прогін НЕ
GPU-bound — карта простоює на 92% часу (0% util, 3.4 Вт). 43% часу з'їдає
`skimage.filters.sato` (→ `scipy.ndimage.correlate1d`) всередині
`kraken.lib.segmentation.vectorize_lines`, ще ~20% — CPU-геометрія Kraken
(`_calc_roi`, `moore_neighborhood`, `boundary_tracing`). Звідси три важелі:
  · `--sato-sigmas 1,3` замість дефолтних (1,3,5,7,9) — 1.30x, метрики якості
    НЕ просідають (виміряно: рядків 36.2 vs 35.2, conf 0.823 vs 0.822);
  · `--seg-height` — сегментер за замовчуванням ресайзить сторінку до 1800 px;
    менша висота дає квадратичну економію, але коштує якістю (h1440 ≈ −4%
    слів, h1200 ≈ −10% fuzzy-recall довгих слів) — тому не вмикається само;
  · `--shard k/n` — прогін CPU-bound на ~1.6 ядра, тож N воркерів по сторінках
    масштабуються майже лінійно. GPU-фаза (2.2 ГБ VRAM piku при h1800) береться
    під міжпроцесний лок `--gpu-lock` + `empty_cache`, інакше 4 ГБ GTX 1650 не
    витримує двох одночасних forward'ів.

Smoke-запуск руками:
    .venv_kraken/Scripts/python.exe scripts/htr_case_run.py \
        --case-dir "data/raw/miastkovka archive/010792-01-00055" \
        --out-dir reports/htr/010792-01-00055 --model <шлях .mlmodel> --limit 3
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

#: Дзеркало `nyshporka/core/progress.py`. Дублювати доводиться: раннер їде під
#: інтерпретатором середовища рушіїв, де пакета немає. Рівність двох описів
#: доводить `tests/test_progress_mirror.py`, а не домовленість.
PROGRESS_PREFIX = "@@PROGRESS@@ "
PROGRESS_SCHEMA = 1

#: Патчі гарячих функцій kraken (`gpu_sato`, `fast_geom`, `seg_ceiling`) лежать
#: у підтеці поруч і вантажаться ЗА ШЛЯХОМ, а не імпортом пакета: раннер їде під
#: інтерпретатором середовища рушіїв, де `nyshporka` не встановлено.
_PATCHES_DIR = Path(__file__).resolve().parent / "patches"

# Пороги прийняття кандидата повороту. Нижче min_conf АБО менше min_chars —
# пробуємо наступний кандидат (сторінка могла лежати на боці / бути порожньою).
DEF_MIN_CONF = 0.35
DEF_MIN_CHARS = 20
# 180°-гард: McCATMuS читає перевернутий догори ногами скоропис з conf ~0.76 на
# повній сторінці (виміряно на ф.792-1-55!) — далеко вище за min_conf, тож без
# гарда 180°-кадр тихо приймався б зі сміттям. Справжні сторінки дають 0.87-0.90 →
# все, що нижче SURE_CONF, довіряємо лише після очної ставки з +180° (гард
# порівняльний: беремо кращий conf). Профіль-детектор 180° не бачить принципово.
DEF_SURE_CONF = 0.82
# АДАПТИВНІСТЬ (2026-07-21, кейс спр.17: писар зі стабільним conf ~0.79 → гард
# бив КОЖНУ сторінку → 55 с/стор замість 26): перші GUARD_WARMUP очних ставок у
# справі — розвідка; якщо жодна не перевернула результат, далі гардимо лише
# аномалії (conf нижче середнього по справі на GUARD_MARGIN — перевернута сторінка
# просідає відносно сусідів на ~0.13).
DEF_GUARD_WARMUP = 15
GUARD_MARGIN = 0.10
# 🐞 ФІКС 2026-07-24 (справа 010792-01-00016): умовою «повний гард до кінця» був
# бінарний `flips > 0` — і ОДНА помилка CNN-детектора орієнтації (`cnn180` на
# 1 сторінці з 265) назавжди вмикала дорогий режим: 115 з 265 сторінок пішли по
# два OCR-проходи (45.6 с проти 22.0 с) при НУЛІ реально перевернутих сторінок,
# тобто +32% часу в нікуди. Гард виправляв не перевернутий скан, а хибний
# кандидат від CNN — це рутинна робота гарда, а не доказ що у справі є 180°.
# Тепер повний режим вмикається лише за СИСТЕМАТИЧНОЮ ознакою: щонайменше
# GUARD_MIN_FLIPS фліпів І частка фліпів ≥ GUARD_FLIP_RATE.
GUARD_MIN_FLIPS = 2
GUARD_FLIP_RATE = 0.05
# 🐞 ФІКС-2 2026-07-25: warmup-розвідка ПЕРЕЖИВАЄ рестарт. `guard_state` жив лише
# у пам'яті процесу, тож кожен перезапуск (а з шардингом — ще й ×3 воркери)
# починав 15 очних ставок наново. Заміряно на 010792-01-00016 після 5 рестартів:
# 147 гардів із 243 сторінок (60%!) при НУЛІ реальних фліпів (жодного orient
# 90/180) — тобто 40.2 с/стор замість 20.3 і ETA 10 год замість 5.5. Тепер стан
# гарда лежить у меті шарда (`guard`) і відновлюється при resume: розвідка
# робиться ОДИН раз на справу, а не один раз на запуск.
#
# ⚠ Спокуса, якої слід уникати: робити SURE_CONF відносним до медіани справи.
# Перевірено симуляцією на 256 реальних сторінках цієї справи — дає 11% гардів
# проти 6% у чинної логіки, тобто ГІРШЕ. Абсолютний поріг + `anomaly` відносно
# середнього вже покривають обидва випадки.


# ── рушії ────────────────────────────────────────────────────────────────────
#: Розширення моделі → рушій. Окремого `--engine` свідомо немає: модель і рушій
#: нерозривні, а зайвий прапорець дав би змогу зібрати неможливу комбінацію.
_ENGINE_BY_SUFFIX = {".mlmodel": "kraken", ".pt": "parseq",
                     ".ckpt": "parseq", ".pth": "parseq"}

#: Письмо, яке модель реально вміє. Потрібне для мети прогону й для попередження
#: в консолі: kraken-Скриба на кирилиці дає тихе сміття БЕЗ падіння conf
#: (ф.726-1-16, 2026-07-22), тобто помилку видно лише оком.
_SCRIPT_BY_PREFIX = (("skryba", "latin"), ("pysar", "cyrillic"),
                     ("mccatmus", "latin"), ("cyr", "cyrillic"))

# PARSeq: conf ненадійний (див. докстрінг), тому 180°-гард за ним вимкнено, а
# retry по поворотах спирається на кількість символів, не на conf.
DEF_SURE_CONF_PARSEQ = 0.0
DEF_MIN_CONF_PARSEQ = 0.0
#: Вужчі за 8 px кропи — артефакт сегментації, PARSeq на них видає шум.
PARSEQ_MIN_CROP_W = 8
#: Наскільки більше символів має дати альтернативний поворот, щоб його взяли
#: (гард орієнтації для parseq). 10% — вище рівня шуму, нижче реальної різниці
#: правильна/перевернута (виміряно 37-88% на ф.196-1-5953).
ORIENT_CHARS_MARGIN = 0.10
#: 🐞 ФІКС 2026-08-07 (ДАВО 904-24-24): скільки символів має дати сторінка, щоб
#: рішення про її орієнтацію взагалі мало сенс. На майже порожньому аркуші —
#: роздільнику частин книги, чистому розвороті — жоден кандидат не проходить
#: `min_chars`, тому пробуються ВСІ ЧОТИРИ повороти, і переможець обирається за
#: `conf`, який для PARSeq сигналом не є. Так дві нормально орієнтовані сторінки
#: (0123 «ЧАСТЬ ТРЕТІЯ О УМЕРШИХЪ» — 64 символи, 0239 — 36) лягли догори ногами:
#: 64 проти ~55 на порожньому аркуші це шум, а не доказ. Нижче цього порога
#: орієнтація НЕ змінюється — лишається 0°, бо це типова орієнтація сканування.
ORIENT_MIN_EVIDENCE = 150


def detect_engine(model: str) -> str:
    suf = Path(model).suffix.lower()
    engine = _ENGINE_BY_SUFFIX.get(suf)
    if engine is None:
        raise SystemExit(
            f"[htr-run] невідомий тип моделі «{suf}» ({Path(model).name}). "
            f"Очікую .mlmodel (kraken/Скриба) або .pt (PARSeq/Писар)")
    return engine


def model_script(model: str, engine: str) -> str:
    """Письмо моделі за іменем файлу; невідоме — за рушієм (kraken у нас лише латинка)."""
    low = Path(model).name.lower()
    for prefix, script in _SCRIPT_BY_PREFIX:
        if prefix in low:
            return script
    return "latin" if engine == "kraken" else "unknown"


def emit(enabled: bool, phase: str, **kw) -> None:
    """Подія прогресу в машинний канал.

    🔴 `"v"` ОБОВ'ЯЗКОВЕ. Читач (`nyshporka.core.progress.parse`) відкидає
    подію з чужою версією схеми — і правильно робить: поле, що змінило сенс,
    гірше за відсутнє. Але доти, доки раннер версії не слав, читач відкидав
    КОЖНУ його подію: прогрес завмирав на нулі, а вотчдог за десять хвилин
    тиші вбивав ЖИВИЙ прогін. Зовні це виглядало як «завис».

    Ось чому дзеркало протоколу тут дозволене, а розходження — ні: раннер їде
    в середовищі рушіїв і читача імпортувати не може, тож рівність двох
    описів доводить тест (`test_progress_mirror`), а не домовленість.
    """
    if enabled:
        print(PROGRESS_PREFIX + json.dumps(
            {"v": PROGRESS_SCHEMA, "phase": phase, **kw}, ensure_ascii=False),
            flush=True)


# ── підняття контрасту (вицвіле чорнило) ─────────────────────────────────────
# Не для всіх справ: на нормальному чорнилі CLAHE лише підсилює текстуру паперу.
# Мірило потреби — контраст «фон p90 мінус чорнило p3» у сірому: <70 = блідо.
# Замір по ф.792-1-43 (2026-07-30): скани 1–1270 дають 73–93, скани 1300–1550 —
# 51–66, і саме там декод падає з ~800 до ~250 символів на сторінку.
ENHANCE_MODES = ("auto", "none", "clahe", "clahew", "clahesmooth")

#: Нижче цього контрасту сторінка вважається вицвілою і йде через `clahesmooth`.
#: Калібровано вимірами по чотирьох справах (2026-07-31):
#:   ф.792-1-43 здорові          76 … 112 (медіана 90)
#:   ф.792-1-43 вицвілий блок    50 …  79 (медіана 69)
#:   ф.792-1-39                  89 … 129
#:   ф.468-1-749 (кирилиця)      65 … 133 (медіана 105)
#: Поріг свідомо консервативний: перекриття 76-79 віддається здоровим, бо CLAHE
#: на нормальному чорнилі лише підсилює зерно паперу, і сегментація починає
#: різати волокна як рядки. Краще не підняти бліду, ніж зіпсувати добру.
AUTO_CONTRAST_THRESHOLD = 72.0
AUTO_ENHANCE_MODE = "clahesmooth"


def page_contrast(im: Image.Image) -> float:
    """Контраст «фон p90 − чорнило p3» у центрі аркуша.

    Краї відрізаються: там палітурка, стіл і пальці фотографа — вони дають
    і найтемніші, і найсвітліші пікселі кадру, тобто перцентилі рахувались би
    по чому завгодно, крім тексту. Крок 2 по обох осях — вимір і так статистичний,
    а на 2272×1704 це вчетверо дешевше.
    """
    a = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = a.shape
    a = a[int(h * 0.15):int(h * 0.85):2, int(w * 0.12):int(w * 0.88):2]
    return float(np.percentile(a, 90) - np.percentile(a, 3))


def enhance_image(im: Image.Image, mode: str) -> Image.Image:
    """CLAHE поверх сірого + опційне вибілювання фону.

    `clahe`       — локальне вирівнювання гістограми (вікно 1/8 сторони);
    `clahew`      — те саме + фон світліший за p75 стає чистим білим;
    `clahesmooth` — `clahew` + gaussian 0.8 проти зерна паперу, яке CLAHE
                    неминуче підсилює разом із чорнилом (сегментація kraken
                    ловить ridge-фільтром і волокна теж).
    Повертає RGB — далі по конвеєру йде звичайний шлях сторінки.
    """
    if mode in ("", "none", "auto"):
        # `auto` вирішується ВИЩЕ, у process_page: там видно контраст сторінки і
        # є куди порахувати статистику по справі
        return im
    from skimage.exposure import equalize_adapthist

    g = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    g = equalize_adapthist(g, kernel_size=(g.shape[0] // 8, g.shape[1] // 8),
                           clip_limit=0.02)
    if mode != "clahe":
        lo, hi = np.percentile(g, 1.0), np.percentile(g, 75.0)
        g = np.clip((g - lo) / max(hi - lo, 1e-6), 0, 1)
    if mode == "clahesmooth":
        from skimage.filters import gaussian
        g = gaussian(g, sigma=0.8, preserve_range=True)
    out = (np.clip(g, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out).convert("RGB")


# ── орієнтація ───────────────────────────────────────────────────────────────
def detect_orientation(im: Image.Image) -> str:
    """'UPRIGHT' | 'ROT' | 'AMBIG' — чи лежать рядки тексту горизонтально.

    Похідна ink-профілю гасить повільні тренди (поля, палітурку) і лишає
    осциляцію рядків; порівнюємо енергію по рядках vs по колонках.
    180° цим не ловиться (рядки лишаються горизонтальними) — його добиває
    conf-retry, якщо трапиться.
    """
    g = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = g.shape
    g = g[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
    ink = np.clip(g.mean() - g, 0, None)
    k = np.ones(5) / 5
    rows = np.convolve(ink.sum(axis=1), k, mode="valid")
    cols = np.convolve(ink.sum(axis=0), k, mode="valid")

    def osc(profile: np.ndarray) -> float:
        p = profile / (profile.sum() + 1e-9)
        d = np.diff(p)
        return float((d * d).sum() * len(p))

    re_, ce = osc(rows), osc(cols)
    if re_ > ce * 1.3:
        return "UPRIGHT"
    if ce > re_ * 1.3:
        return "ROT"
    return "AMBIG"


def rotated(im: Image.Image, orient: int) -> Image.Image:
    """Поворот на orient градусів ПРОТИ годинникової (CCW), як Image.ROTATE_*."""
    if orient == 90:
        return im.transpose(Image.ROTATE_90)
    if orient == 180:
        return im.transpose(Image.ROTATE_180)
    if orient == 270:
        return im.transpose(Image.ROTATE_270)
    return im


def orient_candidates(verdict: str) -> list[int]:
    """Порядок спроб повороту за вердиктом детектора (макс 3 кандидати)."""
    if verdict == "ROT":
        # лежить на боці, але CW чи CCW — невідомо (у ф.792 був CCW=90, буває всяко)
        return [90, 270, 0]
    if verdict == "AMBIG":
        return [0, 90, 270]
    return [0, 90, 270]  # UPRIGHT: retry піде далі по списку лише якщо conf провальний


# ── CNN-класифікатор орієнтації (опційний; тренер scripts/htr_orient_train.py) ──
def load_orient_net(path: str, device: str):
    """TorchScript MobileNetV3 (4 класи). None, якщо не вдалось — фолбек на профіль."""
    try:
        import torch
        net = torch.jit.load(path, map_location=device)
        net.eval()
        return net
    except Exception as exc:
        print(f"[htr-run] ⚠ orient-модель не завантажилась ({exc}) — профіль-детектор",
              flush=True)
        return None


def cnn_fix(net, im: Image.Image, device: str) -> int:
    """Передбачений фікс-поворот (CCW), конвенція тренера: class k → fix=(360-k)%360."""
    import torch
    w, h = im.size
    s = 224 / max(w, h)
    small = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR)
    canvas = Image.new("RGB", (224, 224), (128, 128, 128))
    canvas.paste(small, ((224 - small.width) // 2, (224 - small.height) // 2))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    t = (torch.from_numpy(arr).permute(2, 0, 1) - 0.5) / 0.25
    with torch.no_grad():
        k = int(net(t.unsqueeze(0).to(device)).argmax(1))
    return (360 - (0, 90, 180, 270)[k]) % 360


# ── прискорення: sato / висота сегментації / GPU-лок ─────────────────────────
def install_sato_sigmas(spec: str) -> tuple | None:
    """Звузити масштаби ridge-фільтра `sato` — найдорожчий крок сегментації.

    `vectorize_lines` кличе `filters.sato(bl_map, black_ridges=False)` з
    дефолтними sigmas=(1,3,5,7,9): п'ять масштабів Hessian'а по всій хітмапі,
    43% часу прогону (виміряно py-spy). Baseline-хітмапа — вже тонкі лінії, і
    великі масштаби нічого не додають: на (1,3) якість не змінилась (рядків
    36.2 vs 35.2, conf 0.823 vs 0.822 на 5 сторінках ф.792-1-16), час −30%.

    Патч глобальний на `skimage.filters.sato` — у цьому процесі його кличе лише
    Kraken. Повертає застосовані sigmas (None = лишили дефолт).
    """
    parts = [p.strip() for p in (spec or "").split(",") if p.strip()]
    if not parts:
        return None
    sigmas = tuple(float(p) if "." in p else int(p) for p in parts)
    from skimage import filters as skf

    orig = skf.sato

    def patched(image, sigmas=sigmas, black_ridges=True, mode=None, cval=0):
        # дефолт параметра — саме наші sigmas; Kraken кличе sato без sigmas,
        # тож підміна дефолту і є весь патч
        return orig(image, sigmas=sigmas, black_ridges=black_ridges,
                    mode=mode, cval=cval)

    skf.sato = patched
    return sigmas


def _file_lock_ctx(path: Path):
    """Міжпроцесний ексклюзивний лок на файл (Windows: msvcrt, інші: fcntl)."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "a+b")  # noqa: SIM115 — дескриптор і Є локом до yield'а
        try:
            if sys.platform == "win32":
                import msvcrt
                while True:
                    try:
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    return _ctx


def install_gpu_lock(lock_path: Path, device: str, keep_cache: bool = False) -> None:
    """Серіалізувати між воркерами ЛИШЕ GPU-фазу сегментації.

    `blla.segment` = короткий forward сегментера на GPU (пік 2.2 ГБ VRAM при
    висоті 1800) + довга CPU-геометрія (векторизація, полігони, seam-carving).
    Накриваємо локом тільки forward і одразу віддаємо кеш алокатора: тоді
    паралельні шарди молотять CPU-частину одночасно, а піки VRAM не збігаються
    і в 4 ГБ GTX 1650 вміщається 3 воркери замість одного. Без лока три
    одночасні forward'и = 6.6 ГБ = OOM.
    """
    from kraken import blla

    orig = blla.compute_segmentation_map
    ctx = _file_lock_ctx(lock_path)

    def locked(*a, **kw):
        with ctx():
            try:
                return orig(*a, **kw)
            finally:
                # empty_cache віддає пам'ять ОС — це і тримає піки шардів
                # роз'єднаними, і водночас змушує наступну алокацію йти в драйвер
                # замість кешу. `--keep-cache` дає зміряти, що з двох дорожче.
                if device.startswith("cuda") and not keep_cache:
                    import torch
                    torch.cuda.empty_cache()

    blla.compute_segmentation_map = locked


# ── OCR ──────────────────────────────────────────────────────────────────────
def load_recognizer(model: str, engine: str, device: str):
    """Розпізнавач для рушія. Для parseq — та сама завантажувалка, що в
    `pysar_lines_infer.load_pysar` (гіперпараметри беруться з чекпойнта, інакше
    `load_state_dict` тихо лишає половину ваг випадковими), імпортована, а не
    скопійована — щоб формат чекпойнта описувався в одному місці."""
    if engine == "kraken":
        from kraken.lib import models as kmodels
        return kmodels.load_any(model, device=device)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pysar_lines_infer import load_pysar
    return load_pysar(Path(model), device)


#: Паддінг кропа для kraken-голосу. 16 — рідний дефолт `rpred`, і саме він
#: робить голос ТОТОЖНИМ окремому прогону тієї ж моделі. Число не косметичне:
#: заміряно на 233 рядках ДАВО 904-24-24 проти еталонного `rpred.rpred`
#:   pad=(16,0)  CER 0.0000, дослівно 233/233   ← беремо
#:   pad=0       CER 0.1307, дослівно  63/233   ← так декодував рятувальний прохід
#: Тобто без паддінгу другий рушій читає ЗАМІТНО гірше, ніж уміє, і мовчки:
#: текст лишається схожим на текст, тому в очі це не впадає.
KRAKEN_VOICE_PAD = 16
#: Розмір батча kraken-голосу; 1 = тотожність окремому прогону (див.
#: `kraken_decode_crops`). Виставляється один раз із `main` за `--voice-batch`.
VOICE_BATCH = 1


def load_kraken_voice(model: str, device: str) -> tuple:
    """kraken-модель як ГОЛОС: декодує вже нарізані кропи, без своєї сегментації.

    Повертає `(net, transforms, channels)`. Трансформи будуються з входу самої
    мережі (`net.nn.input`), як це робить `rpred`, — висота й кількість каналів
    у Дяка і Скриби різні від PARSeq-івських, і брати їх «за домовленістю» не
    можна.
    """
    from kraken.lib import models as kmodels
    from kraken.lib.dataset import ImageInputTransforms

    net = kmodels.load_any(model, device=device)
    _b, ch, h, w = net.nn.input
    tr = ImageInputTransforms(batch=1, height=h, width=w, channels=ch,
                              pad=(KRAKEN_VOICE_PAD, 0), valid_norm=False,
                              force_binarization=False)
    return net, tr, ch


def kraken_decode_crops(voice: tuple, crops: list, batch: int = 1) -> list[str]:
    """Прочитати ГОТОВІ кропи kraken-моделлю. Порядок і довжина = як у `crops`.

    🔴 `batch=1` (дефолт) — не недогляд, а вимір. При батчі рядки доводиться
    доповнювати до спільної ширини, і CTC віддає трохи інший текст: на тих
    самих 233 рядках дослівний збіг із `rpred` падає 233/233 → 193/233
    (CER 0.0095), причому паддінг тут ні до чого — після трансформів фон і так
    нуль, перевірено окремо (нулями / «папером» / краєм рядка — три способи,
    той самий CER). Ціна точності — 1.4 → 3.3 с/стор, тобто голос усе одно
    вчетверо дешевший за окремий прогін (10.0 с/стор). Батч лишається під
    `--voice-batch` для випадків, де важить час, а не звірка з еталоном.
    """
    import torch

    net, tr, ch = voice
    mode = "L" if ch == 1 else "RGB"
    out: list[str] = []
    if batch <= 1:
        for c in crops:
            try:
                t = tr(c.convert(mode))
                with torch.no_grad():
                    pr = net.predict_string(t.unsqueeze(0))
                out.append(unicodedata.normalize("NFC", str(pr[0] if pr else "")).strip())
            except Exception:
                out.append("")      # один битий кроп не забирає решту рядків
        return out
    for j in range(0, len(crops), batch):
        chunk = crops[j:j + batch]
        try:
            tt = [tr(c.convert(mode)) for c in chunk]
            wmax = max(x.shape[-1] for x in tt)
            lens = torch.tensor([x.shape[-1] for x in tt])
            padded = torch.stack([
                torch.nn.functional.pad(x, (0, wmax - x.shape[-1])) for x in tt])
            with torch.no_grad():
                res = net.predict_string(padded, lens)
            out += [unicodedata.normalize("NFC", str(s or "")).strip() for s in res]
        except Exception:
            out += [""] * len(chunk)
    return out


def _line_crops(im: Image.Image, seg) -> list:
    """Кропи рядків із сегментації.

    Спершу ОДНИМ проходом по всій сегментації, і лише при збої — порядково.
    Чому саме так (заміряно на ф.196 спр.14536 кадр 0002, 72-74 рядки, кадр
    5811×4777): порядковий виклик `extract_polygons` коштує `dataclasses.replace`
    + новий генератор на КОЖЕН рядок, і сторінка виходила 141 с проти 43.5 с у
    kraken на тій самій сторінці. Пакетний прохід знімає цю різницю, а фолбек
    зберігає стійкість: `extract_polygons` валиться цілим генератором, якщо хоч
    один полігон вироджений, і тоді порядковий шлях дає решту рядків (та сама
    тактика, що в `kraken_lines_cut.py`).

    ⚠ При фолбеку кропи збираються З НУЛЯ, а не доливаються до частково зібраних:
    інакше рядки, зібрані до винятку, продублювались би.
    """
    import dataclasses

    from kraken.lib.segmentation import extract_polygons

    # 🔴 Рамки збираються ТУТ, а не окремим проходом по `seg.lines`: список
    # кропів ФІЛЬТРУЄТСЯ за `PARSEQ_MIN_CROP_W`, тож `seg.lines[i]` і `lines[i]`
    # це РІЗНІ рядки. Окремий прохід дав би зсув індексів, і він був би тихим —
    # рамка малювалась би не там, де текст. Тому рамка кладеться поруч зі своїм
    # кропом, у тому самому фільтрі. Забирає `ocr_page_parseq` (та сама ідіома,
    # що `ocr_page_parseq.side`).
    # 🖼 Разом із рамкою береться і сам ПОЛІГОН рядка: рядок скоропису йде
    # похило й вигинається, тож його bbox накриває шматки сусідніх рядків —
    # для підсвітки в UI прямокутник показує «десь тут», а полігон показує
    # рівно той рядок. Bbox лишається окремо, бо його читають вирізальники
    # черги на звірку, яким потрібна саме прямокутна вирізка.
    def _geom(ln):
        pts = list(getattr(ln, "boundary", None) or getattr(ln, "baseline", None) or [])
        if not pts:
            return None, None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return ([int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
                [[int(x), int(y)] for x, y in pts])

    def _reset():
        _line_crops.boxes = []
        _line_crops.polys = []

    def _add(ln):
        b, p = _geom(ln)
        _line_crops.boxes.append(b)
        _line_crops.polys.append(p)

    _reset()
    try:
        crops = []
        # 🔴 `strict=False` тут СВІДОМИЙ, а не забутий. `extract_polygons` —
        # чужа функція kraken, і чи може вона віддати менше вирізок, ніж рядків
        # (вироджений полігон), ми не міряли. Впасти означало б утратити
        # сторінку через припущення; мовчки обрізати — прив'язати кроп до ЧУЖОЇ
        # геометрії рядка, а це вже спотворення тексту, якого не видно.
        # Тому: не падаємо, але розбіжність називаємо вголос.
        _polys = list(extract_polygons(im, seg))
        if len(_polys) != len(seg.lines):
            print(f"[htr-run] ⚠ сегментація віддала {len(_polys)} вирізок на "
                  f"{len(seg.lines)} рядків — прив'язка геометрії на цій "
                  f"сторінці ненадійна", flush=True)
        for (c, _), ln in zip(_polys, seg.lines, strict=False):
            if c.width >= PARSEQ_MIN_CROP_W:
                crops.append(c)
                _add(ln)
        return crops
    except Exception:
        pass
    crops = []
    _reset()
    for ln in seg.lines:
        try:
            one = dataclasses.replace(seg, lines=[ln])
            crop, _ = next(extract_polygons(im, one))
        except Exception:
            continue
        if crop.width >= PARSEQ_MIN_CROP_W:
            crops.append(crop)
            _add(ln)
    return crops


#: 🔴 Поріг якоря 82, а не 85: на сповідці 1846 рядок «Антонъ Якимовъ Поліщукъ»
#: не відбирався, бо «Антонъ» проти «Антоній» дає 83. Кожен такий недобір — це
#: рядок, який ніхто вже не перечитає.
RESCUE_ANCHOR_MIN = 82.0
#: Скільки СУСІДНІХ рядків брати навколо відібраного (див. `rescue_pick`).
RESCUE_NEIGHBOURS = 1
_RESCUE_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

#: Шлях до файлу-специфікації рятунку; ставить викликач через `--rescue-spec`.
_RESCUE_SPEC_PATH: Path | None = None
_RESCUE_SPEC: dict | None = None


def best_ratio(norm: str, targets: list[str],
               partial: bool = True) -> tuple[float, str]:
    """Найкращий бал токена серед цілей. Generic, тому живе тут.

    `partial` дозволяє відмінкові хвости, але лише коли токен НЕ коротший за
    ціль: інакше уламок на дві літери давав би сто балів будь-чому.
    """
    from rapidfuzz import fuzz

    best, bt = 0.0, ""
    for t in targets:
        sc = float(fuzz.ratio(norm, t))
        if partial and len(norm) >= len(t):
            sc = max(sc, float(fuzz.partial_ratio(norm, t)))
        if sc > best:
            best, bt = sc, t
    return best, bt


def _load_normalizer():
    """Архівна нормалізація — ОДНА реалізація, завантажена за шляхом.

    🔴 Не `from nyshporka.utils…`: раннер їде під інтерпретатором середовища
    рушіїв, де пакета немає. Але й копіювати сюди нормалізатор не можна — це
    єдине місце, де визначено, що дореформене, сучасне й латинізоване написання
    одного прізвища вважаються тим самим словом. Дві копії розійдуться, і
    пошук почне бачити не те, що бачив декод.

    Тому модуль вантажиться ЗА ФАЙЛОМ, як і патчі kraken: одна реалізація, без
    вимоги мати встановлений пакет.
    """
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "utils" / "translit.py"
    spec = importlib.util.spec_from_file_location("_nysh_translit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не знайдено нормалізатор: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.normalize_archival


def rescue_spec() -> dict:
    """Цілі рятувального відбору — ДАНІ від викликача, а не константи тут.

    🔴 Раніше цей блок містив імена й по батькові конкретного роду, а цілі
    підтягувались імпортом сусіднього скрипта пошуку. Для будь-якого іншого
    дослідника це означало б рятунок рядків, схожих на ЧУЖЕ прізвище — тобто
    гірше, ніж відсутність рятунку: витрачений час і хибна впевненість.

    Файл (`--rescue-spec`) містить уже нормалізовані цілі й конфузери плюс
    якорі у вигляді, як у джерелі:

        {"full": ["kovalsk"], "confusers": ["kovalcuk"], "anchors": ["Petrov"]}

    Якорі беруться з канону під РОКИ справи (ім'я корисне, поки людина жива;
    по батькові — поки живі її діти), і збирає їх викликач, у якого канон є.
    """
    global _RESCUE_SPEC
    if _RESCUE_SPEC is not None:
        return _RESCUE_SPEC
    if _RESCUE_SPEC_PATH is None:
        raise RuntimeError(
            "рятувальний прохід потребує --rescue-spec: перелік цілей і якорів. "
            "Без нього довелось би рятувати рядки за чужим прізвищем.")
    data = json.loads(Path(_RESCUE_SPEC_PATH).read_text(encoding="utf-8"))
    norm = _load_normalizer()
    _RESCUE_SPEC = {
        "full": [str(x) for x in (data.get("full") or [])],
        "confusers": [str(x) for x in (data.get("confusers") or [])],
        "anchors": [str(x) for x in (data.get("anchors") or [])],
        "norm": norm,
    }
    if not _RESCUE_SPEC["full"]:
        raise RuntimeError(f"{_RESCUE_SPEC_PATH}: порожній перелік `full` — "
                           f"рятувати нема за чим")
    return _RESCUE_SPEC


def rescue_anchors(years: str = "") -> list[str]:
    """Якорі відбору. Роки лишились у сигнатурі для сумісності виклику.

    Збирає їх викликач і кладе у специфікацію: канон живе в пакеті, а раннер —
    в іншому середовищі.
    """
    return list(rescue_spec()["anchors"])


def rescue_pick(lines: list[str], eye: float, grey: float,
                anchor_keys: list[str] | None = None) -> list[int]:
    """Індекси рядків, які варто перечитати ДРУГИМ рушієм.

    ## Яку діру це закриває

    Писар проходить справу на 500 сторінок за 1-1.5 год, далі фаззі-пошук, далі
    **оком дивляться лише хіти вище ≈78**. Нижче 60 — шум. Між ними на велику
    справу набирається понад тисяча рядків, і **їх не подивиться ніхто**.
    Справжня згадка роду сидить саме там, бо PARSeq має внутрішню мовну модель і
    **підставляє правдоподібне слово** замість написаного.

    CTC (Дяк) судить кадри умовно незалежно — здогадуватись йому нічим, тому він
    калічить локально, зберігаючи корінь. Саме та властивість, щоб витягти хіт
    із смітника. Заміряно 2026-08-08 на метричних книгах, два рятунки З НУЛЯ,
    обидва підтверджені записом у родоводі:

        Писар підставив правдоподібне ЧУЖЕ слово   бал 0.0 → Дяк 90.0
        Писар підставив правдоподібне ЧУЖЕ слово   бал 0.0 → Дяк 87.0

    Хибних спрацювань на СУСІДНЬОМУ прізвищі зі спільним коренем — НУЛЬ; саме
    воно тут головна загроза, бо різниця буває в одну літеру.

    ## Чому фільтр саме ОБ'ЄДНАННЯ, а не «сіра смуга»

    🔴 Обидва золоті рятунки мали в Писаря бал **НУЛЬ**, тобто лежали в шумі, а
    не в сірій смузі — мовна модель підставила зовсім інше слово. Фільтр «60-78»
    їх би пропустив. Але в обох рядках Писар **дослівно** прочитав по батькові:
    формулярні слова PARSeq бере точно, прізвища — ні. Тому:

        1. сіра смуга `grey`..`eye` за балом роду;
        2. АБО якір: ім'я чи по батькові роду (fuzzy ≥85).

    ⚠ Саме АБО, не І: пара «ім'я + по батькові» виглядає точнішою, а ловить
    ОДИН рятунок із трьох — бо HTR калічить то одне, то інше («Григорій» →
    «благочектаріи», «Іосифовъ» → «Осафовъ»).

    ## Ціна (заміряно на справжніх справах)

        метрика ф.904-24      9.2% рядків
        суд ф.474-174         2.9%   (395 рядків на 364 стор.)
        суд ф.474-176         2.2%   (700 на 407)
        суд ф.794-9           2.1%   (228 на 259)

    Тобто сотні рядків, не десятки тисяч: декод Дяком — менше хвилини на справу
    проти 1-1.5 год самого прогону. 🔴 Для порівняння, `--beam` лікує ту саму
    хворобу, але платить за КОЖЕН рядок і коштує ×5-6 часу.
    """
    from rapidfuzz import fuzz

    spec = rescue_spec()
    FULL_N, CONF_N = spec["full"], spec["confusers"]
    _norm = spec["norm"]

    keys = [_norm(x) for x in (anchor_keys if anchor_keys is not None
                                else spec["anchors"])]
    seed: set[int] = set()
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        toks = [_norm(t) for t in _RESCUE_TOKEN.findall(ln)]
        # якір: формулярне ім'я або по батькові
        # ⚠ len ≥ 5, а не 6: «Антонъ» це рівно п'ять нормалізованих літер
        # (`anton`), і на сповідці 1846 рядок «Антонъ Якимовъ Поліщукъ»
        # відпадав саме на довжині, а не на схожості.
        # 🔴 `keys` бувають ПОРОЖНІ — і це законно: якорі збираються з родоводу
        # під роки справи, а на початку дослідження родоводу ще немає. Доти
        # канал якорів просто мовчить, і працює сам прізвищний. Перевірка тут,
        # бо без неї `max()` по порожньому падає ValueError НА ПЕРШОМУ Ж рядку —
        # тобто справа гине посеред прогону через відсутні дані, а не через
        # помилку. Раніше цього не траплялось лише тому, що запасний список імен
        # був зашитий у код.
        if keys and any(len(t) >= 5
                        and max(fuzz.ratio(t, k) for k in keys) >= RESCUE_ANCHOR_MIN
                        for t in toks):
            seed.add(i)
            continue
        # сіра смуга за балом самого прізвища
        for t in toks:
            if len(t) < 7:
                continue
            f, _ = best_ratio(t, FULL_N)
            c, _ = best_ratio(t, CONF_N, partial=False)
            if c >= f:                      # конфузер пояснює токен краще
                continue
            if grey <= f < eye:
                seed.add(i)
                break

    # 🔴🔴 СУСІДИ ОБОВ'ЯЗКОВІ, і це не «про запас». Фільтр судить РЯДОК, а в
    # щільній графі прізвище переноситься, тож доказ живе на ДВОХ рядках — і
    # ХВІСТ переносу не має чим себе видати: у ньому нема ні імені, ні по
    # батькові, ні достатнього балу.
    # Виміряно на сповідці 1846 (ДАХмО 315-1-7864, парафія №56): «Ѳеодоръ
    # Антоніевъ Доли|щинскій» — рядок 38 відібрався за іменем, а рядок 39
    # («щинскій») НІ, тож другий рушій перечитував лише голову й склеїти пару
    # не міг у принципі. У цій справі 5% рядків обриваються посеред прізвища,
    # тобто це норма жанру, а не виняток.
    out = set()
    for i in seed:
        for j in range(i - RESCUE_NEIGHBOURS, i + RESCUE_NEIGHBOURS + 1):
            if 0 <= j < len(lines) and lines[j].strip():
                out.add(j)
    return sorted(out)


def _beam_hypotheses(model, tensors, device: str, beam: int,
                     batch: int, max_steps: int = 100) -> list[list[str]]:
    """n-best кожного кропа: beam search над AR-декодером PARSeq.

    Навіщо. Правильне прочитання буває в моделі, але не першим: на ДАВО
    904-24-24 скан 0106 прізвище роду не взяла ЖОДНА з чотирьох моделей
    (шукане прізвище підмінялось іншим, теж правдоподібним), а в решітці гіпотез воно є —
    з beam-3 береться. Тобто це інший механізм, ніж ансамбль: ансамбль ловить
    там, де моделі розходяться МІЖ СОБОЮ, beam — де одна модель вагається
    ВСЕРЕДИНІ себе. Виміряно, що вони складаються (канон 88.1% → 91.5%).

    У strhub beam search немає — декодер віддає greedy + refine_iters, тому
    цикл нижче свій. `refine_iters` тут не застосовується: він переписує весь
    рядок під готову гіпотезу, а нам потрібні саме РІЗНІ шляхи.

    🔴 ЧОМУ ЦЕ НЕ ВВІМКНЕНО В ЖОДНОМУ З 102 ПРОГОНІВ НА ДИСКУ: **beam коштує
    ×5-6 до часу прогону** (заміряно дослідником). Для справи на 500 сторінок це
    7-9 годин замість 1-1.5, тобто механізм правильний, але неоплатний на потік.
    Він платить за кожен рядок справи, хоч рятує одиниці.

    ⚖ Дешевша альтернатива на ТУ САМУ хворобу («правильне прочитання не є
    топ-1») — другий рушій на ВІДІБРАНИХ рядках: Дяк (CTC) по 2-3% рядків, що
    впали у сіру смугу або мають якір по імені/по батькові, це <1 хв на справу
    проти годин. Заміряно 2026-08-08: два рятунки З НУЛЯ там, де Писар підставив
    правдоподібне ЧУЖЕ слово (бал 0.0 → 90.0 у Дяка), нуль хибних на сусідньому
    прізвищі зі спільним коренем.
    🔴 Beam і Дяк НЕ взаємозамінні: beam ловить,
    де модель вагалась усередині себе, Дяк — де вона була впевнено неправа.
    """
    import torch

    core, tok = model.model, model.tokenizer
    eos, bos, pad = tok.eos_id, tok.bos_id, tok.pad_id
    out: list[list[str]] = []
    for j in range(0, len(tensors), batch):
      with torch.no_grad():
        x = torch.stack(tensors[j:j + batch]).to(device)
        n = x.shape[0]
        mem0 = core.encode(x)
        dim = mem0.shape[-1]
        mem = mem0.unsqueeze(1).expand(n, beam, *mem0.shape[1:]).reshape(n * beam, -1, dim)
        ns = max_steps + 1
        pq = core.pos_queries[:, :ns].expand(n * beam, -1, -1)
        msk = torch.triu(torch.ones((ns, ns), dtype=torch.bool, device=device), 1)
        tgt = torch.full((n * beam, ns), pad, dtype=torch.long, device=device)
        tgt[:, 0] = bos
        sc = torch.full((n, beam), -1e9, device=device)
        sc[:, 0] = 0
        done = torch.zeros(n * beam, dtype=torch.bool, device=device)
        for i in range(max_steps):
            k = i + 1
            dec = core.decode(tgt[:, :k], mem, msk[:k, :k],
                              tgt_query=pq[:, i:k], tgt_query_mask=msk[i:k, :k])
            lp = core.head(dec).squeeze(1).log_softmax(-1)
            # завершена гіпотеза далі тягне лише EOS із нульовою ціною — інакше
            # короткі рядки штрафувались би за кожен зайвий крок і витіснялись
            frozen = torch.full_like(lp, -1e9)
            frozen[:, eos] = 0.0
            lp = torch.where(done.unsqueeze(1), frozen, lp)
            cand = (sc.reshape(-1, 1) + lp).reshape(n, beam * lp.shape[-1])
            sc, idx = cand.topk(beam, dim=-1)
            src = (idx // lp.shape[-1]) + torch.arange(n, device=device).unsqueeze(1) * beam
            chosen = (idx % lp.shape[-1]).reshape(-1)
            tgt = tgt[src.reshape(-1)]
            done = done[src.reshape(-1)]
            tgt[:, k] = chosen
            done = done | (chosen == eos)
            if bool(done.all()):
                break
        ids = tgt[:, 1:].reshape(n, beam, -1)
        for a in range(n):
            hyps = []
            for b in range(beam):
                row = ids[a, b].tolist()
                if eos in row:
                    row = row[:row.index(eos)]
                hyps.append("".join(tok._itos[t] for t in row))
            out.append(hyps)
    return out


# ── 💾 КЕШ СЕГМЕНТАЦІЇ ───────────────────────────────────────────────────────
# Сегментація — 60% вартості сторінки (заміряно: 7.3 с із 12.3 на кадрі з 78
# рядками) і при цьому вона НЕ ЗАЛЕЖИТЬ від моделі розпізнавання: `blla` ріже
# аркуш на рядки, а хто їх потім читає — Писар, Дяк чи модель, якої ще немає, —
# сегментеру байдуже. Доти кожен новий прогін платив за неї заново, тобто вихід
# нової версії моделі коштував ПОВНОГО переганяння всіх справ.
#
# Круговий тест (ДАВО 904-24-24, кадр 0012, 78 рядків): `Segmentation` лягає в
# 53.5 КБ JSON, відновлюється за 0.23 с, і кропи з відновленої сегментації
# ПОБІТОВО ті самі, рамки теж. Тобто повторний прогін іншою моделлю коштує
# рівно декод.
#
# 🔴 Кеш валідний лише за ТИХ САМИХ параметрів нарізки, і мовчазний промах тут
# був би найгіршого сорту — інші рядки, тобто інший текст, без сліду в лозі.
# Тому ключ несе все, що змінює полігони: підняття контрасту (воно йде ДО
# сегментації), висота сегментера, стеля endpoint'ів, сигми sato і версія
# kraken. Кут повороту І СТЕЛЯ — ще й в ІМЕНІ файлу: одна сторінка законно має
# по сегментації на кожен випробуваний поворот, а `--ceiling-retry` законно
# рахує ту саму сторінку двічі з різними стелями. Спільне ім'я на два законні
# результати = вічний промах для обох (див. `Segmenter._file`).
SEG_CACHE_VERSION = 1

#: Версія kraken іде В КЛЮЧ кешу: підмінені гарячі функції сегментації
#: (`scripts/KRAKEN_PATCHES.md`) прив'язані до 7.0.2, і на іншій версії полігони
#: рядків можуть відрізнятись — а такий промах був би тихим.
try:
    from importlib.metadata import version as _pkg_version

    KRAKEN_PIN_VERSION = _pkg_version("kraken")
except Exception:
    KRAKEN_PIN_VERSION = "?"


def _seg_to_blob(seg) -> dict:
    """Segmentation → JSON-придатний dict (те, з чого відновлюються кропи)."""
    def _pts(v):
        return [[int(x), int(y)] for x, y in (v or [])]

    return {
        "type": seg.type, "imagename": str(seg.imagename or ""),
        "text_direction": seg.text_direction,
        "script_detection": bool(seg.script_detection),
        "language": seg.language, "line_orders": seg.line_orders,
        "lines": [{"id": ln.id, "baseline": _pts(ln.baseline),
                   "boundary": _pts(ln.boundary), "tags": ln.tags,
                   "type": ln.type, "base_dir": ln.base_dir,
                   "regions": list(ln.regions or []), "split": ln.split,
                   "language": ln.language} for ln in seg.lines],
        "regions": {k: [{"id": r.id, "boundary": _pts(r.boundary),
                         "tags": r.tags, "language": r.language}
                        for r in v] for k, v in (seg.regions or {}).items()},
    }


def _seg_from_blob(b: dict):
    from kraken.containers import BaselineLine, Region, Segmentation

    return Segmentation(
        type=b["type"], imagename=b["imagename"],
        text_direction=b["text_direction"],
        script_detection=b["script_detection"],
        language=b.get("language"), line_orders=b.get("line_orders"),
        lines=[BaselineLine(
            id=l["id"], baseline=[tuple(p) for p in l["baseline"]],
            boundary=[tuple(p) for p in l["boundary"]], tags=l.get("tags"),
            type=l.get("type") or "baselines", base_dir=l.get("base_dir"),
            regions=l.get("regions") or [], split=l.get("split"),
            language=l.get("language")) for l in b["lines"]],
        regions={k: [Region(id=r["id"],
                            boundary=[tuple(p) for p in r["boundary"]],
                            tags=r.get("tags"), language=r.get("language"))
                     for r in v] for k, v in (b.get("regions") or {}).items()})


class Segmenter:
    """Сегментація сторінки з кешем на диску і ЛЕДАЧОЮ моделлю.

    Ледача модель — не мікрооптимізація: коли справа вже сегментована, `blla`
    не вантажиться взагалі, а це і пікова VRAM сторінки, і плюс воркер на
    4-гігабайтній карті. Прогін «ще одним голосом по вже пройденій справі» стає
    декодом у чистому вигляді.
    """

    def __init__(self, model_path: str, device: str, seg_height: int = 0,
                 cache_dir: Path | None = None, key: dict | None = None,
                 write: bool = True):
        self._path, self._device, self._h = model_path, device, seg_height
        self.dir, self._key, self._write = cache_dir, key or {}, write
        self._model = None
        self.hits = self.misses = self.written = 0

    # модель вантажиться на ПЕРШОМУ промаху, не на старті
    def _net(self):
        if self._model is None:
            from kraken.lib import vgsl
            self._model = vgsl.TorchVGSLModel.load_model(self._path)
            if self._h:
                b, c, h0, w = self._model.input
                self._model.input = (b, c, self._h, w)
                print(f"[htr-run] висота сегментації {h0} → {self._h}", flush=True)
        return self._model

    def _file(self, stem: str, orient: int) -> Path | None:
        # 🔴 Стеля — В ІМЕНІ, а не лише в ключі. Доти сторінка, що спрацювала на
        # `--ceiling-retry`, писалась ДВІЧІ під одним іменем (стеля 400, потім
        # 1600) з різними ключами: у файлі лишався останній, і на наступному
        # прогоні ОБИДВА проходи давали промах ключа. Тобто саме на щільних
        # формулярах, де перепуск і потрібен (ДАЖО 178-51-418: 141 з 244
        # сторінок у стелі), кеш не працював узагалі — мовчки, бо промах ключа
        # виглядає як «сторінки ще не було».
        if not self.dir:
            return None
        c = self._full_key().get("ceiling")
        suf = f".c{c}" if c is not None else ""
        return self.dir / f"{stem}.o{orient}{suf}.seg.json.gz"

    def _full_key(self) -> dict:
        # стеля читається на КОЖНОМУ виклику: `--ceiling-retry` піднімає її на
        # час перепуску сторінки, і сегментація з піднятою стелею — інший
        # результат, який не має права лягти під тим самим ключем
        k = dict(self._key)
        try:
            import seg_ceiling
            k["ceiling"] = seg_ceiling.ceiling()
        except Exception:
            pass
        k["seg_height"] = self._h
        k["v"] = SEG_CACHE_VERSION
        return k

    def load(self, stem: str, orient: int, enhanced: str):
        f = self._file(stem, orient)
        if not f:
            return None
        if not f.is_file():
            # кеш до 2026-08-09 писався без стелі в імені — читаємо, але не
            # пишемо: ключ однаково звіряється нижче, тож помилитись нічим, а
            # інакше фікс імені викинув би вже пораховані справи
            legacy = f.parent / f"{stem}.o{orient}.seg.json.gz"
            if not legacy.is_file():
                return None
            f = legacy
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            return None
        if blob.get("key") != {**self._full_key(), "enhanced": enhanced}:
            return None            # інші параметри нарізки — не наш кеш
        try:
            return _seg_from_blob(blob["seg"])
        except Exception:
            return None

    def save(self, stem: str, orient: int, enhanced: str, seg) -> None:
        f = self._file(stem, orient)
        if not f or not self._write:
            return
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(f".{os.getpid()}.tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump({"key": {**self._full_key(), "enhanced": enhanced},
                           "seg": _seg_to_blob(seg)}, fh, ensure_ascii=False)
            os.replace(tmp, f)
            self.written += 1
        except Exception:
            pass                   # кеш — прискорювач, а не умова роботи

    def segment(self, im: Image.Image, stem: str = "", orient: int = 0,
                enhanced: str = ""):
        if stem:
            got = self.load(stem, orient, enhanced)
            if got is not None:
                self.hits += 1
                return got
        from kraken import blla
        seg = blla.segment(im, model=self._net(), device=self._device)
        self.misses += 1
        if stem:
            self.save(stem, orient, enhanced, seg)
        return seg


def resolve_case_key(case_dir: Path, run_name: str = "",
                     given: str = "") -> str:
    """Ключ справи (`АРХІВ/фонд/справа`) для мети прогону.

    🔴 Ключ ПЕРЕДАЄ ВИКЛИКАЧ (`--case-key`), а не рахує раннер. Раннер їде під
    інтерпретатором середовища рушіїв, де пакета з резолвером немає, і спроба
    імпортувати його звідси провалювалась мовчки — `except Exception: return ""`.

    Ціна виміряна прямо на диску: **0 із 412** мет мали `case_key`, при тому що
    він числився робочим і на нього спирався реєстр справ. Провал був невидимий
    рівно тому, що виглядав як «ключ не вдалось визначити», а не як «код не
    виконався».

    Рахувати ключ мусить той, у кого є каталог і тека справи під рукою — у
    хмарі мета отримує шлях орендованого боксу, з якого справу вже не відновити.
    """
    if given:
        return given
    # Фолбек без каталогу: шифра просто з імені теки. Реєстр звіряє такий ключ
    # зі своїм списком і мовчки ігнорує неспівпадіння, тож помилитись безпечно.
    m = re.match(r"^0?(\d{3,6})[-_](\d{1,3})[-_]0*(\d{1,6})",
                 (run_name or Path(case_dir).name).strip())
    return f"?/{m.group(1)}/{m.group(3)}" if m else ""


#: Маркер робочого простору. Дублюється тут літерально — як і префікс
#: прогрес-каналу: прочитати його з пакета звідси нічим.
WORKSPACE_MARKER = "nyshporka.toml"


def workspace_root(*hints: Path) -> Path:
    """Корінь робочого простору — підйомом угору від того, що дали, до маркера.

    🔴 Не від `__file__`. Доки раннер лежав у `scripts/` дослідницького репо,
    «два рівні вгору від себе» випадково збігалося з коренем даних — і саме тому
    формула прожила стільки років. Після переїзду в пакет вона мовчки поклала б
    кеш сегментації в дерево КОДУ: помилки немає, прогін іде, просто влучань у
    кеш завжди 0%. Дізнатись про це можна лише за рахунком за нічний прогін.

    Фолбек — батько виходу; він гірший, але явний і надрукований.
    """
    for hint in hints:
        cur = Path(hint).resolve()
        for cand in (cur, *cur.parents):
            if (cand / WORKSPACE_MARKER).is_file():
                return cand
    return Path(hints[0]).resolve().parent


def seg_cache_dir_for(case_dir: Path, root: Path) -> Path:
    """Тека кешу справи. Кеш спільний для ВСІХ прогонів цієї справи — інакше
    він не мав би сенсу: економія з'являється саме тоді, коли справу читає
    друга модель, тобто інший прогін в іншій теці."""
    h = hashlib.blake2b(str(case_dir.resolve()).lower().encode("utf-8"),
                        digest_size=4).hexdigest()
    return root / "data" / "derived" / "htr_seg" / f"{_SAFE_SLUG.sub('_', case_dir.name)}__{h}"


_SAFE_SLUG = __import__("re").compile(r"[^\w.\-]+", __import__("re").UNICODE)


def ocr_page_parseq(im: Image.Image, segmenter, rec, device: str,
                    batch: int = 32, seg_ctx: dict | None = None
                    ) -> tuple[list[str], float]:
    """Сегментація kraken'ом → рядкові кропи → PARSeq батчем.

    ⚠ Повернений `conf` — середня ймовірність токена від автогресивного декодера.
    Вона МАЙЖЕ НЕ корелює з правильністю (модель однаково впевнена в марення), тож
    годиться лише як діагностика в UI; порогові рішення на ній не будуються —
    див. `DEF_SURE_CONF_PARSEQ`.
    """
    import torch

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pysar_lines_infer import clean_pysar_text

    # `rec` — або одна модель, або (основна, [(тег, рушій, модель), …], beam):
    # сегментація коштує 60% сторінки, тож усі додаткові голоси декодуються
    # з ОДНОГО її проходу. Інакше кожна зайва модель = ще один повний прогін.
    extra_recs: list = []
    beam = 0
    if isinstance(rec, tuple) and len(rec) == 3 and isinstance(rec[1], list):
        rec, extra_recs, beam = rec
    model, (h, w) = rec
    ctx = seg_ctx or {}
    seg = segmenter.segment(im, ctx.get("stem", ""), ctx.get("orient", 0),
                            ctx.get("enhanced", ""))
    crops = _line_crops(im, seg)
    # рамки — з ТОГО САМОГО фільтра, що й кропи (див. `_line_crops`)
    ocr_page_parseq.boxes = list(getattr(_line_crops, "boxes", []) or [])
    ocr_page_parseq.polys = list(getattr(_line_crops, "polys", []) or [])
    # 🖼 Розмір ЗОБРАЖЕННЯ, у координатах якого лежать рамки — тобто вже
    # повернутого (`rotated`) і, можливо, посиленого (`enhance` геометрії не
    # міняє). Без нього рамка — числа без системи відліку: споживач не знає, від
    # чого масштабувати, а мета розміру не зберігає.
    ocr_page_parseq.size = [int(im.width), int(im.height)]
    if not crops:
        return [], 0.0

    tensors = []
    for crop in crops:
        arr = np.asarray(crop.convert("RGB").resize((w, h), Image.LANCZOS),
                         dtype="float32") / 255.0
        tensors.append(torch.from_numpy((arr - 0.5) / 0.5).permute(2, 0, 1))

    lines: list[str] = []
    confs: list[float] = []
    # 🔴 Рамки вирівнюються по ФІНАЛЬНОМУ списку рядків, а не по кропах: нижче
    # стоїть `if text:`, тобто порожні прочитання ВИПАДАЮТЬ, і `lines[i]` уже не
    # відповідає `crops[i]`. Рамка за індексом кропа показувала б не той рядок —
    # і показувала б МОВЧКИ.
    # 🔴🔴 І оголошення, і індекс мусять бути ПОЗА батч-циклом: декод іде
    # батчами по `batch` кропів, тож `enumerate` дає індекс У МЕЖАХ БАТЧА, а не
    # глобальний. Перша редакція цього коду скидала список на кожному батчі й
    # брала рамку за локальним індексом — вижили б рамки лише останнього батча,
    # ще й не тих рядків. Саме той клас тихого зсуву, від якого застерігає
    # коментар вище; спіймано на пробному прогоні (файл просто не записався,
    # бо довжини не збіглися).
    _all_boxes = list(getattr(_line_crops, "boxes", []) or [])
    _all_polys = list(getattr(_line_crops, "polys", []) or [])
    _kept_boxes: list = []
    _kept_polys: list = []
    # Кропи теж лишаємо вирівняними з рядками — їх забирає рятувальний прохід
    # (`--rescue`), щоб перечитати відібрані рядки ДРУГИМ рушієм БЕЗ повторної
    # сегментації. Пам'ять не додається: кропи вже живі, тут лише посилання.
    _kept_crops: list = []
    kept: list[int] = []                      # глобальні індекси кропів, що вижили
    for j in range(0, len(tensors), batch):
        x = torch.stack(tensors[j:j + batch]).to(device)
        with torch.no_grad():
            probs = model(x).softmax(-1)
        preds, per_tok = model.tokenizer.decode(probs)
        # Обидва з ОДНОГО `decode` — різна довжина означала б ваду рушія, і
        # тихо обрізати її не можна: сторінка мовчки лишилась би без хвоста.
        for _k, (text, p) in enumerate(zip(preds, per_tok, strict=True)):
            # NFC — щоб combining-діакритика не ламала fuzzy-пошук (як у kraken-гілці);
            # clean_pysar_text прибирає маркери конфлікту ‹|›, які модель v5b
            # успадкувала з забрудненого корпусу і вставляє прямо в текст справи
            text = clean_pysar_text(unicodedata.normalize("NFC", str(text or "")))
            if text:
                g = j + _k                    # ГЛОБАЛЬНИЙ індекс кропа
                lines.append(text)
                kept.append(g)
                _kept_boxes.append(_all_boxes[g] if g < len(_all_boxes) else None)
                _kept_polys.append(_all_polys[g] if g < len(_all_polys) else None)
                _kept_crops.append(crops[g] if g < len(crops) else None)
                if p is not None and getattr(p, "numel", lambda: 0)():
                    confs.append(float(p.mean()))
    ocr_page_parseq.boxes = _kept_boxes
    ocr_page_parseq.polys = _kept_polys
    ocr_page_parseq.crops = _kept_crops

    # ── ГОЛОСИ: ті самі кропи, ЖОДНОЇ повторної сегментації ──────────────────
    # Основний текст лишається greedy однією моделлю: n-best у ньому зробив би
    # сторінку нечитабельною (10 гіпотез на рядок), а він потрібен людині.
    #
    # 🔴 Голос вирівнюється по МАСЦІ основного тексту (`kept`), а не фільтрує
    # порожні самостійно. Доти кожна тека відкидала свої порожні прочитання
    # незалежно — і щойно голоси розходились хоч на одному рядку, `<out>-v12`
    # з'їжджав відносно `<out>` на решту сторінки. Зсув був ТИХИЙ: обидві теки
    # виглядають нормальним текстом, а рамка з `.lines.json` показує вже не той
    # рядок. Рядки, які голос прочитав ТАМ, ДЕ ОСНОВНА МОДЕЛЬ ЗАМОВЧАЛА,
    # рахуються і друкуються в підсумку — мовчазна втрата була б гіршою за саму
    # втрату (на пробі Писар давав 0 порожніх на 233 рядки, Дяк 1-3).
    side: dict[str, list[str]] = {}
    lost: dict[str, int] = {}
    kept_set = set(kept)
    for tag, eengine, erec in extra_recs:
        if eengine == "kraken":
            full = kraken_decode_crops(erec, crops, VOICE_BATCH)
        else:
            emodel, (eh, ew) = erec
            etens = tensors if (eh, ew) == (h, w) else [
                torch.from_numpy(
                    (np.asarray(c.convert("RGB").resize((ew, eh), Image.LANCZOS),
                                dtype="float32") / 255.0 - 0.5) / 0.5).permute(2, 0, 1)
                for c in crops]
            full = []
            for j in range(0, len(etens), batch):
                x = torch.stack(etens[j:j + batch]).to(device)
                with torch.no_grad():
                    p = emodel(x).softmax(-1)
                preds, _ = emodel.tokenizer.decode(p)
                full += [clean_pysar_text(unicodedata.normalize("NFC", str(t or "")))
                         for t in preds]
        side[tag] = [full[g] if g < len(full) else "" for g in kept]
        n_lost = sum(1 for i, t in enumerate(full)
                     if t.strip() and i not in kept_set)
        if n_lost:
            lost[tag] = n_lost
    if beam > 1:
        # ⚠ beam-тека вирівнюванню не піддається за побудовою: гіпотез на рядок
        # кілька, і рядків у ній більше, ніж у справі. Вона для пошуку, не для
        # показу поруч із основним текстом.
        hyps = _beam_hypotheses(model, tensors, device, beam, batch)
        side[f"beam{beam}"] = [clean_pysar_text(unicodedata.normalize("NFC", h_))
                               for hs in hyps for h_ in hs
                               if clean_pysar_text(h_).strip()]
    if side:
        ocr_page_parseq.side = side          # забирає `process_page`
    ocr_page_parseq.side_lost = lost

    avg = float(np.mean(confs)) if confs else 0.0
    return lines, avg


def ocr_page(im: Image.Image, segmenter, rec_model, device: str,
             engine: str = "kraken", batch: int = 32,
             seg_ctx: dict | None = None) -> tuple[list[str], float]:
    """Розпізнати сторінку → (рядки NFC, середній посимвольний conf)."""
    if engine == "parseq":
        return ocr_page_parseq(im, segmenter, rec_model, device, batch, seg_ctx)
    from kraken import rpred

    ctx = seg_ctx or {}
    seg = segmenter.segment(im, ctx.get("stem", ""), ctx.get("orient", 0),
                            ctx.get("enhanced", ""))
    lines: list[str] = []
    confs: list[float] = []
    # 🖼 Рамки kraken-гілки. Раніше їх тут не збирали свідомо: «краще без рамок,
    # ніж із рамками не тих рядків» — бо `lines` фільтрується (`if text`), і
    # зіставлення з `seg.lines` за індексом дало б ТИХИЙ зсув. Тепер причини
    # немає: `BaselineOCRRecord` успадковує `BaselineLine`, тобто САМ несе свою
    # геометрію, і рамка береться з того ж об'єкта, що й текст.
    # 🔴 Все або нічого: якщо хоч на одному записі геометрії немає — рамок за
    # сторінку немає взагалі. Частковий список мовчки з'їхав би на решту.
    boxes: list | None = []
    polys: list | None = []
    for rec in rpred.rpred(rec_model, im, seg):
        text = unicodedata.normalize("NFC", str(rec.prediction or "")).strip()
        if text:
            lines.append(text)
            confs.extend(float(c) for c in (rec.confidences or []))
            pts = list(getattr(rec, "boundary", None)
                       or getattr(rec, "baseline", None) or [])
            if not pts or boxes is None:
                boxes = polys = None
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            boxes.append([int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))])
            polys.append([[int(x), int(y)] for x, y in pts])
    ocr_page.boxes = boxes
    ocr_page.polys = polys
    ocr_page.size = [int(im.width), int(im.height)]
    avg = float(np.mean(confs)) if confs else 0.0
    return lines, avg


def _geom_of(engine: str) -> dict:
    """Геометрія рядків ЩОЙНО прочитаної сторінки → у результат цього прочитання.

    🔴 Знімається одразу після `ocr_page`, а не в кінці: рамки лежать атрибутом
    функції, а `process_page` пробує кілька поворотів і бере не обов'язково
    останній (`run()` кешує кандидатів, гард може повернутись до `run(0)`).
    Прочитавши атрибут у кінці, можна взяти рамки ІНШОГО повороту — з тією ж
    кількістю рядків, тобто повз гард довжин, і мовчки.
    """
    src_fn = ocr_page_parseq if engine == "parseq" else ocr_page
    return {"boxes": getattr(src_fn, "boxes", None),
            "polys": getattr(src_fn, "polys", None),
            "size": getattr(src_fn, "size", None)}


def process_page(src: Path, segmenter, rec_model, device: str,
                 min_conf: float, min_chars: float,
                 sure_conf: float = DEF_SURE_CONF, orient_net=None,
                 guard_state: dict | None = None,
                 guard_warmup: int = DEF_GUARD_WARMUP,
                 engine: str = "kraken", batch: int = 32,
                 force_orient: int = -1, enhance: str = "none") -> dict:
    """Сторінка з retry по кандидатах повороту + адаптивний 180°-гард.

    Порядок кандидатів: CNN-фікс (якщо модель є) → профіль-детектор. Обидва лише
    ПРОПОНУЮТЬ порядок — фінальне слово завжди за conf-гейтом і 180°-гардом.
    `guard_state` = {"checks","flips","conf_sum","conf_n"} — накопичується по
    справі в межах процесу (після resume розвідка почнеться заново — це ок).

    Кожен кандидат повороту сегментується ОКРЕМО і кешується окремо (кут — у
    імені файла кешу): при повторному прогоні справи іншою моделлю безкоштовними
    стають не лише прийняті сторінки, а й очні ставки гарда.
    """
    with Image.open(src) as raw:
        im0 = raw.convert("RGB")
    # контраст піднімається ДО детекторів орієнтації: і профіль-детектор, і CNN
    # дивляться на ink-профіль, а на вицвілому аркуші його майже немає
    applied, contrast = enhance, None
    if enhance == "auto":
        # посторінково, а не на справу: у ф.792-1-43 вицвів БЛОК (скани
        # 1290-1550), а решта 1290 аркушів здорові — вмикати CLAHE на всю справу
        # означало б зіпсувати 5/6 її обсягу
        contrast = page_contrast(im0)
        applied = AUTO_ENHANCE_MODE if contrast < AUTO_CONTRAST_THRESHOLD else "none"
    im0 = enhance_image(im0, applied)
    # що САМЕ застосовано до цієї сторінки — у кожен вихід: інакше в справі з
    # `auto` неможливо сказати, чи бліду сторінку підняли, чи вона просто така
    enh = {"enhanced": applied if applied != "none" else "",
           "contrast": round(contrast, 1) if contrast is not None else None}
    # контекст кешу сегментації: кадр + що з ним зробили до нарізки
    sctx = {"stem": src.stem, "enhanced": enh["enhanced"]}
    if force_orient >= 0:
        # Око дослідника > будь-який детектор. Ні профіль, ні CNN, ні 180°-гард не
        # запускаються: одна дорога сегментація на сторінку, нуль шансів на фліп.
        lines, conf = ocr_page(rotated(im0, force_orient), segmenter, rec_model,
                               device, engine, batch,
                               {**sctx, "orient": force_orient})
        return {"orient": force_orient, "lines": lines, "conf": round(conf, 4),
                "chars": sum(len(ln) for ln in lines),
                "detector": f"forced{force_orient}", "retried": False,
                "guarded": False, **_geom_of(engine), **enh}
    verdict = detect_orientation(im0)
    cands = orient_candidates(verdict)
    if orient_net is not None:
        try:
            fix = cnn_fix(orient_net, im0, device)
            verdict = f"cnn{fix}|{verdict}"
            cands = [fix] + [o for o in (0, 90, 180, 270) if o != fix]
        except Exception:
            pass  # CNN упав на цій сторінці → лишаємось на профілі
    tried: dict[int, dict] = {}   # orient → результат (кожен поворот OCR-иться раз)

    def run(orient: int) -> dict:
        if orient not in tried:
            lines, conf = ocr_page(rotated(im0, orient), segmenter, rec_model,
                                   device, engine, batch, {**sctx, "orient": orient})
            tried[orient] = {"orient": orient, "lines": lines,
                             "conf": round(conf, 4),
                             "chars": sum(len(ln) for ln in lines),
                             **_geom_of(engine)}
        return tried[orient]

    pick: dict | None = None
    for idx, orient in enumerate(cands):
        cand = run(orient)
        if cand["conf"] >= min_conf and cand["chars"] >= min_chars:
            pick = cand
            break
        # Перший кандидат від CNN/UPRIGHT-вердикту з хоч якимось текстом не
        # ганяємо по всіх поворотах: це майже завжди бліда сторінка, а не
        # лежача — а 180°-гард нижче все одно зробить очну ставку
        if idx == 0 and cand["chars"] >= min_chars and \
                (verdict.startswith("cnn") or verdict == "UPRIGHT"):
            break
    if pick is None:
        # 🐞 ФІКС 2026-08-07: для PARSeq переможець — за СИМВОЛАМИ, не за conf.
        # Тут була пряма суперечність із власним правилом проєкту («conf PARSeq
        # сигналом якості не є», §2.5): гейт вище й гард нижче спираються на
        # chars, а цей fallback — на conf. Спрацьовує він саме на сторінках, які
        # не пройшли жодного порога, тобто на найненадійніших, і там conf —
        # чистий шум. На ДАВО 904-24-24 саме він перевернув 0123 і 0239.
        key = (lambda c: c["chars"]) if engine == "parseq" else (lambda c: c["conf"])
        pick = max(tried.values(), key=key) if tried else \
            {"orient": 0, "lines": [], "conf": 0.0, "chars": 0}
    # Мізерний текст = немає підстав узагалі щось вирішувати про орієнтацію.
    # Повертаємось до 0° (типова орієнтація сканування), не витрачаючи ще один
    # прохід на очну ставку: різниця в кілька десятків символів на порожньому
    # аркуші не відрізняє правильну сторінку від перевернутої.
    if pick["orient"] != 0 and pick["chars"] < ORIENT_MIN_EVIDENCE:
        pick = run(0)
        return {**pick, "detector": verdict + "|low-evidence",
                "retried": len(tried) > 1, "guarded": False, **enh}
    # ── гард ОРІЄНТАЦІЇ для parseq: критерій — CHARS, не conf ────────────────
    # 🐞 Інцидент ф.196-1-5953 (2026-07-30): CNN-детектор дав `cnn180` на 8
    # НОРМАЛЬНО орієнтованих сторінках із 46, прогін їх перевернув, і декод став
    # суцільним сміттям («мастутник / раслена праналъ вип стапу») — а conf при
    # цьому 0.8511, ВИЩЕ середнього по справі. Тобто conf для parseq не рятує
    # (тому conf-гард нижче для нього й вимкнений), і хибний вердикт CNN не
    # ловився нічим. Причина хибності CNN: кадри — РОЗВОРОТИ з порожньою
    # половиною, а він тренований на одиночних сторінках.
    #
    # Робочий сигнал знайдено виміром: при правильній орієнтації PARSeq видає
    # ЗНАЧНО БІЛЬШЕ символів при тій самій кількості рядків (0003: 886→1218,
    # 0004: 700→964, 0025: 463→869, тобто +37…88%). На перевернутому тексті
    # модель «здається» рано, не бачачи знайомих форм літер. Критерій працює в
    # обидва боки: якщо сторінка СПРАВДІ перевернута, більше символів дасть
    # поворот, і гард візьме його.
    if engine == "parseq" and pick["orient"] != 0 and pick["chars"] > 0:
        alt = run(0)
        if alt["chars"] > pick["chars"] * (1 + ORIENT_CHARS_MARGIN):
            pick = alt
        elif pick["chars"] > alt["chars"] * (1 + ORIENT_CHARS_MARGIN):
            pass                      # поворот справді кращий — лишаємо
        else:
            pick = alt                # різниці немає → 0 як типова орієнтація
        return {**pick, "detector": verdict + "|chars",
                "retried": len(tried) > 1, "guarded": True, **enh}

    # 180°-гард: непевний результат звіряємо з протилежним поворотом (адаптивно)
    gs = guard_state if guard_state is not None else \
        {"checks": 0, "flips": 0, "conf_sum": 0.0, "conf_n": 0}
    avg = gs["conf_sum"] / gs["conf_n"] if gs["conf_n"] else None
    flip_rate = gs["flips"] / gs["checks"] if gs["checks"] else 0.0
    systematic = gs["flips"] >= GUARD_MIN_FLIPS and flip_rate >= GUARD_FLIP_RATE
    routine = systematic or gs["checks"] < guard_warmup
    anomaly = avg is not None and pick["conf"] < avg - GUARD_MARGIN
    guarded = False
    if pick["conf"] < sure_conf and pick["chars"] > 0 and (routine or anomaly):
        guarded = True
        alt = run((pick["orient"] + 180) % 360)
        gs["checks"] += 1
        if alt["conf"] > pick["conf"]:
            gs["flips"] += 1
            pick = alt
    if pick["chars"] > 0:
        gs["conf_sum"] += pick["conf"]
        gs["conf_n"] += 1
    return {**pick, "detector": verdict, "retried": len(tried) > 1,
            "guarded": guarded, **enh}


# ── meta / io ────────────────────────────────────────────────────────────────
def atomic_write(path: Path, text: str) -> None:
    # tmp з pid — інакше паралельні шарди перетирають tmp один одному
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    # на Windows os.replace падає з PermissionError, якщо ціль саме читає
    # в'ювер консолі — мета велика (тисячі сторінок), тож це реально буває
    for attempt in range(4):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.2)


def parse_shard(spec: str) -> tuple[int, int]:
    """'2/3' → (1, 3): 0-based індекс воркера і скільки їх усього."""
    if not spec.strip():
        return 0, 1
    a, _, b = spec.partition("/")
    k, n = int(a), int(b or 1)
    if n < 1 or not (1 <= k <= n):
        raise ValueError(f"--shard {spec}: очікую k/n, 1 ≤ k ≤ n")
    return k - 1, n


def merge_meta(out_dir: Path, base: dict) -> None:
    """Звести `_htr_meta.part*.json` шардів у спільний `_htr_meta.json`.

    Кожен воркер пише ТІЛЬКИ свій парт (тож гонки за записом немає), а спільну
    мету — яку читає в'ювер і сховище прогонів — перезбирає будь-який із них
    після своїх сторінок, під локом `_htr_meta.lock`. Union: базовий шар —
    наявна спільна мета (там лежать сторінки до-шардингових прогонів, їх не
    можна загубити), поверх — парти. Відставання на пів-сторінки некритичне.
    """
    merged_path = out_dir / "_htr_meta.json"
    with _file_lock_ctx(out_dir / "_htr_meta.lock")():
        pages: dict = {}
        failed: list[str] = []
        started = base.get("started")
        try:
            prev = json.loads(merged_path.read_text(encoding="utf-8"))
            pages.update(prev.get("pages") or {})
            started = prev.get("started") or started
        except (OSError, json.JSONDecodeError):
            pass
        done_all = True
        parts = sorted(out_dir.glob("_htr_meta.part*.json"))
        for part in parts:
            try:
                d = json.loads(part.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                done_all = False
                continue
            pages.update(d.get("pages") or {})
            for f in d.get("failed") or []:
                if f not in failed:
                    failed.append(f)
            if d.get("started") and (not started or d["started"] < started):
                started = d["started"]
            done_all = done_all and bool(d.get("done"))
        failed = [f for f in failed if f not in pages]
        merged = {**base, "started": started, "pages": pages, "failed": failed,
                  "done": done_all and bool(parts),
                  "updated": datetime.now().isoformat(timespec="seconds")}
        atomic_write(merged_path,
                     json.dumps(merged, ensure_ascii=False, indent=1) + "\n")


def sync_guard(shared_path: Path, gs: dict, pushed: dict) -> None:
    """Звести стан 180°-гарда між шардами через спільний файл (in-place у `gs`).

    Шарди йдуть ОДНІЄЮ справою — той самий писар, та сама якість сканів, — тож
    вести три окремі розвідки безглуздо: квота стає 15×N замість 15, і кожна
    зайва очна ставка коштує подвійного OCR-проходу. Гірше: фліп, знайдений одним
    шардом, не вмикав посилений режим у двох інших, хоча перевернуті сторінки
    розкидані по всій справі.

    Синхронізація дельтами: у спільний файл доливаємо те, що наросло локально з
    минулого разу, і забираємо звідти агрегат. Гонка двох шардів на одному
    лічильнику дає похибку ±1 перевірку — на тлі 15 це неважливо, тому лок лише
    навколо read-modify-write, без глобальної серіалізації сторінок.
    """
    keys = ("checks", "flips", "conf_sum", "conf_n")
    delta = {k: gs[k] - pushed.get(k, 0) for k in keys}
    try:
        with _file_lock_ctx(shared_path.with_suffix(".lock"))():
            try:
                cur = json.loads(shared_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cur = {}
            merged = {k: (cur.get(k) or 0) + delta[k] for k in keys}
            atomic_write(shared_path, json.dumps(merged, ensure_ascii=False) + "\n")
    except OSError as exc:
        # стан гарда — оптимізація, а не критичний шлях: якщо файл раптом
        # недоступний (антивірус тримає, диск зайнятий), шард має доїхати на
        # власному лічильнику, а не впасти посеред багатогодинного прогону
        print(f"[htr-run] ⚠ синк гарда не вдався ({exc}) — працюю локально",
              flush=True)
        return
    gs.update(merged)          # локальний стан = загальний по справі
    pushed.update({k: gs[k] for k in keys})


def known_pages(out_dir: Path) -> set[str]:
    """Усі вже розпізнані сторінки (свій парт + чужі + доshard-ова мета)."""
    seen: set[str] = set()
    for p in [out_dir / "_htr_meta.json", *out_dir.glob("_htr_meta.part*.json")]:
        try:
            seen.update(json.loads(p.read_text(encoding="utf-8")).get("pages") or {})
        except (OSError, json.JSONDecodeError):
            continue
    return seen


def load_quarantine(out_dir: Path) -> dict[str, dict]:
    """Сторінки, на яких прогін уже вішався — їх пропускаємо не читаючи.

    Файл пише консоль (`HtrManager`), коли вотчдог ДРУГИЙ раз добиває шард на
    тому самому файлі: сторінка, яка кладе сегментер намертво, інакше з'їдала б
    по 10 хв тиші на кожному нічному рестарті й не давала справі дочитатись.
    Формат: `{"pages": {"0042.jpg": {"reason": …, "at": …}}}`.
    """
    try:
        data = json.loads((out_dir / "_htr_quarantine.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    pages = data.get("pages")
    return pages if isinstance(pages, dict) else {}


def add_quarantine(out_dir: Path, page: str, reason: str) -> None:
    """Дописати сторінку в `_htr_quarantine.json` (той самий формат, що в HtrManager).

    Потрібно не лише консолі: при ручному запуску вотчдога немає, а сторінка,
    яка вбиває ПРОЦЕС (не виняток), інакше кладе кожну наступну спробу на тому
    самому кадрі — і справа не дочитується ніколи.
    """
    path = out_dir / "_htr_quarantine.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    known = data.get("pages") if isinstance(data.get("pages"), dict) else {}
    known[page] = {"reason": reason,
                   "at": datetime.now().isoformat(timespec="seconds")}
    try:
        path.write_text(json.dumps({"version": 1, "pages": known},
                                   ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    except OSError as exc:
        print(f"[htr-run] ⚠ карантин не записався ({exc})", flush=True)


def select_pages(case_dir: Path, pages_arg: str, limit: int,
                 shard_k: int, shard_n: int) -> list[Path]:
    """Кадри, які цей процес МУСИТЬ пройти (з урахуванням --pages/--limit/--shard).

    Винесено з main, бо той самий набір потрібен наглядачеві (`supervise`): без
    нього він не знає знаменника і не може сказати, чи прогін повний.
    """
    pages_all = sorted(p for p in case_dir.iterdir()
                       if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    wanted = parse_pages(pages_arg, len(pages_all))
    if wanted is not None:
        pages_all = [p for i, p in enumerate(pages_all, 1) if i in wanted]
    if limit:
        pages_all = pages_all[:limit]
    if shard_n > 1:
        # round-robin, а не блоками: сторінки нерівні за вартістю (порожні vs
        # щільні), тож чергування вирівнює воркери самé по собі
        pages_all = pages_all[shard_k::shard_n]
    return pages_all


def missing_pages(pages_all: list[Path], out_dir: Path,
                  side_dirs: tuple[Path, ...] = ()) -> list[str]:
    """Кадри без тексту НА ДИСКУ — головний приймач повноти прогону.

    🔴 Знаменник беремо з диска (кадр ↔ `<stem>.txt`), а не з лічильників і не з
    коду повернення: сторінка може загубитись без жодного винятку. Замір, що це
    купив (ДАХмО 241-1-886, 2026-08-11): процес помер НАТИВНО на 15-й із 18
    сторінок — лог обірвався без traceback, `rc=1` без діагностики, у меті
    `failed: []`, і прогін виглядав завершеним. Пор. `htr-cloud-shard-ceiling…`,
    де CUDA OOM з'їв 16 сторінок при `rc=0` і порожньому `failed_shards`.

    Побічні теки голосів перевіряються теж: ансамбль пише їх у тому самому
    проході, тож `<out>/0007.txt` без `<out>-diak_v4/0007.txt` = недороблена
    сторінка, а не «модель промовчала».
    """
    gone: list[str] = []
    for p in pages_all:
        if not (out_dir / f"{p.stem}.txt").exists():
            gone.append(p.name)
            continue
        for d in side_dirs:
            if not (d / f"{p.stem}.txt").exists():
                gone.append(p.name)
                break
    return gone


def supervise(args: argparse.Namespace, case_dir: Path, out_dir: Path) -> int:
    """Перезапускати воркер, поки на диску лишаються нерозпізнані кадри.

    Питання не в тому, чи впаде процес, а в тому, чи справа дочитається. Python-
    рівень уже захищений (`except Exception` на сторінку не валить справу), але
    сегментер вміє вбивати процес нативно — без винятку, без traceback, з `rc=1`
    і без жодного рядка в лозі. Тоді сторінки просто немає, і дізнатись про це
    можна лише звіркою з диском.

    Алгоритм: спроба → звірка → якщо прогресу НЕ було (та сама кількість
    пропусків) і воркер упав, перший пропущений кадр іде в карантин із причиною,
    щоб наступна спроба дійшла до решти. Якщо прогрес був — просто повторюємо.
    """
    shard_k, shard_n = parse_shard(args.shard)
    try:
        pages_all = select_pages(case_dir, args.pages, args.limit, shard_k, shard_n)
    except OSError as exc:
        print(f"[htr-run] наглядач: не читається тека справи ({exc})", flush=True)
        return 1
    # побічні теки наглядач не звіряє: їх пише той самий прохід, що й головну,
    # а перелік тегів залежить від розв'язання імен моделей — це робота воркера,
    # і дублювати її тут означало б два джерела правди про склад ансамблю
    # 🔴 викидати треба ПАРУ: при формі «--supervise 3» фільтр лише по префіксу
    # лишав дитині голе «3», і argparse падав на невідомому позиційному аргументі
    child_argv: list[str] = []
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a == "--supervise":
            skip_next = True
            continue
        if a.startswith("--supervise="):
            continue
        child_argv.append(a)
    env = {**os.environ, "NYSHPORKA_HTR_CHILD": "1"}
    rc = 0
    prev_missing: int | None = None
    for attempt in range(1, args.supervise + 2):
        import subprocess
        rc = subprocess.run([sys.executable, str(Path(__file__).resolve()), *child_argv],
                            env=env).returncode
        gone = [p for p in missing_pages(pages_all, out_dir)
                if p not in load_quarantine(out_dir)]
        if not gone:
            break
        stuck = prev_missing is not None and len(gone) >= prev_missing
        prev_missing = len(gone)
        if attempt > args.supervise:
            break
        print(f"[htr-run] 🔁 наглядач: спроба {attempt} дала rc={rc}, "
              f"без тексту {len(gone)} з {len(pages_all)} "
              f"({', '.join(gone[:5])}{'…' if len(gone) > 5 else ''})", flush=True)
        if rc != 0 and stuck:
            # rc=3 — воркер вижив і сам доповів про неповноту (сторінка падає з
            # винятком); будь-який інший ненульовий rc при обірваному лозі —
            # процес помер. Причину пишемо різну, бо лікуються вони по-різному
            why = ("падає з винятком двічі" if rc == 3
                   else f"двічі поклала процес (rc={rc})")
            add_quarantine(out_dir, gone[0], f"{why} — наглядач htr_case_run")
            print(f"[htr-run] ☠ {gone[0]}: {why} → карантин, іду далі без неї",
                  flush=True)
    quar = load_quarantine(out_dir)
    if quar:
        # карантин ≠ «усе гаразд»: сторінки НЕ прочитані, і це має бути видно в
        # кінці, а не тільки у файлі, який ніхто не відкриває
        print(f"[htr-run] ☠ у карантині {len(quar)} стор. — НЕ прочитані: "
              f"{', '.join(sorted(quar))}", flush=True)
    # 🔴 Фінальний `done` для консолі мусить іти ВІД НАГЛЯДАЧА і рахуватись із
    # диска. Інакше в UI черги лишається подія останньої спроби, де всі сторінки
    # пішли в resume-скіп: `pages: 0` при повністю прочитаній справі (HtrManager
    # тримає один результат на воркер і перезаписує його останнім).
    emit(args.progress_json, "done",
         pages=len(pages_all) - len(gone), skipped=0, failed=len(gone),
         quarantined=len(quar), supervised=True)
    if gone:
        print(f"[htr-run] ⚠ НЕПОВНО після {args.supervise + 1} спроб: без тексту "
              f"{len(gone)} з {len(pages_all)} — {', '.join(gone)}", flush=True)
        return 3
    # rc воркера тут уже не інформативний: справа прочитана повністю (звірено з
    # диском), а ненульовий код міг лишитись від спроби, яку наглядач і полагодив
    return 0


def guard_ok(out_dir: Path, engine: str, model: str, force: bool) -> bool:
    """Не дати другому рушієві затерти тексти першого в одній теці прогону.

    Обидва рушії пишуть `<stem>.txt`, тож Писар по теці Скриби перезаписав би
    частину сторінок кириличним декодом, лишивши решту латинським — і жоден
    пошук уже не сказав би, що чим прочитане. Ловимо це ДО завантаження моделей.

    Рушій попереднього прогону беремо з `engine`, а якщо поля немає (усі мети до
    2026-07-30 і прогони старого `pysar_lines_infer.py`) — вгадуємо з розширення
    імені моделі в меті. Немає й того — вважаємо сумісним: тека або порожня, або
    настільки давня, що судити нема з чого.

    Зміна МОДЕЛІ в межах рушія (skryba v4 → v6) не блокується: змішаний корпус
    двох версій одного письма лишається шукабельним, а перечитувати справу
    заново щоразу занадто дорого. Але це видно в логу й в історії `models`.
    """
    prev_model = prev_engine = None
    for p in [out_dir / "_htr_meta.json", *out_dir.glob("_htr_meta.part*.json")]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not (d.get("pages") or {}):
            continue
        prev_model = d.get("model") or prev_model
        prev_engine = d.get("engine") or prev_engine
    if prev_engine is None and prev_model:
        prev_engine = _ENGINE_BY_SUFFIX.get(Path(prev_model).suffix.lower())
    if prev_engine is None or prev_engine == engine:
        if prev_model and Path(prev_model).name != Path(model).name:
            print(f"[htr-run] ⚠ у теці вже є сторінки від «{prev_model}», "
                  f"доганяю «{Path(model).name}» — корпус буде змішаний "
                  f"(той самий рушій {engine}, пошук не ламається)", flush=True)
        return True
    if force:
        print(f"[htr-run] ⚠ --force: затираю прогін рушія {prev_engine} "
              f"(«{prev_model}») рушієм {engine}", flush=True)
        return True
    print(f"[htr-run] ✖ у теці вже лежить прогін ІНШОГО рушія: {prev_engine} "
          f"(«{prev_model}»), а зараз {engine} («{Path(model).name}»).\n"
          f"          Тексти б змішались. Дай окрему теку "
          f"(напр. `<ім'я>-{engine}`) — обидва прогони однієї справи це нормально, "
          f"пошук бачить їх разом. `--force` щоб таки затерти.", flush=True)
    return False


def parse_pages(spec: str | None, n: int) -> set[int] | None:
    """'1-50,60' → множина 1-based індексів; None = усі."""
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(max(1, int(a)), min(n, int(b)) + 1))
        else:
            i = int(part)
            if 1 <= i <= n:
                out.add(i)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", required=True,
                    help="модель розпізнавання: .mlmodel (kraken/Скриба) "
                         "або .pt (PARSeq/Писар) — рушій визначається розширенням")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--limit", type=int, default=0, help="перші N сторінок")
    ap.add_argument("--pages", default="", help="діапазони 1-based: '1-50,60'")
    # None = «не задано» → розв'язується за рушієм (kraken і parseq мають РІЗНІ
    # шкали conf, спільний дефолт був би тихо неправильним для одного з них)
    ap.add_argument("--min-conf", type=float, default=None)
    ap.add_argument("--min-chars", type=int, default=DEF_MIN_CHARS)
    ap.add_argument("--sure-conf", type=float, default=None,
                    help="нижче цього conf результат звіряється з +180° (гард); "
                         "0 = вимкнути. Для parseq вимкнено за замовчуванням — "
                         "його conf не корелює з правильністю")
    ap.add_argument("--batch", type=int, default=32,
                    help="розмір батча рядків (лише parseq)")
    ap.add_argument("--script", default="auto",
                    choices=("auto", "latin", "cyrillic", "mixed"),
                    help="письмо справи — лягає в мету прогону; auto = з імені моделі")
    ap.add_argument("--force", action="store_true",
                    help="дозволити прогін у теку, де вже є прогін ІНШИМ рушієм "
                         "(тексти змішаються — майже завжди потрібна окрема тека)")
    ap.add_argument("--guard-warmup", type=int, default=DEF_GUARD_WARMUP,
                    help="скільки перших очних ставок 180°-гарда робити завжди "
                         "(розвідка); 0 фліпів після — гард лише для аномалій")
    ap.add_argument("--orient-model", default="",
                    help="TorchScript CNN орієнтації (htr_orient_train.py); "
                         "порожньо/нема файлу → профіль-детектор")
    ap.add_argument("--enhance", default="auto", choices=list(ENHANCE_MODES),
                    help=f"підняти контраст вицвілого чорнила перед сегментацією. "
                         f"auto (дефолт) — посторінково, лише де контраст "
                         f"< {AUTO_CONTRAST_THRESHOLD:.0f}; none — ніколи; "
                         f"clahe / clahew (вибілений фон) / clahesmooth "
                         f"(+ згладжування зерна) — примусово на всіх сторінках")
    ap.add_argument("--force-orient", type=int, default=-1,
                    choices=(-1, 0, 90, 180, 270),
                    help="ПРИМУСОВИЙ кут повороту для всіх сторінок (CCW), "
                         "детектори вимикаються. -1 = автовизначення. Потрібно "
                         "коли око вже бачить орієнтацію справи, а детектор "
                         "хибить: на ф.196-1-5953 CNN перевернув 8 нормальних "
                         "сторінок на 180° і декод став сміттям")
    ap.add_argument("--models", default="",
                    help="ДОДАТКОВІ моделі через кому (шлях або ім'я з "
                         "data/spotter/models) — ансамбль. Декодуються з ОДНОГО "
                         "проходу сегментації, кожна у свою теку "
                         "<out>-<тег>; пошук зводить теки разом. Сегментація "
                         "коштує ~80%% сторінки, тому друга модель додає ~20%%, "
                         "а не 100%%, як окремий прогін")
    ap.add_argument("--rescue", default="",
                    help="🛟 РЯТУВАЛЬНИЙ ПРОХІД: шлях до .mlmodel другого рушія "
                         "(Дяк). Відібрані рядки (сіра смуга АБО якір по "
                         "імені/по батькові роду — див. `rescue_pick`) "
                         "перечитуються ним у теку <out>-rescue. Кропи беруться "
                         "З ЦЬОГО Ж прогону, тобто повторної сегментації НЕМА: "
                         "на суді це 2-3%% рядків, менше хвилини на справу проти "
                         "×5-6 часу в --beam. Порожньо = вимкнено.")
    ap.add_argument("--rescue-spec", default="",
                    help="🎯 ЩО САМЕ рятувати: JSON із `full` (нормалізовані "
                         "форми прізвища), `confusers` (слова, що на нього "
                         "схожі, але ним не є) і `anchors` (імена й по батькові "
                         "під роки справи). ОБОВ'ЯЗКОВИЙ для --rescue: без "
                         "нього прохід рятував би рядки за чужим прізвищем, а це "
                         "гірше за відсутність рятунку — витрачений час і хибна "
                         "впевненість. Збирає файл викликач, у якого є канон.")
    ap.add_argument("--rescue-years", default="",
                    help="роки справи (1846 або 1865-1875) — довідково в меті. "
                         "Самі якорі під ці роки збирає викликач і кладе у "
                         "--rescue-spec: ім'я корисне, поки людина жива, "
                         "по батькові — поки живі її діти.")
    ap.add_argument("--case-key", default="",
                    help="шифра справи (`DAHMO/315/8433`) у мету прогону. "
                         "🔴 Рахує її МАШИНА, де тека справи ще під рукою: у "
                         "хмарі `case_dir` — це шлях орендованого боксу, і "
                         "реєстр потім не може прив'язати прогін до справи.")
    ap.add_argument("--rescue-eye", type=float, default=78.0,
                    help="поріг, вище якого хіт і так дивляться оком")
    ap.add_argument("--rescue-grey", type=float, default=60.0,
                    help="низ сірої смуги: нижче — шум")
    ap.add_argument("--beam", type=int, default=0,
                    help="beam search для parseq: N гіпотез на рядок у теку "
                         "<out>-beamN (основний текст лишається greedy). 0/1 = "
                         "вимкнено. Дістає прочитання, яке модель бачила, але не "
                         "поставила першим — на 904-24-24 так знайшовся єдиний "
                         "запис роду, що не брався ЖОДНОЮ з чотирьох моделей")
    ap.add_argument("--voice-batch", type=int, default=1,
                    help="розмір батча для kraken-ГОЛОСУ (--models з .mlmodel). "
                         "1 (дефолт) = текст ТОТОЖНИЙ окремому прогону тієї "
                         "моделі (CER 0.0000 на 233 рядках проти rpred); >1 — "
                         "вдвічі швидше, але CTC при спільній ширині батча дає "
                         "інший текст (дослівно 193/233, CER 0.0095)")
    ap.add_argument("--seg-cache", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="💾 кеш сегментації у data/derived/htr_seg (дефолт ON). "
                         "Сегментація — 60%% сторінки і від моделі НЕ залежить, "
                         "тож наступний прогін тієї ж справи іншою моделлю "
                         "коштує лише декод: 0.23 с замість 7.3 на кадр. "
                         "Кропи з кешу побітово ті самі; ключ несе enhance, "
                         "seg-height, стелю, sato й версію kraken")
    ap.add_argument("--seg-cache-dir", default="",
                    help="де тримати кеш сегментації (дефолт — "
                         "data/derived/htr_seg/<справа>)")
    ap.add_argument("--orient-check", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="ДОПУСКАТИ перевернуті сторінки у справі. За "
                         "замовчуванням ВИМКНЕНО: сторінки вважаються рівними, "
                         "працює один прохід на аркуш і весь ресурс іде на "
                         "розпізнавання. Вмикати лише коли справа справді має "
                         "перевернуті кадри — інакше детектори лише марнують "
                         "час і псують аркуші (ДАВО 904-24-24: 53 спрацювання "
                         "CNN на 476 сторінок, УСІ 53 хибні, 11%% часу в нікуди "
                         "і 2 нормальні сторінки перевернуто)")
    ap.add_argument("--sato-sigmas", default="1,3",
                    help="масштаби ridge-фільтра сегментації (43%% часу прогону); "
                         "'1,3' — дефолт, якість не просідає; порожньо — рідні "
                         "kraken'івські (1,3,5,7,9)")
    ap.add_argument("--keep-cache", action="store_true",
                    help="не звільняти кеш CUDA після кожної сегментації "
                         "(швидше, але піки VRAM шардів збігаються)")
    # 🔴 Обидва прискорення — ДЕФОЛТ ON, і саме тут, а не в консолі. До
    # 2026-07-30 вони були `store_true` (тобто off), а `True` їм ставив лише
    # `htr_manager._build_cmd` — і ручний запуск скрипта мовчки їхав старим
    # CPU-шляхом: 30-43 с/стор проти ~15 і `nvidia-smi` util 0% при повній VRAM.
    # Виглядало як зламана карта. Вихід обох перевірено на рівність оригіналу
    # (gpu_sato_verify / fast_geom_verify), тож бути «за згодою» їм нема підстав.
    ap.add_argument("--fast-geom", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="_calc_roi через STRtree + векторизований shapely "
                         "(вихід побітово той самий — див. fast_geom_verify.py). "
                         "Дефолт ON, вимикач --no-fast-geom")
    ap.add_argument("--gpu-sato", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="рахувати sato на карті (43%% часу сторінки; вихід "
                         "еквівалентний CPU-версії — див. gpu_sato_verify.py). "
                         "Дефолт ON на cuda, вимикач --no-gpu-sato")
    # 🔴 Стеля рядків у сегментації. kraken ріже при >400 кінців скелета, тобто
    # ~200 рядків на сторінку, і робить це МОВЧКИ: помилки немає, декод виглядає
    # повним, у меті лишається рівне `lines: 200`. Викидає найдрібніші
    # компоненти — номери актів, дати, короткі рядки на кінцях граф. Тому
    # ретрай дефолтом ON: на нормальній справі він не вмикається жодного разу
    # (ф.792 — 36-59 рядків/стор, костел ф.685 — 112-156), а на щільному
    # формулярі рятує сторінку ціною одного зайвого проходу. Замір на ДАЖО
    # 178-51-418: 141 з 244 сторінок у стелі, підняття дає +20 рядків за +1.6 с.
    ap.add_argument("--max-endpoints", type=int, default=400,
                    help="стеля кінців скелета в сегментації (400 = рідні "
                         "kraken ≈ 200 рядків на сторінку)")
    ap.add_argument("--ceiling-retry", type=int, default=1600,
                    help="якщо стеля різала — перепустити САМЕ ЦЮ сторінку з "
                         "такою стелею (0 = не перепускати)")
    ap.add_argument("--seg-height", type=int, default=0,
                    help="висота ресайзу сторінки для сегментера (0 = рідна "
                         "1800). 1440 ≈ −4%% слів за 1.35x, 1200 ≈ −10%% "
                         "fuzzy-recall довгих слів за 1.7x — вмикати свідомо")
    ap.add_argument("--shard", default="",
                    help="'k/n' — цей воркер бере кожну n-ту сторінку зі "
                         "зсувом k (round-robin). Мета пишеться у "
                         "_htr_meta.part<k>.json і зводиться у спільну")
    ap.add_argument("--gpu-lock", default="",
                    help="файл міжпроцесного лока GPU-фази сегментації; "
                         "ОБОВ'ЯЗКОВИЙ при --shard на одній карті")
    ap.add_argument("--supervise", type=int, default=2,
                    help="скільки ДОДАТКОВИХ спроб робити, якщо після прогону на "
                         "диску лишились кадри без тексту (дефолт 2, 0 — вимкнути). "
                         "Лікує не виняток, а НАТИВНУ смерть процесу: сегментер "
                         "здатен убити інтерпретатор без traceback, і тоді "
                         "сторінка просто зникає при rc=1 і порожньому failed. "
                         "Кадр, що двічі поклав процес, іде в карантин, щоб "
                         "справа дочиталась без нього")
    ap.add_argument("--progress-json", action="store_true")
    args = ap.parse_args()

    # Дані, яких раннер не має знати сам: чиє прізвище рятуємо, яка шифра справи,
    # що робити після прогону. Усе приходить ззовні, тож модуль лишається
    # придатним для будь-якого дослідження, а не лише для того, у якому він виріс.
    global _RESCUE_SPEC_PATH
    if args.rescue_spec:
        _RESCUE_SPEC_PATH = Path(args.rescue_spec)
    if args.rescue and not args.rescue_spec:
        # 🔴 Падати ЗАРАЗ, а не за годину посеред прогону: без цілей рятунок
        # мовчки нічого не відбере, і виглядатиме це як «нема чого рятувати».
        ap.error("--rescue без --rescue-spec: рятувальний прохід не знає, "
                 "які рядки відбирати")

    case_dir = Path(args.case_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prog = args.progress_json

    # наглядач сам нічого не вантажить (ні моделей, ні GPU) — лише перезапускає
    # воркер, поки на диску є кадри без тексту. `NYSHPORKA_HTR_CHILD` розриває
    # рекурсію: воркер бачить прапорець, але вже не делегує
    if args.supervise > 0 and not os.environ.get("NYSHPORKA_HTR_CHILD"):
        return supervise(args, case_dir, out_dir)

    engine = detect_engine(args.model)
    script = args.script if args.script != "auto" else model_script(args.model, engine)
    if args.min_conf is None:
        args.min_conf = DEF_MIN_CONF_PARSEQ if engine == "parseq" else DEF_MIN_CONF
    if args.sure_conf is None:
        args.sure_conf = DEF_SURE_CONF_PARSEQ if engine == "parseq" else DEF_SURE_CONF
    if not guard_ok(out_dir, engine, args.model, args.force):
        return 2

    import torch
    device = args.device
    if device.startswith("cuda") and not torch.cuda.is_available():
        print("[htr-run] CUDA недоступна — падаю на cpu (буде ~2 хв/стор)", flush=True)
        device = "cpu"

    shard_k, shard_n = parse_shard(args.shard)
    pages_all = select_pages(case_dir, args.pages, args.limit, shard_k, shard_n)
    if not pages_all:
        print("[htr-run] у теці немає сторінок jpg/jpeg/png", flush=True)
        emit(prog, "done", pages=0, skipped=0, failed=0, error="немає сторінок")
        return 1

    meta_path = out_dir / (f"_htr_meta.part{shard_k + 1}.json" if shard_n > 1
                           else "_htr_meta.json")
    meta: dict = {"version": 1, "case_dir": str(case_dir).replace("\\", "/"),
                  # 🔴 Шифра справи, а не лише шлях. `case_dir` у хмарі вказує на
                  # теку ОРЕНДОВАНОГО боксу (`/tmp/htrcase/pages_dl`), якої на
                  # домашній машині не існує — і 66 зі 189 прогонів через це
                  # не зводились до жодної справи, тобто третина декоду проєкту
                  # була «нічия». Записуємо ключ тут, поки справа ще відома.
                  "case_key": resolve_case_key(case_dir, out_dir.name,
                                               args.case_key),
                  "model": Path(args.model).name, "device": device,
                  # рушій і письмо — щоб пошук/консоль могли сказати, ЧИМ
                  # прочитана сторінка, коли на одну справу є кілька прогонів
                  "engine": engine, "script": script,
                  # прогін із піднятим контрастом — окремий артефакт; без цього
                  # поля неможливо сказати, чому в двох теках різний декод
                  "enhance": args.enhance,
                  "started": datetime.now().isoformat(timespec="seconds"),
                  "done": False, "failed": [], "pages": {}}
    old_meta: dict = {}
    if meta_path.exists():
        try:
            old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["pages"] = old_meta.get("pages") or {}
            meta["failed"] = old_meta.get("failed") or []
            meta["started"] = old_meta.get("started") or meta["started"]
        except (json.JSONDecodeError, OSError):
            old_meta = {}
    # resume дивиться ширше за власний парт: сторінку міг зробити прогін до
    # шардингу або воркер з іншою розкладкою k/n
    already = known_pages(out_dir) if shard_n > 1 else set(meta["pages"])
    meta_base = {k: v for k, v in meta.items()
                 if k in ("version", "case_dir", "case_key", "model", "device",
                          "engine", "script", "enhance")}
    saves = 0
    # стан гарда переживає рестарт: без цього кожен запуск (×N шардів) починав
    # 15 очних ставок наново — на 5 рестартах це дало 60% гардованих сторінок
    # замість 6%. Ініціалізуємо ДО save_meta, який його серіалізує.
    guard_state = {"checks": 0, "flips": 0, "conf_sum": 0.0, "conf_n": 0}
    # СПІЛЬНИЙ на всі шарди (одна справа = один писар): без нього кожен шард вів
    # власну розвідку, тобто 15×N очних ставок замість 15, а знайдений одним
    # шардом фліп не вмикав посилений режим в інших
    guard_shared = (out_dir / "_guard.json") if shard_n > 1 else None
    guard_pushed: dict = {}
    if guard_shared is not None:
        sync_guard(guard_shared, guard_state, guard_pushed)
    else:
        # саме з old_meta, а не з meta: у `meta` вище переносяться ЛИШЕ pages/
        # failed/started, тож `meta["guard"]` на старті порожній завжди (на цьому
        # персист і не спрацював з першого разу)
        og = old_meta.get("guard")
        if isinstance(og, dict):
            for k in guard_state:
                if isinstance(og.get(k), (int, float)):
                    guard_state[k] = og[k]
    old_guard = guard_state["checks"] > 0

    def save_meta(force: bool = False) -> None:
        nonlocal saves
        meta["updated"] = datetime.now().isoformat(timespec="seconds")
        meta["guard"] = dict(guard_state)   # щоб resume не починав розвідку заново
        atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
        saves += 1
        # спільну мету (її читає в'ювер) зводимо рідше — вона важча за парт
        if shard_n > 1 and (force or saves % 5 == 0):
            merge_meta(out_dir, meta_base)

    n = len(pages_all)
    shard_note = f" · шард {shard_k + 1}/{shard_n}" if shard_n > 1 else ""
    script_note = {"latin": "латинка", "cyrillic": "кирилиця",
                   "mixed": "мішане", "unknown": "письмо ?"}.get(script, script)
    print(f"[htr-run] {n} стор. · device={device} · рушій={engine} "
          f"({script_note}) · модель={Path(args.model).name}{shard_note}", flush=True)
    if engine == "parseq" and args.sure_conf <= 0 and args.orient_check \
            and args.force_orient < 0:
        # друкуємо ЛИШЕ коли детектори справді працюють — інакше рядок описував
        # би неіснуючу поведінку, а мовчазна неточність у лозі коштує дорожче
        # за відсутній рядок: саме за ним годину шукали, чому сторінки крутить
        print("[htr-run] 180°-гард за conf вимкнено (PARSeq: conf не корелює з "
              "правильністю) — орієнтацію вирішують детектор профілю і CNN",
              flush=True)
    t0 = time.time()
    sigmas = install_sato_sigmas(args.sato_sigmas)
    if sigmas:
        print(f"[htr-run] sato sigmas={list(sigmas)} (рідні kraken — 1,3,5,7,9)",
              flush=True)
    if args.gpu_sato and device.startswith("cuda"):
        # ставиться ПОВЕРХ звуження sigmas — той самий патч skimage.filters.sato,
        # але згортки йдуть на карті. Вихід звірено з CPU-версією до float32-епсилону
        # (scripts/gpu_sato_verify.py), тож полігони рядків не змінюються.
        sys.path.insert(0, str(_PATCHES_DIR))
        from gpu_sato import install_gpu_sato
        used = install_gpu_sato(sigmas or (1, 3, 5, 7, 9), device=device)
        print(f"[htr-run] sato НА GPU, sigmas={list(used)}", flush=True)
    elif not args.gpu_sato:
        # вимкнення прискорення має бути ГУЧНИМ: різниця ×2 у часі сторінки, і
        # найдешевший спосіб її діагностувати — побачити причину в шапці логу
        print("[htr-run] ⚠ sato НА CPU (--no-gpu-sato) — сторінка коштує вдвічі",
              flush=True)
    sys.path.insert(0, str(_PATCHES_DIR))
    import seg_ceiling
    seg_ceiling.install(args.max_endpoints)
    if args.ceiling_retry and args.ceiling_retry > args.max_endpoints:
        print(f"[seg-ceiling] сторінку, що впреться у стелю, перепускаю з "
              f"{args.ceiling_retry // 2} рядками", flush=True)
    if args.fast_geom:
        sys.path.insert(0, str(_PATCHES_DIR))
        from fast_geom import install as install_fast_geom
        install_fast_geom(verbose=True)
    else:
        print("[htr-run] ⚠ геометрія kraken БЕЗ прискорення (--no-fast-geom)",
              flush=True)
    from kraken.kraken import SEGMENTATION_DEFAULT_MODEL
    rec_model = load_recognizer(args.model, engine, device)
    globals()["VOICE_BATCH"] = max(1, int(args.voice_batch))
    # ── ансамбль і beam: додаткові виходи з ОДНІЄЇ сегментації ───────────────
    # 🤝 Голос може бути ІНШОГО РУШІЯ, ніж основна модель: `.mlmodel` (Дяк,
    # Скриба) декодується з тих самих кропів через `kraken_decode_crops`. Це не
    # дрібниця розширення — саме різнорушійний голос і купує найбільше:
    # заміряно, що Дяк на готових кропах коштує 1.4 с/стор проти 10.0 с
    # окремим прогоном, а знаходить те, чого PARSeq не бачить принципово
    # (PRODUCTION.json: 6 сканів із 62, яких не дав жоден Писар).
    side_dirs: dict[str, Path] = {}
    extra_recs: list = []
    if engine == "parseq" and (args.models.strip() or args.beam > 1):
        for spec in [s.strip() for s in args.models.split(",") if s.strip()]:
            mdir = Path(__file__).resolve().parents[1] / "data" / "spotter" / "models"
            p = Path(spec)
            if not p.is_file():
                # ім'я без розширення: пробуємо обидва рушії, .pt першим
                for cand in (mdir / spec, mdir / f"{spec}.pt", mdir / f"{spec}.mlmodel"):
                    if cand.is_file():
                        p = cand
                        break
            if not p.is_file():
                raise SystemExit(f"[htr-run] нема моделі: {spec}")
            vengine = detect_engine(str(p))
            tag = (p.stem.replace("pysar_cyr_", "").replace("diak_cyr_", "diak_")
                   .replace("skryba_f792_", "skryba_"))
            if vengine == "kraken":
                extra_recs.append((tag, "kraken", load_kraken_voice(str(p), device)))
            else:
                extra_recs.append((tag, "parseq", load_recognizer(str(p), "parseq", device)))
            side_dirs[tag] = out_dir.parent / f"{out_dir.name}-{tag}"
        if args.beam > 1:
            side_dirs[f"beam{args.beam}"] = out_dir.parent / f"{out_dir.name}-beam{args.beam}"
        for d in side_dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        rec_model = (rec_model, extra_recs, args.beam)
        voices = ", ".join(f"{t} [{e}]" for t, e, _ in extra_recs) or "—"
        print(f"[htr-run] додаткові виходи з тієї самої сегментації: {voices}"
              f"{f' + beam{args.beam}' if args.beam > 1 else ''} → "
              f"{', '.join(d.name for d in side_dirs.values())}", flush=True)
        if any(e == "kraken" for _, e, _ in extra_recs):
            print(f"[htr-run] 🤝 kraken-голос: pad={KRAKEN_VOICE_PAD}, батч="
                  f"{VOICE_BATCH}"
                  f"{' (тотожно окремому прогону)' if VOICE_BATCH <= 1 else ' (швидше, CER ~1% проти окремого прогону)'}",
                  flush=True)
    elif args.models.strip():
        # мовчазне ігнорування тут коштувало б цілого прогону: людина чекає на
        # другий голос, а на диску його немає
        print(f"[htr-run] ⚠ --models проігноровано: ансамбль реалізований у "
              f"PARSeq-гілці, а основна модель цього прогону — {engine}",
              flush=True)
    # ── сегментер: спільний для обох рушіїв, з кешем і ЛЕДАЧОЮ моделлю ───────
    seg_cache = None
    if args.seg_cache:
        # 🔴 Корінь кешу — від ВИХОДУ, не від `__file__`. Доки раннер лежав у
        # `scripts/` дослідницького репо, `parents[1]` випадково збігався з
        # коренем даних; після переїзду в пакет та сама формула поклала б кеш
        # у дерево КОДУ (`…/site-packages/nyshporka/data/derived/htr_seg`) —
        # без жодної помилки, просто повз workspace. Помітити це можна лише за
        # тим, що влучань завжди 0%, тобто по нічному прогону, який коштував
        # удвічі більше, ніж мав.
        # Явний `--seg-cache-dir` лишається головним каналом: його ставить
        # викликач, який знає workspace.
        seg_cache = (Path(args.seg_cache_dir) if args.seg_cache_dir.strip()
                     else seg_cache_dir_for(case_dir, workspace_root(out_dir, case_dir)))
    segmenter = Segmenter(
        SEGMENTATION_DEFAULT_MODEL, device, seg_height=args.seg_height,
        cache_dir=seg_cache,
        key={"sato": args.sato_sigmas, "kraken": KRAKEN_PIN_VERSION,
             "max_endpoints": args.max_endpoints})
    if seg_cache is not None:
        have = len(list(seg_cache.glob("*.seg.json.gz"))) if seg_cache.is_dir() else 0
        print(f"[htr-run] 💾 кеш сегментації: {seg_cache} ({have} кадрів готово)",
              flush=True)
    if args.gpu_lock and device.startswith("cuda"):
        install_gpu_lock(Path(args.gpu_lock), device, keep_cache=args.keep_cache)
        print(f"[htr-run] GPU-фаза під локом {Path(args.gpu_lock).name}", flush=True)
    elif shard_n > 1 and device.startswith("cuda"):
        print("[htr-run] ⚠ --shard без --gpu-lock: одночасні forward'и можуть "
              "вичерпати VRAM", flush=True)
    # Орієнтація перевіряється лише на явну вимогу. Дефолт «сторінки рівні»
    # обраний заміром, а не з обережності: на ДАВО 904-24-24 детектори дали 53
    # спрацювання з 476 сторінок і ЖОДНОГО правильного — 51 спростував
    # chars-гард другим проходом, а 2 пройшли й перевернули нормальні аркуші.
    # Тобто ціна ~11% часу прогону і два зіпсовані аркуші за нульової користі.
    if not args.orient_check and args.force_orient < 0:
        args.force_orient = 0
        print("[htr-run] орієнтація НЕ перевіряється: сторінки вважаються "
              "рівними, один прохід на аркуш (галочка «можливі перевернуті "
              "сторінки» / --orient-check вмикає детектори)", flush=True)
    orient_net = None
    if args.orient_check and args.orient_model and Path(args.orient_model).is_file():
        orient_net = load_orient_net(args.orient_model, device)
        if orient_net is not None:
            print("[htr-run] орієнтація: CNN-класифікатор", flush=True)
    print(f"[htr-run] моделі завантажено за {time.time() - t0:.0f} с", flush=True)

    done = skipped = failed = enhanced_n = ceiling_n = 0
    # скільки рядків голосу впало через маску основного тексту (див. side у
    # `ocr_page_parseq`) — друкується в підсумку, бо тиха втрата гірша за втрату
    side_lost: dict[str, int] = {}
    # 🛟 тека для кропів рятувального проходу (див. `rescue_pick`)
    rescue_dir = None
    rescue_n = 0
    rescue_keys: list[str] = []
    if args.rescue.strip() and engine == "parseq":
        rescue_dir = out_dir / "_rescue_crops"
        rescue_dir.mkdir(parents=True, exist_ok=True)
        rescue_keys = rescue_anchors(args.rescue_years)
        spec = rescue_spec()
        # 🔴 Порожні якорі проговорюються ВГОЛОС. Це законний стан (родоводу ще
        # може не бути), але вузький відбір без другого каналу зовні не
        # відрізнити від «нема кого рятувати», а різниця між ними — знайдений
        # рядок і незнайдений.
        anchor_note = (f" (роки справи {args.rescue_years})" if args.rescue_years
                       else "")
        if not rescue_keys:
            anchor_note = " ⚠ канал якорів МОВЧИТЬ — у специфікації їх немає"
        print(f"[htr-run] 🛟 рятувальний прохід: {Path(args.rescue).name}, "
              f"сіра смуга {args.rescue_grey:.0f}-{args.rescue_eye:.0f}, "
              f"форм прізвища {len(spec['full'])}, конфузерів "
              f"{len(spec['confusers'])}, якорів {len(rescue_keys)}"
              + anchor_note, flush=True)
    elif args.rescue.strip():
        # ⚠ Мовчки не вимикаємо: рятунок тримається на кропах PARSeq-гілки, і
        # користувач має знати, що прапорець не подіяв, а не гадати про нуль.
        print(f"[htr-run] ⚠ --rescue проігноровано: працює лише з parseq "
              f"(рушій цього прогону — {engine})", flush=True)
    if old_guard:
        print(f"[htr-run] гард відновлено: {guard_state['checks']} перевірок, "
              f"{guard_state['flips']} фліпів (розвідку не повторюю)", flush=True)
    quarantined = load_quarantine(out_dir)
    if quarantined:
        print(f"[htr-run] карантин: {len(quarantined)} стор. пропускаю "
              f"({', '.join(sorted(quarantined)[:5])}{'…' if len(quarantined) > 5 else ''})",
              flush=True)
    for i, src in enumerate(pages_all, 1):
        stem = src.stem
        txt_path = out_dir / f"{stem}.txt"
        if txt_path.exists() and src.name in already:
            skipped += 1
            emit(prog, "htr", i=i, n=n, page=src.name, skipped=True)
            continue
        if src.name in quarantined:
            # не «скіп», а саме збій: сторінка лишилась нерозпізнаною, і це має
            # бути видно в лічильнику, а не розчинитись серед resume-скіпів
            failed += 1
            if src.name not in meta["failed"]:
                meta["failed"].append(src.name)
                save_meta()
            reason = (quarantined[src.name] or {}).get("reason") or "вішала прогін"
            print(f"[htr-run] ⏭ {src.name}: карантин ({reason})", flush=True)
            emit(prog, "htr", i=i, n=n, page=src.name, error=f"карантин: {reason}")
            continue
        # консоль має знати, на ЧОМУ саме шард завис: вотчдог бачить лише тишу,
        # а карантинувати треба конкретний файл (див. HtrManager._note_stall)
        emit(prog, "page_start", i=i, n=n, page=src.name)
        t = time.time()
        # 🔴 скидаємо ПЕРЕД сторінкою: інакше сторінка, де сегментація не дала
        # жодного кропа, мовчки успадкувала б побічні виходи попередньої
        if side_dirs:
            ocr_page_parseq.side = {}
            ocr_page_parseq.side_lost = {}
        # те саме для рамок, і БЕЗУМОВНО: сторінка без кропів успадкувала б рамки
        # попередньої, а вони збіглися б за довжиною з її рядками лише випадково —
        # тобто помилка була б рідкою й тихою, найгіршого сорту
        ocr_page_parseq.boxes = []
        try:
            seg_ceiling.reset()
            res = process_page(src, segmenter, rec_model, device,
                               args.min_conf, args.min_chars, args.sure_conf,
                               orient_net, guard_state, args.guard_warmup,
                               engine, args.batch, args.force_orient,
                               args.enhance)
            # сторінка вперлась у стелю — переганяємо ТІЛЬКИ її, з піднятою.
            # Беремо новий результат лише якщо рядків справді побільшало:
            # інакше зайвий прохід не має права зіпсувати вже здобуте.
            if (args.ceiling_retry and args.ceiling_retry > args.max_endpoints
                    and seg_ceiling.hit(len(res["lines"]))):
                seg_ceiling.set_ceiling(args.ceiling_retry)
                try:
                    res2 = process_page(src, segmenter, rec_model, device,
                                        args.min_conf, args.min_chars,
                                        args.sure_conf, orient_net, guard_state,
                                        args.guard_warmup, engine, args.batch,
                                        args.force_orient, args.enhance)
                except Exception as exc:
                    print(f"[seg-ceiling] ✗ {src.name}: перепуск не вдався "
                          f"({type(exc).__name__}) — лишаю перший результат",
                          flush=True)
                    res2 = None
                finally:
                    seg_ceiling.set_ceiling(args.max_endpoints)
                if res2 and len(res2["lines"]) > len(res["lines"]):
                    print(f"[seg-ceiling] ◆ {src.name}: {len(res['lines'])} → "
                          f"{len(res2['lines'])} рядків "
                          f"(стеля {args.ceiling_retry // 2})", flush=True)
                    res2["ceiling_lifted"] = args.ceiling_retry
                    res = res2
                    ceiling_n += 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # одна сторінка не валить справу
            failed += 1
            if src.name not in meta["failed"]:
                meta["failed"].append(src.name)
            save_meta()
            print(f"[htr-run] ✗ {src.name}: {type(exc).__name__}: {exc}", flush=True)
            emit(prog, "htr", i=i, n=n, page=src.name, error=str(exc))
            if device.startswith("cuda"):
                import torch
                torch.cuda.empty_cache()
            continue
        sec = round(time.time() - t, 1)
        if guard_shared is not None:
            # після кожної сторінки: віддати свою дельту і забрати агрегат по
            # справі — так квота розвідки одна на всіх, а чужий фліп видно одразу
            sync_guard(guard_shared, guard_state, guard_pushed)
        atomic_write(txt_path, "\n".join(res["lines"]) + ("\n" if res["lines"] else ""))
        # 🖼🛟🔒 РАМКИ РЯДКІВ — окремим файлом поруч із текстом. Три причини, і
        # кожної окремо досить:
        #  1. UI має показувати, ЗВІДКИ текст. Доти прогін клав лише `.txt`, і
        #     рамку доводилось добувати ПОШУКОМ КРОПА на скані — пунктиром, ~80%
        #     рядків (CLAUDE.md, кнопка 📄). Тепер координати точні.
        #  2. Другий рушій на відібраних рядках стає майже безкоштовним: без
        #     рамок перечитати «сіру смугу» можна лише через ПОВТОРНУ сегментацію
        #     (заміряно на ф.474-174: кандидати розсіяні по 62% сторінок, 56 хв
        #     проти <1 хв самого декоду). З рамками — `extract_polygons` і все.
        #  3. Доказ-файли цитат: вирізка для `data/source/citations/` стає точною
        #     операцією, а не пошуком на око.
        # 🔴 ОКРЕМИЙ файл, а НЕ `_htr_meta.json`: мета справи на 1377 сторінок уже
        # 308 КБ, шардована на три частини й перезаписується на КОЖНІЙ сторінці
        # трьома воркерами — 55 тис. рамок роздули б її вшестеро й платили б цим
        # на кожному кадрі. Тут ~1.2 КБ на сторінку, пишеться раз.
        # Схема: {"size": [w,h], "boxes": [[x0,y0,x1,y1]|null, …],
        #         "polys": [[[x,y], …]|null, …]}. `boxes` лишається як був —
        # його читають вирізальники черги на звірку, і зміна схеми там була б
        # мовчазною поломкою. `polys` — полігон рядка для підсвітки в UI,
        # `size` — система координат (повернуте зображення), без якої рамка не
        # масштабується ні до чого.
        # ⚠ Рамки дає та гілка, яка їх зібрала: PARSeq — у своєму фільтрі
        # (`_line_crops`), kraken — з самих записів `rpred` (`ocr_page`). Беруться
        # вони з РЕЗУЛЬТАТУ сторінки (`_geom_of` знімає їх одразу після читання),
        # а не з атрибута функції в кінці — інакше при кількох випробуваних
        # поворотах можна взяти рамки не того прочитання.
        _boxes = res.get("boxes")
        if _boxes and len(_boxes) == len(res["lines"]):
            _polys = res.get("polys") or []
            payload = {"size": res.get("size") or None, "boxes": _boxes}
            if len(_polys) == len(_boxes):
                payload["polys"] = _polys
            atomic_write(out_dir / f"{stem}.lines.json",
                         json.dumps(payload, ensure_ascii=False))
        # 🛟 Кропи відібраних рядків — на диск, а Дяк пройде ними ОДНИМ заходом у
        # кінці справи. Чому не тут-і-зараз: карта одна, 4 ГБ, а черга крутить
        # прогін трьома воркерами й сама тримає ~3.7 ГБ — друга модель у пам'яті
        # означала б той самий OOM, що ловився 08-08 (memory
        # `gpu-4gb-shared-with-queue`). Кропи вже дешифровані й вирівняні, тож
        # відкласти їх на диск нічого не коштує: 2-3% рядків справи, ~10-20 МБ.
        if rescue_dir is not None:
            _crops = getattr(ocr_page_parseq, "crops", None) or []
            picks = rescue_pick(res["lines"], args.rescue_eye, args.rescue_grey,
                                anchor_keys=rescue_keys)
            saved = 0
            for idx in picks:
                if idx >= len(_crops) or _crops[idx] is None:
                    continue
                pd = rescue_dir / stem
                pd.mkdir(parents=True, exist_ok=True)
                try:
                    _crops[idx].save(pd / f"line_{idx:04d}.png")
                    saved += 1
                except Exception:
                    pass
            if saved:
                rescue_n += saved
                atomic_write(rescue_dir / stem / "_n_lines.txt",
                             str(len(res["lines"])))
        # побічні виходи (ансамбль / beam) — тими самими кропами І вирівняні по
        # масці основного тексту (див. `ocr_page_parseq`), тому рядок N теки
        # голосу — це рядок N основної теки й рамка N з `.lines.json`
        for tag, d in side_dirs.items():
            body = getattr(ocr_page_parseq, "side", {}).get(tag) or []
            atomic_write(d / f"{stem}.txt", "\n".join(body) + ("\n" if body else ""))
        for tag, k in (getattr(ocr_page_parseq, "side_lost", {}) or {}).items():
            side_lost[tag] = side_lost.get(tag, 0) + k
        meta["pages"][src.name] = {
            "orient": res["orient"], "detector": res["detector"],
            "retried": res["retried"], "guarded": res.get("guarded", False),
            "lines": len(res["lines"]),
            "chars": res["chars"], "conf": res["conf"], "sec": sec,
            # лише коли контраст справді піднято: у нормальній справі поле не
            # з'являється взагалі й мети не роздуває
            **({"enhanced": res["enhanced"]} if res.get("enhanced") else {}),
            # сторінка була в стелі й пішла другим проходом — без цього поля
            # «чому вона 2× довша за сусідню» не пояснити нічим, крім здогадів
            **({"ceiling_lifted": res["ceiling_lifted"]}
               if res.get("ceiling_lifted") else {}),
            **({"contrast": res["contrast"]} if res.get("contrast") is not None else {}),
        }
        if res.get("enhanced"):
            enhanced_n += 1
        if src.name in meta["failed"]:
            meta["failed"].remove(src.name)
        done += 1
        save_meta()
        emit(prog, "htr", i=i, n=n, page=src.name, lines=len(res["lines"]),
             orient=res["orient"], conf=res["conf"], sec=sec,
             guarded=res.get("guarded", False),
             # стан 180°-гарда в UI: без нього «чому сторінка 48 с, а сусідня 21»
             # і «чому темп упаде згодом» не пояснити нічим, крім читання меты
             guard={"checks": guard_state["checks"], "flips": guard_state["flips"],
                    "warmup": args.guard_warmup})

    meta["done"] = True
    save_meta(force=True)
    total_min = (time.time() - t0) / 60
    per = f" · {60 * total_min / done:.1f} с/стор" if done else ""
    # скільки сторінок пішло через підняття контрасту — ГОЛОСНО, бо це єдина
    # ознака, що прогін чіпав вхід сегментації. Мовчазний auto означав би, що
    # хибно підібраний поріг псує справу непомітно
    enh_note = ""
    if args.enhance == "auto" and done:
        enh_note = (f" · контраст піднято на {enhanced_n} з {done} "
                    f"(поріг {AUTO_CONTRAST_THRESHOLD:.0f})")
    elif args.enhance not in ("auto", "none"):
        enh_note = f" · контраст: {args.enhance} на всіх"
    # те саме міркування, що й для контрасту: мовчазна стеля означала б, що
    # справа тихо втратила частину рядків, і в меті це виглядало б нормою
    ceil_note = (f" · стеля піднята на {ceiling_n} з {done}"
                 if ceiling_n else "")
    print(f"[htr-run] ✓ готово: {done} розпізнано · {skipped} скіп · {failed} збоїв "
          f"· {total_min:.1f} хв{per}{enh_note}{ceil_note}", flush=True)
    # 💾 що дав кеш — числом, а не «десь швидше»: без цього рядка неможливо
    # відрізнити «кеш працює» від «кеш мовчки промахується на кожному кадрі»
    if segmenter.dir is not None:
        tot = segmenter.hits + segmenter.misses
        if tot:
            print(f"[htr-run] 💾 сегментація: {segmenter.hits} з кешу · "
                  f"{segmenter.misses} пораховано · {segmenter.written} записано "
                  f"({100 * segmenter.hits / tot:.0f}% влучань)", flush=True)
    # рядки голосів, які основна модель замовчала (див. маску в ocr_page_parseq)
    if side_lost:
        print("[htr-run] ⚠ поза маскою основного тексту: "
              + " · ".join(f"{t} {k} ряд." for t, k in sorted(side_lost.items())),
              flush=True)

    # ── 🛟 РЯТУВАЛЬНИЙ ПРОХІД ────────────────────────────────────────────────
    # Одним заходом, ПІСЛЯ прогону: одне завантаження моделі, нуль конкуренції
    # за 4-гігабайтну карту. Вихід — `<out>-rescue/<стор>.txt` тієї самої
    # довжини, що основний текст: перечитані рядки на своїх місцях, решта
    # порожні. Так пошук і UI зводять дві теки без зсуву — та сама конвенція,
    # що в побічних теках ансамблю й beam.
    if rescue_dir is not None and rescue_n:
        rout = out_dir.parent / f"{out_dir.name}-rescue"
        rout.mkdir(parents=True, exist_ok=True)
        t_r = time.time()
        try:
            # 🐞 ФІКС 2026-08-08: доти рятунок будував трансформи з `pad=0`, і
            # другий рушій читав ГІРШЕ, ніж уміє, — мовчки. Замір проти
            # еталонного `rpred` на 233 рядках ДАВО 904-24-24: pad=0 дає CER
            # 0.1307 і дослівний збіг 63/233, рідний kraken'івський pad=16 —
            # CER 0.0000 і 233/233. Тобто рятувальні рядки, які потім читає око,
            # були зіпсовані на порожньому місці. Тепер шлях спільний із
            # kraken-голосом ансамблю (`load_kraken_voice`), тож розійтись їм
            # більше нема де.
            voice = load_kraken_voice(args.rescue, device)
            n_read = n_pg = 0
            for pd in sorted(p for p in rescue_dir.iterdir() if p.is_dir()):
                nl_f = pd / "_n_lines.txt"
                if not nl_f.is_file():
                    continue
                total_lines = int(nl_f.read_text(encoding="utf-8").strip() or 0)
                body = [""] * total_lines
                files, idxs, crops_ = [], [], []
                for cf in sorted(pd.glob("line_*.png")):
                    idx = int(cf.stem.split("_")[1])
                    if idx >= total_lines:
                        continue
                    try:
                        with Image.open(cf) as cim:
                            crops_.append(cim.convert("RGB"))
                        idxs.append(idx)
                        files.append(cf)
                    except Exception:
                        continue
                # `idxs` і `crops_` наповнюються ПАРОЮ, тож розбіжність тут
                # означала б, що текст ляже на ЧУЖИЙ номер рядка — саме та
                # тиха підміна, від якої рятувальний прохід і рятує.
                for idx, txt in zip(idxs, kraken_decode_crops(voice, crops_,
                                                              VOICE_BATCH),
                                    strict=True):
                    body[idx] = txt.replace("\n", " ").strip()
                    if body[idx]:
                        n_read += 1
                atomic_write(rout / f"{pd.name}.txt", "\n".join(body) + "\n")
                n_pg += 1
            # мета побічної теки ОБОВ'ЯЗКОВА — без неї htr_store.list_cases()
            # прогону не бачить і пошук мовчки віддає нуль (та сама пастка, що
            # з ансамблем і beam)
            atomic_write(rout / "_htr_meta.json", json.dumps({
                "version": 1, "case_dir": str(case_dir), "model": Path(args.rescue).name,
                "engine": "kraken", "script": args.script, "done": True,
                "rescue_of": out_dir.name,
                "rescue": {"lines": rescue_n, "read": n_read, "pages": n_pg,
                           "eye": args.rescue_eye, "grey": args.rescue_grey},
                "pages": {}}, ensure_ascii=False))
            print(f"[htr-run] 🛟 рятунок: перечитано {n_read} рядків на {n_pg} стор. "
                  f"за {(time.time() - t_r)/60:.1f} хв → {rout.name}", flush=True)
            meta["rescue"] = {"lines": rescue_n, "read": n_read, "pages": n_pg,
                              "model": Path(args.rescue).name}
            save_meta()
        except Exception as exc:
            # Не валити прогін: основний текст уже на диску, а кропи лишаються —
            # прохід можна повторити окремо, не переганяючи справу.
            print(f"[htr-run] ⚠ рятувальний прохід не вдався "
                  f"({type(exc).__name__}: {exc}); кропи лишаю в "
                  f"{rescue_dir.name}", flush=True)

    # ── 🧾 ЧЕРГА НА ЗВІРКУ — НЕ ТУТ ──────────────────────────────────────────
    # Раніше прогін будував її сам, імпортом скрипта з теки поруч. Працювало це
    # лише тому, що той скрипт сам дописував корінь коду в `sys.path`, — і коли
    # він почав залежати від пакета, побудова черги мовчки припинилась: імпорт
    # ліниво падав у `except`, а в лозі стояло одне попередження серед сотень
    # рядків прогону.
    #
    # 🔴 Полагодити це гачком не можна, і це не смак. Черга знає, ЧИЄ прізвище
    # шукають, тобто спирається на родовід і на цілі пошуку — а вони живуть у
    # пакеті, якого в середовищі рушіїв немає за побудовою. Будь-який гачок,
    # завантажений ЗВІДСИ, вперся б у ту саму стіну.
    #
    # Тому крок віддано викликачеві: він працює у своєму інтерпретаторі, вже
    # після виходу процесу, і йому для цього потрібен лише `<out>` на диску —
    # ні карти, ні моделей. Раннер лишає все, що для цього треба: `<стор>.txt`,
    # `<стор>.lines.json` (рамки рядків) і теки голосів.
    # 🔴 Мета побічних тек ОБОВ'ЯЗКОВА: без `_htr_meta.json` htr_store.list_cases()
    # прогону не бачить, і пошук по ансамблю мовчки віддає нуль хітів, хоча
    # тексти на диску є. Та сама пастка, що коштувала 20 хв у pysar_lines_infer.
    # ключі мети — імена ФАЙЛІВ справи (з розширенням), як в основній теці:
    # в'ювер шукає сторінку саме за ним, а не за stem
    stem2name = {Path(k).stem: k for k in meta.get("pages", {})}
    for tag, d in side_dirs.items():
        pages_meta = {}
        for f in sorted(d.glob("*.txt")):
            body = f.read_text(encoding="utf-8").splitlines()
            pages_meta[stem2name.get(f.stem, f"{f.stem}.jpg")] = {
                "orient": 0, "detector": f"side:{tag}", "retried": False,
                "guarded": False, "lines": len(body),
                "chars": sum(len(x) for x in body), "conf": None, "sec": None}
        atomic_write(d / "_htr_meta.json", json.dumps({
            "version": 1, "case_dir": str(case_dir).replace("\\", "/"),
            "model": f"{Path(args.model).name}+{tag}", "device": device,
            "script": args.script, "started": meta.get("started"),
            "updated": datetime.now().isoformat(timespec="seconds"),
            "pages": pages_meta, "done": len(pages_meta), "failed": []},
            ensure_ascii=False, indent=1))
        print(f"[htr-run] побічний вихід {d.name}: {len(pages_meta)} стор.", flush=True)
    # 🔴 ПРИЙМАЧ ПОВНОТИ — з диска, а не з лічильників: `done/skipped/failed`
    # рахує лише те, до чого дійшов цей процес, тож сторінка, загублена без
    # винятку, у них не видна взагалі. Неповний прогін НЕ має права вийти нулем:
    # саме мовчазний нуль (точніше — rc=1 без жодного рядка) видав справу 241-1-886
    # за завершену, маючи 14 сторінок із 18.
    quar = load_quarantine(out_dir)
    gone = [p for p in missing_pages(pages_all, out_dir, tuple(side_dirs.values()))
            if p not in quar]
    meta["missing"] = gone
    # карантин у меті теж потрібен: інакше після нього `missing` порожній, rc=0,
    # і слід про непрочитані сторінки лишається лише в окремому файлі
    meta["quarantined"] = sorted(quar)
    save_meta()
    emit(prog, "done", pages=done, skipped=skipped, failed=failed,
         enhanced=enhanced_n, ceiling=ceiling_n, missing=len(gone))
    if gone:
        print(f"[htr-run] ⚠ НЕПОВНО: без тексту {len(gone)} з {len(pages_all)} "
              f"кадрів — {', '.join(gone[:10])}{'…' if len(gone) > 10 else ''}. "
              f"Догнати: --pages <номери> (кеш сегментації вже теплий)", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
