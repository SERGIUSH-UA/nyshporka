"""CLI хмарного прогону: `nysh cloud hosts | plan | prepare | start | state |
fetch | verify | stop`, а для оренди — `nysh cloud go` і `nysh cloud rent`.

`go` — ті самі кроки одним заходом, для випадку, де людини поруч немає: машина
орендується, тож між «почали» й «погасили» не має лишитись жодного кроку, який
хтось мусить згадати зробити.

Решта команд навмисно дрібні й повторювані. Захід триває годинами, і єдиний спосіб
пережити обрив, закритий ноутбук і Ctrl+C — щоб кожен крок можна було просто
викликати ще раз: `start` підхопить свою роботу, `fetch` докачає, `verify`
нічого не змінить.

🔴 Порядок `fetch → verify → stop` тут не рекомендація, а перевірка в коді:
`stop` відмовляється гасити машину, поки роботу не звірено.

🔴 Секції «Читання» ці команди не вимагають — і це рішення, а не недогляд.
`nysh read` вимагає її законно: без локального рушія читати нічим. Але хмарний
прогін існує рівно для тих, у кого рушія немає й не буде — ноутбук на два ядра,
машина без карти, небажання тягнути 2.5 ГБ `torch` заради роботи, яка все одно
поїде кудись. Вимагати тут `nysh sections enable htr` означало б замкнути двері,
до яких людина прийшла. Ваги при цьому потрібні (їх і везуть) — але вони не
рушій і не важать гігабайтів.
"""
from __future__ import annotations

import typer
from rich.markup import escape

from nyshporka import brand
from nyshporka.cloud.base import Box, CloudError
from nyshporka.cloud.plan import CloudPlan
from nyshporka.cloud.state import RunState

app = typer.Typer(help="Прогін справи на іншій машині.", no_args_is_help=True)
hosts_app = typer.Typer(help="Машини, на яких можна читати.", no_args_is_help=True)
app.add_typer(hosts_app, name="hosts")
rent_app = typer.Typer(
    help="Оренда машини: ключ провайдера, баланс і що зараз тарифікується.",
    no_args_is_help=True)
app.add_typer(rent_app, name="rent")

console = brand.console()


def _say(text: str) -> None:
    console.print(text)


def _plural(n: int, one: str, few: str, many: str) -> str:
    """«1 процес · 2 процеси · 5 процесів». Число тут бачать щоразу."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _size(nbytes: int) -> str:
    """Обсяг у тих одиницях, у яких він читається.

    «0.00 ГБ» на дрібній справі — не число, а шум: воно не відрізняє двадцяти
    кадрів від двохсот, а саме за обсягом обирається канал передачі.
    """
    if nbytes >= 1_000_000_000:
        return f"{nbytes / 1e9:.2f} ГБ"
    if nbytes >= 1_000_000:
        return f"{nbytes / 1e6:.0f} МБ"
    return f"{nbytes / 1e3:.0f} КБ"


def _need_run(run_id: str) -> RunState:
    """Захід за іменем, або єдиний незавершений.

    🔴 Коли незавершених кілька — відмова з переліком, а не «візьму перший».
    Мовчазний вибір тут означав би забрати результат одного заходу й погасити
    машину іншого.
    """
    from nyshporka.cloud import state as ST

    if run_id:
        st = ST.load(run_id)
        if st is None:
            raise typer.BadParameter(f"немає заходу «{run_id}»")
        return st
    alive = ST.live()
    if not alive:
        recent = ST.all_runs()
        if not recent:
            console.print("[err]жодного заходу ще не було[/err]")
            raise typer.Exit(code=1)
        return recent[0]
    if len(alive) > 1:
        names = ", ".join(s.run_id for s in alive)
        console.print(f"[err]незавершених заходів кілька: {names}. "
                      f"Назвіть потрібний явно[/err]")
        raise typer.Exit(code=2)
    return alive[0]


# ── машини ───────────────────────────────────────────────────────────────────
@hosts_app.command("list")
def hosts_list(as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Які машини записані й які бекенди доступні."""
    from nyshporka.cloud import registry as REG
    from nyshporka.cloud.ssh import load_hosts
    from nyshporka.cloud.transfer import load_storage

    reg = REG.load()
    rows = load_hosts()
    storage = load_storage()
    if as_json:
        console.print_json(data={
            "backends": [{"id": b.id, "label": b.label, "caps": sorted(b.caps)}
                         for b in reg.all()],
            "broken": [{"name": n, "why": w} for n, w in reg.broken],
            "hosts": [h.as_dict() for h in rows],
            "storage": storage.bucket if storage else ""})
        return

    console.print("[bold]бекенди[/bold]")
    for b in reg.all():
        caps = ", ".join(sorted(b.caps)) or "без оренди"
        console.print(f"  ✅ {b.id} — {b.label} [muted]({caps})[/muted]")
    for name, why in reg.broken:
        # Ховати зламані плагіни не можна: «мого способу немає в списку» інакше
        # не має пояснення.
        console.print(f"  [err]🔴 {name} — не завантажився: {why}[/err]")

    console.print("\n[bold]машини[/bold]")
    if not rows:
        console.print("  [muted]жодної. Додати: "
                      "nysh cloud hosts add <ім'я> <user@host[:порт]>[/muted]")
    for h in rows:
        iron = (f" · {h.cores:g} ядер, {h.vram_gb:g} ГБ карти"
                if h.cores or h.vram_gb else "")
        console.print(f"  {h.name} → {h.target}{iron}")
    if storage:
        console.print(f"\nсховище: {storage.bucket} "
                      f"[muted]{storage.endpoint_url or ''}[/muted]")
    else:
        console.print("\n[muted]об'єктне сховище не налаштоване — великі справи "
                      "їхатимуть напряму й повільно (nysh cloud hosts storage)[/muted]")


@hosts_app.command("add")
def hosts_add(
    name: str = typer.Argument(..., help="коротке ім'я машини"),
    target: str = typer.Argument(..., help="user@host[:порт]"),
    key: str = typer.Option("", "--key", help="шлях до приватного ключа"),
    workdir: str = typer.Option("", "--workdir", help="тека роботи на машині"),
    python: str = typer.Option("", "--python",
                                help="інтерпретатор на машині; типово python3"),
    cores: float = typer.Option(0.0, "--cores", help="заявлені ядра (для плану)"),
    vram: float = typer.Option(0.0, "--vram", help="заявлена пам'ять карти, ГБ"),
    gpus: int = typer.Option(1, "--gpus", help="скільки карт на машині"),
) -> None:
    """Записати машину. 🔴 Ключ — шляхом, ніколи не вмістом і не паролем."""
    from nyshporka.cloud.ssh import DEFAULT_WORKDIR, Host, load_hosts, parse_target, save_hosts

    parsed = parse_target(target)
    if parsed is None:
        raise typer.BadParameter(
            f"«{target}» не схоже на адресу. Треба `user@host` або "
            f"`user@host:порт`")
    rows = [h for h in load_hosts() if h.name != name]
    rows.append(Host(name=name, user=parsed.user, host=parsed.host,
                     port=parsed.port, key=key,
                     workdir=workdir or DEFAULT_WORKDIR,
                     python=python or "python3", cores=cores, vram_gb=vram,
                     gpus=max(1, gpus)))
    path = save_hosts(rows)
    console.print(f"✅ {name} → {parsed.user}@{parsed.host}:{parsed.port} "
                  f"[muted]({path})[/muted]")


