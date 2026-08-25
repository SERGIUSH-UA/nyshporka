"""CLI хмарного прогону: `nysh cloud hosts | plan | prepare | start | state |
fetch | verify | stop`.

Команди навмисно дрібні й повторювані. Захід триває годинами, і єдиний спосіб
пережити обрив, закритий ноутбук і Ctrl+C — щоб кожен крок можна було просто
викликати ще раз: `start` підхопить свою роботу, `fetch` докачає, `verify`
нічого не змінить.

🔴 Порядок `fetch → verify → stop` тут не рекомендація, а перевірка в коді:
`stop` відмовляється гасити машину, поки роботу не звірено.

🔴 Секції «Читання» ці команди НЕ вимагають — і це рішення, а не недогляд.
`nysh read` вимагає її законно: без локального рушія читати нічим. Але хмарний
прогін існує рівно для тих, у кого рушія немає й не буде — ноутбук на два ядра,
машина без карти, небажання тягнути 2.5 ГБ `torch` заради роботи, яка все одно
поїде кудись. Вимагати тут `nysh sections enable htr` означало б замкнути двері,
до яких людина прийшла. Ваги при цьому потрібні (їх і везуть) — але вони не
рушій і не важать гігабайтів.
"""
from __future__ import annotations

import typer

from nyshporka import brand
from nyshporka.cloud.base import Box, CloudError
from nyshporka.cloud.plan import CloudPlan
from nyshporka.cloud.state import RunState

app = typer.Typer(help="Прогін справи на іншій машині.", no_args_is_help=True)
hosts_app = typer.Typer(help="Машини, на яких можна читати.", no_args_is_help=True)
app.add_typer(hosts_app, name="hosts")

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
def hosts_list(as_json: bool = typer.Option(False, "--json")) -> None:
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
    python: str = typer.Option("", "--python"),
    cores: float = typer.Option(0.0, "--cores", help="заявлені ядра (для плану)"),
    vram: float = typer.Option(0.0, "--vram", help="заявлена пам'ять карти, ГБ"),
    gpus: int = typer.Option(1, "--gpus"),
) -> None:
    """Записати машину. 🔴 Ключ — ШЛЯХОМ, ніколи не вмістом і не паролем."""
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
def hosts_rm(name: str = typer.Argument(...)) -> None:
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
    region: str = typer.Option("auto", "--region"),
) -> None:
    """Об'єктне сховище простору — те, що прискорює передачу в рази.

    🔴 Ключі сюди не пишуться. Вони живуть у середовищі
    (`NYSHPORKA_S3_KEY` / `NYSHPORKA_S3_SECRET`) або в `keyring`: цей файл
    кладуть у git і в хмарну синхронізацію, і секрет, покладений у нього один
    раз, витікає назавжди й тихо.
    """
    from nyshporka.cloud.ssh import hosts_path
    from nyshporka.cloud.transfer import load_storage
    from nyshporka.utils.atomic import read_json, write_json

    if not bucket:
        got = load_storage()
        if got is None:
            console.print("[muted]сховище не налаштоване[/muted]")
            return
        console.print(f"{got.bucket} · {got.endpoint_url or 'типовий S3'} "
                      f"· регіон {got.region}")
        return
    raw = read_json(hosts_path(), default={})
    data = raw if isinstance(raw, dict) else {}
    data["storage"] = {"bucket": bucket, "endpoint_url": endpoint,
                       "region": region, "prefix": "nysh"}
    write_json(hosts_path(), data)
    console.print(f"✅ сховище {bucket}. Ключі покладіть у середовище: "
                  f"NYSHPORKA_S3_KEY / NYSHPORKA_S3_SECRET")


