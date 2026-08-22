"""Крос-процесний ліміт запитів: скільки сесій не запусти — бюджет один.

🔴 Навіщо окремий модуль, коли в кожному завантажувачі вже є пауза між
запитами. Та пауза рахує потік ОДНОГО ПРОЦЕСУ, а ліміт сервер міряє по КЛІЄНТУ
(IP). Дві сесії, кожна з чесною паузою, дають рівно подвійний темп, три —
потрійний; при цьому кожна окремо «дотримується ліміту» і виглядає невинно.
Саме так безкоштовний волонтерський сервіс і банить за обхід.

⚠ Не плутати з `core.lock`: той стереже «один писар на ПРОСТІР», щоб двоє не
псували ті самі нотатки; цей — «один бюджет на МАШИНУ». Наслідки протилежні:
замок простору береться в кожному просторі окремо, а черга запитів — ні.

Тут черга спільна: стан лежить у файлі ПОЗА робочим простором (ліміт —
властивість машини, а копій простору й репозиторію на ній буває кілька), і
будь-яке число процесів шикується в одну чергу.

Алгоритм — ТІКЕТИ (ковзне вікно з резервуванням наперед):

  під локом:  t = max(now, grants[-N] + window)   # N — скільки дозволено у вікні
              grants.append(t)
  поза локом: sleep(t - now)                      # лок відпущено, черга рухається

Інваріант, який це дає: кожен запит стоїть не раніше ніж `window` після
N-го попереднього, тож у будь-якому вікні тривалості `window` їх щонайбільше N.
Доведення на пальцях: у вікні, що закінчується на t, з попередніх лишились
щонайбільше N-1 (бо grants[-N] уже випав), плюс сам t → рівно N.

🔴 Спати під локом було б простіше, але тоді лок тримається секундами, і будь-яке
падіння процесу вішає всі інші до таймауту. Тому лок тримається лише на час
арифметики (мілісекунди), а чекає кожен свій тікет самостійно.

Три властивості, заради яких воно так написане:

- **впав процес — ліміт не зламався.** Зарезервований і невикористаний слот
  просто згорає: ми недоберемо запит, а не перевищимо;
- **побився файл стану — ліміт не скинувся.** Нечитабельний стан трактується як
  «вікно щойно заповнене вщент», тобто найконсервативніше з можливого. Скидати
  його в нуль було б рівно тією помилкою, від якої модуль і рятує;
- **стрибнув годинник** (NTP, вихід з гібернації) — гранти з надто далекого
  майбутнього відкидаються, інакше один стрибок уперед заморозив би чергу.

Приймач — не «ми ж поставили sleep», а ЖУРНАЛ: кожен фактичний запит лягає у
`<key>.audit.jsonl`, і `verify()` рахує по ньому максимум у ковзному вікні.

    python -m nyshporka.core.xrate verify duck-inspector --max 5 --window 10
    python -m nyshporka.core.xrate selftest --procs 4    # довести на N процесах
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

# ⚠ `sys.platform`, а не `os.name`: перевіряч типів звужує платформенні гілки
# саме за ним. З `os.name` він бачить обидві гілки на кожній платформі й лається
# на `fcntl` під Windows — тобто змушує глушити помилки там, де їх немає.
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


#: Куди класти стан, якщо машина каже інакше, ніж дефолт.
ENV_STATE_DIR = "NYSHPORKA_XRATE_DIR"
#: Той самий сенс у дослідницькому репозиторії, з якого виділено пакет.
ENV_LEGACY_STATE_DIR = "MEGEN_XRATE_DIR"


class LockTimeout(RuntimeError):
    """Лок не вдалося взяти за відведений час."""


class VerifyResult(TypedDict):
    """Що показав журнал фактичних відправок."""

    events: int
    window: float
    limit: int
    worst: int
    worst_at: float
    pids: int
    ok: bool
    span: float


def default_state_dir() -> Path:
    """Спільна на машину тека стану.

    НЕ в репозиторії й не в робочому просторі: ліміт стосується клієнта (IP), а
    копій і того, і того на машині буває кілька — worktree, друга робоча копія,
    другий простір. Розклавши стан по копіях, ми дістали б рівно ту проблему,
    яку модуль лікує.

    🔴 Стара тека дослідницького репозиторію береться, ЯКЩО вона вже є, а нової
    ще немає. Це не сентименти щодо сумісності: доки поруч працюють і пакет, і
    скрипти того репозиторію, різні теки означають ДВІ ЧЕРГИ НА ОДИН IP — тобто
    подвоєний темп рівно тим механізмом, який мав його стримати.
    """
    for env in (ENV_STATE_DIR, ENV_LEGACY_STATE_DIR):
        val = os.environ.get(env)
        if val:
            return Path(val)

    from platformdirs import user_cache_dir

    new = Path(user_cache_dir("nyshporka", appauthor=False)) / "xrate"
    if new.exists():
        return new
    legacy = _legacy_state_dir()
    return legacy if legacy.is_dir() else new


def _legacy_state_dir() -> Path:
    """Тека стану дослідницького репозиторію — рахується його ж правилом."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "megen" / "xrate"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "megen" / "xrate"


