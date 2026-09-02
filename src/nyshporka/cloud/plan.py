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
    box: Box | None = None
    probe: Probe | None = None
    sizing: Sizing | None = None
    channel: str = ""
    channel_why: str = ""
    speed: Speed | None = None
    hours: float = 0.0
    cost: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return self.probe is not None

    @property
    def need(self) -> Need:
        gb = self.sizing.gb_per_shard if self.sizing else DEFAULT_PROFILE.gb_per_shard
        disk = int(self.bytes_in / (1024 ** 3) * 2) + DISK_HEADROOM_GB
        return Need(pages=self.frames, bytes_in=self.bytes_in, gb_per_shard=gb,
                    disk_gb=disk)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "case_dir": str(self.case_dir),
            "out_dir": str(self.out_dir), "model": self.model.name,
            "voice": self.voice.name if self.voice else "",
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


def build(case_dir: str | Path, *, backend: str = "ssh", target: str = "",
          out_dir: str | Path = "", script: str = "", second_voice: bool = True,
          case_key: str = "") -> CloudPlan:
    """Скласти план без жодної мережевої дії.

    Кидає `PlanError` рівно там, де захід не має сенсу починати: немає кадрів,
    немає ваг під це письмо, тека не пласка.
    """
    from nyshporka.cloud.state import run_id_for
    from nyshporka.cloud.verify import frames_in
    from nyshporka.core.workspace import workspace
    from nyshporka.htr.run import (
        ReadError,
        case_key_for,
        guess_script_full,
        pick_model,
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
        model, voice = pick_model(scr, second_voice=second_voice)
    except ReadError as exc:
        # 🔴 Ваги потрібні навіть для хмари: саме їх туди і везуть. Але сказати
        # це треба інакше, ніж локальному читанню, — там порада «поставте
        # рушій», тут вона зайва й збиває.
        raise PlanError(
            f"{exc} Для хмарного прогону рушій локально не потрібен, а ваги — "
            f"так: саме їх ми й веземо на машину.") from None

    key, why = (case_key, "вказано вручну") if case_key else case_key_for(case)
    out = Path(out_dir) if out_dir else workspace().htr_reports / case.name
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
        run_id=run_id_for(case, model=model.name, script=scr, backend=backend),
        case_dir=case, out_dir=out, model=model, voice=voice, script=scr,
        frames=len(frames), bytes_in=_bytes_of(frames), backend=backend,
        target=target, case_key=key, case_key_why=why, warnings=warnings)


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
    need_gb = plan.bytes_in / (1024 ** 3) * 2 + DISK_HEADROOM_GB
    if probe.disk_free_gb and probe.disk_free_gb < need_gb:
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
    data: dict[str, Any] = {
        "run_id": plan.run_id, "case_dir": plan.case_dir, "out_dir": plan.out_dir,
        "model": plan.model, "script": plan.script, "frames": plan.frames,
        "bytes_in": plan.bytes_in, "backend": plan.backend, "target": plan.target,
        "case_key": plan.case_key, "case_key_why": plan.case_key_why,
        "voice": plan.voice, "box": plan.box, "probe": plan.probe,
        "sizing": plan.sizing, "channel": plan.channel,
        "channel_why": plan.channel_why, "speed": plan.speed, "hours": plan.hours,
        "cost": plan.cost, "warnings": plan.warnings}
    data.update(kw)
    return CloudPlan(**data)