# ── план ─────────────────────────────────────────────────────────────────────
def _print_plan(p: CloudPlan) -> None:
    console.print(f"[bold]{p.case_dir.name}[/bold] · {p.frames} кадрів · "
                  f"{_size(p.bytes_in)}")
    console.print(f"  письмо : {p.script}")
    console.print(f"  модель : {p.model.name}"
                  + (f" + {p.voice.name}" if p.voice else " (один голос)"))
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


@app.command("plan")
def cmd_plan(
    case_dir: str = typer.Argument(..., help="тека зі сканами (ПЛАСКА)"),
    host: str = typer.Option("", "--host", "-h", help="машина: ім'я або user@host"),
    backend: str = typer.Option("ssh", "--backend", "-b"),
    script: str = typer.Option("", "--script", help="latin | cyrillic"),
    case_key: str = typer.Option("", "--case-key"),
    one_voice: bool = typer.Option(False, "--one-voice"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Що поїде на машину — БЕЗ жодної мережевої дії й без жодних витрат.

    Той самий поділ, що `nysh read --dry-run`: дізнатись «модель не та» або
    «кадрів три тисячі» після старту означає втратити ніч, а на орендованій
    машині — ще й гроші.
    """
    from nyshporka.cloud import plan as PL

    try:
        p = PL.build(case_dir, backend=backend, target=host, script=script,
                     case_key=case_key, second_voice=not one_voice)
    except PL.PlanError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    known_host = True
    if host:
        from nyshporka.cloud.run import _backend

        try:
            box = _backend(backend).acquire(p.need, target=host)
            p = PL.with_box(p, box)
        except Exception as exc:
            known_host = False
            console.print(f"[err]🔴 {exc}[/err]")
    # 🔴 Канал називається ВЖЕ ТУТ. Дізнатись, що заливка триватиме дев'ять
    # годин, після того як почалась оренда, — це те саме, що не дізнатись.
    # Швидкості напряму без з'єднання не заміряти, але сказати, чи є швидкий
    # шлях і чого він вартий, можна й без жодного пакета в мережі.
    from nyshporka.cloud.transfer import load_storage

    p = PL.with_channel(p, storage=load_storage(), speed=None)
    if as_json:
        data = p.as_dict()
        data["host_known"] = known_host
        console.print_json(data=data)
        return
    _print_plan(p)
    # 🔴 Не радимо запуск на машині, якої немає. Порада, яка не спрацює,
    # гірша за її відсутність: людина виконає її, дістане ту саму відмову й
    # шукатиме причину в справі, а не в переліку машин.
    if not known_host:
        console.print("\n[warn]⚠ план порахований без машини. Спершу додайте "
                      "її: nysh cloud hosts add <ім'я> <user@host>[/warn]")
        return
    console.print(f"\n[muted]запустити: nysh cloud start {case_dir}"
                  + (f" --host {host}" if host else "") + "[/muted]")


# ── машина ───────────────────────────────────────────────────────────────────
@app.command("prepare")
def cmd_prepare(
    host: str = typer.Argument(..., help="машина: ім'я або user@host"),
    backend: str = typer.Option("ssh", "--backend", "-b"),
) -> None:
    """Зібрати середовище рушіїв на машині. Робиться ОДИН раз на машину.

    Довга команда: ставиться рушій сегментації, torch і колесо під карту.
    Повторний виклик безпечний — наявне не чіпається.
    """
    from nyshporka.cloud.base import Need
    from nyshporka.cloud.probe import measure
    from nyshporka.cloud.run import _backend, prepare

    b = _backend(backend)
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
    case_dir: str = typer.Argument(...),
    host: str = typer.Option("", "--host", "-h"),
    backend: str = typer.Option("ssh", "--backend", "-b"),
    script: str = typer.Option("", "--script"),
    case_key: str = typer.Option("", "--case-key"),
    one_voice: bool = typer.Option(False, "--one-voice"),
    shards: int = typer.Option(0, "--shards", help="скільки процесів; 0 = порахувати"),
    seg_height: int = typer.Option(0, "--seg-height"),
    wait: bool = typer.Option(False, "--wait", help="чекати завершення"),
) -> None:
    """Почати захід. Повертається одразу — робота лишається жити на машині.

    🔴 Повторний виклик на живому заході НЕ бере другої машини, а підхоплює
    свою. Тому після обриву зв'язку правильна дія — просто повторити команду.
    """
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud import run as RUN

    try:
        p = PL.build(case_dir, backend=backend, target=host, script=script,
                     case_key=case_key, second_voice=not one_voice)
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
    as_json: bool = typer.Option(False, "--json"),
    all_runs: bool = typer.Option(False, "--all", help="усі заходи простору"),
) -> None:
    """Що зараз із заходом. Дані беруться з ДИСКА машини, не з лога."""
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
            console.print(f"{mark} {s.run_id} · {s.human_phase()} · "
                          f"{s.pages_done}/{s.frames_total}"
                          + (" · МАШИНА ЖИВА" if s.needs_release else ""))
        return

    st = _need_run(run_id)
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
                          + " [muted](код повернення повноти НЕ доводить — "
                            "звірка окремо)[/muted]")
    for inc in st.incidents[-5:]:
        console.print(f"  [muted]· {inc.get('kind')}: {inc.get('detail')}[/muted]")
    if st.why:
        console.print(f"  [muted]{st.why}[/muted]")


@app.command("fetch")
def cmd_fetch(run_id: str = typer.Argument("")) -> None:
    """Забрати результат. Повторний виклик безпечний і докачує."""
    from nyshporka.cloud import run as RUN

    st = _need_run(run_id)
    try:
        out = RUN.fetch(st, on_line=_say)
    except CloudError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    console.print(f"✅ у {out}")
    console.print(f"[muted]тепер звірка: nysh cloud verify {st.run_id}[/muted]")


@app.command("verify")
def cmd_verify(
    run_id: str = typer.Argument(""),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Скільки сторінок ДІЙСНО прочитано — і чим це доведено.

    🔴 Приймач — диск, а не код повернення прогону: є клас відмов, за якого
    лог обривається, перелік збоїв порожній, а прогін виглядає успішним.
    """
    from nyshporka.cloud import verify as V

    st = _need_run(run_id)
    st.enter("verifying")
    got = V.verify(st.out_dir, case_dir=st.case_dir,
                   expected_hint=st.frames_total)
    st.pages_done = got.got
    st.settle("ok" if got.complete else "incomplete", why=got.detail)
    if as_json:
        console.print_json(data=got.as_dict())
        return
    console.print(got.human())
    if got.detail:
        console.print(f"  [muted]{got.detail}[/muted]")
    if got.complete:
        console.print(f"[muted]можна відпускати машину: "
                      f"nysh cloud stop {st.run_id}[/muted]")
        return
    if V.tail_is_small(got):
        console.print("[warn]⚠ хвіст малий — доганяти його ВДОМА дешевше: "
                      "холодний старт чужої машини коштує близько восьми "
                      "хвилин незалежно від обсягу[/warn]")
        console.print(f"[muted]  nysh read {st.case_dir}[/muted]")
    else:
        console.print("[warn]⚠ машину ще не гасіть: недороблене лежить "
                      "на ній[/warn]")
    raise typer.Exit(code=4)


@app.command("stop")
def cmd_stop(
    run_id: str = typer.Argument(""),
    force: bool = typer.Option(False, "--force",
                               help="кинути захід, не звіряючи"),
) -> None:
    """Зупинити роботу й відпустити машину.

    🔴 Відмовляє, поки роботу не звірено. Забрати й погасити виглядає як одна
    дія, але між ними лежить єдина точка, у якій ще можна врятувати роботу.
    """
    from nyshporka.cloud import run as RUN

    st = _need_run(run_id)
    try:
        RUN.release(st, force=force, on_line=_say)
    except CloudError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    console.print(f"✅ {st.run_id} закрито")
