"""📏 Що це за машина насправді — один вимір перед тим, як щось везти.

Проба коштує секунди, а все після неї — хвилини й гігабайти: заливка ваг,
кадрів, встановлення рушія. Тому вона стоїть ПЕРЕД ними, а не після.

🔴 Заявленому вірити не можна, і це не підозріливість, а тричі оплачений
досвід:

* **`nproc` показує ядра ХОСТА, а не наші.** У контейнері з 48 проданими
  ядрами він чесно каже 192, `free -g` каже 251 ГБ при 62.9. План, побудований
  на цих числах, дає вчетверо більше шардів, ніж машина тягне, і прогін не
  сповільнюється, а завалюється. Правду каже cgroup — `cpu.max` (v2) або
  `cpu.cfs_quota_us` (v1).
* **Пам'ять карт не додається.** Ємність рахується ПОКАРТКОВО: дві карти по
  8 ГБ дають не «16 ГБ на всіх», а по чотири шарди на кожну; наївне
  `int(сума × 0.9 / на_шард)` дало 5 замість 4 і 152 збої на 48 готових
  сторінок.
* **Заявленій швидкості каналу теж.** Пропозиція обіцяла 755 Мбіт/с і
  віддавала 0.5: встановлення рушія падало з «не знайдено версію пакета», і
  виглядало це як зламане дзеркало пакетів.

⚠ Мережу міряти ДО того, як машина під навантаженням. Дванадцять шардів на
100% процесора дають нуль байт за секунду з будь-якого джерела — і це
властивість заміру, а не каналу.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from nyshporka.cloud.base import CloudError, Session

#: Скільки терпіти пробу. Вона легка, але `nvidia-smi` на щойно піднятій
#: машині інколи думає довго — драйвер ще вантажиться.
PROBE_TIMEOUT = 120.0

#: Одна команда замість десяти: кожен зайвий обіг — це ще одна затримка каналу,
#: а їх тут і так більше, ніж роботи. Рядки виду `ключ=значення`, невідоме
#: мовчки пропускається — так проба переживає машину без `nvidia-smi`.
_SCRIPT = r"""
echo "nproc=$(nproc 2>/dev/null || echo 0)"
echo "nproc_all=$(nproc --all 2>/dev/null || echo 0)"
if [ -f /sys/fs/cgroup/cpu.max ]; then
  echo "cgroup_v2=$(cat /sys/fs/cgroup/cpu.max 2>/dev/null)"
fi
if [ -f /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]; then
  echo "cfs_quota=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null)"
  echo "cfs_period=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null)"
fi
echo "mem_total_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null)"
if [ -f /sys/fs/cgroup/memory.max ]; then
  echo "cgroup_mem=$(cat /sys/fs/cgroup/memory.max 2>/dev/null)"
