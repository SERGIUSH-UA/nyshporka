"""Командний рядок `nysh`.

Поки скелет: `--version` і `info`. Обидві команди навмисно не порожні —
встановлюваність пакета доводиться тим, що консольний скрипт справді
запускається у чистому середовищі, а не тим, що `import` не впав.
"""
from __future__ import annotations

import platform
import re
import sys
from pathlib import Path
from typing import Any

import typer

from nyshporka import __version__, brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

# ⚠ `core.morph` навмисно холодний (імпортує лише `dataclasses`), тож на
# час запуску консолі це не впливає — а довідка `--paradigm` мусить
# збиратись із реєстру ще до розбору аргументів.
from nyshporka.core import morph

# 🔴 Обов'язковий параметр, чиї значення видно лише з помилки валідації, —
# те саме глухе місце, що й порада на неіснуючу команду: людина набирає
# осмислене слово («метрична», як у сусідній `nysh case --type`), дістає
# відмову й не має де підглянути перелік. Тому переліки стоять у довідці.
# ⚠ Рядки дублюють `pagestore.models` — інакше `cli.py` мусив би тягнути
# pydantic-моделі на імпорті заради трьох підказок, а він навмисно тримає
# верхні імпорти порожніми. Розбіжність ловить `test_cli_choices_match_models`.
_PAGE_TYPES_HELP = ("birth | marriage | death | confession | revision | census | "
                    "index | title | cover | flyleaf | blank | illegible | mixed | other")
_PAGE_STATUS_HELP = ("full — перелік прізвищ повний · partial — бачив, перелік "
                     "неповний (типово; для blank/cover/flyleaf — full) · "
                     "skipped · unreadable")
_PAGE_METHOD_HELP = "visual | htr | ocr | hybrid | text"
_ROLES_HELP = ("child | father | mother | godfather | godmother | groom | bride | "
               "groom_father | groom_mother | bride_father | bride_mother | "
               "deceased | spouse | witness | priest | midwife | head | member | "
               "convert | sponsor | other")
_RTYPES_HELP = ("birth | marriage | death | conversion | confession_entry | "
                "revision_entry | tally | other")

app = typer.Typer(
    name="nysh",
    # Назва й лінія бренду беруться з `brand.yaml`, а не набрані тут: `--help`
    # — така сама поверхня, як шапка застосунку, і другий примірник тексту
    # розійшовся б із рештою тихо.
    help=f"{brand.active().name_uk} — {brand.active().line_uk} "
         "Читання рукописних архівних справ і пошук прізвища в них.",
    no_args_is_help=True,
    add_completion=False,
)
console = brand.console()
err_console = brand.err()


def _sync_skills() -> None:
    """Перекласти скіли, якщо облік старший за пакет. Тихо, коли робити нічого.

    🔴 Тут, а не в `nysh update`: та команда замінює саму себе
    (`uv tool install --force`), і скіли читала б із теки пакета, яку в ту мить
    саме перезаписують. Перекладає наступний запуск — уже нової збірки.

    🔴 Пише ТІЛЬКИ в теки, куди скіли вже клали руками, і ніколи не заводить
    нових: тека, яку людина не обирала, нам не належить. Правлені файли
    лишаються як є — про них скаже підсумок.
    """
    try:
        from nyshporka import __version__
        from nyshporka import skills as S

        got = S.sync(__version__)
    except Exception:
        return          # скіли — зручність, а не умова роботи
    for dest, tally in got:
        moved = tally.get("updated", 0) + tally.get("new", 0)
        kept = tally.get("kept", 0)
        if not moved and not kept:
            continue
        tail = f", лишено правлених руками: {kept}" if kept else ""
        # 🔴 У stderr. Ця замітка йде ПЕРЕД виводом будь-якої команди, а stdout
        # у `nysh op … --json` читає програма; один людський рядок попереду
        # ламав би їй розбір.
        err_console.print(f"[muted]скіли оновлено до {__version__} у {dest} "
                          f"(файлів: {moved}{tail})[/muted]")
        # 🔴 Помічник читає скіли на СТАРТІ сесії: оновлені файли вже лежать,
        # а сесія, відкрита до оновлення, працює за старою карткою й нових
        # скілів не бачить. Без цього рядка людина дізнавалась би про це
        # з того, що помічник «не знає» щойно оголошеного скіла.
        err_console.print("[muted]щоб помічник побачив нове, почніть із ним "
                          "нову сесію[/muted]")


#: Команди, перед якими скіли не чіпаються: їхній процес живе довго або
#: спілкується протоколом, і побічна робота на старті тут недоречна.
_NO_SKILL_SYNC_FOR = frozenset({"mcp", "serve"})

#: Де нагадування про міграцію агента зайве: сама міграція, створення простору.
_NO_MIGRATION_NAG_FOR = frozenset({"migrate", "init", "mcp", "serve", "version"})


def _nag_migration(sub: str) -> None:
    """Один рядок у stderr, доки простір на цій машині не пройшов міграцію агента.

    🔴 У КОЖНІЙ команді, а не лише в `workspace.info`: агент, що одразу кличе
    `nysh search`, інакше не дізнався б, що половина його звичок застаріла.
    """
    import os

    from nyshporka import migrate as M

    if sub in _NO_MIGRATION_NAG_FOR or os.environ.get(M.ENV_NO_NAG):
        return
    try:
        from nyshporka import __version__
        from nyshporka.core.workspace import workspace

        todo = M.pending(workspace().root, __version__)
    except Exception:
        return
    if todo:
        err_console.print(f"[warn]⚠ Нишпорку оновлено до {__version__}: частина порад, які "
                          f"знає помічник, застаріла — nysh migrate[/warn]")


@app.callback()
def _global_options(
    ctx: typer.Context,
    workspace: str = typer.Option(
        "", "--workspace", "-w", metavar="ТЕКА",
        help="простір для цього запуску (ставиться перед командою)"),
) -> None:
    """Спільна опція всіх команд.

    🔴 Вона існує тому, що текст «робочий простір не знайдено» радив її з
    першого дня, а самої опції не було: людина виконувала пораду й діставала
    «No such option». Порада, яка не працює, гірша за відсутню — за нею йдуть.

    Лишались два способи вказати простір: змінна середовища й файл-маркер. Але
    пояснити генеалогові, як виставити змінну у Windows так, щоб її побачив
    ярлик на робочому столі, — найскладніший абзац документації; разовий
    прапорець коштує рядка.

    ⚠ `envvar=` тут не використовується, хоча Typer це вміє: значення зі змінної
    приїхало б із походженням `explicit`, а на різниці між `env:…` і рештою
    побудована ціла гілка поведінки агента («знайдено здогадом — перепитай
    людину»). Змінну читає драбина простору, і лише вона.
    """
    sub = ctx.invoked_subcommand or ""
    if sub not in _NO_SKILL_SYNC_FOR:
        _sync_skills()
    if workspace:
        from nyshporka.core.workspace import WorkspaceError, use

        try:
            use(workspace)
        except WorkspaceError as exc:
            console.print(f"[err]{exc}[/err]")
            raise typer.Exit(code=2) from None
    _nag_migration(sub)


def _engine_env_here() -> bool:
    """Чи є в цьому просторі середовище рушіїв читання (його оновлює `htr install`)."""
    try:
        from nyshporka.htr.env import venv_python
        from nyshporka.setup.doctor import engine_venv

        return venv_python(engine_venv()).is_file()
    except Exception:
        return False


