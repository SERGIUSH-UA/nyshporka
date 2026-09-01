"""🖋 Яка карта стоїть у машині — питання, яке НЕ МОЖНА ставити torch.

🔴 Саме на цьому конвеєр спотикався (issue #7). Середовище рушіїв збирається в
два кроки: спершу ставиться torch, потім під карту докладається CUDA-колесо. Але
дефолтне колесо з PyPI на Windows — `+cpu`: CUDA в ньому немає взагалі, тож
`torch.cuda.device_count()` віддає 0 навіть при справній RTX і свіжому драйвері.
Питати в такого torch про карту означає питати того, хто за побудовою не знає, —
і отримувати «карти не видно» рівно там, де прискорення й треба доставити. Стан
до того ж самозакріплювався: наступний запуск повторював ту саму пробу тим самим
CPU-колесом, і виходу з нього не було.

Тому джерело правди тут — `nvidia-smi`. Він приїжджає разом із драйвером, про
torch не знає нічого й відповідає ще до того, як у середовищі щось стоїть.

⚠ Питати треба `--query-gpu=...`, а не парсити шапку `nvidia-smi`: у драйверах
600-ї серії поля `Driver version` і `CUDA version` оголошені застарілими
(`nvidia-smi --version` пише «Deprecated, see "KMD version" instead», а в шапці
тепер `KMD Version` / `CUDA UMD Version`). Query-форма відповідає однаково на
обох поколіннях драйверів.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Що дописується до кожної відмови: CPU — це повільно, але робочо.
CPU_NOTE = "лишаю CPU-збірку (читання піде ~2 хв/стор замість ~20 с)"

#: Форма, у якій `nvidia-smi` віддає compute capability. Усе інше — не число.
_CAPABILITY = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class Card:
    """Те, що про карту каже драйвер. Порожнє поле — теж відповідь."""

    name: str
    capability: str = ""   # "8.6"; порожньо — драйвер не сказав
    driver: str = ""       # "581.15"

    def label(self) -> str:
        """Рядок для людини: назва, compute, драйвер — без порожніх хвостів."""
        parts = [self.name or "невідома карта"]
        if self.capability:
            parts.append(f"compute {self.capability}")
        if self.driver:
            parts.append(f"драйвер {self.driver}")
        return " · ".join(parts)


def _smi_path() -> str | None:
    """`nvidia-smi` у PATH, а на Windows ще й там, куди його кладе інсталятор.

    ⚠ У PATH його може не бути при цілком справному драйвері — саме тому шлях
    шукається, а не вважається відомим.
    """
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if os.name != "nt":
        return None
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    for p in (Path(root) / "System32" / "nvidia-smi.exe",
              Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")):
        if p.is_file():
            return str(p)
    return None


def _clean(value: str) -> str:
    """`[N/A]`, `[Not Supported]` і подібне — це «поля немає», а не значення."""
    out = value.strip()
    return "" if out.startswith("[") or out.lower() in ("", "n/a", "not supported") else out


def _ask(smi: str, fields: str, timeout: int) -> list[str] | None:
    """Один запит до `nvidia-smi`; повертається ПЕРШИЙ рядок — це device 0.

    Перший навмисно: саме його бачить torch як `cuda:0`, і брати «найкращу з
    двох» означало б обіцяти карту, на якій прогін не поїде.
    """
    try:
        r = subprocess.run([smi, f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        row = [_clean(v) for v in line.split(",")]
        if any(row):
            return row
    return None


def detect_card(timeout: int = 15) -> Card | None:
    """Карта за словами драйвера. `None` — `nvidia-smi` не відповів узагалі."""
    smi = _smi_path()
    if not smi:
        return None
    row = _ask(smi, "name,compute_cap,driver_version", timeout)
    if row and len(row) >= 3:
        cap = row[1] if _CAPABILITY.match(row[1]) else ""
        return Card(name=row[0], capability=cap, driver=row[2])
    # Драйвери до R510 поля `compute_cap` не знають, і запит падає ЦІЛИМ — разом
    # із назвою й версією, які там були. Тож карту питаємо ще раз, без нього:
    # «карта є, але яка саме — драйвер не каже» і «карти немає» — різні
    # відповіді, і друга закриває напрям, якого не перевіряли.
    row = _ask(smi, "name,driver_version", timeout)
    if row and len(row) >= 2:
        return Card(name=row[0], driver=row[1])
    return None


def explain(card: Card | None, reason: str) -> str:
    """Чому прискорення не вмикається — з наступним кроком, а не самим фактом.

    🔴 Один текст на всі випадки був частиною вади: «карти не видно або вона
    поза відомими межами» склеювало три різні стани, і людина з робочою RTX
    читала його як «моя карта не підтримується».
    """
    manual = "знаєте потрібне колесо — `nysh htr install --cuda cu126`"
    if card is None:
        return (f"NVIDIA-карти на машині не видно (`nvidia-smi` не відповідає) — {CPU_NOTE}.\n"
                f"  Якщо карта є, справа в драйвері: nvidia.com/drivers; {manual}")
    head = card.label()
    if reason == "no_capability":
        return (f"{head}: драйвер не каже compute capability, тож колесо підібрати нема з "
                f"чого — {CPU_NOTE}.\n  Лікує оновлення драйвера; {manual}")
    if reason == "out_of_range":
        return (f"{head}: ця карта поза межами колес, які ми знаємо, — {CPU_NOTE}.\n"
                f"  Неправильне колесо не запустилось би взагалі, тому навмання не ставимо; "
                f"{manual}")
    if reason.startswith("driver_old:"):
        need = reason.split(":", 1)[1]
        return (f"{head}: для CUDA-колеса потрібен драйвер від {need} — {CPU_NOTE}.\n"
                f"  Лікує оновлення драйвера (nvidia.com/drivers), карта тут ні до чого")
    return f"{head}: колеса під цю карту не підібрав — {CPU_NOTE}. {manual}"
