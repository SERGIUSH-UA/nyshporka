"""🗺 Що саме поїде на чужу машину — усе видно до того, як щось почалось.

Той самий поділ, що `manifest` перед завантаженням справи й `read.plan` перед
читанням, і з тієї ж причини: дізнатись «модель не та», «кадрів не двадцять, а
три тисячі» або «заливка триватиме дев'ять годин» після старту означає втратити
ніч, а на орендованій машині — ще й гроші.

🔴 План будується без локального рушія. Людина, у якої немає ні карти, ні
встановленого рушія, — найперший адресат хмарного прогону, і вимагати від неї
`nysh htr install` заради того, щоб порахувати план, означало б замкнути двері,
до яких вона прийшла. Тому тут беруться лише ваги (їх усе одно везти) і письмо,
а перевірка середовища лишається локальному `read`.

🔴 План має дві стадії, і друга не косметична:

    dry        за заявленим залізом — миттєво, без мережі, без грошей;
    measured   за виміряним — після з'єднання, коли відомо, скільки ядер
               насправді дали й скільки пам'яті вільно на картах.

Показувати лише першу — це рівно та вада, через яку прогони брали вчетверо
більше процесів, ніж машина тягне: заявка каже 192 ядра там, де їх 48.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.cloud.base import Box, Need
from nyshporka.cloud.probe import Probe
from nyshporka.cloud.sizing import DEFAULT_PROFILE, EngineProfile, Sizing, plan_sizing
from nyshporka.cloud.transfer import Speed, Storage

#: Запас диска на машині понад самі кадри: розпакований tar, тексти, рушій.
#: ⚠ Завищувати шкідливо — надмірна вимога до диска мовчки відсікає здорові
#: машини на ринку й звужує вибір там, де його й так небагато.
DISK_HEADROOM_GB = 5

#: Місце під середовище рушіїв на СВІЖІЙ (орендованій) машині: venv із torch і
#: бібліотеками CUDA (лише cudnn — 674 МБ колесом), кеш `uv`, ваги.
#: 🔴 Перша ж справжня оренда (19.09.2026) просила в ринку 5 ГБ — запас, мірений
#: на своїй машині, де середовище вже стоїть. Бокс дали на 8 ГБ, `kraken` не
#: поставився (rc=2 посеред завантаження колес), захід закінчився нулем сторінок.
#: Заміряно на тому ж боксі: до збою встигло лягти понад 5 ГБ.
ENGINE_ENV_GB = 20


@dataclass(frozen=True)
class CloudPlan:
    """Захід, як він виглядає до старту."""

    run_id: str
    case_dir: Path
    out_dir: Path
    model: Path
    script: str
    frames: int
    bytes_in: int
    backend: str
    target: str = ""
    case_key: str = ""
    case_key_why: str = ""
    voice: Path | None = None
    #: Голоси понад другий (`--with latin`) — див. `htr.run.Plan.extra_voices`.
    extra_voices: tuple[Path, ...] = ()
    box: Box | None = None
    probe: Probe | None = None
    sizing: Sizing | None = None
    channel: str = ""
    channel_why: str = ""
    speed: Speed | None = None
    hours: float = 0.0
    cost: float | None = None
    warnings: list[str] = field(default_factory=list)
    #: Стелі, якими людина обмежила захід. `None` — стелі немає.
    #: 🔴 Їдуть у `Need` як є й не послаблюються ніде на шляху: план їх лише
    #: несе, а зважувати можна все інше (ядра, пам'ять, диск).
    budget_usd: float | None = None
    max_hours: float | None = None
    max_price_usd_h: float | None = None
    #: Виміряна щільність письма цієї справи (рядків на сторінку), якщо вона
    #: вже частково прочитана. Поправка до кошторису, не вимога.
    lines_per_page: float | None = None
    #: Звідки кадри НАСПРАВДІ. Непорожнє лише тоді, коли на машину їде стиснута
    #: копія: у мету прогону після забору мусить лягти оригінал, бо кроп зі
    #: стиснутого кадру вдвічі дрібніший, а звіряють знахідку саме кропом.
    source_dir: Path | None = None
    #: Скільки сторінок лишилось читати, коли частину вже прочитано (повтор
    #: після стелі бюджету). `None` — читати все. На ринок іде саме це число:
    #: кошторис на всю справу там, де лишилась третина, завищив би вилку й
    #: даремно вимагав би дозволу людини.
    pages_left: int | None = None
    #: Машину беруть з ринку під цей захід, тож середовища рушіїв на ній немає
    #: за побудовою — і диска треба на нього теж (`ENGINE_ENV_GB`).
    fresh_machine: bool = False
    #: Тека ПЕРШОГО прогону — непорожня лише тоді, коли це перечитування
    #: справи іншою моделлю. Там лежать `.lines.json`, якими звіряється
    #: геометрія кешу сегментації, і, можливо, сам кеш, забраний із хмари.
    #: 🔴 Не те саме, що `out_dir`: у перечитування тека СВОЯ (з тегом моделі),
    #: бо тексти першого прогону забір не перезаписує.
    base_out: Path | None = None

    @property
    def voices(self) -> tuple[Path, ...]:
        return tuple(v for v in (self.voice, *self.extra_voices) if v is not None)

    @property
    def measured(self) -> bool:
        return self.probe is not None

    @property
    def need(self) -> Need:
        from nyshporka.cloud.sizing import useful_cores

        gb = self.sizing.gb_per_shard if self.sizing else DEFAULT_PROFILE.gb_per_shard
        disk = int(self.bytes_in / (1024 ** 3) * 2) + DISK_HEADROOM_GB
        if self.fresh_machine:
            disk += ENGINE_ENV_GB
        pages = self.frames if self.pages_left is None else max(1, self.pages_left)
        return Need(pages=pages, bytes_in=self.bytes_in, gb_per_shard=gb,
                    disk_gb=disk, max_hours=self.max_hours,
                    budget_usd=self.budget_usd,
                    max_price_usd_h=self.max_price_usd_h,
                    prefer_cores=useful_cores(pages),
                    lines_per_page=self.lines_per_page,
                    min_compute_cap=_oldest_card() if self.fresh_machine else None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "case_dir": str(self.case_dir),
            "out_dir": str(self.out_dir), "model": self.model.name,
            "voice": self.voice.name if self.voice else "",
            "voices": [v.name for v in self.voices],
            "script": self.script, "frames": self.frames,
            "bytes_in": self.bytes_in, "backend": self.backend,
            "target": self.target, "case_key": self.case_key,
            "case_key_why": self.case_key_why, "measured": self.measured,
            "box": self.box.as_dict() if self.box else None,
            "probe": self.probe.as_dict() if self.probe else None,
            "sizing": self.sizing.as_dict() if self.sizing else None,
            "channel": self.channel, "channel_why": self.channel_why,
            "transfer_eta_s": (self.speed.eta_sec(self.bytes_in)
                               if self.speed else None),
            "hours": self.hours, "cost": self.cost,
            "budget_usd": self.budget_usd, "max_hours": self.max_hours,
            "max_price_usd_h": self.max_price_usd_h,
            "lines_per_page": self.lines_per_page,
            "source_dir": str(self.source_dir) if self.source_dir else "",
            "base_out": str(self.base_out) if self.base_out else "",
            "warnings": list(self.warnings)}


class PlanError(RuntimeError):
    """План не складається — з поясненням, чого бракує."""


def _bytes_of(frames: list[Path]) -> int:
    total = 0
    for p in frames:
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def _unidentified(case_dir: Path) -> str:
    """Пояснення, коли шифру ще НЕ встановлено свідомо. Порожньо — стану немає.

    🔴 Різницю між «забули описати» й «ще не ототожнено» видно лише з паспорта
    теки, і без неї план докоряв би дослідникові за рішення, яке той ухвалив
    свідомо: матеріал знайдено за селом у дзеркалі плівок, номер плівки
    відомий, фонд і опис — ще ні.
    """
    from nyshporka.cases.register import read_sidecar

    sc = read_sidecar(case_dir)
    if not sc.get("unidentified"):
        return ""
    film = str(sc.get("film") or "").strip()
    return ("шифру ще не встановлено (заявлено в паспорті теки"
            + (f"; плівка {film}" if film else "") + ")")


def _oldest_card() -> float | None:
    """Найстаріша архітектура карти, під яку маніфест рушіїв має колесо torch."""
    try:
        from nyshporka.htr import manifest as M

        floors = [float(row["min_capability"]) for row in M.active().cuda_matrix]
    except Exception:
        return None
    return min(floors) if floors else None


def _rents(backend: str) -> bool:
    """Чи бекенд бере машину з ринку. Лише локальний реєстр, без мережі."""
    try:
        from nyshporka.cloud import registry

        found = registry.load().get(backend)
    except Exception:
        return False
    return "rent" in (getattr(found, "caps", None) or ())


def build(case_dir: str | Path, *, backend: str = "ssh", target: str = "",
          out_dir: str | Path = "", script: str = "", second_voice: bool = True,
          model: str = "",
          case_key: str = "", also: list[str] | tuple[str, ...] = (),
          budget_usd: float | None = None, max_hours: float | None = None,
          max_price_usd_h: float | None = None,
          lines_per_page: float | None = None,
          source_dir: str | Path = "",
          pages_left: int | None = None) -> CloudPlan:
    """Скласти план без жодної мережевої дії.

    Кидає `PlanError` рівно там, де захід не має сенсу починати: немає кадрів,
    немає ваг під це письмо, тека не пласка.
    """
    for name, value in (("--budget", budget_usd), ("--max-hours", max_hours),
                        ("--max-price", max_price_usd_h)):
        # 🔴 Нуль і від'ємне — відмова, а не «стелі немає». Стеля, яку мовчки
        # прочитали як відсутню, — це захід без обмеження витрат там, де людина
        # щойно спробувала його обмежити.
        if value is not None and value <= 0:
            raise PlanError(f"{name} мусить бути додатним числом, а не {value:g}. "
                            f"Без стелі — просто не передавайте прапорець.")
    from nyshporka.cloud.state import run_id_for
    from nyshporka.cloud.verify import frames_in
    from nyshporka.core.workspace import workspace
    from nyshporka.htr.run import (
        ReadError,
        case_key_for,
        guess_script_full,
        model_tag,
        pick_model,
        resolve_model,
        resolve_voices,
    )

    case = Path(case_dir).expanduser().resolve()
    if not case.is_dir():
        raise PlanError(f"теки немає: {case}")
    frames = frames_in(case)
    if not frames:
        nested = [d.name for d in case.iterdir()
                  if d.is_dir() and any(x.is_file() for x in d.iterdir())]
        if nested:
            raise PlanError(
                f"у самій теці кадрів немає, вони в підтеках "
                f"({', '.join(nested[:4])}). Читання не рекурсивне — вкажіть "
                f"підтеку або зберіть кадри в одну пласку теку.")
        raise PlanError(f"у теці {case} немає зображень сторінок")

    guess = guess_script_full(case, script)
    scr = guess.script
    if scr == "unknown":
        # 🔴 «Не знаю» — повноцінна відповідь, і для хмари вона дорожча, ніж
        # для локального читання. Мовчазне «нехай буде кирилиця» коштує тут не
        # лише ночі прогону, а й заливки гігабайтів та оренди машини — заради
        # теки правдоподібного сміття, бо невідповідність рушія письму не дає
        # збою: текст виходить, впевненість не падає.
        raise PlanError(
            f"письмо справи не визначається: {guess.why} Вкажіть його явно — "
            f"`--script cyrillic` або `--script latin`. Вгадати тут не можна: "
            f"помилка дає не збій, а осмислене на вигляд сміття.")
    try:
        weights, voice = pick_model(scr, second_voice=second_voice)
    except ReadError as exc:
        # 🔴 Ваги потрібні навіть для хмари: саме їх туди і везуть. Але сказати
        # це треба інакше, ніж локальному читанню, — там порада «поставте
        # рушій», тут вона зайва й збиває.
        raise PlanError(
            f"{exc} Для хмарного прогону рушій локально не потрібен, а ваги — "
            f"так: саме їх ми й веземо на машину.") from None

    # ── перечитування іншою моделлю ──────────────────────────────────────────
    # 🔴 Тека виходу дістає суфікс `-<тег моделі>`, і робить це складач плану, а
    # не викликач: у теці першого прогону вже лежать тексти, забір їх НЕ
    # перезаписує, і тег, поставлений десь вище по шляху, можна обійти. Інша
    # тека дає заразом інший `run_id` (модель у нього входить) і інший префікс
    # чекпоінтів, тобто дві моделі не крадуть роботу одна в одної.
    reread = False
    if str(model or "").strip():
        try:
            named, named_script = resolve_model(str(model).strip())
        except ReadError as exc:
            raise PlanError(str(exc)) from None
        # 🔴 Названа БОЙОВА модель — не перечитування, а звичайний прогін. Без
        # цієї гілки `--model pysar_cyr_v17.pt` завів би теку `-pysar_v17`
        # поруч зі справжньою й перечитав би справу за гроші, нічого не
        # додавши.
        if named != weights:
            reread, weights, voice, scr = True, named, None, named_script
            if also:
                # Ансамбль є лише в PARSeq-гілці: додаткові голоси читають ті
                # самі рядки основної моделі, тож «перечитати іншою» і «додати
                # голос» — різні дії, і разом вони означали б неясно що.
                raise PlanError(
                    "`--with` додає голос до бойової пари, а `--model` читає "
                    "справу ІНШОЮ моделлю в окрему теку — разом вони не йдуть. "
                    "Оберіть щось одне.")

    try:
        extra = resolve_voices(also, main=weights, have=[voice] if voice else [])
    except ReadError as exc:
        raise PlanError(str(exc)) from None

    key, why = (case_key, "вказано вручну") if case_key else case_key_for(case)
    base_out = workspace().htr_reports / case.name
    out = Path(out_dir) if out_dir else (
        base_out.with_name(f"{case.name}-{model_tag(weights)}") if reread else base_out)
    warnings: list[str] = []
    if not key:
        # 🔴 «Шифри немає» і «шифру ще не встановлено» — різні стани, і докір
        # доречний лише в першому. Другий заявлений у паспорті теки (плівка
        # відома, фонд і опис — ні), тобто це рішення дослідника, а не
        # недбалість; повторювати йому пораду покласти опис означає вимагати
        # вигадати шифру — рівно те, чого стан і має уникнути.
        stated = _unidentified(case)
        if stated:
            why = stated
        else:
            warnings.append(
                "шифри справи не знайдено — прогін ляже «нічиїм», і облік його "
                "не побачить. Покладіть `_source.json` у теку справи, передайте "
                "`--case-key` або, якщо шифру ще не встановлено, опишіть теку "
                "плівкою: `nysh case <тека> --film <номер>`")
    if guess.is_guess:
        # Не «чи передали прапорець», а чим доведене письмо: опис справи — це
        # факт, жанр і роки — сильний здогад, ім'я теки — найслабша ознака.
        warnings.append(
            f"письмо «{scr}» вгадано ({guess.why}). Помилка тут дає не збій, а "
            f"осмислене на вигляд сміття — звірте перші сторінки або вкажіть "
            f"письмо явно")
    if voice is None and scr == "cyrillic":
        warnings.append(
            "другого голосу немає — читатиме один рушій. Другий помиляється "
            "інакше й витягує те, де перший підставив правдоподібне слово")

    return CloudPlan(
        run_id=run_id_for(case, model=weights.name, script=scr, backend=backend),
        case_dir=case, out_dir=out, model=weights, voice=voice, extra_voices=extra,
        script=scr,
        frames=len(frames), bytes_in=_bytes_of(frames), backend=backend,
        fresh_machine=_rents(backend),
        target=target, case_key=key, case_key_why=why, warnings=warnings,
        budget_usd=budget_usd, max_hours=max_hours,
        max_price_usd_h=max_price_usd_h, lines_per_page=lines_per_page,
        source_dir=Path(source_dir) if source_dir else None,
        base_out=base_out if reread else None,
        pages_left=pages_left)


def with_box(plan: CloudPlan, box: Box, *,
             profile: EngineProfile = DEFAULT_PROFILE) -> CloudPlan:
    """Уточнити план заявленим залізом машини — ще без з'єднання."""
    if box.cores <= 0:
        # Машина без опису заліза — не привід відмовляти: SSH-ціль, яку людина
        # додала одним рядком, залізо не декларує, і виміряємо ми його одразу
        # по з'єднанню. Просто не вигадуємо чисел.
        return _replace(plan, box=box, warnings=[*plan.warnings, 
            "залізо машини не описане — план буде порахований після з'єднання"])
    sizing = plan_sizing(cores=box.cores, vram_gb_min=box.vram_gb,
                         gpus=box.gpus, profile=profile, pages=plan.frames)
    return _finish(plan, box=box, probe=None, sizing=sizing, profile=profile)