@hosts_app.command("rm")
def hosts_rm(name: str = typer.Argument(..., help="коротке ім'я машини")) -> None:
    """Прибрати машину з переліку."""
    from nyshporka.cloud.ssh import load_hosts, save_hosts

    rows = load_hosts()
    left = [h for h in rows if h.name != name]
    if len(left) == len(rows):
        console.print(f"[err]немає машини «{name}»[/err]")
        raise typer.Exit(code=1)
    save_hosts(left)
    console.print(f"✅ прибрано {name}")


@hosts_app.command("storage")
def hosts_storage(
    bucket: str = typer.Argument("", help="назва сегмента; порожньо — показати"),
    endpoint: str = typer.Option("", "--endpoint", help="адреса S3-сумісного API"),
    region: str = typer.Option("auto", "--region", help="регіон сховища"),
) -> None:
    """Об'єктне сховище простору — те, що прискорює передачу в рази.

    🔴 Ключі сюди не пишуться. Вони живуть у середовищі
    (`NYSHPORKA_S3_KEY` / `NYSHPORKA_S3_SECRET`) або в `keyring`: цей файл
    кладуть у git і в хмарну синхронізацію, і секрет, покладений у нього один
    раз, витікає назавжди й тихо.
    """
    from nyshporka.cloud.ssh import update_config
    from nyshporka.cloud.transfer import load_storage

    if not bucket:
        got = load_storage()
        if got is None:
            console.print("[muted]сховище не налаштоване[/muted]")
            return
        console.print(f"{got.bucket} · {got.endpoint_url or 'типовий S3'} "
                      f"· регіон {got.region}")
        return
    row = {"bucket": bucket, "endpoint_url": endpoint, "region": region,
           "prefix": "nysh"}
    update_config(lambda data: data.__setitem__("storage", row))
    console.print(f"✅ сховище {bucket}. Ключі покладіть у середовище: "
                  f"NYSHPORKA_S3_KEY / NYSHPORKA_S3_SECRET")


# ── план ─────────────────────────────────────────────────────────────────────
def _print_plan(p: CloudPlan) -> None:
    console.print(f"[bold]{p.case_dir.name}[/bold] · {p.frames} кадрів · "
                  f"{_size(p.bytes_in)}")
    console.print(f"  письмо : {p.script}")
    console.print(f"  модель : {p.model.name}"
                  + ("".join(f" + {v.name}" for v in p.voices) or " (один голос)"))
    console.print(f"  шифра  : {p.case_key or '—'}"
                  + (f" [muted]({p.case_key_why})[/muted]" if p.case_key else ""))
    console.print(f"  вихід  : {p.out_dir}")
    if p.sizing is not None:
        s = p.sizing
        console.print(
            f"  машина : {s.cores:g} {_plural(int(s.cores), 'ядро', 'ядра', 'ядер')}"
            f" · {s.shards} {_plural(s.shards, 'процес', 'процеси', 'процесів')}"
            f" [muted](більше не дає: {s.capped_by or '—'})[/muted]")
        console.print(f"  темп   : ~{s.pages_per_hour:.0f} стор/год "
                      f"[muted](тисне: {s.limited_by})[/muted]")
        console.print(f"  час    : ~{p.hours:.1f} год"
                      + (f" · ~${p.cost:.2f}" if p.cost else ""))
    if p.channel:
        console.print(f"  канал  : {p.channel} — {p.channel_why}")
    for w in p.warnings:
        console.print(f"[warn]⚠ {w}[/warn]")


#: Що сказати, коли бекенда оренди немає в реєстрі. Оренду дає окремий пакет:
#: свій SDK, свій акаунт і своя тарифікація в ядрі не живуть.
_RENT_HINT = ("бекенда оренди немає. Його дає окремий пакет-плагін: "
              "`pip install \"nyshporka[rent]\"`, далі — "
              "`nysh cloud rent login`. Що є зараз: `nysh cloud hosts list`")


def _usd(value: float | None, digits: int = 2) -> str:
    """Гроші або чесне «невідомо». Нуль замість невідомого тут — брехня."""
    return "невідомо" if value is None else f"${value:.{digits}f}"


def _print_money(p: CloudPlan, est: object) -> None:
    """Кошторис ринку й вилка — числами бекенда, без жодного власного."""
    from nyshporka.cloud import money as M

    console.print("\n[bold]оренда[/bold]")
    if not isinstance(est, M.Estimate):
        console.print("  кошторис: [muted]невідомо — цей бекенд кошторисів не "
                      "дає. Стелю витрат назвіть самі: --budget[/muted]")
    elif est.empty:
        console.print(f"  [warn]⚠ {est.human()}[/warn]")
    else:
        console.print(f"  ринок  : {est.human()}")
        if est.usd_per_1000 is not None:
            console.print(f"  ціна   : {_usd(est.usd_per_1000)} за тисячу сторінок")
        if est.cost is not None:
            low, high = M.budget_fork(est.cost, density_known=(
                p.lines_per_page is not None and est.lines_per_page is not None))
            console.print(f"  вилка  : {_usd(low)}–{_usd(high)} "
                          f"[muted](верх — бюджет заходу; щільність письма "
                          f"невідома до першого читання)[/muted]")
    stated = [f"бюджет {_usd(p.budget_usd)}" if p.budget_usd is not None else "",
              f"до {p.max_hours:g} год" if p.max_hours is not None else "",
              f"машина до {_usd(p.max_price_usd_h, 3)}/год"
              if p.max_price_usd_h is not None else ""]
    if any(stated):
        console.print("  стелі  : " + " · ".join(s for s in stated if s))
    console.print(f"  [muted]автозапуск без людини — до "
                  f"{_usd(M.autostart_ceiling())} (nysh cloud rent ceiling)[/muted]")