elif [ -f /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
  echo "cgroup_mem=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null)"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=memory.total,memory.free \
             --format=csv,noheader,nounits 2>/dev/null \
    | while IFS=, read -r t f; do echo "gpu=$t,$f"; done
fi
echo "disk_free_gb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {printf "%.1f", $4/1048576}')"
echo "python=$({ command -v python3 >/dev/null 2>&1 && python3 -V 2>&1; } || echo none)"
echo "uname=$(uname -sr 2>/dev/null)"
"""


@dataclass(frozen=True)
class Probe:
    """Виміряне залізо. Усе, чим план має право користуватись."""

    #: 🔴 Ядра ефективні — мінімум із того, що видно, і того, що дозволено.
    cores: float = 0.0
    cores_seen: float = 0.0
    ram_gb: float = 0.0
    #: Пам'ять НАЙМЕНШОЇ карти. Саме вона обмежує число шардів на карту.
    vram_gb_min: float = 0.0
    vram_gb_total: float = 0.0
    gpus: int = 0
    disk_free_gb: float = 0.0
    python: str = ""
    uname: str = ""
    net_mbps: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_gpu(self) -> bool:
        return self.gpus > 0 and self.vram_gb_min > 0

    @property
    def cpu_lied(self) -> bool:
        """Чи розходиться видиме з дозволеним. Саме по собі не вирок."""
        return self.cores_seen > 0 and self.cores < self.cores_seen * 0.9

    def as_dict(self) -> dict[str, Any]:
        return {"cores": self.cores, "cores_seen": self.cores_seen,
                "ram_gb": self.ram_gb, "vram_gb_min": self.vram_gb_min,
                "vram_gb_total": self.vram_gb_total, "gpus": self.gpus,
                "disk_free_gb": self.disk_free_gb, "python": self.python,
                "uname": self.uname, "net_mbps": self.net_mbps}

    def human(self) -> str:
        # Саме «вільно», а не «встановлено»: на боксі поруч може рахувати чужа
        # задача, і тоді паспортні 24 ГБ до нас стосунку не мають.
        gpu = (f"{self.gpus}×{self.vram_gb_min:.0f} ГБ вільно на карті"
               if self.has_gpu else "без карти")
        return (f"{self.cores:g} ядер · {self.ram_gb:.0f} ГБ пам'яті · {gpu} · "
                f"{self.disk_free_gb:.0f} ГБ вільно · {self.python or '—'}")


def _num(text: str) -> float:
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return 0.0


def parse(lines: list[str]) -> Probe:
    """Розібрати вивід проби. Чиста функція — тестується без машини."""
    kv: dict[str, str] = {}
    gpus: list[tuple[float, float]] = []
    for raw in lines:
        line = raw.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key == "gpu":
            total, _, free = val.partition(",")
            gpus.append((_num(total) / 1024.0, _num(free) / 1024.0))
        else:
            kv[key] = val.strip()

    seen = _num(kv.get("nproc", "0")) or _num(kv.get("nproc_all", "0"))
    allowed = 0.0
    v2 = kv.get("cgroup_v2", "")
    if v2 and not v2.startswith("max"):
        raw_quota, _, raw_period = v2.partition(" ")
        period = _num(raw_period) or 100000.0
        allowed = _num(raw_quota) / period if period else 0.0
    elif kv.get("cfs_quota"):
        quota = _num(kv["cfs_quota"])
        period = _num(kv.get("cfs_period", "100000")) or 100000.0
        if quota > 0:
            allowed = quota / period
    # 🔴 Мінімум, а не «що знайшли». Обидва числа бувають правдиві поодинці й
    # брехливі разом: `nproc` бачить хост, а квота буває не виставлена зовсім.
    cores = min(x for x in (seen, allowed) if x > 0) if (seen or allowed) else 0.0

    ram = _num(kv.get("mem_total_kb", "0")) / 1048576.0
    cg_mem = kv.get("cgroup_mem", "")
    if cg_mem and not cg_mem.startswith("max"):
        limit = _num(cg_mem) / (1024.0 ** 3)
        if 0 < limit < ram:
            ram = limit

    # Вільна пам'ять карти, а не встановлена: на боксі поруч може вже щось
    # рахувати чужа задача, і тоді «24 ГБ» до нас не мають стосунку.
    free_each = [free for _, free in gpus if free > 0]
    total_each = [total for total, _ in gpus]
    return Probe(
        cores=round(cores, 2), cores_seen=round(seen, 2), ram_gb=round(ram, 1),
        vram_gb_min=round(min(free_each), 2) if free_each else 0.0,
        vram_gb_total=round(sum(free_each), 2) if free_each else 0.0,
        gpus=len(gpus), disk_free_gb=_num(kv.get("disk_free_gb", "0")),
        python=kv.get("python", ""), uname=kv.get("uname", ""),
        raw={"kv": kv, "gpu_total_gb": [round(t, 2) for t in total_each]})


def measure(session: Session, *, net_url: str = "") -> Probe:
    """Виміряти машину одним заходом.

    `net_url` — необов'язкова перевірка каналу. 🔴 Якщо посилання не відповідає,
    це НЕ вирок машині: протухле посилання на наше ж сховище виглядає точно так
    само, як мертвий канал хоста, і одного разу відправило в бан чергу цілком
    здорових машин. Тому невдача заміру лишає `net_mbps = None`, і причина
    називається окремо.
    """
    got = session.run(_SCRIPT, timeout=PROBE_TIMEOUT)
    if got.rc != 0 and not got.out.strip():
        raise CloudError(
            f"машина не відповіла на пробу (rc={got.rc}): "
            f"{got.err.strip()[:200] or 'порожньо'}")
    probe = parse(got.out.splitlines())
    if not net_url:
        return probe
    return _with_net(probe, _measure_net(session, net_url))


def _with_net(probe: Probe, mbps: float | None) -> Probe:
    return Probe(cores=probe.cores, cores_seen=probe.cores_seen,
                 ram_gb=probe.ram_gb, vram_gb_min=probe.vram_gb_min,
                 vram_gb_total=probe.vram_gb_total, gpus=probe.gpus,
                 disk_free_gb=probe.disk_free_gb, python=probe.python,
                 uname=probe.uname, net_mbps=mbps, raw=probe.raw)


_SPEED_RE = re.compile(r"speed=([\d.]+)")


def _measure_net(session: Session, url: str) -> float | None:
    """Скачати 32 МБ і подивитись на швидкість.

    ⚠ `rc=28` від curl — це спрацював `--max-time`, а не збій: швидкість при
    цьому виміряна ПРАВИЛЬНО, просто файл не докачано. Читати це як помилку
    означало б вважати повільним рівно те, що виміряли.
    """
    import shlex

    cmd = (f"curl -s -o /dev/null --max-time 20 -r 0-33554432 "
           f"-w 'speed=%{{speed_download}}\\nhttp=%{{http_code}}\\n' "
           f"{shlex.quote(url)} 2>/dev/null || true")
    got = session.run(cmd, timeout=60.0)
    m = _SPEED_RE.search(got.out)
    if not m:
        return None
    bytes_per_sec = _num(m.group(1))
    return round(bytes_per_sec * 8 / 1_000_000, 2) if bytes_per_sec > 0 else None