@contextmanager
def _locked(path: Path, timeout: float = 300.0) -> Iterator[None]:
    """Ексклюзивний файловий лок, портативний Windows/POSIX.

    Обидва рушії беремо в НЕблокуючому режимі й крутимо власний цикл: у msvcrt
    блокуючий `LK_LOCK` пробує рівно 10 разів по секунді й падає, а нам потрібен
    свій таймаут і чесна діагностика.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # ⚠ Без `with` навмисно: файл мусить лишатись відкритим, доки триває лок,
    # тобто до виходу з цього менеджера; закриває його `finally` нижче.
    fh = open(path, "a+b")  # noqa: SIM115
    try:
        # У msvcrt локується ДІАПАЗОН БАЙТІВ, тож у файлі має бути що локувати:
        # на порожньому файлі lock проходить у всіх одночасно й нічого не боронить.
        if os.fstat(fh.fileno()).st_size == 0:
            fh.write(b"L")
            fh.flush()
        fh.seek(0)
        deadline = time.monotonic() + timeout
        delay = 0.005
        while True:
            try:
                if sys.platform == "win32":
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise LockTimeout(f"{path} зайнято понад {timeout:.0f} с") from None
                time.sleep(delay)
                delay = min(delay * 1.6, 0.25)
        try:
            yield
        finally:
            try:
                fh.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        fh.close()


class CrossProcessLimiter:
    """Ковзне вікно `max_events` запитів на `window` секунд, спільне на машину.

    `safety` розтягує вікно (1.2 = рахуємо 10 с ліміту як 12). Це не забобон:
    сервер міряє вікно від МОМЕНТУ ОТРИМАННЯ, а мережеві затримки в наших
    запитів різні, тож рівно розкладені по 10 с відправки можуть злипнутись
    на тому боці. Запас з'їдає цю різницю.
    """

    def __init__(self, key: str, *, max_events: int = 5, window: float = 10.0,
                 safety: float = 1.2, state_dir: Path | None = None,
                 audit: bool = True, slack: float = 0.25) -> None:
        if max_events < 1:
            raise ValueError("max_events має бути ≥ 1")
        self.key = key
        self.max_events = int(max_events)
        # 🔴 `slack` — не косметика і не «про всяк випадок». Тікет каже, коли
        # запит МОЖНА відправити, а міряють нас по тому, коли він ПІШОВ, і між
        # цими моментами є дрейф: `sleep` на Windows прокидається з точністю
        # ~15 мс, плюс планувальник. Дрейф у кожного запиту свій, тож поставлені
        # рівно на межу гранти перетинаються фактами й дають N+1 у вікні —
        # заміряно на самотесті (2 і 3 процеси: 6 при ліміті 5).
        self.slack = float(slack)
        self.window = float(window) * float(safety) + self.slack
        self.raw_window = float(window)
        self.safety = float(safety)
        self.audit = audit
        d = state_dir or default_state_dir()
        d.mkdir(parents=True, exist_ok=True)
        self.dir = d
        self.state_path = d / f"{key}.json"
        self.lock_path = d / f"{key}.lock"
        self.audit_path = d / f"{key}.audit.jsonl"
        self.waited_total = 0.0
        self.calls = 0

    # ── стан ─────────────────────────────────────────────────────────────────
    def _load(self, now: float) -> list[float]:
        try:
            raw: Any = json.loads(self.state_path.read_text(encoding="utf-8"))
            grants = [float(x) for x in raw["grants"]]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError):
            # 🔴 Побитий стан ≠ порожній стан. Порожній дозволив би пачку
            # запитів одразу — тобто збій файлу став би обходом ліміту.
            # Тому найгірше припущення: вікно щойно заповнене вщент.
            return [now] * self.max_events
        # Гранти з далекого майбутнього — слід стрибка годинника; лишати їх
        # означає заморозити чергу на невизначений час.
        return [g for g in grants if g <= now + self.window * 4]

    def _save(self, grants: list[float]) -> None:
        keep = grants[-(self.max_events * 4):]
        tmp = self.state_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"grants": keep, "max": self.max_events,
                                   "window": self.window}), encoding="utf-8")
        os.replace(tmp, self.state_path)  # атомарно й на Windows

    def reserve(self) -> float:
        """Взяти тікет. Повертає момент (wall clock), раніше за який не можна."""
        with _locked(self.lock_path):
            now = time.time()
            grants = sorted(self._load(now))
            if len(grants) >= self.max_events:
                t = max(now, grants[-self.max_events] + self.window)
            else:
                t = now
            grants.append(t)
            self._save(grants)
        return t

    def _note(self, tag: str) -> None:
        if not self.audit:
            return
        # 🔴 Час береться ДО лока, а запис іде ПІД локом — кожна половина
        # лікує свою ваду.
        #
        # Спершу писали зовсім без лока: мовляв, короткий рядок у режимі
        # дозапису лягає атомарно, а чекання лока зсунуло б записаний час і
        # зіпсувало б рівно той журнал, яким дотримання ліміту й доводиться.
        # Перше виявилось неправдою на Windows: там перехід у кінець файлу
        # й запис — не одна операція, тож конкурентний дозапис ГУБИТЬ рядки.
        # Заміряно: три процеси по три запити, п'ять прогонів — двічі в
        # журналі опинилось 8 записів замість 9.
        #
        # Втрата тут дорожча за будь-який зсув: журнал недорахує відправок,
        # темп у звіті вийде НИЖЧИЙ за фактичний, і перевищення ліміту — те
        # єдине, заради чого журнал існує, — лишиться непоміченим.
        #
        # Тому лок повернуто, але позначку часу знято до нього: чекання
        # лока більше не потрапляє у виміряний момент відправки.
        line = json.dumps({"t": time.time(), "pid": os.getpid(), "tag": tag},
                          ensure_ascii=False)
        with _locked(self.lock_path), open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def acquire(self, tag: str = "") -> float:
        """Дочекатися свого тікета. Повертає, скільки секунд прочекали."""
        t = self.reserve()
        wait = max(0.0, t - time.time())
        if wait:
            time.sleep(wait)
        self.waited_total += wait
        self.calls += 1
        self._note(tag)
        return wait

    @contextmanager
    def slot(self, tag: str = "") -> Iterator[float]:
        yield self.acquire(tag)


# ── приймач: довести по журналу, а не по намірах ─────────────────────────────
def verify(audit_path: Path, max_events: int, window: float,
           since: float | None = None) -> VerifyResult:
    """Максимум подій у ковзному вікні за журналом ФАКТИЧНИХ відправок."""
    ts: list[float] = []
    pids: set[object] = set()
    if audit_path.exists():
        for raw_line in audit_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            t = float(rec.get("t", 0))
            if since is None or t >= since:
                ts.append(t)
                pids.add(rec.get("pid"))
    ts.sort()
    worst, worst_at, i = 0, 0.0, 0
    for j, t in enumerate(ts):
        while ts[i] <= t - window:
            i += 1
        n = j - i + 1
        if n > worst:
            worst, worst_at = n, t
    return VerifyResult(events=len(ts), window=window, limit=max_events,
                        worst=worst, worst_at=worst_at, pids=len(pids),
                        ok=worst <= max_events,
                        span=(ts[-1] - ts[0]) if len(ts) > 1 else 0.0)


def _selftest(procs: int, calls: int, max_events: int, window: float) -> int:
    """Довести інваріант на N ПРОЦЕСАХ, а не на N потоках.

    Потоки одного процесу поділили б пам'ять і не довели б нічого — ламається
    саме міжпроцесна межа. Стан кладеться у власну тимчасову теку, щоб самотест
    не з'їдав бюджет живого ключа.
    """
    import shutil
    import subprocess
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="xrate_selftest_"))
    key = "selftest"
    env = dict(os.environ, **{ENV_STATE_DIR: str(d)})
    code = ("from nyshporka.core.xrate import CrossProcessLimiter as L;"
            f"l=L({key!r},max_events={max_events},window={window},safety=1.0);"
            f"[l.acquire('p') for _ in range({calls})]")
    t0 = time.time()
    kids = [subprocess.Popen([sys.executable, "-c", code], env=env)
            for _ in range(procs)]
    rc = [k.wait() for k in kids]
    res = verify(d / f"{key}.audit.jsonl", max_events, window)
    took = time.time() - t0
    print(f"процесів {procs} × запитів {calls} = {procs * calls}; "
          f"ліміт {max_events}/{window:g} с; зайняло {took:.1f} с")
    print(f"  журнал: {res['events']} подій від {res['pids']} процесів, "
          f"розтягнуто на {res['span']:.1f} с")
    print(f"  максимум у вікні {window:g} с: {res['worst']} (дозволено {max_events})")
    expect = max(0.0, (procs * calls - max_events) * window / max_events)
    print(f"  теоретичний мінімум часу: {expect:.1f} с")
    ok = (res["ok"] and all(r == 0 for r in rc)
          and res["events"] == procs * calls and res["pids"] == procs)
    print("  ✅ ліміт витримано" if ok else "  ❌ ЛІМІТ ПЕРЕВИЩЕНО")
    shutil.rmtree(d, ignore_errors=True)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="nyshporka.core.xrate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="перевірити журнал ключа")
    v.add_argument("key")
    v.add_argument("--max", type=int, default=5)
    v.add_argument("--window", type=float, default=10.0)
    v.add_argument("--last", type=float, default=0.0, help="лише останні N секунд")
    s = sub.add_parser("selftest", help="довести інваріант на N процесах")
    s.add_argument("--procs", type=int, default=3)
    s.add_argument("--calls", type=int, default=4)
    s.add_argument("--max", type=int, default=5)
    s.add_argument("--window", type=float, default=10.0)
    st = sub.add_parser("state", help="показати стан ключа")
    st.add_argument("key")
    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return _selftest(a.procs, a.calls, a.max, a.window)

    d = default_state_dir()
    if a.cmd == "state":
        p = d / f"{a.key}.json"
        print(p, "—", p.read_text(encoding="utf-8") if p.exists() else "стану немає")
        return 0

    since = time.time() - a.last if a.last else None
    res = verify(d / f"{a.key}.audit.jsonl", a.max, a.window, since)
    print(f"{a.key}: {res['events']} запитів від {res['pids']} процесів, "
          f"розтяг {res['span']:.1f} с")
    print(f"максимум у вікні {a.window:g} с: {res['worst']} (ліміт {a.max}) — "
          + ("✅ ок" if res["ok"] else "❌ ПЕРЕВИЩЕНО"))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