def with_probe(plan: CloudPlan, probe: Probe, *,
               profile: EngineProfile = DEFAULT_PROFILE,
               shards: int = 0, gb_per_shard: float = 0.0) -> CloudPlan:
    """Уточнити план виміряним залізом. Саме цей план іде в роботу."""
    sizing = plan_sizing(cores=probe.cores, vram_gb_min=probe.vram_gb_min,
                         gpus=probe.gpus, profile=profile, shards=shards,
                         pages=plan.frames, gb_per_shard=gb_per_shard or None)
    extra: list[str] = []
    if probe.cpu_lied:
        extra.append(
            f"машина показує {probe.cores_seen:g} ядер, а дозволено "
            f"{probe.cores:g} — рахуємо за дозволеними. Заявленому числу тут "
            f"вірити не можна: воно від хоста, а не від нашої частки")
    if not probe.has_gpu:
        extra.append("карти не видно — читатиме процесор; це працює, але значно "
                     "повільніше")
    need_gb = plan.need.disk_gb
    # Допуск 15%: орендований бокс видають рівно на запитаний обсяг, і вільного
    # на ньому завжди трохи менше — без допуску попередження горіло б на кожній
    # оренді й перестало б щось означати.
    if probe.disk_free_gb and probe.disk_free_gb < need_gb * 0.85:
        extra.append(
            f"на машині {probe.disk_free_gb:.0f} ГБ вільно, а треба близько "
            f"{need_gb:.0f} ГБ (кадри розпакуються)")
    return _finish(plan, box=plan.box, probe=probe, sizing=sizing,
                   profile=profile, extra=extra)


