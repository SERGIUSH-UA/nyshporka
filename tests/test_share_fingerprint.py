"""Відбиток зйомки: те, що мусить збігтися, і те, що не сміє.

🔴 Кадри тут із ФАКТУРОЮ, а не суцільною заливкою. `Image.new("RGB", …,
"white")` після зменшення дає однаковий хеш на будь-якому розмірі й
будь-якій якості — такий тест проходив би, не перевіряючи нічого, і саме
цього роду тест найнебезпечніший: він створює враження покриття.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest

from nyshporka.share import align, fingerprint

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
ImageFilter = pytest.importorskip("PIL.ImageFilter")

#: Розмір аркуша. Близький до справжнього скану (замір на PEV.1890 —
#: 1604×2568), і це не косметика: на дрібному аркуші з тонким штрихом
#: структура гине при зменшенні, і тест починає міряти власну синтетику
#: замість алгоритму. Перша версія цього файлу була саме такою — 900×1400
#: з лінією в два пікселі, — і ресайз до 50 % там був невідрізненний від
#: зовсім іншого аркуша.
W, H = 1600, 2400


def _arkush(seed: int, *, size: tuple[int, int] = (W, H)) -> Any:
    """Аркуш, схожий на чорнило: товстий штрих і м'який край.

    Розмиття наприкінці — не прикраса: чорнило на папері має м'який край,
    і саме він переживає зменшення. Гостра однопіксельна лінія зникає.
    """
    im = Image.new("RGB", size, (236, 228, 208))
    d = ImageDraw.Draw(im)
    rng = seed or 1
    for row in range(26):
        y = int(size[1] * (0.06 + row * 0.035))
        x = int(size[0] * 0.09)
        while x < size[0] * 0.92:
            rng = (rng * 1103515245 + 12345) % (1 << 31)
            w = int(size[0] * 0.03) + rng % int(size[0] * 0.07)
            d.line([(x, y + rng % 11), (x + w, y - rng % 11)],
                   fill=(55 + rng % 35, 42, 32), width=5 + rng % 4)
            x += w + int(size[0] * 0.012) + rng % 12
    return im.filter(ImageFilter.GaussianBlur(1.2))


def kadry(root: Path, *, n: int = 20, quality: int = 92,
          scale: float = 1.0, seed0: int = 1000) -> Path:
    """Тека кадрів справи.

    🔴 При `scale` аркуш малюється в повному розмірі й ЗМЕНШУЄТЬСЯ, а не
    малюється одразу дрібним. Це різні речі: намальований наново дрібний
    аркуш має інші абсолютні товщини штриха, тобто це інше зображення, а не
    та сама зйомка в іншому розмірі. Тест на ресайз із таким матеріалом
    перевіряв би не те, що обіцяє.
    """
    d = root / "kadry"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        im = _arkush(seed0 + i * 37)
        if scale != 1.0:
            im = im.resize((int(W * scale), int(H * scale)), Image.Resampling.LANCZOS)
        im.save(d / f"{i:04d}.jpg", "JPEG", quality=quality)
    return d


def test_vidbytok_perezhyvaie_perekoduvannia(tmp_path: Path) -> None:
    """🔴 Головне. Та сама зйомка, розібрана іншим інструментом.

    Зйомка ходить у мережі як PDF, а на сторінки її розбирає кожен своїм
    інструментом — байти після цього різні в усіх. Якщо відбиток цього не
    переживає, він не працює взагалі: саме на цей випадок він і заводився.
    """
    a = kadry(tmp_path / "a", quality=92)
    b = kadry(tmp_path / "b", quality=45)      # інша якість — інші байти

    fa, fb = fingerprint.fingerprint(a), fingerprint.fingerprint(b)
    zbihlos, zvireno = fingerprint.compare(fa, fb)
    assert zvireno == 5
    assert zbihlos == 5, "перекодування не сміє ламати відбиток"

    # І байтовий канал при цьому справді різний — інакше тест нічого не довів.
    sha_a = {s["sha256"] for s in fa["slots"]}
    sha_b = {s["sha256"] for s in fb["slots"]}
    assert not (sha_a & sha_b), "якщо байти збіглися, перевірено не той канал"


def test_vidbytok_perezhyvaie_resayz(tmp_path: Path) -> None:
    """Хмарний шлях зменшує кадри до 3100 px — це не інша зйомка."""
    a = kadry(tmp_path / "a")
    b = kadry(tmp_path / "b", scale=0.5, quality=85)
    zbihlos, zvireno = fingerprint.compare(
        fingerprint.fingerprint(a), fingerprint.fingerprint(b))
    assert (zbihlos, zvireno) == (5, 5)


def test_vidbytok_perezhyvaie_povorot(tmp_path: Path) -> None:
    """🔴 Кадри лежать на боці, і хмарний шлях їх розвертає.

    Замір у `cloud/frames.py`: 706 кадрів із 711 в одній партії були
    горизонтальні. Без нормалізації орієнтації відбиток не збігався б саме
    в найчастішому випадку.
    """
    pryamo = kadry(tmp_path / "pryamo")
    na_boci = tmp_path / "boci" / "kadry"
    na_boci.mkdir(parents=True)
    for f in sorted(pryamo.glob("*.jpg")):
        with Image.open(f) as im:
            im.transpose(Image.Transpose.ROTATE_90).save(na_boci / f.name, "JPEG", quality=92)

    zbihlos, zvireno = fingerprint.compare(
        fingerprint.fingerprint(pryamo), fingerprint.fingerprint(na_boci))
    assert (zbihlos, zvireno) == (5, 5)


def test_vidbytok_rozriznyaie_zyomky(tmp_path: Path) -> None:
    """Інша зйомка тієї самої справи — інший відбиток.

    Найсуворіший бік: відбиток, стійкий до перекодування, але однаковий на
    двох різних зйомках, гірший за його відсутність — він упевнено скаже
    «ті самі кадри» на чужих.
    """
    a = kadry(tmp_path / "a", seed0=1000)
    b = kadry(tmp_path / "b", seed0=7777)     # інші аркуші, та сама кількість
    zbihlos, zvireno = fingerprint.compare(
        fingerprint.fingerprint(a), fingerprint.fingerprint(b))
    assert zvireno == 5
    assert zbihlos == 0


def test_slot_bez_khesha_ne_zarakhovuietsia(tmp_path: Path) -> None:
    """🔴 Кадр, який не відкрився, лишає слот ПОРОЖНІМ.

    Дослівний повтор знахідки рев'ю 21.09 у `htr/seg.py`: там п'ять кадрів
    без розміру в сайдкарі вичерпували вибірку, і запобіжник казав «усе
    гаразд», не звіривши жодного разу. Тут та сама форма помилки коштувала
    б мітки «та сама зйомка», виданої без порівняння.
    """
    d = kadry(tmp_path, n=10)
    bytyi = sorted(d.glob("*.jpg"))[fingerprint.positions_for(10)[1] - 1]
    bytyi.write_bytes("не зображення".encode())

    got = fingerprint.fingerprint(d)
    assert len(got["slots"]) == 5
    assert fingerprint.checked(got) == 4, "битий кадр не має рахуватись перевіреним"
    porozhnii = [s for s in got["slots"] if not s.get("phash")]
    assert porozhnii and porozhnii[0]["why"], "порожній слот мусить нести причину"


def test_poriadok_kadriv_odnakovyi_na_bud_yakiy_systemi(tmp_path: Path) -> None:
    """🔴 Сортування за іменем, а не за `Path`.

    `PurePath.__lt__` порівнює регістронечутливо на Windows і чутливо на
    POSIX. Тека з `0001.JPG` і `0001b.jpg` дала б різний порядок, тобто
    `n`-й кадр — різний кадр, і відбиток на позиціях ламався б мовчки.
    """
    d = tmp_path / "kadry"
    d.mkdir()
    for name in ("0002.jpg", "0001.JPG", "0001b.jpg", "0003.jpg"):
        _arkush(abs(hash(name)) % 9999).save(d / name, "JPEG", quality=90)

    names = [p.name for p in align.frames_sorted(d)]
    assert names == sorted(names), "порядок мусить бути побайтовим за іменем"


def test_korotka_sprava_ne_daie_pyaty_odnakovykh(tmp_path: Path) -> None:
    """На трьох кадрах слотів три, а не п'ять однакових.

    Відбиток із трьох чесніший за «п'ятірний» із трьома повторами: збіг
    такого доводив би менше, ніж заявляє.
    """
    d = kadry(tmp_path, n=3)
    got = fingerprint.fingerprint(d)
    assert len(got["slots"]) == 3
    assert len({s["n"] for s in got["slots"]}) == 3


def test_vidbytok_inshoi_versii_ne_porivniuietsia(tmp_path: Path) -> None:
    """Правило змінилось — старий відбиток мовчки не зіставляється."""
    d = kadry(tmp_path)
    mine = fingerprint.fingerprint(d)
    stare = {**fingerprint.fingerprint(d), "version": fingerprint.FP_VERSION + 1}
    assert fingerprint.compare(mine, stare) == (0, 0)


def test_mitka_exact_lyshe_na_povnomu_zbihu(tmp_path: Path) -> None:
    """🔴 `exact` — тільки всі слоти й та сама кількість кадрів.

    Збіг чотирьох із п'яти означає, що десь у зйомці зайвий або пропущений
    аркуш, і далі за ним усе з'їхало на одиницю — кроп різав би сусідній
    рядок.
    """
    svoya = kadry(tmp_path / "svoya", n=20)
    chuzha = fingerprint.fingerprint(kadry(tmp_path / "chuzha", n=20, quality=50))

    frames = align.frames_of(svoya)
    povnyi = align.grade(frames, svoya, their_fp=chuzha)
    assert povnyi.label == align.EXACT
    assert povnyi.can_crop

    # Той самий відбиток, але заявлено іншу кількість кадрів.
    zsunutyi = {**chuzha, "frames": 21}
    assert align.grade(frames, svoya, their_fp=zsunutyi).label == align.BY_POSITION


def test_chuzha_zyomka_ne_daie_prava_na_krop(tmp_path: Path) -> None:
    """Інші кадри — мітка падає до `text-only`, кроп заборонено."""
    svoya = kadry(tmp_path / "svoya", n=20, seed0=1000)
    chuzha = fingerprint.fingerprint(kadry(tmp_path / "chuzha", n=20, seed0=5555))

    got = align.grade(align.frames_of(svoya), svoya, their_fp=chuzha)
    assert got.label == align.TEXT_ONLY
    assert not got.can_crop


def test_bez_vidbytka_povedinka_ta_sama(tmp_path: Path) -> None:
    """Старий пакет без відбитка міряється як раніше — за іменами."""
    d = kadry(tmp_path, n=6)
    got = align.grade(align.frames_of(d), d)
    assert got.label == align.BY_NAME


def test_vidbytok_ne_chytaie_use_pidriad(tmp_path: Path) -> None:
    """Відкривається рівно п'ять кадрів, а не вся справа.

    Саме через ціну читання `align.frames_of` не рахує хешів за
    замовчуванням; якщо відбиток почне читати все, він успадкує ту саму
    проблему на справі в 3772 кадри.
    """
    d = kadry(tmp_path, n=40)
    vidkryti: list[str] = []
    original = Image.open

    def _spy(fp: Any, *a: Any, **kw: Any) -> Any:
        if isinstance(fp, (str, Path)):
            vidkryti.append(Path(fp).name)
        return original(fp, *a, **kw)

    Image.open = _spy
    try:
        fingerprint.fingerprint(d)
    finally:
        Image.open = original

    assert len(vidkryti) == 5, f"відкрито {len(vidkryti)} кадрів замість п'яти"


def test_vidbytok_stalyi_mizh_zapuskamy(tmp_path: Path) -> None:
    """Хеш не залежить від того, коли його порахували."""
    d = kadry(tmp_path, n=8)
    assert fingerprint.fingerprint(d) == fingerprint.fingerprint(d)


def test_vidbytok_ne_zalezhyt_vid_konteynera(tmp_path: Path) -> None:
    """JPEG проти PNG — той самий аркуш."""
    d_jpg = kadry(tmp_path / "j", n=12)
    d_png = tmp_path / "p" / "kadry"
    d_png.mkdir(parents=True)
    for f in sorted(d_jpg.glob("*.jpg")):
        with Image.open(f) as im:
            im.save(d_png / f"{f.stem}.png", "PNG")

    zbihlos, zvireno = fingerprint.compare(
        fingerprint.fingerprint(d_jpg), fingerprint.fingerprint(d_png))
    assert (zbihlos, zvireno) == (5, 5)


def test_normalizovanyi_sha256_buv_by_marnym(tmp_path: Path) -> None:
    """Довідковий тест: чому різницевий хеш, а не sha256 зменшеного.

    Він не перевіряє наш код — він фіксує ЗАМІР, на якому стоїть вибір.
    Якщо колись захочеться «спростити» до sha256 нормалізованого
    зображення, цей тест покаже, що спрощення не працює зовсім.
    """

    def norm_sha(path: Path) -> str:
        with Image.open(path) as im:
            small = im.convert("L").resize((256, 256), Image.Resampling.LANCZOS)
            return hashlib.sha256(small.tobytes()).hexdigest()

    a = kadry(tmp_path / "a", n=1, quality=95)
    kadr = next(a.glob("*.jpg"))
    b = tmp_path / "b"
    b.mkdir()
    with Image.open(kadr) as im:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=75)
        (b / "0001.jpg").write_bytes(buf.getvalue())

    assert norm_sha(kadr) != norm_sha(b / "0001.jpg"), (
        "якщо це раптом збіглося — замір застарів, перевірити вибір хеша"
    )