@app.command("plan")
def cmd_plan(
    case_dir: str = typer.Argument(..., help="тека зі сканами (пласка)"),
    host: str = typer.Option("", "--host", "-h", help="машина: ім'я або user@host"),
    backend: str = typer.Option("ssh", "--backend", "-b",
                                 help="де читати: ssh — своя машина; інші — `nysh cloud hosts list`"),
    script: str = typer.Option("", "--script",
                                help="письмо: latin | cyrillic; порожньо — визначити самому"),
    case_key: str = typer.Option("", "--case-key", help="шифра справи для мети прогону"),
    one_voice: bool = typer.Option(False, "--one-voice",
                                   help="без другого рушія (швидше, але сліпіше)"),
    with_: list[str] = typer.Option(
        [], "--with",
        help="ще голос тим самим проходом: `latin` (Скриба) або ім'я ваг"),
    budget: float | None = typer.Option(
        None, "--budget", help="стеля витрат на захід, $ (для оренди)"),
    max_hours: float | None = typer.Option(
        None, "--max-hours", help="стеля тривалості заходу, годин"),
    max_price: float | None = typer.Option(
        None, "--max-price", help="стеля ціни машини, $/год"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що поїде на машину — без жодних витрат і без оренди.

    Той самий поділ, що `nysh read --dry-run`: дізнатись «модель не та» або
    «кадрів три тисячі» після старту означає втратити ніч, а на орендованій
    машині — ще й гроші. Для бекенда з орендою показує ще й кошторис ринку —
    🔴 план не орендує ніколи, з `--host` чи без.
    """
    from nyshporka.cloud import money as M
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud.base import bills

    try:
        p = PL.build(case_dir, backend=backend, target=host, script=script,
                     case_key=case_key, second_voice=not one_voice, also=with_,
                     budget_usd=budget, max_hours=max_hours,
                     max_price_usd_h=max_price)
    except PL.PlanError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    known_host = True
    rents = False
    estimate: M.Estimate | None = None
    if host or backend != "ssh":
        from nyshporka.cloud.run import _backend

        try:
            b = _backend(backend)
            rents = bills(b)
            if rents:
                # 🔴 `acquire` у бекенда з орендою — це й Є оренда. Доти план із
                # `--host` кликав його заради опису заліза, тобто «безплатна»
                # команда брала б машину. Кошторис — окремим необов'язковим
                # методом, який нічого не бере.
                estimate = M.ask_estimate(b, p.need)
            elif host:
                p = PL.with_box(p, b.acquire(p.need, target=host))
        except Exception as exc:
            known_host = False
            console.print(f"[err]🔴 {exc}[/err]")
    # 🔴 Канал називається вже тут. Дізнатись, що заливка триватиме дев'ять
    # годин, після того як почалась оренда, — це те саме, що не дізнатись.
    # Швидкості напряму без з'єднання не заміряти, але сказати, чи є швидкий
    # шлях і чого він вартий, можна й без жодного пакета в мережі.
    from nyshporka.cloud.transfer import load_storage

    p = PL.with_channel(p, storage=load_storage(), speed=None)
    if as_json:
        data = p.as_dict()
        data["host_known"] = known_host
        data["estimate"] = estimate.as_dict() if estimate is not None else None
        console.print_json(data=data)
        return
    _print_plan(p)
    if rents:
        _print_money(p, estimate)
        console.print(f"\n[muted]сухий прогін із рішенням: nysh cloud go "
                      f"{case_dir} --backend {backend} --dry-run[/muted]")
        return
    # 🔴 Не радимо запуск на машині, якої немає. Порада, яка не спрацює,
    # гірша за її відсутність: людина виконає її, дістане ту саму відмову й
    # шукатиме причину в справі, а не в переліку машин.
    if not known_host:
        if backend != "ssh":
            console.print(f"\n[warn]⚠ {escape(_RENT_HINT)}[/warn]")
            return
        console.print("\n[warn]⚠ план порахований без машини. Спершу додайте "
                      "її: nysh cloud hosts add <ім'я> <user@host>[/warn]")
        return
    console.print(f"\n[muted]запустити: nysh cloud start {case_dir}"
                  + (f" --host {host}" if host else "") + "[/muted]")


# ── машина ───────────────────────────────────────────────────────────────────
@app.command("prepare")
def cmd_prepare(
    host: str = typer.Argument(..., help="машина: ім'я або user@host"),
    backend: str = typer.Option("ssh", "--backend", "-b",
                                 help="де читати: ssh — своя машина; інші — `nysh cloud hosts list`"),
) -> None:
    """Зібрати середовище рушіїв на машині. Робиться один раз на машину.

    Довга команда: ставиться рушій сегментації, torch і колесо під карту.
    Повторний виклик безпечний — наявне не чіпається.
    """
    from nyshporka.cloud.base import Need, bills
    from nyshporka.cloud.probe import measure
    from nyshporka.cloud.run import _backend, prepare

    b = _backend(backend)
    if bills(b):
        # 🔴 `acquire` на орендному бекенді — це ОРЕНДА, і гасити її тут нічим:
        # команда закінчується, а лічильник іде. Але й сенсу в ній немає:
        # орендована машина щоразу нова, тож готувати її наперед означає
        # платити за середовище, яке зникне разом із нею. Усередині заходу це
        # робиться саме собою.
        console.print(
            f"[err]«{backend}» орендує машини, а `prepare` готує ТУ, що вже є. "
            f"Орендована машина щоразу нова: середовище на ній ставиться "
            f"всередині заходу, і платити за нього окремо нема за що.[/err]")
        console.print("[muted]прочитати справу: nysh cloud go <тека> "
                      f"--backend {backend}[/muted]")
        raise typer.Exit(code=2)
    box = b.acquire(Need(pages=0), target=host)
    session = b.connect(box)
    try:
        probe = measure(session)
        console.print(f"машина: {probe.human()}")
        state = prepare(session, f"{_workdir_of(box)}/_prepare",
                        on_line=lambda s: console.print(f"[muted]  {s}[/muted]"))
    finally:
        session.close()
    if state.ready:
        console.print(f"✅ середовище готове: {state.detail}")
    else:
        console.print(f"[err]🔴 не вийшло: {state.detail}[/err]")
        raise typer.Exit(code=1)


def _workdir_of(box: Box) -> str:
    raw = box.meta.get("host") if isinstance(box.meta, dict) else None
    if isinstance(raw, dict) and raw.get("workdir"):
        return str(raw["workdir"]).rstrip("/")
    return "~/nysh-run"


# ── захід ────────────────────────────────────────────────────────────────────
@app.command("start")
def cmd_start(
    case_dir: str = typer.Argument(..., help="тека зі сканами (пласка)"),
    host: str = typer.Option("", "--host", "-h", help="машина: ім'я або user@host"),
    backend: str = typer.Option("ssh", "--backend", "-b",
                                 help="де читати: ssh — своя машина; інші — `nysh cloud hosts list`"),
    script: str = typer.Option("", "--script",
                                help="письмо: latin | cyrillic; порожньо — визначити самому"),
    case_key: str = typer.Option("", "--case-key", help="шифра справи для мети прогону"),
    one_voice: bool = typer.Option(False, "--one-voice",
                                   help="без другого рушія (швидше, але сліпіше)"),
    with_: list[str] = typer.Option(
        [], "--with",
        help="ще голос тим самим проходом: `latin` (Скриба) або ім'я ваг"),
    shards: int = typer.Option(0, "--shards", help="скільки процесів; 0 = порахувати"),
    seg_height: int = typer.Option(0, "--seg-height",
                                    help="висота сегментації (0 = рідна 1800)"),
    budget: float | None = typer.Option(
        None, "--budget", help="стеля витрат на захід, $ (для оренди)"),
    max_hours: float | None = typer.Option(
        None, "--max-hours", help="стеля тривалості заходу, годин"),
    max_price: float | None = typer.Option(
        None, "--max-price", help="стеля ціни машини, $/год"),
    wait: bool = typer.Option(False, "--wait", help="чекати завершення"),
) -> None:
    """Почати захід. Повертається одразу — робота лишається жити на машині.

    🔴 Повторний виклик на живому заході не бере другої машини, а підхоплює
    свою. Тому після обриву зв'язку правильна дія — просто повторити команду.
    """
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud import run as RUN

    try:
        p = PL.build(case_dir, backend=backend, target=host, script=script,
                     case_key=case_key, second_voice=not one_voice, also=with_,
                     budget_usd=budget, max_hours=max_hours,
                     max_price_usd_h=max_price)
    except PL.PlanError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    try:
        st = RUN.start(p, workers=shards, seg_height=seg_height, on_line=_say)
    except CloudError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    console.print(f"\nзахід [bold]{st.run_id}[/bold] · {st.human_phase()}")
    console.print(f"[muted]стежити: nysh cloud state {st.run_id}[/muted]")
    if wait:
        RUN.wait(st, on_pulse=lambda pl: console.print(
            f"  {pl.pages_done}/{pl.frames_total} ({pl.pct}%)"))
        console.print("[muted]забрати: nysh cloud fetch " + st.run_id + "[/muted]")


@app.command("state")
def cmd_state(
    run_id: str = typer.Argument("", help="ім'я заходу; порожньо — незавершений"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
    all_runs: bool = typer.Option(False, "--all", help="усі заходи простору"),
) -> None:
    """Що зараз із заходом. Дані беруться з диска машини, не з лога."""
    from nyshporka.cloud import run as RUN
    from nyshporka.cloud import state as ST

    if all_runs:
        rows = ST.all_runs()
        if as_json:
            console.print_json(data=[s.as_dict() for s in rows])
            return
        if not rows:
            console.print("[muted]жодного заходу ще не було. Почати: "
                          "nysh cloud plan <тека> --host <машина>[/muted]")
            return
        for s in rows:
            mark = "🔴" if s.needs_release else ("✅" if s.verdict == "ok" else "·")
            # 🔴 У відчепленого заходу наша фаза заморожена на хвилині, коли ми
            # від нього відійшли, — показувати її означало б упевнено назвати
            # «читає» те, що годину як скінчилось. Правду про нього знає
            # наглядач, і питають його окремою командою на один захід.
            where = (f"веде наглядач {s.supervisor}" if s.supervisor
                     else s.human_phase())
            console.print(f"{mark} {s.run_id} · {where} · "
                          f"{s.pages_done}/{s.frames_total}"
                          + (" · машина жива" if s.needs_release else ""))
        return

    st = _need_run(run_id)
    if st.supervisor:
        _state_detached(st, as_json=as_json)
        return
    pulse = None
    if st.phase in ("running", "uploading") and st.box:
        try:
            pulse = RUN.poll(st)
            st.pages_done = pulse.pages_done
            ST.save(st)
        except CloudError as exc:
            console.print(f"[warn]⚠ машина не відповідає: {exc}[/warn]")
    if as_json:
        data = st.as_dict()
        data["pulse"] = (
            {"alive": pulse.alive, "finished": pulse.finished,
             "pages_done": pulse.pages_done, "pct": pulse.pct, "rc": pulse.rc}
            if pulse else None)
        console.print_json(data=data)
        return
    console.print(f"[bold]{st.run_id}[/bold] · {st.human_phase()}"
                  + (f" · {st.verdict}" if st.verdict else ""))
    console.print(f"  справа : {st.case_dir}")
    console.print(f"  машина : {st.box.get('label') or st.box.get('id') or '—'}"
                  + (" [err](жива, не звільнена)[/err]" if st.needs_release else ""))
    if pulse:
        console.print(f"  поступ : {pulse.pages_done}/{pulse.frames_total} "
                      f"({pulse.pct}%)"
                      + (" · робота йде" if pulse.alive else
                         " · процесу немає"))
        if pulse.finished:
            console.print(f"  вийшло : rc={pulse.rc}"
                          + " [muted](код повернення повноти не доводить — "
                            "звірка окремо)[/muted]")
    for inc in st.incidents[-5:]:
        console.print(f"  [muted]· {inc.get('kind')}: {inc.get('detail')}[/muted]")
    if st.why:
        console.print(f"  [muted]{st.why}[/muted]")


def _state_detached(st: RunState, *, as_json: bool) -> None:
    """Стан заходу, який веде відчеплений наглядач: питаємо його, не свій запис.

    🔴 Свій запис — знімок хвилини відчеплення, і він однаково каже «читає» і
    про живу роботу, і про ту, що скінчилась уночі. Наглядач знає, де машина,
    скільки витрачено й чи забрано результат; ми — ні.
    """
    from nyshporka.cloud import supervised as SUP

    data = SUP.state_of(st)
    if data and SUP.finished(data):
        # Наглядач доповів підсумок — запис заходу оновлюємо зараз, а не
        # лишаємо назавжди на хвилині, коли ми від нього відчепились.
        st = SUP.absorb(st, data)
    if as_json:
        out = st.as_dict()
        out["supervisor_state"] = data or None
        console.print_json(data=out)
        raise typer.Exit(code=0 if data else 1)
    console.print(f"[bold]{st.run_id}[/bold] · наглядач {st.supervisor}")
    console.print(f"  справа : {st.case_dir}")
    if not data:
        console.print("[warn]⚠ наглядач не відповідає: стану немає. Він міг "
                      "завершитись або впасти до того, як завів журнал[/warn]")
        console.print(f"[muted]  перевірити руками: gpurunner htr state "
                      f"--session {st.supervisor}[/muted]")
        raise typer.Exit(code=1)
    budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    box = data.get("box") if isinstance(data.get("box"), dict) else {}
    console.print(f"  фаза   : {data.get('phase') or '?'}"
                  + (f" · {data.get('verdict')}" if data.get("verdict") else ""))
    if data.get("why"):
        console.print(f"  [muted]{escape(str(data['why']))}[/muted]")
    for case in data.get("cases") or []:
        if not isinstance(case, dict):
            continue
        done, want = case.get("pages_done") or 0, case.get("n_pages_expected") or 0
        pph = _num(case.get("pages_per_hour")) or 0
        console.print(f"  сторінок: {done} з {want}"
                      + (f" · ~{pph:.0f} стор/год" if pph else "")
                      + (f" · {case.get('status')}" if case.get("status") else ""))
    if box:
        console.print(f"  машина : {box.get('gpu') or '?'} "
                      f"{box.get('label') or box.get('id') or ''}".rstrip())
    if budget:
        console.print(f"  гроші  : {_usd(_num(budget.get('spent_usd')))} з "
                      f"{_usd(_num(budget.get('cap_usd')))} · "
                      f"{_num(budget.get('elapsed_h')) or 0:.2f} з "
                      f"{_num(budget.get('max_hours')) or 0:g} год")
    console.print(f"  вихід  : {st.out_dir}")
    if data.get("human_action_required"):
        # 🔴 Наглядач працює сам, і єдиний стан, у якому він чогось чекає від
        # людини, мусить бути видно одразу — інакше машина тарифікується, поки
        # прохання лежить у журналі.
        console.print(f"[err]🔴 потрібна людина: "
                      f"{escape(str(data.get('human_action') or '—'))}[/err]")


def _num(value: object) -> float | None:
    from nyshporka.cloud.money import as_number

    return as_number(value)


def _detached_only(st: RunState, what: str) -> None:
    """Відмовити командам, які в відчепленому заході нічого не означають.

    🔴 Не косметика. `verify` без наглядача записав би вирок `incomplete` живому
    заходу — а вирок ставить фазу `failed`, після чого ні перелік живих, ні
    пошук чужого заходу його вже не бачать, і наступний `go` спокійно бере
    ДРУГУ машину під ту саму справу. `fetch` так само: забирати нема звідки,
    бо машини в нашому записі немає.
    """
    if not st.supervisor:
        return
    console.print(
        f"[err]{escape(what)} тут нічого не дасть: захід веде наглядач "
        f"{st.supervisor}, і машина в нього, а не в нас. Забір, звірку й "
        f"гасіння він робить сам.[/err]")
    console.print(f"[muted]як справи: nysh cloud state {st.run_id} · "
                  f"згорнути: nysh cloud stop {st.run_id}[/muted]")
    raise typer.Exit(code=2)


def _stop_detached(st: RunState, *, force: bool) -> None:
    """Згорнути відчеплений захід — і сказати правду про машину.

    🔴 Типово ми просимо зупинити РОБОТУ, а не вбиваємо наглядача: побачивши,
    що робота скінчилась, він забирає прочитане, звіряє повноту й гасить
    оренду. Убити його — означає лишити машину горіти без нікого, хто її
    погасить: гасити її нам нічим, бо в нашому записі її немає.
    """
    from nyshporka.cloud import supervised as SUP

    if st.siblings:
        # 🔴 Наглядач і машина в партії одні на всіх. Не сказавши цього, ми
        # дали б людині погасити роботу, про яку вона зараз не думає.
        console.print(f"[warn]⚠ цей захід везе ще {len(st.siblings)} "
                      f"{_plural(len(st.siblings), 'справу', 'справи', 'справ')}: "
                      f"{escape(', '.join(st.siblings))}. Наглядач один на всю "
                      f"чергу, тож згортається ВЕСЬ захід[/warn]",
                      highlight=False)
    res = SUP.stop(st, force=force)
    if res.ok and not res.killed:
        console.print(f"✅ {st.run_id}: наглядач {st.supervisor} згортає захід "
                      f"— забере прочитане, звірить і погасить машину сам")
        console.print(f"[muted]стежити: nysh cloud state {st.run_id}[/muted]")
    elif res.ok:
        console.print(f"[warn]⚠ наглядача {st.supervisor} вбито (--force). "
                      f"МАШИНУ НІКОМУ ГАСИТИ: забору й звірки не було, "
                      f"прочитане лишилось на ній[/warn]")
    else:
        console.print(f"[err]наглядача {st.supervisor} спинити не вдалось[/err]")
    if res.said:
        console.print(f"[muted]{escape(res.said)}[/muted]", highlight=False)
    if res.killed or not res.ok:
        # 🔴 Єдине, що стоїть між живою машиною й рахунком, — людина. Мовчання
        # тут коштує стільки, скільки машина горітиме до свого таймера.
        machine = f" (інстанс {res.machine})" if res.machine else ""
        console.print(f"[err]🔴 машина могла лишитись живою{escape(machine)}. "
                      f"Перевірте ПРОСТО ЗАРАЗ: `nysh cloud rent status` — він "
                      f"питає провайдера напряму й бачить навіть те, про що ми "
                      f"не знаємо; погасити можна там-таки в кабінеті[/err]")
    raise typer.Exit(code=0 if res.ok else 2)


@app.command("fetch")
def cmd_fetch(run_id: str = typer.Argument(
        "", help="ім'я заходу; порожньо — незавершений")) -> None:
    """Забрати результат. Повторний виклик безпечний і докачує."""
    from nyshporka.cloud import run as RUN

    st = _need_run(run_id)
    _detached_only(st, "забір")
    try:
        out = RUN.fetch(st, on_line=_say)
    except CloudError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    console.print(f"✅ у {out}")
    console.print(f"[muted]тепер звірка: nysh cloud verify {st.run_id}[/muted]")


@app.command("verify")
def cmd_verify(
    run_id: str = typer.Argument("", help="ім'я заходу; порожньо — незавершений"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Скільки сторінок дійсно прочитано — і чим це доведено.

    🔴 Приймач — диск, а не код повернення прогону: є клас відмов, за якого
    лог обривається, перелік збоїв порожній, а прогін виглядає успішним.
    """
    from nyshporka.cloud import verify as V

    st = _need_run(run_id)
    _detached_only(st, "звірка")
    st.enter("verifying")
    got = V.verify(st.out_dir, case_dir=st.case_dir,
                   expected_hint=st.frames_total)
    st.pages_done = got.got
    st.settle("ok" if got.complete else "incomplete", why=got.detail)
    if as_json:
        console.print_json(data=got.as_dict())
        # 🔴 Той самий вирок, що й людині. Поки вихід стояв лише в кінці
        # людської гілки, машинний читач діставав на неповному прогоні код 0 —
        # тобто «успіх» там, де людина читає «машину ще не гасіть», і оренда
        # гасилась на недороблену роботу.
        raise typer.Exit(code=0 if got.complete else 4)
    console.print(got.human())
    if got.detail:
        console.print(f"  [muted]{got.detail}[/muted]")
    if got.complete:
        console.print(f"[muted]можна відпускати машину: "
                      f"nysh cloud stop {st.run_id}[/muted]")
        return
    if V.tail_is_small(got):
        console.print("[warn]⚠ хвіст малий — доганяти його вдома дешевше: "
                      "холодний старт чужої машини коштує близько восьми "
                      "хвилин незалежно від обсягу[/warn]")
        console.print(f"[muted]  nysh read {st.case_dir}[/muted]")
    else:
        console.print("[warn]⚠ машину ще не гасіть: недороблене лежить "
                      "на ній[/warn]")
    raise typer.Exit(code=4)


@app.command("stop")
def cmd_stop(
    run_id: str = typer.Argument("", help="ім'я заходу; порожньо — незавершений"),
    force: bool = typer.Option(False, "--force",
                               help="кинути захід, не звіряючи"),
) -> None:
    """Зупинити роботу й відпустити машину.

    🔴 Відмовляє, поки роботу не звірено. Забрати й погасити виглядає як одна
    дія, але між ними лежить єдина точка, у якій ще можна врятувати роботу.
    """
    from nyshporka.cloud import run as RUN

    st = _need_run(run_id)
    if st.supervisor:
        _stop_detached(st, force=force)
        return
    try:
        RUN.release(st, force=force, on_line=_say)
    except CloudError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    console.print(f"✅ {st.run_id} закрито")


# ── захід однією командою ────────────────────────────────────────────────────
@app.command("go")
def cmd_go(
    case: list[str] = typer.Argument(
        ..., help="справа або кілька: теки кадрів чи шифри з бібліотеки. Кілька "
                  "справ їдуть ОДНІЄЮ чергою на одну машину"),
    backend: str = typer.Option("vast", "--backend", "-b",
                                 help="бекенд оренди; які є — `nysh cloud hosts list`"),
    budget: float | None = typer.Option(
        None, "--budget", help="стеля витрат, $; без неї — верх вилки кошторису"),
    max_hours: float | None = typer.Option(
        None, "--max-hours", help="стеля тривалості, годин; без неї — утричі від прогнозу"),
    max_price: float | None = typer.Option(
        None, "--max-price", help="стеля ціни машини, $/год"),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="дозвіл ЛЮДИНИ на захід понад стелю автозапуску"),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="усе, крім оренди: кадри, стискання, план, кошторис, рішення"),
    rerun: bool = typer.Option(
        False, "--rerun",
        help="справу вже прочитано цією моделлю — перечитати. ⚠ У хмарі це "
             "знімає НАШУ відмову, але машина однаково підніме точки "
             "відновлення того самого прогону, якщо вони лишились у сховищі: "
             "ключ точок несе модель, тож начисто перечитує інша МОДЕЛЬ "
             "(`--model`)"),
    allow_partial: bool = typer.Option(
        False, "--allow-partial",
        help="кадрів менше, ніж знає бібліотека, або тека ще пишеться — однаково їхати"),
    rotate_landscape: bool = typer.Option(
        False, "--rotate-landscape",
        help="при стисканні повернути кадри, де ширина більша за висоту, на 90° "
             "за годинниковою (зйомка з книгою на боці; НЕ для розворотів)"),
    script: str = typer.Option("", "--script",
                                help="письмо: latin | cyrillic; порожньо — визначити самому"),
    model: str = typer.Option(
        "", "--model",
        help="перечитати справу ІНШОЮ моделлю (файл або ім'я ваг): письмо від "
             "моделі, вихід `<справа>-<тег>`, готова сегментація першого "
             "прогону їде на машину — сторінка коштує лише розпізнавання"),
    with_: list[str] = typer.Option(
        [], "--with",
        help="ще голос тим самим проходом: `latin` (Скриба) або ім'я ваг"),
    one_voice: bool = typer.Option(False, "--one-voice",
                                   help="без другого рушія (швидше, але сліпіше)"),
    case_key: str = typer.Option("", "--case-key", help="шифра справи для мети прогону"),
    transport: str = typer.Option(
        "auto", "--transport",
        help="чим везти дані на машину: `auto` — об'єктним сховищем, якщо воно "
             "налаштоване, інакше на саму машину; `box` — завжди на машину "
             "(сховища не потрібно); `store` — лише сховищем"),
    max_usd_per_1000: float = typer.Option(
        0.0, "--max-usd-per-1000",
        help="скільки ви згодні платити за тисячу сторінок, $ (0 = типове "
             "значення провайдера). Щільний аркуш — сповідний розпис, клірова "
             "відомість — читається вдвічі довше за метрику, і на типовому "
             "порозі захід виглядає як «машин немає»: беріть 0.30-0.35"),
    thin: bool = typer.Option(
        False, "--thin",
        help="вести захід самому, не віддаючи наглядачеві: команда триматиме "
             "з'єднання з орендованою машиною до кінця прогону й помре разом "
             "із терміналом. Для дрібної справи; своя машина по SSH — це не "
             "`go`, а `nysh cloud start`"),
    param: list[str] = typer.Option(
        [], "-p", "--param",
        help="параметр роботи для машини, `ключ=значення` (напр. "
             "`shards=6`, `max_endpoints=600`). Наш обчислений параметр "
             "ваш перекриває"),
    tick: float = typer.Option(60.0, "--tick", help="як часто питати машину, секунд"),
    as_json: bool = typer.Option(
        False, "--json", help="останнім рядком — один JSON-об'єкт із підсумком"),
) -> None:
    """Прочитати справу на орендованій машині — від кадрів до погашеної оренди.

    Звіряє кадри, стискає завеликі, збирає ваги й раннер в архів, складає план,
    рахує кошторис вилкою й вирішує, чи можна стартувати без людини. Далі захід
    веде ВІДЧЕПЛЕНИЙ наглядач: орендує машину, регулює флот під заміряний темп,
    доганяє пропуски, забирає результат, звіряє повноту по диску, гасить оренду
    й оновлює облік — уже без цієї команди, тож термінал можна закрити одразу.
    Питати про нього — `nysh cloud state`, спиняти — `nysh cloud stop`.

    `--thin` веде захід самотужки, з'єднанням із машиною: воно живе рівно
    стільки, скільки живий термінал, зате не потребує наглядача.

    Після обриву термінала правильна дія — повторити ту саму команду: живий
    захід буде підхоплено, другої машини не візьмуть.

    Коди виходу: 0 готово (або пущено відчеплено) · 2 відмова до оренди ·
    3 збій · 4 неповно · 5 стеля грошей · 6 ринок порожній · 7 стеля годин ·
    8 бракує балансу · 9 машину НЕ погашено · 10 потрібен --confirm ·
    130 перервано.
    """
    import json as _json

    from nyshporka.cloud import go as GO

    def on_event(kind: str, text: str, **_data: object) -> None:
        # Поступ — рядками для людини; у режимі `--json` вони йдуть так само, а
        # машинний читач бере ОСТАННІЙ рядок.
        # `escape`: у тексті подій бувають шляхи й `pip install "пакет[extra]"`,
        # а rich читає квадратні дужки як розмітку й мовчки їх з'їдає.
        style = {"warning": "warn", "failed": "err", "ceiling": "warn"}.get(kind)
        safe = escape(text)
        console.print(f"[{style}]{safe}[/{style}]" if style else safe,
                      highlight=False)

    # 🔴 Форму параметра перевіряємо ТУТ, а не мовчки віддаємо машині: наглядач
    # відкидає елемент без «=» без жодного слова, і людина дізнавалась би про
    # помилку з того, що ручка «не подіяла» — після оренди.
    if bad := [item for item in param if "=" not in item or not item.split("=", 1)[0].strip()]:
        console.print(f"[err]параметр мусить бути `ключ=значення`: "
                      f"{escape(', '.join(bad))}[/err]")
        raise typer.Exit(code=2)

    res = GO.go(case, backend=backend, budget=budget, max_hours=max_hours,
                max_price=max_price, confirm=confirm, dry_run=dry_run,
                with_voices=with_, second_voice=not one_voice, script=script,
                model=model,
                case_key=case_key, rerun=rerun, allow_partial=allow_partial,
                rotate_landscape=rotate_landscape, thin=thin,
                transport={"store": "r2"}.get(transport, transport),
                max_usd_per_1000=max_usd_per_1000, params=param,
                on_event=on_event,
                tick_sec=max(1.0, tick))
    if as_json:
        # `print`, а не rich: один рядок без переносів і розфарбування — його
        # розбирають `json.loads` від останнього рядка виводу.
        print(_json.dumps(res.as_dict(), ensure_ascii=False))
        raise typer.Exit(code=res.exit_code)
    mark = {"ok": "✅", "dry_run": "·", "detached": "▶"}.get(res.verdict, "🔴")
    console.print(f"\n{mark} [bold]{res.verdict}[/bold]"
                  + (f" — {escape(res.why)}" if res.why else ""), highlight=False)
    if res.verdict == "detached":
        # Тут «витрачено» ще не існує: наглядач тільки пішов по машину. Замість
        # нулів, які читаються як «безплатно», — чим питати й чим спиняти.
        console.print(f"  сторінок : {res.pages_total}")
        console.print(f"  бюджет   : {_usd(res.budget_usd)} · стеля часу "
                      f"{res.max_hours:g} год" if res.max_hours else "")
        if len(res.cases) > 1:
            # 🔴 Черга друкується поіменно. Одного рядка «вихід» на партію не
            # буває: справи лягають у різні теки, і людина мусить бачити, за що
            # саме вона зараз заплатить.
            console.print(f"  черга    : {len(res.cases)} "
                          f"{_plural(len(res.cases), 'справа', 'справи', 'справ')}")
            for c in res.cases:
                console.print(f"    · {c.pages_total:>5} стор · {c.out_dir}")
            console.print(f"[muted]стан: nysh cloud state {res.cases[0].run_id} · "
                          f"спинити (ВСЮ чергу): nysh cloud stop "
                          f"{res.cases[0].run_id}[/muted]")
        else:
            console.print(f"  вихід    : {res.out_dir}")
            console.print(f"[muted]стан: nysh cloud state {res.run_id} · "
                          f"спинити: nysh cloud stop {res.run_id}[/muted]")
        for note in res.notes:
            console.print(f"[warn]⚠ {escape(note)}[/warn]", highlight=False)
        raise typer.Exit(code=res.exit_code)
    if res.rented:
        console.print(f"  сторінок : {res.pages_done} з {res.pages_total}")
        console.print(f"  витрачено: {_usd(res.spent_usd)} за {res.rent_hours:.2f} год")
        console.print("  машина   : " + ("погашена" if res.released
                                          else "[err]НЕ ПОГАШЕНА[/err]"))
    if res.out_dir and res.verdict != "dry_run":
        console.print(f"  вихід    : {res.out_dir}")
    for note in res.notes:
        console.print(f"[warn]⚠ {escape(note)}[/warn]", highlight=False)
    if res.verdict == "needs_confirm":
        console.print("[muted]дозволити цей захід: та сама команда з --confirm; "
                      "підняти стелю назавжди: nysh cloud rent ceiling[/muted]")
    if res.verdict in ("budget_stop", "deadline", "incomplete"):
        console.print("[muted]прочитане збережено; повторна команда дочитає "
                      "решту — готове поїде на машину й не читатиметься вдруге[/muted]")
    raise typer.Exit(code=res.exit_code)


