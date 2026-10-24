"""📜 Звід живе на голому ядрі пакета.

Помічник ставить Нишпорку лише заради Зводу — без консолі, рушіїв і хмари
(`uv tool install nyshporka`). Якщо модуль Зводу чи дивилка кропів потягнуть
імпортом щось із extras, людина побачить `No module named …` на першій же
команді, а в розробника все працюватиме: тут extras стоять завжди. Тому
перевірка — в окремому процесі, за `sys.modules`.
"""
from __future__ import annotations

import subprocess
import sys

EXTRAS = ("fastapi", "uvicorn", "torch", "kraken", "boto3", "paramiko", "cv2",
          "selectolax", "lxml", "aiosqlite", "paddleocr", "tantivy", "curl_cffi")

PROBE = f"""
import sys
import nyshporka.zvid.helper, nyshporka.zvid.owner, nyshporka.zvid.cli
import nyshporka.train.view, nyshporka.train.tasks, nyshporka.train.sheets
import nyshporka.ops_zvid, nyshporka.ops_train
bad = [m for m in {EXTRAS!r} if m in sys.modules]
print(",".join(bad))
"""


def test_zvid_and_crop_viewer_import_nothing_from_extras() -> None:
    got = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True,
                         timeout=120)
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == "", f"Звід тягне extras: {got.stdout.strip()}"