def _need(section: str) -> None:
    """Відмовити, якщо секція вимкнена у профілі простору.

    🔴 Потрібно саме тут, окремо від `core.ops.call()`. Найдовші команди —
    `read`, `get`, `crawl` — роблять роботу прямо в процесі, а не через реєстр
    (прогін ставлять на ніч по ssh, і вимагати для цього піднятого браузера
    було б гірше). Тобто фільтр, який стоїть лише в реєстрі, пропускав би рівно
    найвитратнішу роботу.
    """
    from nyshporka.core import sections as S
    from nyshporka.core.workspace import WorkspaceError, workspace

    if section in S.required_ids():
        return
    try:
        active = workspace().sections
    except WorkspaceError:
        return  # простору ще немає — профіль не привід відмовляти
    if section in active:
        return
    sec = S.get(section)
    console.print(
        f"[err]секція «{sec.label() if sec else section}» вимкнена у профілі "
        f"простору.[/err]\n  увімкнути: [bold]nysh sections enable {section}[/bold]")
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Версія пакета."""
    console.print(__version__)


@app.command()
def info() -> None:
    """Стан установки: що вже є, чого ще немає."""
    # 🐾 Знак друкується тут і лише тут. У `version` його немає навмисно: той
    # вивід парсять — і три рядки прикраси зламали б кожен `$(nysh version)`.
    # У робочих командах теж немає: їхній вивід читає агент, і банер коштував
    # би контексту на кожному виклику.
    console.print(brand.banner(__version__))
    console.print(f"  python  {platform.python_version()} ({sys.platform})")

    # Важкі extras перевіряються наявністю, а не імпортом у момент старту.
    # 🔴 HTR — за середовищем рушіїв, а не за torch поруч із застосунком: той
    # у читанні не бере участі, і з 0.24 extra `htr` його вже не ставить.
    from importlib.util import find_spec

    from nyshporka.setup.update import has_htr

    for label, module, extra in (
        ("консоль", "fastapi", "app"),
        ("архіви", "aiolimiter", "archives"),
        ("HTR", "", "htr"),
    ):
        have = has_htr() if extra == "htr" else find_spec(module) is not None
        # 🔴 `\[` — екранування для rich. Без нього `[app]` з'їдається як
        # розмітка, і порада перетворюється на «pip install nyshporka», тобто
        # рівно ту команду, яка extra не ставить. Порада, що не працює, гірша
        # за відсутню: користувач виконує її і бачить той самий стан.
        mark = ("[ok]є[/ok]" if have
                else rf"[muted]немає — pip install 'nyshporka\[{extra}]'[/muted]")
        if extra == "htr" and not have:
            from nyshporka.htr.env import intel_mac

            # Рушії — окреме середовище поруч із простором; extra тут нічого
            # не ставить. На Intel Mac воно збирається з conda-forge.
            mark = ("[muted]окремим кроком: nysh htr install (з conda-forge)[/muted]"
                    if intel_mac() else "[muted]немає — nysh htr install[/muted]")
        console.print(f"  {label:8s} {mark}")


@app.command()
def sources(as_json: bool = typer.Option(False, "--json",
                                         help="машинний вивід: увесь конверт")) -> None:
    """Звідки брати матеріал: що вміє кожне джерело, де його межі й що доводить нуль."""
    from nyshporka import ops as O

    _need("material")
    env = O.call("sources.list", {})
    if as_json:
        console.print_json(data=env.as_dict())
        return
    for row in env.data.get("sources") or []:
        caps = ", ".join(row.get("caps") or []) or "—"
        console.print(f"  [bold]{row['id']:<10}[/bold] {row['label']}"
                      + (f" [warn](лише --source {row['id']})[/warn]"
                         if row.get("explicit_only") else ""))
        console.print(f"  {'':<10} [muted]уміє: {caps}[/muted]")
        about = row.get("about")
        if about is None:
            # 🔴 Джерело без опису не ховається: його межі й сенс нуля невідомі,
            # і саме це людина мусить побачити поруч із ним.
            console.print(f"  {'':<10} [warn]без опису — межі й сенс нуля невідомі, "
                          f"перевірити руками[/warn]")
            continue
        match = ", ".join(about.get("match_on") or [])
        how = f" ({about['match_how']})" if about.get("match_how") else ""
        console.print(f"  {'':<10} [muted]клас: {about['where_class']}"
                      + (f" · шукає в: {match}{how}" if match else " · не шукає")
                      + "[/muted]")
        console.print(f"  {'':<10} [muted]нуль: {about['zero_means']}[/muted]")
    # 🔴 Зламані плагіни називаються поіменно (`broken_source`): «мого архіву
    # немає в списку» інакше не має пояснення, і причину шукатимуть у себе.
    _notes(env)


@app.command()
def look(path: str = typer.Argument(..., help="тека зі сканами, PDF або тека з PDF")) -> None:
    """Що це за матеріал: скільки кадрів, чи це одна справа, чи багато."""
    from nyshporka.sources.local import LocalSource, inspect

    shape = inspect(path)
    mark = "[ok]✓[/ok]" if shape.usable else "[warn]![/warn]"
    console.print(f"{mark} {shape.explain()}")
    if shape.kind == "cases":
        for node in shape.cases:
            console.print(f"    [muted]{node.frames:>6} кадрів[/muted]  {node.label}")
        console.print("\n[muted]Оберіть одну зі справ вище або поставте всі в чергу.[/muted]")
        raise typer.Exit(code=1)
    if not shape.usable:
        raise typer.Exit(code=1)
    m = LocalSource().manifest(str(shape.path))
    if m.bytes_estimate:
        console.print(f"  [muted]обсяг: {m.bytes_estimate / 1024 / 1024:.0f} МБ[/muted]")


def _sources_registry() -> Any:
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.sources import load

    try:
        return load(workspace().root)
    except WorkspaceError:
        return load(None)


def _pick(source_id: str) -> Any:
    reg = _sources_registry()
    src = reg.get(source_id)
    if src is None:
        console.print(f"[err]немає джерела «{source_id}»[/err] — є: "
                      + ", ".join(s.id for s in reg.all()))
        raise typer.Exit(code=2)
    return src


def _print_address(addr: Any) -> None:
    """Шапка відповіді про конкретну справу — перед списком знахідок.

    Питання «що це за 127-1078-1662» відрізняється від «де є щось про моє село»
    саме тим, що відповідь у нього одна, а не перелік. Показати її списком
    означало б сховати найважливіше — чи справа вже на диску — між рядками.
    """
    if not addr:
        return
    console.print(f"[bold]{addr.get('shifra') or ''}[/bold] "
                  f"[muted](адреса справи)[/muted]")
    for row in addr.get("local") or []:
        seen = (f" · переглянуто аркушів: {row['noted']}" if row.get("noted")
                else " · оком ще не дивились")
        console.print(f"  ✅ на цій машині: [bold]{row.get('path') or row.get('key')}"
                      f"[/bold]{seen}")
    reg = addr.get("registry") or {}
    if reg:
        row = reg.get("row") or {}
        head = " · ".join(str(x) for x in (row.get("title"), row.get("years")) if x)
        console.print(f"  📔 у реєстрі опису {reg.get('label') or ''}: {head[:160]}")
    console.print("")


@app.command()
def find(q: str = typer.Argument(..., help="село, прізвище, слово із заголовка "
                                           "або шифра справи"),
         source: str = typer.Option("", "--source", help=(
             "лише це джерело; іменні бази (martyrolog) — тільки так")),
         text: bool = typer.Option(False, "--text",
                                   help="шукати текстом, навіть якщо запит "
                                        "схожий на шифру"),
         limit: int = typer.Option(20, "--limit", help="скільки показати")) -> None:
    """Де взагалі є щось про моє село — пошук по каталогах джерел."""
    from rich.markup import escape

    from nyshporka import ops as O

    env = O.call("catalog.search", {"q": q, "source": source, "limit": limit,
                                    "by_address": not text})
    _answer(env)
    _print_address(env.data.get("address"))
    hits = env.data.get("hits") or []
    for h in hits:
        head = " · ".join(x for x in (h.get("shifra"), h.get("years"),
                                      h.get("place")) if x)
        pad = f"  {'':<{len(h['source'])}}  "
        # 🔴 Усе, що прийшло від джерела, — через `escape`. Примітка `ia` несе
        # сирий OCR газет, і `[/Ред.]` у ньому rich читав як закривальний тег:
        # `find` падав на першій же такій знахідці разом зі знаменником, а
        # `[sic]` мовчки зникав із тексту.
        console.print(f"  [bold]{escape(h['source'])}[/bold]  {escape(h['title'])}")
        console.print(f"{pad}[muted]{escape(head)}[/muted]")
        console.print(f"{pad}[muted]{escape(h['ref'])}[/muted]")
        # 🔴 Місце, примітка й пряме посилання доїжджали до конверта, але в
        # терміналі не друкувались — тобто джерело, яке відповідає «книги цього
        # СЕЛА, ось адреса копії», у CLI показувало саму лише шифру. Заразом це
        # єдине місце, де видно межу відповіді («з 271 за цією назвою»).
        if h.get("note"):
            console.print(f"{pad}[muted]{escape(h['note'])}[/muted]")
        if h.get("url"):
            console.print(f"{pad}[muted]{escape(h['url'])}[/muted]")
        if h.get("crop_url"):
            console.print(f"{pad}[muted]кроп: {escape(h['crop_url'])}[/muted]")
    cov = env.data.get("coverage") or {}
    # 🔴 Знаменник друкується завжди, і найважливіший він саме тоді, коли
    # знахідок нуль: без нього «нічого не знайшлось» читається як «цього не
    # існує», хоча дивились в одному каталозі з трьох.
    basis = "; ".join(
        f"{b['source']}: {b['kind']}" + (f" від {b['taken']}" if b.get("taken") else "")
        for b in (cov.get("basis") or []))
    console.print(f"\n[muted]знайдено {len(hits)} · шукали в: "
                  + escape(f"{', '.join(cov.get('searched') or []) or '—'}"
                           + (f" ({basis})" if basis else "")) + "[/muted]")
    # Покриття іменної бази по архівах — число, без якого «немає» не сказати.
    for b in cov.get("basis") or []:
        per = b.get("by_archive") or {}
        if per:
            spread = ", ".join(f"{k} {v}" for k, v in sorted(
                per.items(), key=lambda kv: -int(kv[1])))
            console.print(escape(f"  покриття {b['source']}: {sum(per.values())} "
                                 f"осіб у {len(per)} архівах — {spread}"),
                          style="muted")
    # 🔴 Що доводить нуль кожного джерела. «Немає в назвах альбомів» і «немає в
    # тексті книг» — однаковий 0 у лічильнику й різні висновки у звіті. На
    # повний нуль той самий перелік уже стоїть у попередженні нижче, тож рядки
    # друкуються лише поруч зі знахідками інших джерел — інакше кожен сенс нуля
    # стояв би на екрані двічі.
    if hits:
        for z in cov.get("zeros") or []:
            console.print(f"[muted]  0 · {escape(z['source'])}: "
                          f"{escape(z['means'])}[/muted]")
    # Не опитані навмисно — не нуль, а інше питання (іменна база осіб).
    for n in cov.get("not_asked") or []:
        console.print(f"[muted]  не питали · {escape(n['source'])}: "
                      f"{escape(n['why'])}[/muted]")
    # 🔴 всі попередження конверта, а не лише про недоступні джерела. Саме тут
    # їде різниця між «не знайшлось» і «не знайшлось у зрізі піврічної давнини»,
    # і показувати її вибірково — те саме, що не показувати.
    _notes(env)


@app.command()
def browse(source: str = typer.Argument(..., help="id джерела (`nysh sources`)"),
           ref: str = typer.Argument("", help="вузол; порожньо = верхній рівень")) -> None:
    """Що лежить у фонді, описі, теці дзеркала."""
    from nyshporka.sources.base import SourceError

    _need("material")
    src = _pick(source)
    try:
        nodes = src.browse(ref or None)
    except SourceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    for n in nodes:
        frames = f"{n.frames:>7} кадрів" if n.frames else " " * 14
        mark = "📄" if n.kind == "case" else "📁"
        console.print(f"  {mark} {frames}  {n.label}")
        console.print(f"     [muted]{n.ref}[/muted]")
    console.print(f"\n[muted]{len(nodes)} вузлів[/muted]")


@app.command()
def get(source: str = typer.Argument(..., help="id джерела"),
        ref: str = typer.Argument(..., help="адреса справи чи плівки"),
        out: Path = typer.Option(..., "--out", help="куди складати кадри"),
        frames: str = typer.Option("", "--frames",
                                   help="діапазон кадрів «12-80»; порожньо = всі"),
        why: str = typer.Option("", "--why",
                                help="навіщо ця справа — лягає в паспорт теки"),
        whole: bool = typer.Option(False, "--whole",
                                   help="не різати розвороти на сторінки (джерела, що "
                                        "ріжуть розвороти по згину: skanoteka)")) -> None:
    """Завантажити справу або плівку.

    Спершу друкується маніфест і лише потім починається качання: справа буває
    на кілька гігабайтів, і питання «скільки це» мусить мати відповідь ДО, а не
    після — перервана закачка лишає теку в невизначеному стані.

    🔴 Поруч із кадрами лягає паспорт: джерело, адреса, час і звірка «обіцяно /
    взято».
    \f
    Доти команда лишала на диску самі пікселі — тобто теку невідомого
    походження, у якій наступна сесія не знала ні звідки вона, ні чи повна.
    """
    from nyshporka.sources.base import SourceError

    _need("material")
    ref = ref.strip()       # адреса з файла CRLF несе `\r` — див. `provenance`
    src = _pick(source)
    import inspect

    # Різ розвороту вміє не кожне джерело: прапорець без дії гірший за відмову —
    # людина думала б, що кадри лишились цілими.
    splits = "split" in inspect.signature(src.fetch).parameters
    if whole and not splits:
        console.print(f"[err]--whole: джерело «{src.id}» розворотів не ріже — "
                      f"кадри й так лягають цілими[/err]")
        raise typer.Exit(code=2)
    rng: tuple[int, int] | None = None
    if frames:
        try:
            a, _, b = frames.partition("-")
            rng = (int(a), int(b or a))
        except ValueError:
            console.print("[err]--frames очікує «12-80»[/err]")
            raise typer.Exit(code=2) from None
    try:
        man = src.manifest(ref)
    except SourceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    console.print(f"[bold]{man.title or ref}[/bold] — кадрів "
                  + (str(man.frames) if man.frames is not None else "невідомо")
                  + (f", беремо {rng[0]}-{rng[1]}" if rng else ""))
    for s in man.sheets[:12]:
        console.print(f"  [muted]Л.{s.frm}-{s.to}  {s.label[:80]}[/muted]")
    if len(man.sheets) > 12:
        console.print(f"  [muted]…ще {len(man.sheets) - 12} записів покажчика[/muted]")

    state = {"last": -1}

    def progress(done: int = 0, total: int = 0, **_: Any) -> None:
        pct = int(done * 100 / total) if total else 0
        if pct != state["last"]:
            state["last"] = pct
            console.print(f"  [muted]{done}/{total} ({pct}%)[/muted]", end="\r")

    try:
        kw: dict[str, Any] = {"split": False} if whole else {}
        res = src.fetch(ref, out, frames=rng, on_progress=progress, **kw)
    except SourceError as exc:
        # Та сама відмова, що й на маніфесті: джерело може відмовити й посеред
        # завантаження (мережа, обрізаний перелік файлів), і це текст, а не
        # трасування.
        console.print(f"\n[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    console.print(f"\n✓ {res.frames} кадрів ({res.bytes / 1024 / 1024:.0f} МБ), "
                  f"пропущено {res.skipped} → {res.dest}")
    for e in res.errors[:5]:
        console.print(f"[warn]⚠ {e}[/warn]")
    if len(res.errors) > 5:
        console.print(f"[warn]⚠ …ще {len(res.errors) - 5} збоїв[/warn]")
    # Нотатки — не збої: файл ліг цілим, але людина мусить знати, що з ним не
    # так (напр. «текстового шару немає»). Код виходу вони не міняють.
    for n in getattr(res, "notes", None) or []:
        console.print(f"[muted]ℹ {n}[/muted]")

    # 🔴 Приймач — знаменник, а не відсутність помилок. Дзеркало, що віддало
    # сорок кадрів із трьохсот і жодного HTTP-збою, давало «✓ 40 кадрів» і код
    # 0: обіцянка маніфесту друкувалась рядком вище й ніде не звірялась. Той
    # самий клас вади, що обірваний zip, який браузер записує як успіх.
    #
    # 🔴 Просити діапазон — не те саме, що просити все: там знаменником стає
    # сам діапазон, а не обсяг справи.
    want = (rng[1] - rng[0] + 1) if rng else man.frames

    # 🔴 Той самий приймач лягає на диск, а не лише на екран. Числа «обіцяно /
    # взято» живуть рівно одну сесію, а тека лишається — і без них наступний,
    # хто її відкриє, не має способу дізнатись, чи вона повна. Паспорт один на
    # всі входи (`record_fetch`): збої, хеші, нові й уже наявні кадри.
    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import completeness

    passport: dict[str, Any] = {"title": man.title}
    if splits:
        passport["spreads_split"] = not whole
    if rng:
        passport["frames_range"] = f"{rng[0]}-{rng[1]}"
    claimed = man.meta.get("shifra") or {}
    if isinstance(claimed, dict) and any(claimed.values()):
        # ⚠ Саме `claimed`, а не `shifra`: це те, що каже сторінка джерела, і
        # звірити його оком ще ніхто не звіряв. Записане під іменем справжньої
        # шифри, воно стало б у реєстрі фактом — а помилка на один номер
        # приписує теці чужу справу.
        passport["shifra_claimed"] = claimed
    try:
        verdict = record_fetch(res.dest, res, source=src.id, ref=ref,
                               url=str(man.meta.get("url") or ""), want=want, why=why,
                               extra=passport)
    except OSError as exc:      # диск є, кадри лягли — паспорт не критичний
        console.print(f"[warn]⚠ паспорт не записався: {exc}[/warn]")
        verdict = completeness(res, want)

    # Приймач один на термінал і чергу демона — `sources.base.completeness`.
    _dali_pislia_zavantazhennia(res.dest)
    if res.causes:
        from rich.markup import escape as _esc

        console.print(f"[warn]чому не взялось:[/warn] {_esc(res.why())}")

    if verdict.state == "unknown":
        # ⚠ Мовчазний «✓» тут був би найгіршим із варіантів: він читається як
        # доведена повнота. Нуль без знаменника не є доказом повноти.
        console.print(f"[warn]⚠ {verdict.message(res)}[/warn]")
    elif verdict.state in ("partial", "empty"):
        console.print(f"[warn]⚠ {verdict.message(res)}[/warn]")
        console.print("[muted]  качати заново дешевше зараз, ніж шукати "
                      "пропущений аркуш у декоді[/muted]")
        raise typer.Exit(code=1)
    if res.errors:
        raise typer.Exit(code=1)


@app.command()
def crawl(source: str = typer.Argument("archium", help="id джерела"),
          groups: str = typer.Option("", "--groups",
                                     help="групи фондів через кому; порожньо = давні акти"),
          fresh: bool = typer.Option(False, "--fresh",
                                     help="почати наново, а не продовжити"),
          from_file: str = typer.Option("", "--from",
                                        help="файл списку для джерел, чий каталог "
                                             "приходить файлом (volok)")) -> None:
    """Зібрати каталог справ, по якому потім працює `nysh find`.

    🔴 Потрібне не всім джерелам, а тим, чий сайт не індексує заголовків справ.
    Для ARCHIUM без цього кроку пошук неможливий у принципі — і саме тому він
    відмовляється відповідати нулем.
    """
    from nyshporka.sources.base import SourceError

    _need("material")
    src = _pick(source)
    if hasattr(src, "import_list"):
        # Каталог, який не обходиться, а приходить від автора файлом.
        if not from_file:
            console.print(f"[warn]каталог «{source}» не обходиться, а кладеться "
                          f"файлом: `nysh crawl {source} --from <файл>`[/warn]")
            raise typer.Exit(code=2)
        try:
            meta = src.import_list(Path(from_file))
        except SourceError as exc:
            console.print(f"[err]{exc}[/err]")
            raise typer.Exit(code=1) from None
        console.print(f"✓ список від {meta['taken']}: альбомів {meta['rows']}"
                      + (f" · посилань не на альбом {meta['not_albums']}"
                         if meta.get("not_albums") else ""))
        return
    if from_file:
        console.print(f"[warn]джерело «{source}» каталогу з файлу не приймає[/warn]")
        raise typer.Exit(code=2)
    if not hasattr(src, "crawl"):
        console.print(f"[warn]джерело «{source}» не потребує обходу — "
                      f"його каталог доступний одразу[/warn]")
        raise typer.Exit(code=0)

    def progress(done: int = 0, total: int = 0, note: str = "", unit: str = "",
                 **_: Any) -> None:
        console.print(f"  [muted]{done}/{total} {unit or 'фонд'} · {note}[/muted]",
                      end="\r")

    stats = src.crawl(tuple(g.strip() for g in groups.split(",") if g.strip()) or None,
                      on_progress=progress, resume=not fresh)
    if stats.get("summary"):
        # Джерело, чий каталог не складається з фондів і описів, звітує своїми словами.
        console.print(f"\n✓ {stats['summary']}")
        return
    console.print(f"\n✓ фондів {stats['fonds']} (пропущено готових "
                  f"{stats['skipped']}) · описів {stats['inventories']} · "
                  f"справ {stats['cases']}")
    if stats.get("short"):
        # 🔴 Неповний опис — частина відповіді, а не шум: без цього рядка
        # каталог виглядав би повним, і нуль пошуку по ньому читався б як
        # «справи немає».
        console.print(f"[warn]⚠ описів, що віддали менше справ, ніж обіцяє сам "
                      f"сайт: {stats['short']}. Наступний `nysh crawl {source}` "
                      f"перечитає лише їх[/warn]")


@app.command()
def init(
    path: str = typer.Argument("", help="куди покласти простір; порожньо — запропоную"),
    name: str = typer.Option("", "--name", help="як зветься дослідження"),
    preset: str = typer.Option("", "--preset",
                               help="набір частин: catalog | amateur | researcher | lab"),
    yes: bool = typer.Option(False, "--yes", "-y", help="без питань (для інсталятора)"),
) -> None:
    """Створити робочий простір — теку, де житиме дослідження.

    🔴 Мовчки простір не створюється ніколи: тека, що з'явилась сама, — це
    дослідження, яке потім не можуть знайти.
    """
    from nyshporka.core import sections as S
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.setup import wizard

    if preset and preset not in S.PRESETS:
        console.print(f"[err]невідомий пресет «{preset}»[/err]")
        console.print(f"[muted]є: {', '.join(sorted(S.PRESETS))}[/muted]")
        raise typer.Exit(code=2)
    try:
        p = wizard.plan(path or None)
    except WorkspaceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    # 🔴 Не лише куди, а й чому туди. `nysh init --yes` в інсталяторі не питає
    # нічого, тож цей рядок — єдине місце, де людина може помітити, що шлях
    # узявся не звідти, звідки вона думала.
    console.print(f"Простір: [bold]{p.root}[/bold]"
                  + f"  [muted]({wizard.origin_phrase(p.origin)})[/muted]"
                  + ("" if p.creating else "  [muted](уже існує)[/muted]"))
    if p.warning:
        console.print(f"[warn]⚠ {p.warning}[/warn]")
    if p.creating and not yes and not typer.confirm("Створити?", default=True):
        raise typer.Exit(code=1)

    # 🔴 Питання ставиться лише в діалозі й лише при створенні. Інсталятор і
    # скрипти йдуть із `--yes`, і мовчазний дефолт там мусить лишати застосунок
    # повним: звузити його за людину, яка нічого не обирала, — гірше, ніж
    # показати їй зайвий екран.
    if p.creating and not preset and not yes:
        console.print("\nЧим користуватиметесь? Це можна змінити будь-коли "
                      "(`nysh sections`).")
        for pid in ("amateur", "researcher", "lab"):
            names = ", ".join(
                s.label() for s in S.all_sections()
                if s.id in S.PRESETS[pid] and not s.required)
            console.print(f"  [bold]{pid}[/bold] [muted]— {names}[/muted]")
        preset = typer.prompt("Набір", default=S.DEFAULT_PRESET)
        while preset not in S.PRESETS:
            console.print(f"[warn]є: {', '.join(sorted(S.PRESETS))}[/warn]")
            preset = typer.prompt("Набір", default=S.DEFAULT_PRESET)

    root = wizard.create(p.root, name=name, preset=preset)
    console.print(f"✅ готово: {root}")
    if preset:
        console.print(f"[muted]частини: {preset} · змінити — `nysh sections`[/muted]")
    # ⚠ Профіль названо тут, а не лишено доктору: інакше єдиним місцем, де про
    # нього дізнаються, лишається попередження — тобто перше, що бачить людина
    # після успішного `init`, це ⚠ про крок, якого їй ніхто не пропонував.
    console.print("[muted]далі: `nysh profile init <Прізвище>` · "
                  "`nysh look <тека зі сканами>` · `nysh serve`[/muted]")


@app.command()
def update(
    check: bool = typer.Option(False, "--check",
                               help="лише подивитись, не ставити"),
    preset: str = typer.Option("", "--preset",
                               help="набір частин, якщо слід інсталятора втрачено"),
) -> None:
    """Оновити застосунок: подивитись версію на pypi.org і поставити нову.

    ⚠ Установлення саме себе на ходу не робиться: `uv tool install --force`
    міняє те саме середовище, з якого зараз запущено `nysh`. Закрийте
    застосунок (`nysh serve`) перед оновленням.
    \f
    🔴 Досі шляху оновлення не було зовсім — ні команди, ні перевірки версії,
    ні рядка в `doctor`. Людина з `.exe`-установленням дізнатись про нову
    збірку не могла нізвідки, тож вада, полагоджена вчора, лишалась у неї
    назавжди.
    """
    import subprocess

    from rich.markup import escape

    from nyshporka.setup import update as U

    rel = U.latest()
    console.print(f"стоїть: [bold]{rel.installed}[/bold]")
    if not rel.known:
        # 🔴 «Не питали» — окрема відповідь. Мовчазне «все свіже» тут було б
        # тим самим нулем без знаменника, лише про власну версію.
        console.print(f"[warn]на pypi.org не подивились: {rel.why}[/warn]")
        raise typer.Exit(code=1)
    console.print(f"на pypi.org: [bold]{rel.latest}[/bold]")
    if not rel.newer:
        console.print("[muted]оновлювати нема на що[/muted]")
        raise typer.Exit(code=0)
    cmd = U.command(preset)
    # 🔴 `escape` обов'язковий. `nyshporka[app,archives]` rich читав як розмітку
    # і з'їдав: людина бачила `uv tool install … nyshporka`, копіювала — і
    # ставила пакет БЕЗ консолі й архівів, тобто `nysh serve` після такого
    # «оновлення» вже не стартував. Рядок той самий, що в кнопці застосунку, —
    # з лапками, бо шлях до uv буває з пробілом.
    console.print(f"[muted]{escape(U.how_to_update(preset))}[/muted]")
    if check:
        raise typer.Exit(code=0)
    if not U.runs_in_place():
        # 🔴 Не виконуємо там, де виконання не може вдатись або не наше. Рядок
        # вище вже названо — лишається сказати, де й коли його набрати.
        if not U.tool_env():
            why = f"застосунок стоїть у pip-середовищі {sys.prefix}, і оновлює його той самий pip"
        else:
            why = ("на Windows застосунок не замінює сам себе: nysh.exe, з якого "
                   "запущено цю команду, зайнятий до її завершення")
        console.print(f"[warn]не ставлю: {escape(why)}[/warn]\n"
                      "  закрийте застосунок і виконайте рядок вище в новому вікні термінала")
        if _engine_env_here():
            console.print("  далі тим самим вікном: [bold]nysh htr install[/bold] — оновить "
                          "рушії читання на місці, якщо нова збірка підняла їхній пін")
        if sys.platform == "win32" and U.tool_env():
            console.print("[muted]без термінала — новий nyshporka-setup.exe поверх цього: "
                          "простір, моделі й довідники лишаються[/muted]")
        raise typer.Exit(code=1)
    try:
        rc = subprocess.call(cmd)
    except OSError as exc:
        console.print(f"[warn]не вдалося запустити uv ({exc}) — "
                      f"перевстановіть застосунок інсталятором[/warn]")
        raise typer.Exit(code=1) from None
    if rc != 0:
        console.print("[warn]оновлення не завершилось. Найчастіша причина — "
                      "застосунок запущений: закрийте `nysh serve` і "
                      "повторіть[/warn]")
        raise typer.Exit(code=rc)
    console.print(f"✅ {rel.latest}")
    # 🔴 Рушії читання живуть в окремому середовищі, і оновлення застосунку їх
    # не чіпає. Нова збірка може підняти їхній пін (0.24: kraken 7.0.2 → 7.1.1),
    # а на старому раннер не стартує — тож одразу кличемо `htr install` УЖЕ
    # НОВОЇ збірки: він оновить середовище на місці або скаже, що все на місці.
    if _engine_env_here():
        import shutil

        new_nysh = shutil.which("nysh")
        if new_nysh:
            console.print("[muted]оновлюю рушії читання на місці: nysh htr install[/muted]")
            subprocess.call([new_nysh, "htr", "install"])
        else:
            console.print("далі: [bold]nysh htr install[/bold] — оновить рушії читання на місці")
    # 🔴 Скіли не їдуть разом із пакетом: вони лежать копією в теці агента.
    # Перекладає їх НАСТУПНИЙ запуск уже нової збірки (`_sync_skills`), а не
    # цей процес — він старий. Тому називаємо, коли це станеться, а не радимо
    # класти руками: порада «покласти наново» розходилась із тим, що робить
    # застосунок, і з `docs/agent.md`.
    from nyshporka import skills as S

    if S.installed():
        console.print("[muted]скіли агента перекладуться самі при наступному "
                      "запуску нової збірки[/muted]")


@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y",
                             help="зняти; без нього — лише показати"),
    engines: bool = typer.Option(False, "--engines",
                                 help="і середовище рушіїв (~2.5 ГБ)"),
    models: bool = typer.Option(False, "--models", help="і ваги моделей письма"),
    catalog: bool = typer.Option(False, "--catalog", help="і паки довідників"),
    skills: bool = typer.Option(False, "--skills", help="і скіли агента"),
    state: bool = typer.Option(False, "--state", help="і стан застосунку"),
    everything: bool = typer.Option(False, "--all",
                                    help="усе перелічене разом"),
) -> None:
    """Зняти застосунок: рівно те, що поставили, і нічого з дослідження.

    🔴 Робочий простір не знімається ЖОДНИМ прапорцем — там скани, прочитане й
    роками зібране дослідження. Знімається пакет, тека застосунку, слід
    інсталятора й рядок, який інсталятор дописав у PATH; решта — поіменно.

    ⚠ Без `--yes` команда нічого не робить: друкує перелік і виходить. Зняти
    те, що ставилось годинами, з одного необережного натискання не можна.
    """
    from nyshporka.setup import uninstall as U

    if everything:
        engines = models = catalog = skills = state = True
    p = U.plan(engines=engines, models=models, catalog=catalog,
               skills=skills, state=state)

    console.print("[bold]Зняти:[/bold]")
    for item in p.items:
        size = f"  [muted]{U.human(item.size)}[/muted]" if item.size else ""
        console.print(f"  {item.what}{size}")
        if item.note:
            console.print(f"    [muted]{item.note}[/muted]")
    if p.kept:
        console.print("\n[bold]Лишається:[/bold]")
        for line in p.kept:
            console.print(f"  [muted]{line}[/muted]")

    if not yes:
        console.print("\n[muted]нічого не зроблено — повторіть із `--yes`[/muted]")
        raise typer.Exit(code=0)

    console.print("")
    try:
        for line in U.remove(p, dry=False):
            console.print(line)
    except U.Forbidden as exc:
        # 🔴 Це не «не вийшло», це запобіжник: щось у плані вказало всередину
        # простору. Зупиняємось, не доробивши, — недознятий застосунок дешевший
        # за знесене дослідження.
        console.print(f"[warn]зупинились: {exc}[/warn]")
        raise typer.Exit(code=1) from None
    console.print(f"\n[muted]керовані інтерпретатори лишились: "
                  f"{U.uv_python_hint()}[/muted]")


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перевірити те, що ламається тихо: карта, хмарна тека, місце, рушії."""

    from nyshporka.setup import doctor as doc

    checks = doc.run()
    if as_json:
        console.print_json(data=[{"name": c.name, "level": c.level,
                                  "detail": c.detail, "fix": c.fix}
                                 for c in checks])
        raise typer.Exit(code=0 if all(c.level != "fail" for c in checks) else 1)
    for c in checks:
        console.print(f"{c.mark} [bold]{c.name}[/bold]  {c.detail}")
        if c.fix and c.level != "ok":
            # `escape`: порада на кшталт `pip install "пакет[extra]"` інакше
            # втрачає дужки — rich читає їх як розмітку й друкує команду, якої
            # не існує.
            from rich.markup import escape

            console.print(f"   [muted]{escape(c.fix)}[/muted]")
    bad = [c for c in checks if c.level == "fail"]
    raise typer.Exit(code=1 if bad else 0)