# ── оренда ───────────────────────────────────────────────────────────────────
def _rent_backend(name: str) -> object:
    """Бекенд з орендою за іменем — або чесна підказка, як його поставити."""
    from nyshporka.cloud import registry as REG
    from nyshporka.cloud.base import bills

    reg = REG.load()
    got = reg.get(name)
    if got is None:
        console.print(f"[err]немає бекенда «{name}»: {escape(_RENT_HINT)}[/err]")
        for bad, why in reg.broken:
            console.print(f"[err]  🔴 {bad} — не завантажився: {why}[/err]")
        raise typer.Exit(code=1)
    if not bills(got):
        console.print(f"[err]«{name}» нічого не орендує — ключ і баланс йому "
                      f"не потрібні[/err]")
        raise typer.Exit(code=1)
    return got


@rent_app.command("status")
def rent_status(
    backend: str = typer.Option("vast", "--backend", "-b", help="бекенд оренди"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Ключ, баланс і 🔴 що ЗАРАЗ тарифікується на акаунті.

    Головний запобіжник грошей: машина, про яку забули, коштує більше за всі
    прочитані справи разом. Перелік береться в провайдера, а не з нашого
    стану, — саме тому він бачить і те, чого Нишпорка не орендувала.

    Коди виходу: 0 чисто · 1 увійти не можна · 3 щось тарифікується поза
    заходами цього простору, або спитати про це не вдалось.
    """
    b = _rent_backend(backend)
    fn = getattr(b, "status", None)
    if not callable(fn):
        console.print(f"[warn]⚠ бекенд «{backend}» не вміє звітувати про акаунт "
                      f"(немає `status`). Що тарифікується — дивіться в кабінеті "
                      f"провайдера.[/warn]")
        raise typer.Exit(code=1)
    try:
        raw = fn()
    except CloudError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    view = _account(raw if isinstance(raw, dict) else {})
    if as_json:
        console.print_json(data={"backend": backend, **view.as_dict()})
        raise typer.Exit(code=view.exit_code)
    console.print(f"[bold]{backend}[/bold]")
    _print_account(view)
    raise typer.Exit(code=view.exit_code)


class _Account:
    """Відповідь `status()` бекенда оренди — розібрана, без жодної домислу.

    🔴 `burning` має ТРИ стани, і зводити їх до двох не можна: перелік машин,
    порожній перелік («нічого не горить») і `None` («спитати не вдалось»).
    Показане як «нічого» невдале питання — це рівно та відповідь, після якої
    забута машина тарифікується тиждень.
    """

    def __init__(self, data: dict[str, object]) -> None:
        from nyshporka.cloud import money as M
        from nyshporka.cloud import state as ST

        self.api_key: bool | None = (bool(data["api_key"])
                                     if "api_key" in data else None)
        self.ssh_key = str(data.get("ssh_key") or "")
        self.balance = M.as_number(data.get("balance_usd"))
        raw_problems = data.get("problems")
        self.problems = ([str(p) for p in raw_problems if str(p).strip()]
                         if isinstance(raw_problems, list) else [])
        self.ready: bool | None = bool(data["ready"]) if "ready" in data else None
        self.ceiling = M.autostart_ceiling()
        burning = data.get("burning")
        self.burning_known = isinstance(burning, list)
        # Чиї це машини: звіряємо з власними живими заходами. Чужа — не помилка
        # (людина могла орендувати щось сама), але сказати про неї треба вголос.
        #
        # 🔴 Відчеплений захід машини в нашому записі НЕ має — її бере й тримає
        # наглядач. Доти кожна така машина виглядала «не з заходів цього
        # простору», тобто власний живий захід звітував як чужа забута оренда:
        # найгірша з можливих неправд у команді, яку читають саме для того, щоб
        # вирішити, що гасити. Тому для них питаємо наглядача — він знає, який
        # інстанс узяв.
        ours = {str(s.box.get("id")): s.run_id for s in ST.live() if s.box}
        for st in ST.all_runs():
            if not st.supervisor or st.phase in ("done", "failed"):
                continue
            from nyshporka.cloud import supervised as SUP

            box = SUP.state_of(st).get("box")
            iid = str((box or {}).get("instance_id") or "") if isinstance(box, dict) else ""
            if iid:
                ours.setdefault(iid, st.run_id)
        self.rows: list[dict[str, object]] = []
        for r in (burning if isinstance(burning, list) else []):
            if not isinstance(r, dict):
                continue
            iid = str(r.get("instance_id") or "")
            self.rows.append({
                "instance_id": iid, "label": str(r.get("label") or ""),
                "gpu_name": str(r.get("gpu_name") or ""),
                "status": str(r.get("status") or ""),
                "price_usd_h": M.as_number(r.get("dph_total")),
                "run_id": ours.get(iid, "")})

    @property
    def exit_code(self) -> int:
        """0 — чисто; 1 — увійти не можна (ключ, проблеми); 3 — щось
        тарифікується ПОЗА заходами цього простору або спитати не вдалось.

        Трійка — для агента, який питає «чи не горить щось забуте»: на це
        питання «не знаю» не може виглядати як «ні».
        """
        if self.api_key is False or self.problems:
            return 1
        if not self.burning_known or any(not r["run_id"] for r in self.rows):
            return 3
        return 0

    def as_dict(self) -> dict[str, object]:
        return {"ready": self.ready, "problems": self.problems,
                "api_key": self.api_key, "ssh_key": self.ssh_key or None,
                "balance_usd": self.balance,
                "autostart_max_usd": self.ceiling,
                "burning": self.rows if self.burning_known else None}


def _account(data: dict[str, object]) -> _Account:
    return _Account(data)


def _print_account(view: _Account) -> None:
    key = {True: "✅ є", False: "[err]🔴 немає — nysh cloud rent login[/err]",
           None: "невідомо"}[view.api_key]
    console.print(f"  ключ API : {key}")
    # Відсутній SSH-ключ — не проблема: пару згенерує перша оренда.
    console.print(f"  ключ SSH : {view.ssh_key or 'ще немає — зʼявиться з першою орендою'}",
                  highlight=False)
    console.print(f"  баланс   : {_usd(view.balance)}")
    console.print(f"  автозапуск без людини — до {_usd(view.ceiling)}")
    for p in view.problems:
        console.print(f"  [err]🔴 {p}[/err]", highlight=False)
    if not view.burning_known:
        console.print("  [warn]⚠ що тарифікується — НЕВІДОМО: спитати в провайдера "
                      "не вдалось. Це не «нічого»: повторіть або звірте в його "
                      "кабінеті.[/warn]")
    elif not view.rows:
        console.print("  тарифікується: нічого ✅")
    else:
        prices = [r["price_usd_h"] for r in view.rows]
        known = [p for p in prices if isinstance(p, float)]
        total = (f"разом {_usd(sum(known), 3)}/год"
                 if len(known) == len(prices) else "сума невідома")
        console.print(f"  [err]🔴 тарифікується зараз: {len(view.rows)} · {total}[/err]")
        for r in view.rows:
            whose = (f"захід {r['run_id']}" if r["run_id"]
                     else "[warn]НЕ з заходів цього простору[/warn]")
            price = r["price_usd_h"]
            console.print(
                f"    {r['instance_id']} {r['label']} {r['gpu_name']} · "
                f"{_usd(price if isinstance(price, float) else None, 3)}/год · "
                f"{r['status'] or 'стан невідомий'} · {whose}", highlight=False)


#: Звідки взяти ключ, якщо його не дали прапорцем. Загальне ім'я — перше; друге
#: складається з імені бекенда (`VAST_API_KEY`), бо саме так його вже тримають
#: ті, хто користувався провайдером раніше.
ENV_RENT_KEY = "NYSHPORKA_RENT_KEY"


@rent_app.command("login")
def rent_login(
    backend: str = typer.Option("vast", "--backend", "-b", help="бекенд оренди"),
    key: str = typer.Option(
        "", "--key",
        help="ключ API провайдера. ⚠ З прапорця він лишається в історії "
             "оболонки — без прапорця ключ питається прихованим запитом"),
) -> None:
    """Віддати ключ API провайдера бекенду оренди.

    🔴 Нишпорка ключа не зберігає й не друкує: він іде в `login` бекенда, і де
    лежати — вирішує той (зазвичай там само, де його тримає власний клієнт
    провайдера). У просторі дослідження ключа немає й не буде: простір кладуть
    у git і в хмарну синхронізацію.
    """
    import os

    b = _rent_backend(backend)
    fn = getattr(b, "login", None)
    if not callable(fn):
        console.print(f"[err]бекенд «{backend}» не приймає ключ командою (немає "
                      f"`login`) — налаштуйте його так, як каже його документація[/err]")
        raise typer.Exit(code=1)
    secret = (key or os.environ.get(ENV_RENT_KEY, "")
              or os.environ.get(f"{backend.upper()}_API_KEY", "")).strip()
    if not secret:
        secret = str(typer.prompt(f"ключ API «{backend}»", hide_input=True)).strip()
    if not secret:
        console.print("[err]ключ порожній[/err]")
        raise typer.Exit(code=1)
    try:
        raw = fn(secret)
    except CloudError as exc:
        # 🔴 Текст чужого винятку може нести ключ (бекенди люблять цитувати
        # запит) — вирізаємо його перед друком.
        console.print(f"[err]{str(exc).replace(secret, '***')}[/err]",
                      highlight=False)
        raise typer.Exit(code=1) from None
    # `login` повертає той самий звіт, що й `status`. 🔴 Ключ, який провайдер
    # ВІДХИЛИВ, бекенд однаково зберігає — і каже про це рядком у `problems`.
    # Тож «метод не кинув» ще не означає «увійшли»: відмова читається звідти.
    view = _account(raw if isinstance(raw, dict) else {})
    view.problems = [p.replace(secret, "***") for p in view.problems]
    if view.problems or view.api_key is False:
        console.print(f"[err]🔴 увійти не вдалось — бекенд «{backend}» ключ "
                      f"зберіг, але працювати з ним не може:[/err]")
        _print_account(view)
        raise typer.Exit(code=1)
    console.print(f"✅ ключ прийнято бекендом «{backend}»")
    _print_account(view)
    console.print("[muted]далі — сухий прогін без оренди: nysh cloud go "
                  "<справа> із прапорцем сухого прогону[/muted]")


@rent_app.command("ceiling")
def rent_ceiling(
    usd: float | None = typer.Argument(
        None, help="нова стеля, $; порожньо — показати чинну"),
) -> None:
    """Стеля автозапуску: до якої суми `nysh cloud go` стартує без людини.

    Порівнюється з ВЕРХОМ вилки кошторису, а не з прогнозом: захід, який
    «мав коштувати долар», на щільному письмі коштує два з половиною.
    """
    from nyshporka.cloud import money as M

    if usd is None:
        console.print(f"стеля автозапуску: {_usd(M.autostart_ceiling())}")
        return
    try:
        got = M.set_autostart_ceiling(usd)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    console.print(f"✅ стеля автозапуску: {_usd(got)}")