def with_channel(plan: CloudPlan, *, storage: Storage | None,
                 speed: Speed | None) -> CloudPlan:
    """Назвати канал і час передачі — числом, а не порадою."""
    from nyshporka.cloud.transfer import pick_channel

    channel, why = pick_channel(nbytes=plan.bytes_in, storage=storage, sftp=speed)
    return _replace(plan, channel=channel, channel_why=why, speed=speed)


def _finish(plan: CloudPlan, *, box: Box | None, probe: Probe | None,
            sizing: Sizing, profile: EngineProfile,
            extra: list[str] | None = None) -> CloudPlan:
    from nyshporka.cloud.sizing import predict_cost, predict_hours

    hours = predict_hours(plan.frames, sizing, profile=profile)
    price = box.price_usd_h if box else None
    cost = predict_cost(plan.frames, sizing, price, profile=profile)
    return _replace(plan, box=box, probe=probe, sizing=sizing, hours=hours,
                    cost=cost, warnings=[*plan.warnings, *(extra or ())])


def _replace(plan: CloudPlan, **kw: Any) -> CloudPlan:
    # 🔴 `dataclasses.replace`, а не перелік полів руками. Перелік губив кожне
    # нове поле мовчки: стеля витрат, додана в план, зникала б на першому ж
    # уточненні залізом — тобто рівно перед орендою, де вона й потрібна.
    from dataclasses import replace

    return replace(plan, **kw)