@app.command()
def sample(
    force: bool = typer.Option(False, "--force",
                               help="перезаписати вже розгорнуті файли"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Розгорнути вкладену зразкову справу — щоб пройти застосунок без сканів.

    Три аркуші ДАХмО ф.315 оп.1 спр.159 (1821-1822) з готовим машинним декодом
    двома голосами. Гортач, пошук у декоді й реєстр працюють на них одразу, ще
    до того, як людина поставить рушії; прочитати їх заново можна після
    `nysh htr install` і `nysh models get`.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.setup import sample as S

    try:
        got = S.install(workspace(), force=force)
    except WorkspaceError:
        console.print("[err]простору ще немає[/err] — спершу `nysh init`")
        raise typer.Exit(code=1) from None
    except FileNotFoundError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None
    if as_json:
        console.print_json(data=got)
        return
    console.print(f"✅ {got['shifra']} — {len(got['frames'])} аркушів "
                  f"із {got['frames_total']}")
    console.print(f"   тека: {got['case_dir']}")
    for run in got["runs"]:
        console.print(f"   декод: {run}")
    if not got.get("registry_built"):
        console.print("[warn]реєстр справ не перезібрався[/warn] — "
                      "`nysh cases build`, інакше «Мої справи» покажуть нуль")
    # 🔴 `search`, а не `find`: перше шукає в прочитаному, друге — в каталогах
    # архівів. Зразкова справа дає саме декод, тож порада «find Липовеньке»
    # вела найпершого відвідувача рівно в той хибний нуль, проти якого написано
    # решту застосунку: команда відпрацьовувала бездоганно й не знаходила нічого.
    console.print("[muted]далі: `nysh serve` → «Гортач», або "
                  "`nysh search Липовеньке`[/muted]")


def _supriaha_autoshare(case_key: str) -> None:
    """Хвіст успішного прогону в режимі згоди «завжди».

    🔴 Не має права зробити з успішного прогону невдалий. Усе, що тут може
    піти не так — пул лежить, токена немає, ворота не пустили, — це привід
    написати рядок, а не зіпсувати код повернення команди, за яким люди
    ставлять свої прогони в черги й скрипти.
    """
    from rich.markup import escape

    try:
        from nyshporka import ops as O

        env = O.call("share.autoshare", {"case": case_key, "complete": True})
    except Exception as exc:
        console.print(f"  [warn]⚠ Супряга: автовіддача не спрацювала: "
                      f"{escape(str(exc))}[/warn]")
        return
    d = env.data or {}

    # 🔴 Попередження друкуються ЗАВЖДИ, і першими. У режимі «завжди»
    # людина не дивиться на результат — вона на нього поклалась; мовчазна
    # невдача означає, що вона вважає справу відданою, а та лежить у себе
    # на диску. Це гірше, ніж не мати режиму зовсім.
    for w in env.warnings or []:
        console.print(f"  [warn]⚠ {escape(str(w.text))}[/warn]")
    if not env.ok:
        # Операція впала всередині (`O.call` перетворює виняток на відмову
        # без попереджень): доти тут не друкувалось НІЧОГО.
        why = str(env.error or "") or "невідома причина"
        console.print(f"  [warn]⚠ Супряга: справу не віддано — {escape(why)}[/warn]")
        return

    if d.get("skipped") or not d.get("packed"):
        return
    from nyshporka.share.upload import OUTCOME_TEXT, VIDDANO

    vyhid = str(d.get("outcome") or "")
    if vyhid == VIDDANO:
        console.print(f"  🤝 віддано в Супрягу: внесок {d.get('contribution')}")
    elif vyhid in OUTCOME_TEXT:
        style = "muted" if vyhid == "vzhe_ye" else "warn"
        console.print(f"  [{style}]Супряга: {OUTCOME_TEXT[vyhid]}[/{style}]")
    else:
        console.print(f"  [muted]спаковано, але не віддано: "
                      f"{escape(str(d.get('path') or ''))}[/muted]")


def _supriaha_lookup(case_key: str, frames: int) -> None:
    """Чи цю справу вже прочитали — питання до пулу перед прогоном.

    🔴 Ніколи не спиняє прогін і ніколи не падає. Пул лежить, мережі немає,
    відповідь дивна — людина просто читає сама, як читала досі. Тихий
    фолбек тут не зручність, а умова: прогін на ніч не має зриватись через
    чужий сервер.

    Рішення лишається за людиною й тоді, коли текст знайшовся: ми друкуємо
    рядок, а не пропонуємо вибір. Питання посеред довгої команди — це те
    саме, від чого відмовились у режимах згоди.

    🔴 Типово ВИМКНЕНО (`profile.lookup=False`) і вмикається людиною:
    запит несе шифру справи й ключ, тобто сервер бачить, що саме читає ця
    людина. `PRIVACY.md` обіцяє, що фонових запитів немає, доки їх не
    ввімкнули. Без ключа пул не питається зовсім: він однаково відповів би
    401, а запит без відповіді — це витік без користі.
    """
    from rich.markup import escape

    try:
        from nyshporka.share import catalog as C
        from nyshporka.share import profile as P
        from nyshporka.share.upload import token

        if not P.load().lookup:
            return
        if not token():
            console.print("  [muted]Супряга: питати пул перед прогоном можна лише "
                          "під'єднаній Нишпорці — nysh share login[/muted]")
            return
        got = C.lookup(case_key, frames=frames)
    except Exception:
        return
    if got.get("need_key"):
        console.print(f"  [muted]Супряга: {escape(str(got.get('why') or ''))}[/muted]")
        return
    if not got.get("found"):
        return

    modeli = ", ".join(str(m) for m in (got.get("models") or [])) or "невідомо чим"
    console.print(
        f"  [bold]цю справу вже прочитали:[/bold] {escape(str(got.get('pages')))} стор. · "
        f"{escape(modeli)} · {escape(str(got.get('license') or '—'))}"
    )
    if got.get("status") == "nove":
        console.print("  [muted]мітка «не перевірено» — текст ще не дивилась людина[/muted]")
    # Порада — зі ШИФРОЮ, яку знає пул, і без лапок-ялинок: shell передав би
    # їх частиною запиту, і пошук не знайшов би нічого.
    zapyt = str(got.get("shifra") or case_key)
    console.print(f"  [muted]забрати: nysh share pull \"{escape(zapyt)}\" --take[/muted]")


@app.command()
def read(
    case_dir: str = typer.Argument(..., help="пласка тека зі сканами справи"),
    out: str = typer.Option("", "--out", help="куди класти текст"),
    script: str = typer.Option("", "--script",
                              help="письмо: latin | cyrillic; порожньо — визначити самому"),
    one_voice: bool = typer.Option(False, "--one-voice",
                                   help="без другого рушія (швидше, але сліпіше)"),
    case_key: str = typer.Option("", "--case-key",
                                help="шифра справи для мети прогону; порожньо — з бібліотеки"),
    limit: int = typer.Option(0, "--limit", help="лише перші N кадрів"),
    pages: str = typer.Option("", "--pages", help="діапазони кадрів: 1-50,60"),
    shard: str = typer.Option("", "--shard",
                              help="«k/n» — цей процес бере кожен n-й кадр"),
    workers: int = typer.Option(
        1, "--workers", "-j", min=1,
        help="скільки шардів читає справу на одній карті (2–3 на 8 ГБ): поки "
             "один рахує процесором, інший зайнятий карткою; без карти — один"),
    gpu_lock: str = typer.Option("", "--gpu-lock",
                                 help="спільний файл-лок GPU; обов'язковий при --shard"),
    gpu_sato: bool = typer.Option(True, "--gpu-sato/--no-gpu-sato",
                                  help="рахувати sato на карті; зняти при шардингу"),
    seg_height: int = typer.Option(0, "--seg-height",
                                   help="висота сегментації (0 = рідна 1800)"),
    model: str = typer.Option(
        "", "--model",
        help="перечитати ЯВНО названою моделлю (файл або ім'я ваг): письмо від "
             "моделі, вихід `<справа>-<тег>`, сегментація — з кешу"),
    seg_cache: str = typer.Option(
        "", "--seg-cache",
        help="тека готової сегментації (*.seg.json.gz), напр. забраної з хмари"),
    with_: list[str] = typer.Option(
        [], "--with",
        help="ще голос тим самим проходом: `latin` (Скриба) або ім'я ваг; для "
             "мішаного письма — замість другого прогону"),
    force: bool = typer.Option(
        False, "--force",
        help="стартувати, навіть якщо інша справа вже читається"),
    rerun: bool = typer.Option(
        False, "--rerun",
        help=("запустити, хоч справу вже прочитано ЦІЄЮ моделлю: раннер дочитає "
              "сторінки без тексту, готові не перечитує. Перечитати все — "
              "окрема тека (--out) або інша модель (--model)")),
    dry: bool = typer.Option(False, "--dry-run", help="лише показати план"),
) -> None:
    """Прочитати справу рукописним рушієм.

    🔴 Читає прямо тут, а не через застосунок — і це свідомо. Прогін ставлять
    на ніч, часто по ssh, і вимагати для цього піднятого браузера означало б
    зробити найдовшу роботу найкрихкішою.

    Важелі ресурсів (`--shard`, `--gpu-lock`, `--no-gpu-sato`, `--seg-height`)
    існують тому, що машина в кожного своя. Як ними користуватись —
    https://nyshporka.online/docs/agents/htr-tuning/
    \f
    Раннер мав ці важелі від початку, але доступні вони були лише прямим
    викликом — тобто рівно та людина, якій найбільше треба стиснути прогін під
    слабку карту, важелів не мала.
    """
    from nyshporka.htr import session as S
    from nyshporka.htr.run import ReadError
    from nyshporka.htr.run import plan as make_plan

    _need("htr")
    try:
        p = make_plan(case_dir, out_dir=out, script=script,
                      second_voice=not one_voice, model=model, seg_cache=seg_cache,
                      also=with_)
    except ReadError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None

    console.print(f"[bold]{p.case_dir.name}[/bold] — {p.frames} кадрів · "
                  f"письмо {p.script} · {p.model.name}"
                  + "".join(f" + {v.name}" for v in p.voices))
    console.print(f"  [muted]{p.out_dir}[/muted]")
    if bokom := getattr(p, "bokovi", ""):
        console.print(f"  ⚠ {bokom}", style="warn", markup=False)
    # 🔴 Вже прочитане цією моделлю не перечитується мовчки: прогін коштує
    # ночі, а на диску вже лежить те саме. Судить мета поруч із текстом, а не
    # реєстр: реєстр міг не побачити прогону, що скінчився хвилину тому.
    #
    # ⚠ Але лише там, де прогін СПРАВДІ був би повним і справді почався б:
    # `--dry-run` нічого не запускає, а `--pages`/`--limit` читають ЧАСТИНУ, і
    # вимагати для них `--rerun` означало б вимагати дозволу на те, чого
    # перевірка не стосується (знайдено рев'ю 21.09.2026).
    if not rerun and not dry and not pages and not limit:
        from nyshporka.cloud.go import already_read

        if why := already_read(p.out_dir, model=p.model.name, frames=p.frames):
            console.print(f"[err]{why}. Перечитати наново — окремою текою "
                          f"(`--out <тека>`) або іншою моделлю (`--model`); "
                          f"`--rerun` у цю теку дочитає лише сторінки без тексту[/err]")
            raise typer.Exit(code=1)
    if p.seg_why:
        # Перечитування без кешу коштує вдвічі дорожче (18.4 проти 9.1 с/стор),
        # тож причина мусить бути видна ДО старту, а не в лозі після.
        console.print(f"  [muted]{'✓' if p.seg_ready else '⚠'} "
                      f"сегментація: {p.seg_why}[/muted]")
    # ⚠ Попередження лишається для того, хто задав `--shard` РУКАМИ й свій лок:
    # спільний лок плану вже стоїть, але людина, яка керує шардами вручну,
    # мусить знати, що вони мають ділити один файл.
    if shard and not gpu_lock:
        # ⚠ Не відмова, а попередження: шардинг без спільного лока працює, доки
        # карта витримує кілька одночасних сегментацій. Щойно не витримає —
        # прогін не сповільниться, а завалиться, і причина буде невидима.
        console.print("[warn]⚠ --shard без --gpu-lock: процеси змагатимуться "
                      "за карту. Дайте всім шардам один файл-лок[/warn]")
    # 🔴 Шифру беремо з бібліотеки самі, якщо її не дали. Раннер уміє
    # `--case-key` давно, але покладатись на те, що людина його щоразу набере,
    # виявилось помилкою: замір 2026-08-19 по 909 прогонах — ключ мали сім.
    # А без ключа прив'язка декоду до справи тримається на розборі імені теки,
    # і будь-яке «людське» ім'я прогону робить справу непрочитаною для всіх,
    # хто читає лише `_htr_meta.json`.
    if not case_key:
        try:
            from nyshporka.cases.resolve import LibraryIndex, _from_path
            case_key = _from_path(str(p.case_dir), LibraryIndex()) or ""
        except Exception:
            case_key = ""
        if not case_key:
            # Каталог теки ще не бачив, а паспорт у ній уже лежить: шифра з
            # нього подорожує разом із кадрами.
            from nyshporka.htr.run import case_key_for

            case_key = case_key_for(p.case_dir)[0]
        if case_key:
            console.print(f"  [muted]шифра: {case_key}[/muted]")
        else:
            console.print("  [warn]шифри немає: бібліотека цієї теки не знає — "
                          "прив'язка триматиметься на імені прогону[/warn]")

    # 🔴 Питаємо пул ДО того, як витратити гроші. У цьому й уся Супряга:
    # людина не мусить про неї думати, а прогін, який уже хтось зробив, не
    # мусить робитись удруге. Стоїть поряд із `already_read` вище й з тієї
    # самої причини — «на диску вже лежить те саме» й «у пулі вже лежить те
    # саме» це одне питання, задане двом сховищам.
    if case_key and not (rerun or dry or pages or limit):
        _supriaha_lookup(case_key, p.frames)
    # 🔴 Лок карти береться З ПЛАНУ, коли людина не задала свій.
    #
    # Доти сюди їхала сама лише опція командного рядка (типово порожня), а
    # `p.gpu_lock` — спільний на простір — не читався взагалі. Тобто найдовший
    # і найменш наглядний шлях, прогін на ніч по ssh, ішов БЕЗ лока, і два
    # `nysh read` (чи термінал плюс застосунок) заходили на карту разом — рівно
    # той звіт, з якого почалась ця правка. Черга демона сюди не дістає: вона
    # не бачить прогонів командного рядка, а карта в них спільна.
    if workers > 1 and shard:
        console.print("[err]--workers і --shard разом не працюють:[/err] "
                      "--workers сам розкладає справу на шарди")
        raise typer.Exit(code=2)
    # 🔴 Шарди мають сенс лише на карті: на процесорі вони б'ються за ті самі
    # ядра (`Plan.shards` тоді згортає їх до одного й каже чому). Карту питаємо
    # драйвер, як скрізь, — torch у цьому процесі може й не стояти.
    device = ""
    if workers > 1:
        from nyshporka.htr import gpu as G

        device = "cuda" if G.detect_card() is not None else ""
    opts: dict[str, Any] = {
        "case_key": case_key, "limit": limit, "pages": pages, "shard": shard,
        "gpu_lock": gpu_lock, "gpu_sato": gpu_sato, "seg_height": seg_height,
        "workers": workers, "device": device}
    if dry:
        for cmd in S.commands(p, **opts)[0]:
            console.print("  [muted]" + " ".join(cmd) + "[/muted]")
        return

    # 🔴 Черга для командного рядка. Лок карти серіалізує лише фазу
    # сегментації, тож два прогони СТАРТУЮТЬ разом і обидва міряють вільну
    # VRAM як свою — кожен бере стільки шардів, скільки помістилось би одному.
    # Далі вони штовхаються цілу ніч. Черга застосунку сюди не дістає: вона
    # живе в процесі демона й прогонів термінала не бачить.
    # ⚠ Шарди ТІЄЇ САМОЇ справи проходять: це штатний спосіб її прочитати.
    from nyshporka.htr import runs as R

    busy = R.others(p.case_dir.name)
    if busy and not force:
        console.print("[warn]![/warn] карту вже читає інша справа:")
        for r in busy:
            console.print(f"    [muted]{r.label()}[/muted]")
        console.print("[muted]дочекайтесь кінця — або, якщо певні, що місця "
                      "вистачить, `--force`[/muted]")
        raise typer.Exit(code=1)

    def _say(ev: Any, human: str | None) -> None:
        if ev is not None and ev.n:
            console.print(
                f"  [muted]{ev.i}/{ev.n} ({ev.pct:.0f}%) {ev.item}[/muted]",
                end="\r")
        elif human:
            console.print(f"  [muted]{human}[/muted]")

    got = S.read_case(p, on_event=_say, **opts)
    for note in got.notes:
        console.print(f"  [muted]{note}[/muted]")
    rc, done, missing, partial = got.rc, got.done, got.missing, got.partial
    console.print(f"\n{'✅' if rc == 0 and not missing else '🔴'} "
                  f"сторінок з текстом: {done} з {p.frames}"
                  + (f" · без тексту: {missing}" if missing else "")
                  + (" · частковий прогін, повноту не міряю" if partial else ""))
    # 🔴 Цей рядок і пересилають як замір: темп машини з пристроєм, шардами,
    # голосами й щільністю, а не «19 с/стор», яке ні з чим не порівняти.
    if got.pace is not None and got.pace.pages:
        console.print(f"⏱ {got.pace.line()}")

    # 🔴 Перед `Exit`, інакше не виконається. Хвіст успішного прогону: у
    # режимі згоди «завжди» пакет збирається й іде в пул сам. У решті
    # режимів функція мовчить, і жодна її невдача не робить із успішного
    # прогону невдалий — код повернення нижче від неї не залежить.
    if rc == 0 and not missing and not partial and case_key:
        _supriaha_autoshare(case_key)

    raise typer.Exit(code=0 if rc == 0 and not missing else 1)


@app.command("case")
def case_cmd(
    case_dir: str = typer.Argument(
        ..., help="ШЛЯХ до теки зі сканами (не шифра — вона йде в --shifra)"),
    shifra: str = typer.Option("", "--shifra", help="«ДАХмО 315-1-8433»"),
    title: str = typer.Option("", "--title", help="назва справи"),
    doc_type: str = typer.Option("", "--type", help="метрична / сповідна / ревізька"),
    year_from: int = typer.Option(0, "--from", help="рік початку"),
    year_to: int = typer.Option(0, "--to", help="рік кінця"),
    place: str = typer.Option("", "--place", help="село, повіт, губернія"),
    note: str = typer.Option("", "--note", help="примітка до справи"),
    film: str = typer.Option("", "--film",
                             help="номер плівки, коли шифру ще не встановлено"),
    dgs: str = typer.Option("", "--dgs",
                            help="номер групи зображень FamilySearch (DGS), якщо "
                                 "кадри в теці — з неї: джерело сканів у паспорті"),
    one_case: bool = typer.Option(False, "--one-case",
                                  help="тека — одна справа, хоч шифра чи ім'я "
                                       "схожі на діапазон справ"),
    adopt: bool = typer.Option(False, "--adopt",
                               help="взяти теку під облік, якщо вона лежить "
                                    "поза простором"),
) -> None:
    """Завести або виправити справу: сказати, що лежить у цій теці.

    🔴 Без шифри тека лишається купою файлів — ні ключа, ні обліку, ні
    можливості послатись на знахідку.

    ⚠ Тека поза простором лишається невидимою в переліках: обхід іде по
    `data/raw` і по оголошених коренях справ. `--adopt` оголошує цю теку
    коренем у `nyshporka.toml` — файли при цьому не переносяться.
    \f
    Прапорця тут довго не було, хоч операція поле мала: єдиним шляхом з командного
    рядка лишався `nysh op case.register --args …`, тобто найпотрібніша
    новачкові дія була доступна найнезручнішим входом.
    """
    from nyshporka import ops as O

    env = O.call("case.register", {
        "case_dir": case_dir, "shifra": shifra, "title": title,
        "doc_type": doc_type, "place": place, "note": note, "film": film,
        "dgs": dgs, "one_case": one_case,
        "year_from": year_from or None, "year_to": year_to or None,
        "adopt": adopt})
    _answer(env)
    sc = env.data["sidecar"]
    # ⚠ Тека без шифри теж описана, і заголовок відповіді мусить це казати
    # прямо: «✅ без назви» на неототожненому матеріалі читалось би як успішно
    # заведена справа.
    head = sc.get("shifra") or f"плівка {sc.get('film') or '?'} · шифру ще не встановлено"
    console.print(f"✅ [bold]{head}[/bold] — {sc.get('title') or 'без назви'}")
    if sc.get("year_from") or sc.get("place"):
        console.print(f"   [muted]{sc.get('place') or ''} "
                      f"{sc.get('year_from') or ''}"
                      f"{'-' + str(sc['year_to']) if sc.get('year_to') else ''}[/muted]")
    kopiia = env.data.get("local_copy") or {}
    if kopiia:
        console.print(f"   [muted]локальна копія FamilySearch DGS {kopiia['dgs']}: "
                      f"кадрів у теці {kopiia['frames']}"
                      + (f", із id кадру FS — {kopiia['with_apid']}"
                         if kopiia.get("fs_meta") else ", `_fs_meta.json` немає")
                      + (f"; реєстр опису чекає {kopiia['expected']}"
                         if kopiia.get("expected") else "") + "[/muted]")
    _notes(env)


@app.command("archive")
def archive_cmd(
    repo: str = typer.Argument(..., help="код архіву: DAHMO, CDIAK, ANRM…"),
    fond: str = typer.Argument(..., help="номер фонду"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що пак знає про фонд: губернія, опис за замовчуванням.

    Опис за замовчуванням іде в ключ справи, чия тека й паспорт опису не
    називають; без нього опис такої справи — «_» (невідомий).
    """
    from nyshporka import ops as O

    env = O.call("archive.fond", {"repo": repo, "fond": fond})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['repo_label'] or d['repo']} ф.{d['fond']}[/bold] "
                  f"{d.get('name') or ''}")
    console.print(f"  губернія: {d.get('guberniya') or '—'} · опис за "
                  f"замовчуванням: {d.get('default_opys') or '—'}")
    if d.get("note"):
        console.print(f"  [muted]{d['note']}[/muted]")
    _notes(env)


# 🔴 Група, але без ламання входу: `nysh profile` без підкоманди й далі показує
# профіль. Заводити його доти не було чим взагалі — `config/` після `nysh init`
# лишалась порожньою, файл не писав ніхто, а команда падала з exit 1 і не
# називала виходу. Тобто екран обіцяв налаштування, якого не існувало.
profile_app = typer.Typer(help="Чий рід шукаємо: форми прізвища, корені, парадигма.",
                          invoke_without_command=True)
app.add_typer(profile_app, name="profile")


@profile_app.callback(invoke_without_command=True)
def profile_root(ctx: typer.Context) -> None:
    """Чий рід шукаємо: форми прізвища, корені, парадигма."""
    if ctx.invoked_subcommand is None:
        profile_cmd(as_json=False)


@profile_app.command("init")
def profile_init(
    display: str = typer.Argument(..., help="прізвище, як воно пишеться: Сікорський"),
    name: str = typer.Option("", "--name", help="ключ профілю; типово — з прізвища"),
    paradigm: str = typer.Option("adj_skyi", "--paradigm",
                                 help=morph.paradigm_ids()),
    orth: str = typer.Option("uk", "--orth",
                             help="якою орфографією подано прізвище: "
                                  "uk | ru_modern | ru_prereform | pl"),
) -> None:
    """Завести профіль дослідження — файл, у якому живе «чий рід шукаємо».

    Основа відсікається за таблицею самої парадигми, форми породжуються з неї.
    Основи на інші орфографії лишаються порожніми навмисно: вивести їх правилом
    не можна (`core.morph`), а вгадана основа мовчки викидає половину написань
    із пошуку — і жодного сліду про це не лишиться.

    🔴 Іде через ту саму операцію, що й форма в браузері.
    \f
    Доти команда писала файл повз реєстр, тобто той самий запис існував двічі — а реєстр операцій
    заведено рівно для того, щоб дія оголошувалась один раз і три обличчя не
    могли розійтись у тому, що вона робить.
    """
    from nyshporka import ops as O

    env = O.call("profile.set", {"display": display, "name": name,
                                 "paradigm": paradigm, "orth": orth})
    if not env.ok:
        console.print(f"[err]{env.error}[/err]")
        raise typer.Exit(code=1)
    d = env.data
    was = {"created": "заведено", "added": "додано", "updated": "оновлено"}
    console.print(f"✅ профіль «{d['name']}» {was.get(d['mode'], d['mode'])}: {d['path']}")
    for w in env.warnings:
        console.print(f"[warn]⚠ {w.text}[/warn]")
    console.print(f"[muted]написань: {len(d.get('spellings') or [])} · "
                  f"перевірити: `nysh profile`[/muted]")


def profile_cmd(as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Чий рід шукаємо: форми прізвища, корені, парадигма.

    🔴 Перше, що варто спитати на чужому просторі: пошук спирається на цей файл,
    а він лежить у просторі, не в пакеті. Без нього прізвище й усі його
    написання доводиться щоразу набирати руками.
    """
    from nyshporka import ops as O

    env = O.call("profile.show", {})
    if _answer(env, as_json):
        return
    d = env.data
    if not d.get("present"):
        # ⚠ Не відмова: на свіжій установці профілю немає ніде, і `nysh init`
        # його не створює. Червоне тут читалось би як поламка, тоді як це
        # нормальний стан із відомим виходом.
        console.print(f"[muted]{d.get('why') or 'профілю ще немає'}[/muted]")
        console.print("завести: `nysh profile init <Прізвище>` "
                      "або у вікні застосунку, розділ «Рід»")
        return
    console.print(f"[bold]{d.get('display') or d.get('name')}[/bold] "
                  f"[muted]парадигма {d.get('paradigm') or '—'}[/muted]")
    console.print(f"  корені: {', '.join(d.get('roots') or []) or '—'}")
    console.print(f"  форми: {len(d.get('spellings') or [])} · "
                  f"самоперевірка: {d.get('selftest_mode')}")


profile_app.command("show")(profile_cmd)


@app.command("search")
def search_cmd(
    q: str = typer.Argument(..., help="прізвище або слово"),
    case: str = typer.Option(
        "", "--case",
        help="лише в цій справі: ключ «DAHMO/315/1/8433», шифра "
             "«ДАХмО 315-1-8433», шлях теки або ім'я прогону"),
    where: str = typer.Option("decode", "--where",
                              help="decode | pages | records | all"),
    context: int = typer.Option(1, "--context",
                                help="рядків сусідства (0 — лише сам рядок)"),
    thresh: int = typer.Option(80, "--thresh", help="поріг схожості 50-100"),
    limit: int = typer.Option(40, "--limit", help="скільки показати"),
    given: bool = typer.Option(
        True, "--given/--no-given",
        help="розкривати гніздо написань імені (Явдоха=Євдокія, Осип=Іосиф)"),
    folk: bool = typer.Option(
        False, "--folk",
        help="додати побутових двійників імені (Васса=Анна) — зв'язок "
             "біографічний, кожен такий хіт звіряти окремо"),
    rank: bool = typer.Option(
        True, "--rank/--no-rank",
        help="опускати вниз те, що профіль пояснює чужим словом. Не викидає"),
    use_profile: bool = typer.Option(
        True, "--profile/--no-profile",
        help="шукати всіма написаннями прізвища з профілю простору"),
    anchors: bool = typer.Option(
        False, "--anchors",
        help="ще й канал імен: ім'я + по батькові роду поруч. Потребує --case"),
    record: bool = typer.Option(
        False, "--record",
        help="ще й канал запису: ознаки роду з різних колонок одного запису. "
             "Потребує --case"),
    family: str = typer.Option(
        "", "--family",
        help="чий рід: ім'я профілю (`nysh profile`); порожньо — рід, "
             "написанням якого є запит"),
    selfcheck: bool = typer.Option(
        False, "--selfcheck",
        help="поміряти, чи бачить пошук аркуші, де прізвище виписане оком. "
             "Потребує --case"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Знайти прізвище в тому, що вже прочитано.

    🔴 Хіт друкується вікном, а не рядком. Рядок сам по собі не розрізняє
    прізвищ зі спільним коренем, а в одній парафії їх буває кілька: заміряно на
    метриках одного села — 78 кандидатів верхівки розклались на три різні роди
    з тим самим коренем плюс причт. Розрізняє їх сусідство: географія стоїть
    рядком вище, перенесена половина слова — нижче.

    Якщо справу читано двома рушіями, поруч іде читання другого: збіг означає
    надійне читання, розбіжність — що ознака в пікселях і судити має око.
    """
    from nyshporka import ops as O

    _need("research")
    env = O.call("search.run", {"q": q, "case": case, "where": where,
                                "context": context, "thresh": thresh,
                                "limit": limit, "given": given, "folk": folk,
                                "rank": rank, "profile": use_profile,
                                "anchors": anchors, "record": record,
                                "family": family,
                                "selfcheck": selfcheck})
    if _answer(env, as_json):
        return
    hits = env.data.get("hits") or []
    for h in hits:
        # 🔴 Три області — три форми хіта, і одна на всіх не працює: рядок
        # декоду має `name/page/line_no/line`, виписане прізвище — `shifra/
        # scan/matched`, розібраний запис — ще й роль та тип акту. Спільний
        # друк по полях декоду віддавав «None · None · рядок None» на
        # виписаному й розібраному, тобто ховав ВЕСЬ вміст відповіді, яка в
        # `--json` була на місці.
        area = str(h.get("area") or "")
        tag = f"[muted]{area}[/muted] " if area else ""
        # 🔴 Написання, яким знайдено, друкується ЛИШЕ коли воно не те, що
        # набрали. Мовчазний хіт по двійнику з довідника читається як хіт по
        # запиту, а важить менше: його ще треба звірити з тим, що шукали саме
        # цю особу.
        why = str(h.get("stem_origin") or "q")
        mark = ""
        if why != "q":
            what = "побутове" if why == "folk" else "довідник"
            mark = f" · [warn]{what}: {h.get('stem')}[/warn]"
        if h.get("line_no") is not None:
            head = f"{h.get('name')} · {h.get('page')} · рядок {h.get('line_no')}"
            console.print(f"[bold]{h.get('score')}[/bold]  {tag}{head}{mark}")
            for b in (h.get("context") or {}).get("before") or []:
                console.print(f"      [muted]↑ {b}[/muted]")
            console.print(f"    [warn]»[/warn] {h.get('line')}")
            for a in (h.get("context") or {}).get("after") or []:
                console.print(f"      [muted]↓ {a}[/muted]")
            if h.get("alt"):
                console.print(f"      [accent]2-й голос:[/accent] "
                              f"[muted]{h['alt']['line']}[/muted]")
            continue
        scan = h.get("scan") or ", ".join(h.get("scans") or []) or "?"
        head = f"{h.get('shifra') or h.get('key')} · скан {scan}"
        console.print(f"[bold]{h.get('score')}[/bold]  {tag}{head}{mark}")
        console.print(f"    [warn]»[/warn] {h.get('matched') or h.get('name')}")
        # Роль і тип акту — не оформлення: «батько» і «восприємник» це різні
        # відповіді на те саме прізвище.
        bits = [str(x) for x in (h.get("role"), h.get("rtype"), h.get("date"),
                                 h.get("place"), h.get("page_type"),
                                 h.get("status")) if x]
        if bits:
            console.print(f"      [muted]{' · '.join(bits)}[/muted]")
        if h.get("comment"):
            console.print(f"      [muted]{str(h['comment'])[:160]}[/muted]")
    # ⚓ Канал імен друкується ОКРЕМИМ блоком. Домішати його до прізвищних
    # рядків означало б стерти різницю між «тут наше прізвище» і «тут наші
    # люди» — а це різні за силою відповіді.
    anchor = env.data.get("coverage", {}).get("anchor") or {}
    for h in (anchor.get("hits") or []):
        console.print(f"[accent]⚓[/accent]  {h.get('name')} · {h.get('page')} · "
                      f"рядок {h.get('line_no')} · [warn]{h.get('matched')}[/warn]")
        console.print(f"    [muted]{h.get('line')}[/muted]")
    from nyshporka.search.cli import print_records

    print_records((env.data.get("coverage", {}).get("record") or {}).get("hits") or [])
    # 🔴 Знаменник друкується завжди, і найважливіший він саме при нулі:
    # без нього «не знайшлось» читається як «цього не існує».
    _notes(env)
    # 🔴 При `--where all` знаменники НЕ складаються: прогони декоду й справи
    # виписаного це різні одиниці. Друкуються поруч, кожен зі своєю назвою.
    areas = (env.data.get("coverage") or {}).get("areas") or {}
    for name, info in areas.items():
        cov = info.get("coverage") or {}
        if info.get("error"):
            console.print(f"[muted]{name}: відмова — {info['error']}[/muted]")
        elif cov.get("runs") is not None:
            console.print(f"[muted]{name}: {info.get('total', 0)} · прогонів "
                          f"{cov.get('runs')}, сторінок {cov.get('pages')}[/muted]")
        else:
            console.print(f"[muted]{name}: {info.get('total', 0)} · справ "
                          f"{cov.get('cases')}[/muted]")
    console.print(f"[muted]показано {len(hits)} із {env.data.get('total', len(hits))}[/muted]")
    from nyshporka.search import reach as _reach

    okhopleno = _reach.line((env.data.get("coverage") or {}).get("reach") or {})
    if okhopleno:
        from rich.markup import escape

        console.print(f"[muted]{escape(okhopleno)}[/muted]")
    if hits:
        console.print("[muted]подивитись оком: гортач у `nysh serve` — і брати "
                      "line_index, не line_no[/muted]")


@app.command("review")
def review_cmd(
    source: str = typer.Option("", "--source", help="лише з цього джерела"),
    min_score: float = typer.Option(0.0, "--min-score",
                                   help="лише кандидати з балом не нижче цього"),
) -> None:
    """Перебрати кандидатів із зовнішніх джерел: рішення за людиною.

    🔴 Жоден кандидат не потрапляє в канон машиною. Це не обережність, а
    вимірювана вартість: збіг прізвища й десятиліття дає правдоподібну, але
    чужу особу, і виявляється це через покоління дерева.

    Кандидатів додають завантажувачі зовнішніх сайтів, яких у цій версії ще
    немає (умови використання чужих сервісів), тож на щойно створеному
    просторі черга буде порожня — це стан, а не поламка.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.matching.review import review_loop

    _need("research")
    review_loop(workspace().root, source=source or None, min_score=min_score,
                console=console)


def _dali_pislia_zavantazhennia(dest: Any) -> None:
    """Сказати, що кадри на диску — ще не справа в обліку.

    🔴 Завантаження закінчувалось словом «готово», а тека без шифри не
    потрапляла ні в каталог, ні в читання, ні у віддачу — і ніде не було
    сказано чому (звіт користувача 29.09.2026: двадцять справ із `meta.json`
    завантажувача й без реєстрації). Порада стоїть тут, бо саме тут людина ще
    пам'ятає, яку справу качала.
    """
    from rich.markup import escape

    try:
        from nyshporka.cases.chain import after_fetch

        lanka = after_fetch(Path(dest))
    except Exception:       # порада не має права зламати завантаження
        return
    if lanka is None:
        return
    console.print("[warn]⚠ кадри на диску, але справу ще не зареєстровано:[/warn] "
                  f"[muted]{escape(lanka.why)}[/muted]")
    console.print(f"  далі: {escape(lanka.fix)}")


cases_app = typer.Typer(help="Реєстр справ: що є, що прочитано, що прошукано.",
                        no_args_is_help=True)
app.add_typer(cases_app, name="cases")

# 🗺 Газетир: від села до справ по всіх фондах — зворотний напрям до реєстру
# опису. Модуль існував, але зареєстрований не був: команди `nysh geog …` не
# існувало, хоч код і повідомлення на неї вже посилались (глухий кут у сенсі
# `test_no_dead_ends`).
# ⛪ Парафії й зведені книги: канал, якого немає в описі — чия це церква
# і які села всередині книги повіту. Стоїть поруч із газетиром: той веде від
# села до фондів одного архіву, цей — до парафій у всіх архівах покажчика.
from nyshporka.parish.cli import app as parish_app  # noqa: E402

app.add_typer(parish_app, name="parish")

from nyshporka.geog.cli import app as geog_app  # noqa: E402
from nyshporka.geog.cli import church_app  # noqa: E402

app.add_typer(geog_app, name="geog")
# ⛪ Церкви ~1772 (база Шади): чи була в селі парафія до поділів, чия, і — через
# зшивку з газетиром — де тепер її книги. Третє питання поруч із газетиром
# («де книги») і покажчиком («чия парафія в описі»).
app.add_typer(church_app, name="church")

# 🗄 Текстовий стор: усе прочитане в одному файлі, регекс і стан індексу без
# обходу дерева прогонів. Секція та сама, що й у пошуку.
from nyshporka.search.cli import app as text_app  # noqa: E402

app.add_typer(text_app, name="text")

# 🗂 Каталог — довідники, які їдуть у комплекті й оновлюються окремо від коду.
from nyshporka.catalog.cli import app as catalog_app  # noqa: E402

app.add_typer(catalog_app, name="catalog")

from nyshporka.fonds.cli import app as registry_app  # noqa: E402

app.add_typer(registry_app, name="registry")

# ☁️ Читання на чужій машині. Секція та сама, що й у локального читання, — це
# те саме читання, лише там, де ядер більше (найдорожче в сторінці рахує
# процесор, а не карта). Окремої секції немає навмисно: вкладка, порожня без
# стороннього плагіна, була б обіцянкою без входу.
from nyshporka.cloud.cli import app as cloud_app  # noqa: E402

app.add_typer(cloud_app, name="cloud")

# 🧪 Лабораторія: розмітка рядків і трен Писаря. Секція `lab`.
from nyshporka.train.cli import app as train_app  # noqa: E402

app.add_typer(train_app, name="train")

# 🤝 Обмін прочитаним між дослідниками (Супряга). Секція та сама, що й у
# читання: пакет несе рівно те, що дав рушій, і без прочитаного тут нема чого
# віддавати.
from nyshporka.queue.cli import app as queue_app  # noqa: E402
from nyshporka.share.cli import app as share_app  # noqa: E402

app.add_typer(share_app, name="share")
app.add_typer(queue_app, name="queue")


@cases_app.command("build")
def cases_build(
    rescan: bool = typer.Option(True, "--rescan/--no-rescan",
                                help="перечитати ще й диск (нові теки)"),
    fetch_cloud: bool = typer.Option(
        False, "--fetch-cloud",
        help="стягнути PDF, вивантажені в хмару (OneDrive / iCloud «лише онлайн»), "
             "щоб порахувати їх сторінки; число запам'ятовується, і вдруге файл "
             "не відкривається"),
) -> None:
    """Зібрати реєстр справ.

    🔴 Реєстр — це зріз п'яти сховищ, а не сховище, і він старіє за хвилини:
    застарілий зріз виглядає як відповідь («декоду немає») там, де роботу
    зробили годину тому. Тому перезбирати його треба після кожного прогону,
    завантаження й занесення в облік.
    \f
    Команди для цього довго не існувало, хоч усі повідомлення на неї посилались.
    """
    from nyshporka import pdfcount
    from nyshporka.cases import db
    from nyshporka.library import renamed_report

    res = db.rebuild(rescan=rescan, fetch_cloud=fetch_cloud)
    if res["rescanned"]:
        console.print(f"[muted]бібліотеку перезібрано: {res['entries']} справ[/muted]")
    for line in renamed_report():
        console.print(f"[warn]{line}[/warn]")
    if res["cloud"]["skipped"]:
        console.print(f"[warn]⚠ {pdfcount.describe(res['cloud']['skipped'])}[/warn]")
    console.print(f"✅ реєстр: [bold]{res['cases']}[/bold] справ · "
                  f"нерозв'язаних прогонів: {res.get('orphans', 0)} · {res['path']}")


@cases_app.command("rekey")
def cmd_rekey(
    do: bool = typer.Option(False, "--apply", help="перенести (з архівом для відкату)"),
    back: bool = typer.Option(False, "--rollback", help="відкотити останній перенос"),
    stamp: str = typer.Option("", "--stamp", help="який перенос відкотити (тека в data/cases/rekey/)"),
    force: bool = typer.Option(False, "--force",
                               help="відкотити, хоч після переносу файли змінювались"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перенести облік простору на ключі з описом (`REPO/фонд/опис/справа`).

    Без прапорців — лише план: що зміниться, що злиється, чого не перевести.
    Нічого не пише. `--apply` переносить: спершу архів усього, що зачіпається
    (`data/cases/rekey/<час>/backup.zip`), потім запис, перебудова бібліотеки й
    реєстру, самоперевірка й позначка `keys = 2` у маркері простору.
    `--rollback` повертає файли з архіву.

    🔴 Переносити, коли інші сесії й застосунок зупинено: запис у сховище
    сторінок посеред переносу ліг би під старий ключ.
    """
    import json

    from nyshporka.cases import rekey as RK

    try:
        if back:
            got = RK.rollback(stamp or None, force=force)
            if as_json:
                console.print_json(json.dumps(got, ensure_ascii=False))
                return
            console.print(f"✅ відкочено перенос {got['stamp']}: повернуто файлів "
                          f"{got['restored']}, прибрано створених {got['removed']}")
            return
        if do:
            got = RK.apply()
            if as_json:
                console.print_json(json.dumps(got, ensure_ascii=False))
                return
            if got.get("noop"):
                console.print("Простір уже на ключах з описом; переносити нічого.")
                return
            mark = "⚠" if got["problems"] else "✅"
            console.print(f"{mark} перенесено: файлів сторінок {got['pages']}, сховищ "
                          f"{len(got['stores'])}; архів — {got['backup']}")
            stuck = got.get("stuck") or {}
            if stuck:
                console.print(f"  [warn]не переведено ({sum(len(v) for v in stuck.values())})"
                              f" — лишилось як є:[/warn]")
                for store, keys in sorted(stuck.items()):
                    console.print(f"  [warn]  {store}: {', '.join(keys[:5])}"
                                  f"{' …' if len(keys) > 5 else ''}[/warn]", markup=True)
            for p in got["problems"]:
                console.print(f"  [warn]{p}[/warn]")
            if got["problems"]:
                console.print(f"  [warn]відкат: nysh cases rekey --rollback --stamp "
                              f"{got['stamp']}[/warn]")
                raise typer.Exit(1)
            return
        pl = RK.plan()
    except RK.RekeyError as exc:
        console.print(f"[warn]{exc}[/warn]")
        raise typer.Exit(1) from None
    if as_json:
        console.print_json(json.dumps(pl.as_dict(), ensure_ascii=False))
        return
    console.print(RK.report(pl), end="", highlight=False, markup=False)


@cases_app.command("list")
def cases_list_cmd(
    q: str = typer.Option("", "--q", help="підрядок: шифра, назва, місце"),
    repo: str = typer.Option("", "--repo", help="лише цей архів: DAHMO, CDIAK…"),
    year: str = typer.Option("", "--year", help="рік або «1840-1860»"),
    kind: str = typer.Option("", "--kind",
                             help="case | bundle | unfiled (матеріал без шифри)"),
    limit: int = typer.Option(40, "--limit", help="скільки показати"),
) -> None:
    """Перелік справ із станом обробки."""
    from nyshporka import ops as O

    env = O.call("cases.list", {"q": q, "repo": repo, "year": year,
                                "kind": kind, "limit": limit})
    _answer(env)
    from rich.table import Table as _T

    t = _T(header_style="bold")
    for col in ("шифра", "назва", "кадрів", "читання"):
        t.add_column(col, max_width=44, no_wrap=True, overflow="ellipsis")
    for r in env.data.get("cases") or []:
        t.add_row(r.get("shifra") or r.get("key") or "",
                  (r.get("title") or "[muted]без назви[/muted]")[:60],
                  str(r.get("frames") or 0),
                  r.get("htr_stage") or "—")
    console.print(t)
    if env.stale and env.stale.is_stale:
        console.print(f"[warn]⚠ зріз застарів[/warn] [muted]"
                      f"{'; '.join(env.stale.reasons[:2])} — nysh cases build[/muted]")


@cases_app.command("split")
def cases_split_cmd(
    case_dir: str = typer.Argument(..., help="збірна тека — кадри кількох справ"),
    part: list[str] = typer.Option(
        [], "--part",
        help="«<справа>=<перший файл>..<останній файл>»; кадри поза справами — «-=…»"),
    map_file: str = typer.Option("", "--map", help="файл карти JSON замість --part"),
    dry: bool = typer.Option(False, "--dry-run", help="лише показати, що буде зроблено"),
    copy: bool = typer.Option(False, "--copy",
                              help="копіювати кадри, якщо жорстке посилання не створюється"),
    undo: bool = typer.Option(False, "--undo", help="зняти розбивку цієї теки"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Розкласти збірну теку на справи.

    Межі справ називаєте ви — іменами файлів. Нічого не видаляється: теки
    справ — жорсткі посилання на ті самі кадри, стара тека лишається.
    """
    from rich.markup import escape as _e

    from nyshporka import ops as O
    from nyshporka.cli_emit import answer, notes

    env = O.call("cases.split", {"case_dir": case_dir, "parts": part, "map_file": map_file,
                                 "dry_run": dry, "copy_frames": copy, "undo": undo})
    if answer(env, as_json):
        return
    d = env.data or {}
    if undo:
        console.print(f"розбивку знято: {_e(str(d.get('case_dir')))} · прибрано "
                      f"прогонів: {len(d.get('runs_removed') or [])}")
        for row in d.get("kept") or []:
            console.print(f"  [warn]{_e(row)}[/warn]")
        notes(env)
        return
    console.print(f"[bold]{_e(str(d.get('case_dir')))}[/bold] — {d.get('frames')} кадрів"
                  + (" · проба, нічого не змінено" if d.get("dry_run") else " · розкладено"))
    for p in d.get("parts") or []:
        name = p["shifra"] or "поза справами"
        console.print(f"  {_e(name):<26} кадри {p['from']}–{p['to']} "
                      f"({p['frames']}): {_e(p['first'])} … {_e(p['last'])}")
        if p.get("dir"):
            console.print(f"    [muted]→ {_e(p['dir'])}"
                          + (f" · нотаток сторінок: {p['notes']}" if p.get("notes") else "")
                          + "[/muted]")
        for old, new in (p.get("runs") or {}).items():
            console.print(f"    [muted]прогін {_e(old)} → {_e(new)}[/muted]")
    notes(env)


@cases_app.command("chain")
def cases_chain_cmd(
    show_all: bool = typer.Option(False, "--all",
                                  help="показати й теки без обриву"),
    quick: bool = typer.Option(False, "--quick",
                               help="без обходу диска — лише те, що реєстр уже знає"),
    limit: int = typer.Option(12, "--limit", help="скільки тек показати на ланку"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Де обірвано ланцюг справи: скани → паспорт → каталог → прогін.

    Для кожної теки зі сканами каже, на якій ланці вона стоїть, і дає команду,
    що веде далі. `meta.json` завантажувача — запис про завантаження, а не
    паспорт справи: тека з ним і без шифри в каталог не потрапляє.
    """
    from rich.markup import escape

    from nyshporka import ops as O
    from nyshporka.cases import chain as C

    env = O.call("cases.chain", {"all": show_all, "walk": not quick})
    if as_json:
        console.print_json(data=env.data if env.ok else {"error": env.error})
        raise typer.Exit(code=0 if env.ok else 1)
    if not env.ok:
        console.print(f"[warn]⚠ {escape(str(env.error))}[/warn]")
        raise typer.Exit(code=1)
    data = env.data
    lich = data["summary"]
    by_link: dict[str, list[dict[str, Any]]] = {}
    for r in data["rows"]:
        by_link.setdefault(r["link"], []).append(r)
    order = (*C.BREAKS, C.NO_RUN, C.PARTIAL_RUN, C.OK)
    for link in order:
        rows = by_link.get(link) or []
        if not rows:
            continue
        mark = "[warn]✗[/warn]" if link in C.BREAKS else "·"
        console.print(f"\n{mark} [bold]{C.NAZVY[link]}[/bold] — {lich[link]}")
        for r in rows[:limit]:
            odyn = "стор." if link == C.ORPHAN_RUN else "кадр."
            kadry = f" · {r['frames']} {odyn}" if r["frames"] else ""
            console.print(f"  {escape(r['path'])}{kadry}")
            if r["why"]:
                console.print(f"     [muted]{escape(r['why'])}[/muted]")
            if r["fix"]:
                console.print(f"     → {escape(r['fix'])}")
        if len(rows) > limit:
            console.print(f"  [muted]… і ще {len(rows) - limit} (--limit N, --json)[/muted]")
    # Знаменник: скільки тек пройдено і скільки з них дійшли до каталогу.
    cili = data["folders"] - sum(lich[k] for k in C.BREAKS if k != C.ORPHAN_RUN)
    zvidky = "обхід диска" if data["walked"] else "реєстр, без обходу диска"
    console.print(f"\nтек із матеріалом: [bold]{data['folders']}[/bold] ({zvidky}) · "
                  f"дійшли до каталогу: {cili} · обривів: {data['broken']}")
    if not show_all and not data["broken"]:
        console.print("✅ ланцюг цілий: кожна тека зі сканами має справу")
    if not show_all:
        console.print(f"[muted]не читано: {lich[C.NO_RUN]} · частково: "
                      f"{lich[C.PARTIAL_RUN]} · прочитано: {lich[C.OK]} "
                      f"(перелік: --all)[/muted]")


@cases_app.command("bind")
def cases_bind_cmd(
    run: str = typer.Argument(..., help="ім'я теки прогону в reports/htr"),
    key: str = typer.Argument(..., help="ключ справи: DAHMO/315/159"),
    why: str = typer.Option("", "--why", help="на чому стоїть рішення"),
) -> None:
    """Прив'язати прогін до справи руками — коли автомат не може.

    Найчастіший випадок: прогін зроблено в хмарі, і в його меті лишився шлях
    орендованого боксу. Декод є, а показати аркуш нічим, бо невідомо, де кадри.
    """
    from nyshporka import ops as O

    env = O.call("cases.bind", {"run": run, "key": key, "why": why})
    _answer(env)
    console.print(f"✅ {env.data['run']} → {env.data['key']}")
    _notes(env)
    console.print("[muted]реєстр треба перезібрати: nysh cases build[/muted]")


# 🗂 Корені справ — теки зі сканами поза простором. Оголошення робилось лише
# побічним ефектом заведення справи (`nysh case --adopt`), а воно вимагає
# шифри — тобто накрити теку-контейнер із десятками книг було нічим: шифра на
# контейнер злила б їх в одну справу. Лишалось правити `nyshporka.toml` руками,
# а це файл, якого людина не заводила.
roots_app = typer.Typer(help="Теки зі сканами, що лежать поза простором.",
                        no_args_is_help=True)
app.add_typer(roots_app, name="roots")


@roots_app.command("list")
def roots_list_cmd() -> None:
    """Де застосунок шукає справи — і що з цього оголошено руками."""
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None

    # 🔴 Перелік будується з оголошеного, а не з `case_roots()`: той віддає лише
    # теки, які зараз існують. Зовнішній диск від'єднують — і корінь мовчки
    # зникає з переліку разом зі справами, тобто рівно там, де людині потрібна
    # причина, вона бачить порожнє місце й читає це як поламку застосунку.
    rows = [(ws.raw, "простір"), *((p, "оголошено") for p in ws.extra_case_roots)]
    for path, origin in rows:
        gone = "" if path.is_dir() else "  [warn]← теки немає[/warn]"
        console.print(f"  [muted]{origin}[/muted]  {path}{gone}")
    console.print(f"[muted]усього {len(rows)} · "
                  f"додати — nysh roots add <тека>[/muted]")


@roots_app.command("add")
def roots_add_cmd(
    path: str = typer.Argument(..., help="тека зі сканами: справа або контейнер справ"),
) -> None:
    """Оголосити теку зі сканами — обхід бачитиме її там, ДЕ вона лежить.

    🔴 Файли не переносяться й не копіюються. Оголошення явне й записується в
    маркер простору, бо це розширення зони, у якій застосунок дозволяє собі
    читати диск, — і переїжджає воно разом із простором.

    ⚠ Шифра тут, на відміну від `nysh case --adopt`, не потрібна: контейнер із
    десятками книг справою не є, і дати йому шифру означало б оголосити їх
    однією справою.
    """
    from nyshporka.core.workspace import WorkspaceError, add_case_root

    try:
        root = add_case_root(path)
    except WorkspaceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    console.print(f"✅ корінь справ: [bold]{root}[/bold]")
    console.print("[muted]далі: `nysh cases build`, потім `nysh cases list`[/muted]")


@roots_app.command("remove")
def roots_remove_cmd(
    path: str = typer.Argument(..., help="оголошений корінь — як у `nysh roots list`"),
) -> None:
    """Зняти оголошений корінь. Скани лишаються на місці."""
    from nyshporka.core.workspace import WorkspaceError, remove_case_root

    try:
        gone = remove_case_root(path)
    except WorkspaceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    if not gone:
        console.print("[warn]![/warn] такого кореня не оголошено "
                      "[muted](перелік — nysh roots list)[/muted]")
        raise typer.Exit(code=1)
    console.print(f"✅ знято: {path}")
    console.print("[muted]файли не чіпались; справи з цієї теки зникнуть із "
                  "реєстру після `nysh cases build`[/muted]")


pages_app = typer.Typer(help="Облік переглянутого оком.", no_args_is_help=True)
app.add_typer(pages_app, name="pages")

# 📓 Нотатник справи: звірене оком, опис, помилки опису, копії — у тому самому
# файлі сховища сторінок. Загальне знання їде в пул окремо від тексту.
from nyshporka.note.cli import app as note_app  # noqa: E402

app.add_typer(note_app, name="note")


@pages_app.command("status")
def pages_status_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    scans: str = typer.Option("", "--scans",
                              help="кома-список сканів: питати про ці аркуші, "
                                   "а не про справу цілком"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що в цій справі вже дивились, а що ні — перед тим, як відкривати."""
    from nyshporka import ops as O

    env = O.call("pages.status", {"case": case, "scans": scans})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['shifra']}[/bold] {d.get('title') or ''}")
    # 🔴 Дві форми відповіді, а не одна з полем більше: питання про названі
    # аркуші й питання про справу — різні, і зведення («на диску», «статуси»)
    # у першому просто немає. Поки друкувалка була одна, точковий режим
    # падав `KeyError` рівно на тому полі, заради якого його кличуть.
    if d.get("scans") is not None:
        for s in d["scans"]:
            if s["noted"]:
                console.print(f"  ✅ {s['scan']} — дивились "
                              f"({s['page_type']}/{s['status']}, прізвищ "
                              f"{s['surnames_n']}, {s['noted_date']})")
            else:
                console.print(f"  ▫️ {s['scan']} — не заносили")
        _notes(env)
        return
    console.print(f"  на диску: {d.get('total_disk', 0)} · анотовано: {d['noted']} "
                  f"· записів: {d['records']} · статуси: {d.get('by_status') or {}}")
    if d.get("unnoted_count"):
        console.print(f"  [warn]необроблених: {d['unnoted_count']}[/warn]")


@pages_app.command("note")
def pages_note_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    scan: str = typer.Argument(..., help="голе ім'я файлу: 0030.JPG"),
    page_type: str = typer.Option(..., "--type", help=_PAGE_TYPES_HELP),
    surnames: str = typer.Option("", "--surnames", help="кома-список ЯК У джерелі"),
    places: str = typer.Option("", "--places", help="кома-список місць, як у джерелі"),
    years: str = typer.Option("", "--years", help="кома-список років: 1858,1859"),
    sheet: str = typer.Option("", "--sheet", help="архівний аркуш: 31зв-32"),
    status: str = typer.Option(None, "--status", help=_PAGE_STATUS_HELP),
    method: str = typer.Option("visual", "--method", help=_PAGE_METHOD_HELP),
    comment: str = typer.Option("", "--comment",
                                 help="що на сторінці й чому це не те, що шукали"),
    agent: str = typer.Option("", "--agent",
                              help="хто заносив: ім'я людини або сесії"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Занести переглянуту сторінку.

    🔴 без винятків: кожен скан, який реально відкривали, заноситься — навіть
    якщо він виявився пустишкою. Негативний результат коштує тих самих очей, а
    без запису наступна сесія перегляне той самий аркуш ще раз.
    """
    from nyshporka import ops as O

    env = O.call("pages.note", {
        "case": case, "scan": scan, "page_type": page_type,
        "surnames": surnames, "places": places, "years": years, "sheet": sheet,
        "status": status, "method": method, "comment": comment, "agent": agent})
    if _answer(env, as_json):
        return
    console.print(f"✅ {env.data['shifra']} {scan}")
    _notes(env)


@pages_app.command("note-batch")
def pages_note_batch_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    file: Path = typer.Option(None, "-f", "--file",
                              help="JSON-масив анотацій; без -f — читаємо stdin"),
    replace: bool = typer.Option(False, "--replace",
                                 help="замінити наявні, а не домержити"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Занести переглянуті сторінки пачкою: аркуші заносять десятками.

    🔴 Крива анотація не забирає з собою решту: валідні лягають, невалідні
    вертаються переліком. Втратити сорок сторінок через одну одруківку — гірше,
    ніж занести тридцять дев'ять і назвати сорокову.
    """
    import sys as _sys

    from nyshporka import ops as O

    text = file.read_text(encoding="utf-8") if file else _sys.stdin.read()
    env = O.call("pages.note_batch",
                 {"case": case, "notes": text, "replace": replace})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"✅ {d['shifra']}: додано {len(d.get('added') or [])}, "
                  f"домержено {len(d.get('merged') or [])}, "
                  f"замінено {len(d.get('replaced') or [])}, "
                  f"не прийнято {d.get('failed', 0)}")
    _notes(env)


@pages_app.command("grep")
def pages_grep_cmd(
    q: str = typer.Argument(..., help="прізвище або назва місця"),
    where: str = typer.Option("pages", "--where", help="pages | records | decode"),
    case: str = typer.Option("", "--case", help="лише в цій справі"),
    axis: str = typer.Option("name", "--axis",
                             help="name — по прізвищу · place — по місцю "
                                  "(лише pages|records)"),
    role: str = typer.Option("", "--role", help=_ROLES_HELP),
    rtype: str = typer.Option("", "--rtype", help=_RTYPES_HELP),
    thresh: int = typer.Option(80, "--thresh", help="поріг схожості 50-100"),
    limit: int = typer.Option(50, "--limit", help="скільки показати"),
    given: bool = typer.Option(
        True, "--given/--no-given",
        help="розкривати гніздо написань імені (Явдоха=Євдокія)"),
    folk: bool = typer.Option(
        False, "--folk", help="додати побутових двійників імені (Васса=Анна)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Знайти прізвище в тому, що вже прочитано."""
    from nyshporka import ops as O

    env = O.call("search.run", {"q": q, "where": where, "case": case,
                                "axis": axis, "role": role, "rtype": rtype,
                                "thresh": thresh, "limit": limit,
                                "given": given, "folk": folk})
    if _answer(env, as_json):
        return
    is_rec = where == "records"
    for h in (env.data.get("hits") or [])[:limit]:
        # 🔴 `matched` — найцінніше в знахідці, і саме його друкувалка й губила:
        # шукали «Ковальський», а в джерелі стоїть «Ковальскій». Заради цієї
        # різниці пошук і фаззі; без неї на екрані лишався голий номер скана.
        what = str(h.get("matched") or h.get("line") or h.get("text")
                   or h.get("surname") or h.get("name") or "")
        score = h.get("score")
        # 🔴 Хіт запису — інша форма, а не бідніша: аркуш у ньому лежить під
        # `scans` (їх буває кілька на один акт), а `scan` немає зовсім. Поки
        # форма була одна на всіх, колонка аркуша в записах стояла порожня —
        # тобто зникало саме те, чим знахідку перевіряють.
        sheet = (", ".join(h.get("scans") or []) if is_rec
                 else h.get("scan") or h.get("page") or "")
        role_col = f"{h.get('role') or ''}: " if is_rec and h.get("role") else ""
        tail = ""
        if is_rec:
            tail = "  " + " · ".join(
                x for x in (h.get("rtype"), h.get("date"), h.get("place")) if x)
        console.print(f"  [bold]{h.get('case') or h.get('shifra') or h.get('key') or ''}"
                      f"[/bold] {sheet}  {role_col}{what[:80]}"
                      + (f" [muted]{score}[/muted]" if score is not None else "")
                      + (f" [muted]{tail}[/muted]" if tail.strip() else ""))
    _notes(env)


@pages_app.command("show")
def pages_show_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    scan: str = typer.Argument("", help="одна сторінка: голе ім'я файлу"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Показати занесене про справу як воно лежить у сховищі."""
    from nyshporka import ops as O

    env = O.call("pages.show", {"case": case, "scan": scan})
    if _answer(env, as_json):
        return
    console.print_json(data=env.data)
    _notes(env)


records_app = typer.Typer(help="Розібрані записи джерела: хто, коли, чиї.",
                          no_args_is_help=True)
app.add_typer(records_app, name="records")


@records_app.command("add")
def records_add_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    # ⚠ Вхід через `-f/--file`, як у `pages note-batch`. Доти `--json` тут
    # означав ФАЙЛ, а в сусідній команді — машинний вивід: те саме слово в
    # тому самому обліку робило дві протилежні речі.
    file: Path = typer.Option(None, "-f", "--file",
                              help="JSON-масив записів; без -f — читаємо stdin"),
    replace: bool = typer.Option(False, "--replace",
                                 help="🔴 стерти ВСІ наявні записи справи"),
    confirm: int = typer.Option(-1, "--confirm",
                                help="скільки записів дозволено стерти — "
                                     "число беруть із відмови на --replace"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Занести розібрані акти структурою, а не прозою.

    Проза не шукається за роллю: «хто був батьком» і «хто був восприємником» у
    ній однакові рядки. Невалідні елементи пропускаються зі звітом — не
    втрачати сорок розібраних актів через одруківку в сорок першому.
    """
    from nyshporka import ops as O

    payload = (file.read_text(encoding="utf-8") if file else sys.stdin.read())
    env = O.call("records.add", {"case": case, "records": payload,
                                 "replace": replace, "confirm": confirm})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"✅ [bold]{d.get('shifra') or d.get('case')}[/bold] "
                  f"додано: {d.get('added', 0)} · оновлено: {d.get('updated', 0)}")
    _notes(env)


@records_app.command("grep")
def records_grep_cmd(
    q: str = typer.Argument(..., help="прізвище або назва місця"),
    case: str = typer.Option("", "--case", help="лише в цій справі"),
    role: str = typer.Option("", "--role", help=_ROLES_HELP),
    rtype: str = typer.Option("", "--rtype", help=_RTYPES_HELP),
    axis: str = typer.Option("name", "--axis", help="name — по прізвищу · "
                                                   "place — по місцю"),
    thresh: int = typer.Option(80, "--thresh", help="поріг схожості 50-100"),
    limit: int = typer.Option(50, "--limit", help="скільки показати"),
    given: bool = typer.Option(
        True, "--given/--no-given",
        help="розкривати гніздо написань імені (Явдоха=Євдокія)"),
    folk: bool = typer.Option(
        False, "--folk", help="додати побутових двійників імені (Васса=Анна)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Знайти прізвище серед розібраних записів — за роллю й типом акту.

    \f
    ⚠ Сусідня команда кличеться як звичайна функція, тож КОЖЕН її параметр
    треба передати явно: неназваний прийде сюди об'єктом `typer.Option`, а не
    своїм значенням, і операція відмовить на перевірці типу. Саме так поїхали
    сім тестів, коли до `pages grep` додали два нові прапорці, а тут ні.
    """
    pages_grep_cmd(q=q, where="records", case=case, axis=axis, role=role,
                   rtype=rtype, thresh=thresh, limit=limit,
                   given=given, folk=folk, as_json=as_json)


@records_app.command("show")
def records_show_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    rid: str = typer.Argument(..., help="id запису — з `records grep`"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Показати один розібраний запис як він лежить у сховищі."""
    from nyshporka import ops as O

    env = O.call("pages.show", {"case": case, "rid": rid})
    if _answer(env, as_json):
        return
    console.print_json(data=env.data)
    _notes(env)


@records_app.command("prep")
def records_prep_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    scans: str = typer.Option("all", "--scans", help="«0022-0024,0461» або «all»"),
    prof: str = typer.Option("", "--profile", help="профіль книги; типово — за справою"),
    rows: int = typer.Option(0, "--rows", help="смуг на сторінку; 0 = з профілю"),
    only: str = typer.Option("", "--only", help="лише ці тайли: head/full/left/right"),
    force: bool = typer.Option(False, "--force", help="різати й вичитані начисто"),
    refresh: bool = typer.Option(False, "--refresh", help="перерізати, ігноруючи кеш"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Нарізати розворот на тайли, які модель справді читає.

    🔴 Розворот метричної книги — ~4000×3000, модель бачить його в 0.39×, і
    скоропис розсипається. Провал такої вичитки виглядає не помилкою, а
    впевнено неправильним текстом.

    Сам розбір робить агент — ваш і вашим ключем. Команда друкує, у що це
    обійдеться, ДО того, як ви почнете книгу на дві сотні аркушів.
    """
    from nyshporka import ops as O

    env = O.call("records.prep", {"case": case, "scans": scans, "profile": prof,
                                  "rows": rows, "only": only, "force": force,
                                  "refresh": refresh})
    if _answer(env, as_json):
        return
    d = env.data
    made = d["prepared"]
    cached = sum(1 for item in made if item["cached"])
    tail = f", з кешу {cached}" if cached else ""
    console.print(f"[bold]{d['shifra']}[/bold] — нарізано {len(made)} сканів "
                  f"[dim](профіль {d['profile']}{tail})[/dim]")
    for item in made[:20]:
        mark = " [dim](з кешу)[/dim]" if item["cached"] else ""
        console.print(f"  {item['scan']}: {item['tiles']} тайлів → "
                      f"{item['dir']}{mark}")
    if len(made) > 20:
        console.print(f"  [dim]…ще {len(made) - 20}[/dim]")
    console.print(f"Контракт вичитки для агента: [accent]{d['contract']}[/accent]")
    _notes(env)


@records_app.command("ingest")
def records_ingest_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    from_json: str = typer.Option("-", "--file", help="файл; «-» — stdin"),
    dir_: str = typer.Option("", "--dir", help="тека з JSON-виводами: усі за раз"),
    replace: bool = typer.Option(False, "--replace",
                                 help="замінити анотації сторінок повністю"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прийняти вивід вичитки: сторінки й акти одним JSON.

    Невалідний елемент не валить батч: лягає все, що пройшло перевірку, а решта
    повертається переліком — щоб виправити саме її, а не читати сторінку вдруге.
    """
    from nyshporka import ops as O

    payload = ""
    if not dir_:
        payload = (sys.stdin.read() if from_json == "-"
                   else Path(from_json).read_text(encoding="utf-8"))
    env = O.call("records.ingest", {"case": case, "payload": payload,
                                    "dir": dir_, "replace": replace})
    if _answer(env, as_json):
        return
    d = env.data
    refused = f", не пройшло {d['failed']}" if d["failed"] else ""
    console.print(f"✅ [bold]{d['shifra']}[/bold]: сторінок {d['pages']}, "
                  f"актів {d['records']}{refused}")
    for e in d.get("errors", [])[:10]:
        console.print(f"  [warn]{e['kind']} #{e['index']}:[/warn] "
                      f"[muted]{e['error'][:200]}[/muted]")
    _notes(env)


@records_app.command("audit")
def records_audit_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    prof: str = typer.Option("", "--profile", help="профіль книги"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Чексуми книги: діри в нумерації й розбіжність із власним підсумком.

    🔴 Єдиний доказ повноти, який не є самозвітом того, хто читав. Секція без
    дір і зі збіжним підсумком доведено повна — це інша річ, ніж «агент сказав,
    що все прочитав».
    """
    from nyshporka import ops as O
    from nyshporka.records import checksum

    env = O.call("records.audit", {"case": case, "profile": prof})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['shifra']}[/bold] — сторінок {d['pages_noted']}, "
                  f"записів {d['records']} (подій {d['events']}, "
                  f"підсумків {d['tallies']})")
    lane_label = {"m": "мужеска", "f": "женска", "": "наскрізний"}
    for year in d["years"]:
        for lane in year["lanes"]:
            colour = "err" if lane["missing"] else "ok"
            label = lane_label.get(lane["lane"], lane["lane"])
            console.print(
                f"  [{colour}]{year['year']} {year['rtype']:9} {label:11} "
                f"вичитано {lane['count']:>4} · №№ {lane['min']}–{lane['max']}"
                f"  діри: {checksum.compact(lane['missing'])}[/{colour}]")
    for check in d["tally_checks"]:
        mark, close = ("[ok]✅", "[/ok]") if check["ok"] else ("[err]⚠", "[/err]")
        console.print(f"  {mark} підсумок {check['period']}: книга "
                      f"{checksum.fmt_counts(check['expected'])} / вичитано "
                      f"{checksum.fmt_counts(check['actual'])}{close}")
    if d["clean"]:
        console.print("[ok]✅ чисто — дір і розбіжностей немає[/ok]")
    _notes(env)
    if not d["clean"]:
        raise typer.Exit(1)


@records_app.command("merge")
def records_merge_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    branch_a: str = typer.Option(..., "--a", help="тека JSON першої вичитки"),
    branch_b: str = typer.Option(..., "--b", help="тека JSON другої вичитки"),
    prof: str = typer.Option("", "--profile", help="профіль книги"),
    apply: bool = typer.Option(False, "--apply", help="занести узгоджене у сховище"),
    tasks: str = typer.Option("", "--tasks", help="куди скласти чергу спірних місць"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Звести дві незалежні вичитки: збіг у сховище, спір — на людський розсуд.

    🔴 Один прохід джерелом істини не є: модель подає помилкове прочитання так
    само впевнено, як правильне.
    """
    from nyshporka import ops as O

    env = O.call("records.merge", {"case": case, "a": branch_a, "b": branch_b,
                                   "profile": prof, "apply": apply,
                                   "tasks": tasks})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['shifra']}[/bold] — злито {d['merged']} актів "
                  f"(A: {d['records_a']}, B: {d['records_b']}) "
                  f"[dim](профіль {d['profile']}, перевага «{d['prefer']}»)[/dim]")
    console.print(f"  полів збіглося: [ok]{d['agreed_fields']}[/ok] · "
                  f"спірних: [warn]{d['conflicts']}[/warn] "
                  f"на {d['scans_to_escalate']} сканах")
    if d["tasks_path"]:
        console.print(f"  черга спірного: {d['tasks_path']}")
    _notes(env)


export_app = typer.Typer(help="Виписка зі справи таблицею — у файл або на екран.",
                         no_args_is_help=True)
app.add_typer(export_app, name="export")


@export_app.command("case")
def export_case_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    out: str = typer.Option("", "--out", "-o",
                            help="куди писати файл; без нього — на екран"),
    what: str = typer.Option("acts", "--what",
                             help="acts — рядок=акт, ролі в колонки · "
                                  "records — рядок=учасник · pages · tally · "
                                  "all (лише xlsx)"),
    fmt: str = typer.Option("xlsx", "--format",
                            help="xlsx | csv | tsv"),
    headers: str = typer.Option("uk", "--headers",
                                help="uk — людські шапки · raw — ключі полів"),
    force: bool = typer.Option(False, "--force", help="перезаписати наявний файл"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прочитане зі справи — таблицею, придатною до Ексселю.

    🔴 Без `--out` нічого не пишеться на диск: виписка йде за межі застосунку,
    і теку для неї називає людина.

    Кожен рядок несе скан. Виписка без посилання на аркуш — переказ:
    перевірити її можна тільки перечитавши всю справу, тобто ніяк.
    """
    from nyshporka import ops as O

    if not out:
        env = O.call("export.case", {"case": case, "what": what})
        if _answer(env, as_json):
            return
        d = env.data
        _table_preview(d.get("columns", []), d.get("rows", []),
                       human=headers == "uk", view=what)
        console.print(f"[dim]{len(d.get('rows', []))} рядків · "
                      f"щоб забрати файлом — додайте --out[/dim]")
        _notes(env)
        return

    env = O.call("export.write", {"case": case, "out": out, "what": what,
                                  "format": fmt, "headers": headers,
                                  "overwrite": force})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"✅ [bold]{d.get('shifra') or d.get('case')}[/bold] → "
                  f"{d['path']} · рядків: {d['rows']} · аркушів: {d['sheets']}")
    _notes(env)


canon_app = typer.Typer(
    help="Канон роду: перевірка, індекс, наступний ID. Картки правлять файлами.",
    no_args_is_help=True)
app.add_typer(canon_app, name="canon")


@canon_app.command("check")
def canon_check_cmd(
    hash_: bool = typer.Option(False, "--hash", help="перерахувати sha256 доказів"),
    show_info: bool = typer.Option(False, "--info", help="показати й довідкові рядки"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Чи цілий канон після правки. Код 1, якщо є помилки.

    Схема кожної картки, зв'язки особа ↔ родина в обидва боки, хронологія,
    існування місць і джерел, докази на диску й у маніфесті.
    """
    from rich.markup import escape

    from nyshporka import ops as O

    env = O.call("canon.check", {"hash": hash_})
    if as_json:
        _answer(env, True)
        if env.ok and env.data.get("errors"):
            raise typer.Exit(code=1)
        return
    if _answer(env, False):
        return
    d = env.data
    colour = {"ERROR": "red", "WARN": "yellow", "INFO": "dim"}
    for it in d["issues"]:
        if it["severity"] == "INFO" and not show_info:
            continue
        console.print(f"[{colour[it['severity']]}]{it['severity']:5}[/] "
                      f"{escape(it['where'])} · {escape(it['text'])}")
    loaded = " · ".join(f"{k} {v}" for k, v in d["loaded"].items())
    console.print(f"\n{'✅' if not d['errors'] else '⛔'} помилок {d['errors']} · "
                  f"попереджень {d['warnings']} · довідок {d['info']}"
                  f"{'' if show_info else ' (--info)'} · {loaded}")
    _notes(env)
    if d["errors"]:
        raise typer.Exit(code=1)


@canon_app.command("index")
def canon_index_cmd(
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перебудувати базу роду (`data/derived`) з карток канону."""
    from nyshporka import ops as O

    env = O.call("canon.index", {})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"✅ осіб {d['persons']} · родин {d['families']} · місць {d['places']} · "
                  f"джерел {d['sources']} · фактів {d['facts']} → {d['sqlite']}")
    ev = d["evidence"]
    if ev["records"]:
        console.print(f"[dim]доказів у маніфесті {ev['records']} · дописано посилань "
                      f"{ev['added']}[/dim]")
    _notes(env)


@canon_app.command("new-id")
def canon_new_id_cmd(
    kind: str = typer.Argument(..., help="person | family | place"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Наступний вільний ID. Нічого не резервує — пишіть картку одразу."""
    from nyshporka import ops as O

    env = O.call("canon.new_id", {"kind": kind})
    if _answer(env, as_json):
        return
    console.print(env.data["id"])


@canon_app.command("hook")
def canon_hook_cmd(
    install: bool = typer.Option(False, "--install", help="поставити git pre-commit у простір"),
) -> None:
    """Git pre-commit: аркуш понад 2 МБ у доказах і помилки в картках, що комітяться."""
    from nyshporka.canon import hook as H
    from nyshporka.core.workspace import workspace

    if not install:
        console.print("[muted]--install поставить хук у .git/hooks/pre-commit простору[/muted]")
        return
    try:
        target = H.install(workspace().root)
    except H.HookError as exc:
        console.print(f"[warn]![/warn] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"✅ встановлено: {target}")


@canon_app.command("precommit", hidden=True)
def canon_precommit_cmd() -> None:
    """Те, що кличе git pre-commit (див. `nysh canon hook`)."""
    from nyshporka.canon import hook as H
    from nyshporka.core.workspace import workspace

    raise typer.Exit(code=H.main(workspace().root))


@canon_app.command("import")
def canon_import_cmd(
    file: str = typer.Argument(..., help="файл .ged"),
    source_id: str = typer.Option("S_GEDCOM", "--source-id", help="ID картки джерела"),
    title: str = typer.Option("", "--title", help="назва джерела"),
    authority: str = typer.Option("", "--authority", help="MyHeritage, Geni, …"),
    alias_prefix: str = typer.Option("GED", "--alias-prefix",
                                     help="префікс ідентифікаторів чужої програми"),
    private_born_after: int = typer.Option(1946, "--private-born-after",
                                           help="без смерті й народжені від цього року — живі"),
    trust_tree: bool = typer.Option(False, "--trust-tree",
                                    help="факти з датою чи місцем — confirmed"),
    dry_run: bool = typer.Option(False, "--dry-run", help="лише порахувати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Засіяти ПОРОЖНІЙ канон із GEDCOM. Злиття з наявним немає.

    Факти приходять як `hypothesis` з цитатою на сам файл: дерево з іншої
    програми — переказ джерел, а не джерело.
    """
    from nyshporka import ops as O

    env = O.call("canon.import", {
        "file": file, "source_id": source_id, "source_title": title,
        "authority": authority, "alias_prefix": alias_prefix,
        "private_born_after": private_born_after, "trust_tree": trust_tree,
        "dry_run": dry_run})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"{'✅' if d['written'] else '🔎'} осіб {d['persons']} · родин "
                  f"{d['families']} · місць {d['places']} · живих {d['private']}"
                  f" · файл → {d['copied_to']}")
    _notes(env)


@app.command("migrate")
def migrate_cmd(
    paths: list[str] = typer.Argument(None, help="з --scan: теки чи файли для перевірки"),
    show: str = typer.Option("", "--show", help="надрукувати міграцію цієї версії"),
    scan: bool = typer.Option(False, "--scan",
                              help="шукати застарілі тези в пам'яті й нотатках агента"),
    done: bool = typer.Option(False, "--done", help="позначити пройденою (усі або --version)"),
    version: str = typer.Option("", "--version", help="лише ця версія міграції"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Міграція агента після оновлення пакета: що змінилось і що зробити.

    Без прапорців — непройдені міграції з живою перевіркою кожного кроку.
    `--show 0.19` — текст міграції; `--scan` — застарілі тези в пам'яті агента,
    CLAUDE.md і правлених скілах; `--done` — позначити пройденою.
    """
    from rich.markup import escape

    from nyshporka import migrate as M
    from nyshporka import ops as O

    if show:
        m = M.get(show)
        if m is None:
            console.print(f"[warn]![/warn] міграції {show} немає; є: "
                          f"{', '.join(x.version for x in M.load_all())}")
            raise typer.Exit(code=1)
        console.print(m.body, markup=False, highlight=False)
        console.print("\n[bold]Застарілі тези[/bold] (nysh migrate --scan):")
        for s in m.stale:
            console.print(f"  • {s.id}: {s.now}", markup=False, highlight=False)
        return
    if scan:
        env = O.call("migrate.scan", {"paths": paths or [], "version": version})
        if _answer(env, as_json):
            return
        hits = env.data["hits"]
        for h in hits:
            console.print(f"{h['path']}:{h['line']} [{h['stale']}]", markup=False)
            console.print(f"    {h['text']}", markup=False, highlight=False)
            console.print(f"    → {h['now']}", markup=False, highlight=False)
        console.print(f"\n{'✅ застарілих тез немає' if not hits else f'⚠ знайдено {len(hits)}'}"
                      f" · прочесано {len(env.data['scanned'])} місць")
        _notes(env)
        return
    if done:
        env = O.call("migrate.done", {"version": version})
        if _answer(env, as_json):
            return
        marked = env.data["marked"]
        console.print(f"✅ позначено: {', '.join(marked)}" if marked else "нічого не позначено")
        _notes(env)
        return
    env = O.call("migrate.status", {})
    if _answer(env, as_json):
        return
    d = env.data
    if not d["pending"]:
        console.print(f"✅ простір мігровано до {d['package']} — переходити нема з чого")
        return
    mark = {"ok": "[green]✓[/green]", "todo": "[yellow]○[/yellow]", "n/a": "[dim]–[/dim]"}
    for m in d["pending"]:
        console.print(f"\n[bold]{m['version']}[/bold] — {escape(m['title'])}  "
                      f"[dim](nysh migrate --show {m['version']})[/dim]")
        for s in m["steps"]:
            who = " [dim](з людиною)[/dim]" if s["human"] else ""
            console.print(f"  {mark[s['state']]} {escape(s['do'])}{who}")
            if s["detail"]:
                console.print(f"      [dim]{escape(s['detail'])}[/dim]")
    console.print("\n[dim]пройшли — nysh migrate --done[/dim]")


site_app = typer.Typer(help="Сайт роду з канону: зібрати теку зі статикою.",
                       no_args_is_help=True)
app.add_typer(site_app, name="site")


@site_app.command("build")
def site_build_cmd(
    public: bool = typer.Option(False, "--public",
                                help="відкрита версія: без живих, зі сторожем витоків"),
    out: str = typer.Option("", "--out", "-o", help="тека збірки"),
    force: bool = typer.Option(False, "--force", help="перезаписати чужу непорожню теку"),
    no_html: bool = typer.Option(False, "--no-html", help="лише сирці MkDocs"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зібрати сайт роду: сторінки осіб, родин, місць, джерел, дерево, граф, мапа.

    Приватна версія — для себе й родини (живі з датами до десятиліття).
    Відкрита (`--public`) — для публікації: живих немає, а готовий HTML
    перевіряє сторож; знайшов ім'я прихованого — HTML видаляється.
    """
    from nyshporka import ops as O

    env = O.call("site.build", {"public": public, "out": out, "force": force,
                                "html": not no_html})
    if _answer(env, as_json):
        return
    d = env.data
    c = d["counts"]
    console.print(f"✅ {'відкрита' if d['public'] else 'приватна'} версія · осіб {c['persons']} · "
                  f"родин {c['families']} · місць {c['places']} · джерел {c['sources']}"
                  + (f" · приховано {d['hidden']}" if d["public"] else ""))
    console.print(f"   {d['html'] or d['out']}")
    _notes(env)


@site_app.command("serve")
def site_serve_cmd(
    public: bool = typer.Option(False, "--public", help="відкрита версія"),
    port: int = typer.Option(8765, "--port", help="порт на 127.0.0.1"),
) -> None:
    """Зібрати й показати сайт у браузері на цій машині (лише 127.0.0.1).

    Показує рівно те, що зібрано й перевірено, — ту саму теку, яку викладають.
    """
    import functools
    import http.server

    from nyshporka import ops as O

    env = O.call("site.build", {"public": public})
    if _answer(env, False):
        return
    html = env.data["html"]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=html)
    console.print(f"http://127.0.0.1:{port}/ — Ctrl+C, щоб зупинити")
    import contextlib

    with (http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as srv,
          contextlib.suppress(KeyboardInterrupt)):
        srv.serve_forever()


evidence_app = typer.Typer(help="Докази канону: кроп у постійний стор.",
                           no_args_is_help=True)
app.add_typer(evidence_app, name="evidence")


@evidence_app.command("add")
def evidence_add_cmd(
    file: str = typer.Argument(..., help="зображення-вирізка рядка"),
    provenance: str = typer.Option(..., "--provenance", "-p",
                                   help="архів чи зібрання латиницею: dahmo, oral, press"),
    name: str = typer.Option("", "--name", help="ім'я в сторі; типово — як у файлу"),
    overwrite: bool = typer.Option(False, "--overwrite",
                                   help="замінити наявний доказ з іншим вмістом"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Покласти доказ у `data/source/citations/<походження>/` сірим JPEG.

    Шлях із відповіді вписується в `media[]` картки й у цитату факту.
    """
    from nyshporka import ops as O

    env = O.call("evidence.add", {"file": file, "provenance": provenance,
                                  "name": name, "overwrite": overwrite})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"✅ {d['path']} · {d['size'] // 1024} КБ · sha256 {d['sha256'][:12]}…")
    _notes(env)


#: Колонки з прозою: у файлі вони найцінніші, на екрані розсувають рядок на
#: півсторінки й ховають усе решта.
_WIDE_COLUMNS = frozenset({"quote", "comment", "note", "places"})

#: Службові колонки: у файлі потрібні (ключ, певність, друга дата), на екрані
#: з'їдають місце, де мали б стояти імена — заради яких прев'ю й дивляться.
_PREVIEW_SKIP = frozenset({"rid", "date2", "confidence", "sheet", "method"})

#: Скільки колонок терміналу видно, поки таблиця ще читається рядками.
_PREVIEW_COLUMNS = 8


def _table_preview(columns: list[str], rows: list[dict[str, str]], *,
                   human: bool, view: str = "", limit: int = 15) -> None:
    """Показ на екран — навмисно куций.

    Це прев'ю, а не таблиця. Повна справа — сотні рядків і два десятки
    колонок; вивалена в термінал, вона переносить кожну комірку на власний
    рядок і витісняє з екрана попередження, заради яких конверт існує. Тут
    видно лише, що саме поїде у файл; читати це треба в Екселі.
    """
    from rich.table import Table

    from nyshporka import tabular

    if not rows:
        console.print("[dim](порожньо)[/dim]")
        return
    # Порожні в усій вибірці колонки не показуються: у книзі самих народжень їх
    # більшість, і вони видавлюють за край саме те, що заповнене.
    filled = [c for c in columns
              if any(str(r.get(c, "")).strip() for r in rows)]
    shown = [c for c in filled
             if c not in _WIDE_COLUMNS and c not in _PREVIEW_SKIP
             ][:_PREVIEW_COLUMNS]

    table = Table(box=None, pad_edge=False)
    for column in shown:
        table.add_column(tabular.label_for(column, view) if human else column,
                         overflow="ellipsis", max_width=20, no_wrap=True)
    for row in rows[:limit]:
        # Кілька носіїв ролі склеєні через «; » — на екрані показуємо першого,
        # щоб рядок лишався рядком.
        table.add_row(*(str(row.get(c, "")).split("; ")[0] for c in shown))
    console.print(table)

    tail = []
    if len(rows) > limit:
        tail.append(f"…ще {len(rows) - limit} рядків")
    if len(filled) > len(shown):
        tail.append(f"колонок показано {len(shown)} з {len(filled)}")
    if tail:
        console.print(f"[dim]{' · '.join(tail)}[/dim]")


htr_app = typer.Typer(help="Рушії читання рукопису.", no_args_is_help=True)
app.add_typer(htr_app, name="htr")


@htr_app.command("env")
def htr_env_cmd(as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Що стоїть у середовищі рушіїв: версії, чого бракує.

    Загальну готовність машини каже `nysh doctor`; тут — подробиці саме про
    рушій, потрібні тоді, коли прогін падає, а `doctor` каже «все гаразд».
    """
    from nyshporka import ops as O

    env = O.call("htr.env", {})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"{'✅' if d['ok'] else '⚠'} інтерпретатор: {d['python'] or '—'}")
    console.print(f"  kraken {d.get('kraken') or '—'} · torch "
                  f"{d.get('torch') or '—'} · cuda {d.get('cuda') or '—'}")
    _notes(env)


@htr_app.command("install")
def htr_install(
    no_cuda: bool = typer.Option(False, "--no-cuda", help="не чіпати torch"),
    cuda: str = typer.Option("", "--cuda", metavar="ТЕГ",
                             help="поставити колесо вручну (cu126, cu128) замість детекту"),
) -> None:
    """Зібрати середовище рушіїв — окремий інтерпретатор поруч із простором.

    🔴 Окремий не для краси: сегментація йде на `kraken==7.1.1` з патчами
    приватних функцій, доведеними рівними оригіналу саме на цій версії.
    Інша версія дала б тиху розбіжність — ті самі скани, інші полігони рядків,
    інший текст, без помилки в лозі. Тримати такий пін в основному середовищі
    означало б нав'язати його всьому, що там є.
    """
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    _need("htr")

    if cuda and not re.fullmatch(r"cu\d{3,4}", cuda):
        # Тег іде в URL індексу PyTorch. Помилка тут дала б не відмову, а
        # неіснуючий індекс і довге незрозуміле падіння `uv`.
        console.print(f"[err]невідома форма тега: {cuda} — очікується cu126, cu128 тощо[/err]")
        raise typer.Exit(code=2)
    try:
        venv = doc.engine_venv()
    except WorkspaceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    try:
        rep = E.setup(venv, with_cuda=not no_cuda, force_tag=cuda)
    except E.ToolMissing as exc:
        # 🔴 Не трасою стека: `uv` і `git` — не залежності пакета, тож у того,
        # хто ставив `pip install`, їх може не бути зовсім, і саме він
        # найімовірніше опиниться тут.
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None
    console.print(f"\npython : {rep.python or '—'}")
    console.print(f"kraken : {rep.kraken or '—'}")
    console.print(f"torch  : {rep.torch or '—'}  cuda={rep.cuda} "
                  f"capability={rep.capability or '—'}")
    for p in rep.problems:
        console.print(f"[warn]⚠ {p}[/warn]")
    if rep.missing:
        console.print(f"[err]🔴 бракує: {', '.join(rep.missing)}[/err]")
    raise typer.Exit(code=0 if rep.ok else 1)


models_app = typer.Typer(help="Ваги моделей письма.", no_args_is_help=True)
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list() -> None:
    """Що є, чого немає, що зіпсоване."""
    from nyshporka.setup import packs

    _need("htr")
    from nyshporka.htr import manifest as _M

    state = packs.as_dict()
    manifest = _M.active()
    mark = {"ok": "✅", "absent": "▫️", "broken": "🔴", "superseded": "·"}
    for p in state["packs"]:
        size = f"{p['size'] / 2**20:.0f} МБ" if p["size"] else "?"
        # 🔴 Рушій визначається за іменем файлу через маніфест, а не за полем
        # `engine`: там лежить `kraken`, а `.mlmodel` буває двох письм — тобто
        # Скриба й Дяк злилися б в один бейдж. Саме цю плутанину бейдж і має
        # прибирати з очей.
        eng = manifest.engine_for_model(Path(p["path"]).name) if p.get("path") else None
        badge = f"{brand.engine_tag(eng.id)} " if eng else ""
        # 🔴 `id` друкується, бо саме його треба набрати в `models get`. Перелік
        # із самими людськими назвами («Писар v17») лишав людину без того
        # слова, якого від неї чекає наступна команда.
        console.print(f"  {mark.get(p['state'], '?')} {badge}[bold]{p['label']}[/bold] "
                      f"[accent]{p['id']}[/accent] "
                      f"[muted]{p['script']}/{p['engine']} · {size}[/muted]")
    console.print(f"[muted]тека: {state['dir']}[/muted]")


@models_app.command("get")
def models_get(
    which: str = typer.Argument("", help="id пака; порожньо — усі, яких бракує"),
) -> None:
    """Завантажити ваги. sha256 звіряється завжди."""
    from nyshporka.setup import packs

    _need("htr")
    known = packs.catalog()
    # 🔴 Невідоме ім'я мусить бути відмовою, а не «нічого робити».
    # Друкарська помилка в id («pysar» замість «pysar-cyr-v17») давала «✅ усе
    # на місці»: людина читала це як «ваги стоять», ішла читати справу — і
    # діставала відмову аж там, де вже незрозуміло, при чому тут ваги.
    if which and not any(p.id == which for p in known):
        console.print(f"[err]немає пака «{which}»[/err]")
        console.print("[muted]є: " + ", ".join(p.id for p in known) + "[/muted]")
        raise typer.Exit(code=1)
    # Замінені паки (попереднє покоління ваг) — лише на явне прохання за id:
    # «усі, яких бракує» означає бойові, а не всю історію.
    want = ([p for p in known if p.id == which] if which
            else [p for p in known if not p.superseded])
    want = [p for p in want if not packs.verify(p)]
    if not want:
        console.print("✅ усе на місці")
        return
    # 🔴 Одна відмова не гасить решту. Аргумент обіцяє «усі, яких бракує», а
    # вихід на першому ж паку означав «усі до першої вади»: коли ваги
    # викладають частинами, недоступний пак ховає ті, що взялися б, і людина
    # бачить одну назву замість переліку того, чого їй бракує. Тому збираємо
    # збої, а код повернення лишається ненульовим — мовчазного успіху тут бути
    # не може.
    failed: list[str] = []
    for p in want:
        console.print(f"⬇ {p.label} …")
        try:
            dst = packs.fetch(p)
        except Exception as exc:
            console.print(f"[err]✗ {p.id}: {exc}[/err]")
            failed.append(p.id)
            continue
        console.print(f"  ✅ {dst}")
    if failed:
        got = len(want) - len(failed)
        console.print(f"[warn]не вдалося: {len(failed)} із {len(want)}[/warn]"
                      + (f" · взято: {got}" if got else ""))
        raise typer.Exit(code=1)


def _stdin_is_tty() -> bool:
    """Чи можна спитати підтвердження набором. Окремою функцією — для тестів."""
    return sys.stdin.isatty()


def _stdout_is_tty() -> bool:
    """Чи вивід іде в термінал, а не в файл чи журнал служби."""
    return sys.stdout.isatty()


@app.command()
def serve(
    port: int = typer.Option(8788, "--port", help="порт"),
    host: str = typer.Option(
        "127.0.0.1", "--host",
        help="вихід у мережу: IP цієї машини, 0.0.0.0 чи :: (усі інтерфейси). "
             "Друкує застереження, просить підтвердження й пускає пристрої лише "
             "з ключем доступу; петля 127.0.0.1 працює, як і без прапорця"),
    tls_cert: Path | None = typer.Option(
        None, "--tls-cert", help="сертифікат PEM для https (разом із --tls-key)"),
    tls_key: Path | None = typer.Option(
        None, "--tls-key", help="закритий ключ PEM без пароля (разом із --tls-cert)"),
    rotate_key: bool = typer.Option(
        False, "--rotate-key", help="новий ключ доступу — усі сполучені пристрої виходять"),
    confirm_host: str = typer.Option(
        "", "--confirm-host",
        help="підтвердження без набору (служба, скрипт): та сама адреса, що в --host"),
    confirm_public: bool = typer.Option(
        False, "--confirm-public",
        help="друге підтвердження без набору — для 0.0.0.0 / :: чи публічної адреси"),
    no_browser: bool = typer.Option(False, "--no-browser",
                                    help="не відкривати вкладку самому"),
) -> None:
    """Підняти застосунок у браузері.

    🔴 Дефолт — петля 127.0.0.1: тут архів однієї людини — канон про живих
    родичів, скани, нотатки. `--host` відкриває його в мережі лише як свідомий
    вибір: конкретне застереження, підтвердження набором адреси (або
    прапорцями без термінала), і кожен мережевий пристрій — лише з ключем
    доступу. Прапорця «слухати всюди» без цього всього немає: його рано чи
    пізно вмикають «на хвилинку» й лишають.
    """
    from importlib.util import find_spec

    # 🔴 Перевірка ДО виклику, а не лише навколо імпорту. Демон імпортується й
    # без extra `app`, а про відсутній сервер дізнається вже всередині
    # `serve()` — і людина з набором без консолі діставала рамку трасування на
    # пів екрана, в кінці якої ховалось «pip install 'nyshporka[app]'».
    # Знайдено прогоном у чистому venv 12.09.2026.
    if find_spec("uvicorn") is None or find_spec("fastapi") is None:
        console.print("[err]браузерна консоль потребує сервера — extra `app` не "
                      "поставлено[/err]")
        console.print(r"[muted]pip install 'nyshporka\[app]'[/muted]")
        raise typer.Exit(code=1)
    try:
        from nyshporka.daemon import serve as _serve
    except (ImportError, RuntimeError) as exc:
        console.print(f"[err]{exc}[/err]")
        console.print(r"[muted]pip install 'nyshporka\[app]'[/muted]")
        raise typer.Exit(code=1) from None
    from rich.markup import escape

    from nyshporka.daemon import app as D

    # 🔴 Усе з адресою — без розмітки й емодзі: rich читав `[fd00::5]` як тег, а
    # `:ab:` усередині IPv6 друкував як 🆎.
    def _refuse(text: str) -> None:
        console.print(f"[err]{escape(text)}[/err]", emoji=False, highlight=False)

    extras = bool(tls_cert or tls_key or rotate_key or confirm_host or confirm_public)
    if D.is_loopback_host(host):
        if extras:
            console.print("[err]--tls-cert, --tls-key, --rotate-key і --confirm-* діють "
                          "лише з мережевим --host[/err]")
            raise typer.Exit(code=1)
        _serve(host=host, port=port, open_browser=not no_browser)
        return

    try:
        addr = D.network_host(host)
        if (tls_cert is None) != (tls_key is None):
            raise ValueError("--tls-cert і --tls-key задаються лише разом")
        if tls_cert is not None and tls_key is not None:
            D.check_tls(str(tls_cert), str(tls_key))
    except ValueError as exc:
        _refuse(str(exc))
        raise typer.Exit(code=1) from None

    from nyshporka.core.workspace import workspace as _workspace

    lines = D.exposure_warnings(addr, port, tls=tls_cert is not None,
                                key_path=D.access_key_path(_workspace().root))
    # 🔴 Застереження друкується ЗАВЖДИ, навіть із прапорцями підтвердження, і
    # під службою дублюється в stderr: stdout там часто не йде нікуди.
    outs = [console] if _stdout_is_tty() else [console, brand.err()]
    for out in outs:
        for line in lines:
            out.print(line, style="warn", markup=False, emoji=False, highlight=False)

    public = D.is_public_exposure(addr)

    def _same_addr(typed: str) -> bool:
        try:
            return D.network_host(typed) == addr
        except ValueError:
            return False

    refusal = ""
    if confirm_host or confirm_public:
        if not _same_addr(confirm_host):
            refusal = f"--confirm-host мусить дослівно повторити адресу з --host ({host})"
        elif public and not confirm_public:
            refusal = (f"{addr} — усі інтерфейси чи публічна адреса: потрібен ще "
                       f"--confirm-public")
    elif _stdin_is_tty():
        typed = typer.prompt("Щоб відкрити, наберіть адресу дослівно",
                             default="", show_default=False)
        if not _same_addr(typed):
            refusal = "адреса не збіглась — не відкриваю"
        elif public:
            typed = typer.prompt(f"Це видно за межами локальної мережі. Наберіть "
                                 f"«{D.PUBLIC_PHRASE}»", default="", show_default=False)
            if typed.strip() != D.PUBLIC_PHRASE:
                refusal = "фраза не збіглась — не відкриваю"
    else:
        refusal = ("без термінала вихід у мережу підтверджується прапорцями: "
                   "--confirm-host <адреса> (і --confirm-public для 0.0.0.0, :: чи "
                   "публічної адреси)")
    if refusal:
        _refuse(refusal)
        raise typer.Exit(code=1)

    try:
        _serve(host=addr, port=port, open_browser=not no_browser, confirmed=True,
               rotate_key=rotate_key,
               tls_cert=str(tls_cert) if tls_cert is not None else None,
               tls_key=str(tls_key) if tls_key is not None else None,
               show_secret=_stdout_is_tty())
    except ValueError as exc:
        _refuse(str(exc))
        raise typer.Exit(code=1) from None


def _op_card(op: Any, *, with_doc: bool = False) -> dict[str, Any]:
    """Машинний опис операції: чим є, що приймає, чим загрожує.

    🔴 `schema` їде разом із переліком, а не окремим запитом на кожну операцію.
    Той, хто кличе операцію з командного рядка (`nysh op …`), інакше знає лише
    ім'я — і мусить видобувати назви полів по одній із помилок валідації,
    витрачаючи хід на кожну. Схема вже є в реєстрі; не віддавати її означало
    тримати повну поверхню за напівзачиненими дверима.
    """
    card: dict[str, Any] = {
        "name": op.name, "summary": op.summary, "section": op.section,
        "mutates": op.mutates, "long": op.long, "agent": op.agent,
        "schema": op.schema(),
    }
    if with_doc:
        # Докстрінг — те, що не доїжджає ні в перелік tool'ів, ні в підпис
        # операції: там однорядковий summary, а причина «чому саме так» разом
        # із замірами й ціною помилки живе тут.
        import inspect

        card["doc"] = inspect.getdoc(op.fn) or ""
    return card


@app.command("ops")
def ops_list(agent_only: bool = typer.Option(False, "--agent",
                                             help="лише те, що бачить агент"),
             as_json: bool = typer.Option(False, "--json",
                                          help="машинний перелік зі схемами аргументів"),
             ) -> None:
    """Перелік операцій — те саме, що доступне агентові й браузеру."""
    from nyshporka import ops as O

    picked = O.for_agent() if agent_only else O.all_ops()
    if as_json:
        console.print_json(data={"v": 1, "ops": [_op_card(o) for o in picked]})
        return
    for op in picked:
        marks = "".join(("✎" if op.mutates else " ", "⏳" if op.long else " ",
                         "🤖" if op.agent else " "))
        console.print(f"  {marks} [bold]{op.name:<18}[/bold] [muted]{op.section:<9}[/muted] "
                      f"{op.summary}")
    if not as_json:
        console.print("\n[muted]✎ пише на диск · ⏳ довга (див. `nysh op <ім'я> --describe`) "
                      "· 🤖 доступна агентом[/muted]")
        console.print("[muted]аргументи: nysh op <ім'я> --describe · "
                      "усе разом: nysh ops --json[/muted]")


# ── секції ───────────────────────────────────────────────────────────────────
sections_app = typer.Typer(help="Які частини застосунку ввімкнено.",
                           invoke_without_command=True)
app.add_typer(sections_app, name="sections")


def _print_sections(data: dict[str, Any]) -> None:
    # Знак секції — той самий, що в шапці застосунку: перелік тут і навігація
    # там мусять читатись як одне місце, а не як два різні продукти.
    glyphs = (data.get("glyphs") or {}).get("sections") or {}
    for r in data["sections"]:
        if r["required"]:
            mark, note = "🔒", "завжди"
        elif not r["visible"]:
            # Порожню секцію показуємо чесно: вона оголошена, але вмикати нічого.
            mark, note = "▫️", "порожня"
        else:
            mark, note = ("✅", "увімкнено") if r["active"] else ("⬜", "вимкнено")
        glyph = glyphs.get(r["id"], " ")
        console.print(f"  {mark} {glyph} [bold]{r['id']:<9}[/bold] {r['label']:<12} "
                      f"[muted]{note} · {r['ops']} операцій[/muted]")
        console.print(f"     [muted]{r['why']}[/muted]")
    preset = data.get("preset")
    console.print(f"[muted]пресет: {preset or 'власний набір'} · "
                  f"є: {', '.join(sorted(data['presets']))}[/muted]")


def _sections_call(payload: dict[str, Any]) -> None:
    from nyshporka import ops as O

    env = O.call("sections.set", payload)
    _answer(env)
    _notes(env)
    _print_sections(env.data)


@sections_app.callback()
def sections_root(ctx: typer.Context) -> None:
    """Показати секції, якщо підкоманди немає."""
    if ctx.invoked_subcommand is not None:
        return
    from nyshporka import ops as O

    env = O.call("sections.show")
    _answer(env)
    _notes(env)
    _print_sections(env.data)


@sections_app.command("enable")
def sections_enable(section: str = typer.Argument(..., help="id секції")) -> None:
    """Увімкнути секцію."""
    _sections_call({"enable": [section]})


@sections_app.command("disable")
def sections_disable(section: str = typer.Argument(..., help="id секції")) -> None:
    """Вимкнути секцію."""
    _sections_call({"disable": [section]})


@sections_app.command("preset")
def sections_preset(name: str = typer.Argument(..., help="catalog | amateur | researcher | lab"),
                    ) -> None:
    """Взяти готовий набір секцій."""
    _sections_call({"preset": name})


@app.command("op")
def op_run(
    name: str = typer.Argument(..., help="ім'я операції, напр. workspace.info"),
    args: str = typer.Option("{}", "--args", help="аргументи як JSON"),
    as_json: bool = typer.Option(True, "--json/--human", help="формат виводу"),
    describe: bool = typer.Option(False, "--describe",
                                  help="аргументи й пояснення, без виконання"),
) -> None:
    """Виконати операцію напряму.

    🔴 Це і є те, що робить командний рядок повним: кожна операція доступна тут
    без окремої команди. Дружні команди (`look`, `sources`) — лише зручні
    обгортки над тими самими операціями, тож відстати від агента CLI не може.

    `--describe` віддає схему аргументів і повний докстрінг, нічого не
    виконуючи. Це вхід для того, хто працює без переліку tool'ів: там видно
    лише однорядковий підпис, а тут — назви полів і причина, чому операція
    така. Розвідка мусить бути дешевою і безпечною, інакше її роблять
    навмання — викликом мутації «щоб подивитись, що відповість».
    """
    import json as _json

    from nyshporka import ops as O

    if describe:
        op = O.get(name)
        if op is None:
            known = ", ".join(sorted(o.name for o in O.all_ops()))
            console.print(f"[err]невідома операція «{name}».[/err] Є: {known}")
            raise typer.Exit(code=2)
        console.print_json(data=_op_card(op, with_doc=True))
        raise typer.Exit(code=0)

    try:
        payload = _json.loads(args)
    except ValueError as exc:
        console.print(f"[err]--args не є JSON:[/err] {exc}")
        raise typer.Exit(code=2) from None

    env = O.call(name, payload)
    if as_json:
        console.print_json(data=env.as_dict())
    else:
        note = env.as_agent_text()
        if note:
            console.print(note)
        # Дані лише коли вони є: на відмові `data` порожня, і надрукований
        # `null` під поясненням причини читається як відповідь на питання.
        if env.ok:
            console.print_json(data=env.data)
    raise typer.Exit(code=0 if env.ok else 1)


skills_app = typer.Typer(help="Скіли агента: порядок роботи, який вантажиться за потреби.",
                         no_args_is_help=True)
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list() -> None:
    """Які скіли несе пакет."""
    from nyshporka import skills as S

    got = S.available()
    for sk in got:
        console.print(f"  [bold]{sk.name:<16}[/bold] {sk.title}")
        extra = [p for p in sk.files() if p.name != "SKILL.md"]
        if extra:
            console.print(f"  {'':<16} [muted]+ {len(extra)} довідник(ів)[/muted]")
    if not got:
        console.print("[warn]![/warn] скілів у пакеті немає")
        return
    console.print(f"\n[muted]усього {len(got)} · встановити: nysh skills install[/muted]")


@skills_app.command("install")
def skills_install(
    target: str = typer.Option("", "--target",
                               help="тека, куди класти (типово .claude/skills)"),
    user: bool = typer.Option(False, "--user",
                              help="глобально, для всіх проєктів"),
    force: bool = typer.Option(False, "--force",
                               help="перезаписати навіть правлене руками"),
    only: str = typer.Option("", "--only", help="лише ці скіли, через кому"),
    prune: bool = typer.Option(False, "--prune",
                               help="прибрати скіли, яких у пакеті вже немає"),
) -> None:
    """Покласти скіли туди, де їх бачить агент.

    🔴 Не в робочий простір Нишпорки: простір — це тека даних, і скіл,
    покладений туди, не побачить ніхто. Агент читає `.claude/skills/` проєкту
    або `~/.claude/skills/` користувача, і команда кладе саме туди.
    """
    from nyshporka import __version__
    from nyshporka import skills as S

    if user and target:
        console.print("[warn]![/warn] --user і --target разом не мають сенсу")
        raise typer.Exit(code=1)
    dest = (Path.home() / ".claude" / "skills" if user
            else Path(target or ".claude/skills"))

    names = tuple(n.strip() for n in only.split(",") if n.strip())
    known = {s.name for s in S.available()}
    if unknown := set(names) - known:
        console.print(f"[warn]![/warn] немає таких скілів: {', '.join(sorted(unknown))}"
                      f"  (є: {', '.join(sorted(known))})")
        raise typer.Exit(code=1)

    out = S.install(dest, version=__version__, force=force, names=names, prune=prune)
    if not out:
        console.print("[warn]![/warn] нічого не встановлено")
        raise typer.Exit(code=1)

    tally: dict[str, int] = {}
    for o in out:
        tally[o.verdict] = tally.get(o.verdict, 0) + 1
    word = {"new": "нових", "updated": "оновлено", "same": "без змін",
            "kept": "лишено (правлено руками)", "orphan": "сиріт",
            "pruned": "прибрано сиріт"}
    parts = [f"{word[k]} {v}" for k, v in tally.items() if k in word]
    console.print(f"✓ {dest} — " + " · ".join(parts))

    # 🔴 Правлене руками називається поіменно: зведене число тут читалось би як
    # «щось не поклалось», хоча це свідоме рішення інструмента не чіпати чужу
    # роботу. Мовчазний пропуск був би гіршим за помилку.
    if kept := [o.rel for o in out if o.verdict == "kept"]:
        console.print("  [muted]не чіпав (є ваші правки; --force перезапише):[/muted]")
        for rel in kept:
            console.print(f"    {rel}")

    # Сирота — скіл, якого в пакеті вже немає: агент вантажить його нарівні з
    # чинними. Називаємо поіменно й кажемо, як прибрати.
    if orphans := [o.rel for o in out if o.verdict == "orphan"]:
        console.print("  [warn]![/warn] [muted]у пакеті вже немає (агент їх досі бачить; "
                      "--prune прибере незмінені):[/muted]")
        for rel in orphans:
            console.print(f"    {rel}")

    where = "у будь-якому проєкті" if user else "у цьому проєкті"
    console.print(f"  [muted]видно агентові {where}; перезапустіть сесію[/muted]")


#: 🔴 MCP-сервер прибрано в 0.19. Команда лишилась як вказівник: конфіг агента
#: (`.mcp.json`, `claude mcp add`), прописаний раніше, і далі кличе
#: `nysh mcp serve` — без неї агент бачив би «No such command» і не знав, куди
#: йти. Порядок переходу — міграція агента 0.19 (`nysh migrate`).
MCP_ZNYKLO = ("MCP-сервер Нишпорки прибрано в 0.19. Агентові — командний рядок: "
              "`nysh op <ім'я> --args '<json>'` дістає всі операції, `nysh ops` їх "
              "перелічує. Прибрати сервер із конфігу агента: `claude mcp remove "
              "nyshporka` або рядок `nyshporka` у `.mcp.json`. Решта кроків — "
              "`nysh migrate`.")


@app.command("mcp", hidden=True, context_settings={"allow_extra_args": True,
                                                   "ignore_unknown_options": True})
def mcp_gone() -> None:
    """Прибрано в 0.19 — друкує, куди перейти."""
    err_console.print(f"[warn]{MCP_ZNYKLO}[/warn]")
    raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
