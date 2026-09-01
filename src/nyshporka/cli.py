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
                     "неповний · skipped · unreadable")
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


@app.callback()
def _global_options(
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
    if not workspace:
        return
    from nyshporka.core.workspace import WorkspaceError, use

    try:
        use(workspace)
    except WorkspaceError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=2) from None


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

    # Важкі extras перевіряються наявністю, а не імпортом у момент старту:
    # тягнути torch заради рядка «встановлено» коштувало б секунд на кожен запуск.
    from importlib.util import find_spec

    for label, module, extra in (
        ("консоль", "fastapi", "app"),
        ("архіви", "aiolimiter", "archives"),
        ("HTR", "torch", "htr"),
    ):
        have = find_spec(module) is not None
        # 🔴 `\[` — екранування для rich. Без нього `[app]` з'їдається як
        # розмітка, і порада перетворюється на «pip install nyshporka», тобто
        # рівно ту команду, яка extra не ставить. Порада, що не працює, гірша
        # за відсутню: користувач виконує її і бачить той самий стан.
        mark = ("[ok]є[/ok]" if have
                else rf"[muted]немає — pip install 'nyshporka\[{extra}]'[/muted]")
        console.print(f"  {label:8s} {mark}")


@app.command()
def sources() -> None:
    """Звідки можна брати матеріал — і що кожне джерело вміє."""
    _need("material")
    reg = _sources_registry()
    for src in reg.all():
        caps = ", ".join(sorted(src.caps)) or "—"
        console.print(f"  [bold]{src.id:<10}[/bold] {src.label}")
        console.print(f"  {'':<10} [muted]уміє: {caps}[/muted]")
    # 🔴 Зламані плагіни називаються поіменно: «мого архіву немає в списку»
    # інакше не має пояснення, і людина шукатиме причину в своїх налаштуваннях.
    for name, why in reg.broken:
        console.print(f"  [err]✗ {name}[/err] [muted]{why}[/muted]")


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
         source: str = typer.Option("", "--source", help="лише це джерело"),
         text: bool = typer.Option(False, "--text",
                                   help="шукати текстом, навіть якщо запит "
                                        "схожий на шифру"),
         limit: int = typer.Option(20, "--limit")) -> None:
    """Де взагалі є щось про моє село — пошук по каталогах джерел."""
    from nyshporka import ops as O

    env = O.call("catalog.search", {"q": q, "source": source, "limit": limit,
                                    "by_address": not text})
    _answer(env)
    _print_address(env.data.get("address"))
    hits = env.data.get("hits") or []
    for h in hits:
        head = " · ".join(x for x in (h.get("shifra"), h.get("years")) if x)
        console.print(f"  [bold]{h['source']}[/bold]  {h['title']}")
        console.print(f"  {'':<{len(h['source'])}}  [muted]{head}[/muted]")
        console.print(f"  {'':<{len(h['source'])}}  [muted]{h['ref']}[/muted]")
    cov = env.data.get("coverage") or {}
    # 🔴 Знаменник друкується завжди, і найважливіший він саме тоді, коли
    # знахідок нуль: без нього «нічого не знайшлось» читається як «цього не
    # існує», хоча дивились в одному каталозі з трьох.
    basis = "; ".join(
        f"{b['source']}: {b['kind']}" + (f" від {b['taken']}" if b.get("taken") else "")
        for b in (cov.get("basis") or []))
    console.print(f"\n[muted]знайдено {len(hits)} · шукали в: "
                  f"{', '.join(cov.get('searched') or []) or '—'}"
                  + (f" ({basis})" if basis else "") + "[/muted]")
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
                                   help="діапазон кадрів «12-80»; порожньо = всі")) -> None:
    """Завантажити справу або плівку.

    Спершу друкується маніфест і лише потім починається качання: справа буває
    на кілька гігабайтів, і питання «скільки це» мусить мати відповідь ДО, а не
    після — перервана закачка лишає теку в невизначеному стані.
    """
    from nyshporka.sources.base import SourceError

    _need("material")
    src = _pick(source)
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

    res = src.fetch(ref, out, frames=rng, on_progress=progress)
    console.print(f"\n✓ {res.frames} кадрів ({res.bytes / 1024 / 1024:.0f} МБ), "
                  f"пропущено {res.skipped} → {res.dest}")
    for e in res.errors[:5]:
        console.print(f"[warn]⚠ {e}[/warn]")
    if len(res.errors) > 5:
        console.print(f"[warn]⚠ …ще {len(res.errors) - 5} збоїв[/warn]")

    # 🔴 Приймач — знаменник, а не відсутність помилок. Дзеркало, що віддало
    # сорок кадрів із трьохсот і жодного HTTP-збою, давало «✓ 40 кадрів» і код
    # 0: обіцянка маніфесту друкувалась рядком вище й ніде не звірялась. Той
    # самий клас вади, що обірваний zip, який браузер записує як успіх.
    #
    # 🔴 Просити діапазон — не те саме, що просити все: там знаменником стає
    # сам діапазон, а не обсяг справи.
    want = (rng[1] - rng[0] + 1) if rng else man.frames
    got = res.frames + res.skipped
    if want is None:
        # ⚠ Мовчазний «✓» тут був би найгіршим із варіантів: він читається як
        # доведена повнота. Нуль без знаменника не є доказом повноти.
        console.print("[warn]⚠ джерело не назвало числа кадрів, тож повноту "
                      "я не міряю — звірте з описом справи вручну[/warn]")
    elif got != want:
        console.print(f"[warn]⚠ маніфест обіцяв {want}, узято {got} "
                      f"({res.frames} завантажено, {res.skipped} пропущено) — "
                      f"тека неповна[/warn]")
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
                                     help="почати наново, а не продовжити")) -> None:
    """Зібрати каталог справ, по якому потім працює `nysh find`.

    🔴 Потрібне не всім джерелам, а тим, чий сайт не індексує заголовків справ.
    Для ARCHIUM без цього кроку пошук неможливий у принципі — і саме тому він
    відмовляється відповідати нулем.
    """
    _need("material")
    src = _pick(source)
    if not hasattr(src, "crawl"):
        console.print(f"[warn]джерело «{source}» не потребує обходу — "
                      f"його каталог доступний одразу[/warn]")
        raise typer.Exit(code=0)

    def progress(done: int = 0, total: int = 0, note: str = "", **_: Any) -> None:
        console.print(f"  [muted]{done}/{total} фондів · {note}[/muted]", end="\r")

    stats = src.crawl(tuple(g.strip() for g in groups.split(",") if g.strip()) or None,
                      on_progress=progress, resume=not fresh)
    console.print(f"\n✓ фондів {stats['fonds']} (пропущено готових "
                  f"{stats['skipped']}) · описів {stats['inventories']} · "
                  f"справ {stats['cases']}")


@app.command()
def init(
    path: str = typer.Argument("", help="куди покласти простір; порожньо — запропоную"),
    name: str = typer.Option("", "--name", help="як зветься дослідження"),
    preset: str = typer.Option("", "--preset",
                               help="набір частин: amateur | researcher | lab"),
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
    console.print("[muted]далі: `nysh look <тека зі сканами>` або `nysh serve`[/muted]")


@app.command()
def update(
    check: bool = typer.Option(False, "--check",
                               help="лише подивитись, не ставити"),
    preset: str = typer.Option("", "--preset",
                               help="набір частин, якщо слід інсталятора втрачено"),
) -> None:
    """Оновити застосунок: подивитись версію на pypi.org і поставити нову.

    🔴 Досі шляху оновлення не було зовсім — ні команди, ні перевірки версії,
    ні рядка в `doctor`. Людина з `.exe`-установленням дізнатись про нову
    збірку не могла нізвідки, тож вада, полагоджена вчора, лишалась у неї
    назавжди.

    ⚠ Установлення саме себе на ходу не робиться: `uv tool install --force`
    міняє те саме середовище, з якого зараз запущено `nysh`. Закрийте
    застосунок (`nysh serve`) перед оновленням.
    """
    import subprocess

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
    console.print(f"[muted]{' '.join(cmd)}[/muted]")
    if check:
        raise typer.Exit(code=0)
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


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json"),
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
            console.print(f"   [muted]{c.fix}[/muted]")
    bad = [c for c in checks if c.level == "fail"]
    raise typer.Exit(code=1 if bad else 0)


@app.command()
def sample(
    force: bool = typer.Option(False, "--force",
                               help="перезаписати вже розгорнуті файли"),
    as_json: bool = typer.Option(False, "--json"),
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


@app.command()
def read(
    case_dir: str = typer.Argument(..., help="пласка тека зі сканами справи"),
    out: str = typer.Option("", "--out", help="куди класти текст"),
    script: str = typer.Option("", "--script", help="latin | cyrillic"),
    one_voice: bool = typer.Option(False, "--one-voice",
                                   help="без другого рушія (швидше, але сліпіше)"),
    case_key: str = typer.Option("", "--case-key", help="шифра справи у мету"),
    limit: int = typer.Option(0, "--limit", help="лише перші N кадрів"),
    pages: str = typer.Option("", "--pages", help="діапазони кадрів: 1-50,60"),
    shard: str = typer.Option("", "--shard",
                              help="«k/n» — цей процес бере кожен n-й кадр"),
    gpu_lock: str = typer.Option("", "--gpu-lock",
                                 help="спільний файл-лок GPU; обов'язковий при --shard"),
    gpu_sato: bool = typer.Option(True, "--gpu-sato/--no-gpu-sato",
                                  help="рахувати sato на карті; зняти при шардингу"),
    seg_height: int = typer.Option(0, "--seg-height",
                                   help="висота сегментації (0 = рідна 1800)"),
    dry: bool = typer.Option(False, "--dry-run", help="лише показати план"),
) -> None:
    """Прочитати справу рукописним рушієм.

    🔴 Читає прямо тут, а не через застосунок — і це свідомо. Прогін ставлять
    на ніч, часто по ssh, і вимагати для цього піднятого браузера означало б
    зробити найдовшу роботу найкрихкішою.

    Важелі ресурсів (`--shard`, `--gpu-lock`, `--no-gpu-sato`, `--seg-height`)
    існують тому, що машина в кожного своя. Раннер мав їх від початку, але
    доступні вони були лише прямим викликом — тобто рівно та людина, якій
    найбільше треба стиснути прогін під слабку карту, важелів не мала.
    Як ними користуватись — `docs/agents/htr-tuning.md`.
    """
    import subprocess

    from nyshporka.core.progress import split
    from nyshporka.htr.run import ReadError
    from nyshporka.htr.run import plan as make_plan

    _need("htr")
    try:
        p = make_plan(case_dir, out_dir=out, script=script,
                      second_voice=not one_voice)
    except ReadError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(code=1) from None

    console.print(f"[bold]{p.case_dir.name}[/bold] — {p.frames} кадрів · "
                  f"письмо {p.script} · {p.model.name}"
                  + (f" + {p.voice.name}" if p.voice else ""))
    console.print(f"  [muted]{p.out_dir}[/muted]")
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
        if case_key:
            console.print(f"  [muted]шифра: {case_key}[/muted]")
        else:
            console.print("  [warn]шифри немає: бібліотека цієї теки не знає — "
                          "прив'язка триматиметься на імені прогону[/warn]")
    # 🔴 Лок карти береться З ПЛАНУ, коли людина не задала свій.
    #
    # Доти сюди їхала сама лише опція командного рядка (типово порожня), а
    # `p.gpu_lock` — спільний на простір — не читався взагалі. Тобто найдовший
    # і найменш наглядний шлях, прогін на ніч по ssh, ішов БЕЗ лока, і два
    # `nysh read` (чи термінал плюс застосунок) заходили на карту разом — рівно
    # той звіт, з якого почалась ця правка. Черга демона сюди не дістає: вона
    # не бачить прогонів командного рядка, а карта в них спільна.
    cmd = p.command(case_key=case_key, limit=limit, pages=pages, shard=shard,
                    gpu_lock=gpu_lock or str(p.gpu_lock or ""),
                    gpu_sato=gpu_sato, seg_height=seg_height)
    if dry:
        console.print("  [muted]" + " ".join(cmd) + "[/muted]")
        return

    p.out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        ev, human = split(line.rstrip())
        if ev is not None and ev.n:
            console.print(f"  [muted]{ev.i}/{ev.n} ({ev.pct:.0f}%) {ev.item}[/muted]",
                          end="\r")
        elif human:
            console.print(f"  [muted]{human}[/muted]")
    rc = proc.wait()

    # 🔴 Приймач повноти — диск, а не код повернення: при шардингу тиха втрата
    # сторінок дає rc=0 і порожній перелік збоїв.
    from nyshporka.htr.run import count_frames

    # ⚠ `done`, а не `pages`: так зветься прапорець `--pages`, і однойменна
    # локальна змінна затінювала його рівно в тому місці, де рахується повнота.
    done = len(list(p.out_dir.glob("*.txt")))
    # 🔴 Приймач «усі кадри мають текст» дійсний лише для повного прогону.
    # Частковий (--limit / --pages / --shard) прочитав менше навмисно, і
    # рахувати різницю як утрату означало б лякати червоним там, де все гаразд;
    # а звикнувши до червоного, його перестають читати й на справжній утраті.
    partial = bool(limit or pages or shard)
    missing = 0 if partial else max(0, count_frames(p.case_dir) - done)
    console.print(f"\n{'✅' if rc == 0 and not missing else '🔴'} "
                  f"сторінок з текстом: {done} з {p.frames}"
                  + (f" · без тексту: {missing}" if missing else "")
                  + (" · частковий прогін, повноту не міряю" if partial else ""))
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
    note: str = typer.Option("", "--note"),
    adopt: bool = typer.Option(False, "--adopt",
                               help="взяти теку під облік, якщо вона лежить "
                                    "поза простором"),
) -> None:
    """Завести або виправити справу: сказати, що лежить у цій теці.

    🔴 Без шифри тека лишається купою файлів — ні ключа, ні обліку, ні
    можливості послатись на знахідку.

    ⚠ Тека поза простором лишається невидимою в переліках: обхід іде по
    `data/raw` і по оголошених коренях справ. `--adopt` оголошує цю теку
    коренем у `nyshporka.toml` — файли при цьому не переносяться. Прапорця
    тут довго не було, хоч операція поле мала: єдиним шляхом з командного
    рядка лишався `nysh op case.register --args …`, тобто найпотрібніша
    новачкові дія була доступна найнезручнішим входом.
    """
    from nyshporka import ops as O

    env = O.call("case.register", {
        "case_dir": case_dir, "shifra": shifra, "title": title,
        "doc_type": doc_type, "place": place, "note": note,
        "year_from": year_from or None, "year_to": year_to or None,
        "adopt": adopt})
    _answer(env)
    sc = env.data["sidecar"]
    console.print(f"✅ [bold]{sc['shifra']}[/bold] — {sc.get('title') or 'без назви'}")
    if sc.get("year_from") or sc.get("place"):
        console.print(f"   [muted]{sc.get('place') or ''} "
                      f"{sc.get('year_from') or ''}"
                      f"{'-' + str(sc['year_to']) if sc.get('year_to') else ''}[/muted]")
    _notes(env)


@app.command("archive")
def archive_cmd(
    repo: str = typer.Argument(..., help="код архіву: DAHMO, CDIAK, ANRM…"),
    fond: str = typer.Argument(..., help="номер фонду"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Що пак знає про фонд: губернія, опис у ключі, дефолти.

    🔴 Питати це треба перед тим, як складати ключ справи. У частині фондів
    опис входить у ключ, і без нього різні книги злипаються в одну — знайти
    це потім можна лише за чужими сторінками у своїй справі.
    """
    from nyshporka import ops as O

    env = O.call("archive.fond", {"repo": repo, "fond": fond})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['repo_label'] or d['repo']} ф.{d['fond']}[/bold] "
                  f"{d.get('name') or ''}")
    console.print(f"  губернія: {d.get('guberniya') or '—'} · опис у ключі: "
                  f"{'так' if d.get('opys_in_key') else 'ні'} · опис за "
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

    🔴 Іде через ту саму операцію, що й форма в браузері. Доти команда писала
    файл повз реєстр, тобто той самий запис існував двічі — а реєстр операцій
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


def profile_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
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
        help="лише в цій справі: ключ «DAHMO/315/8433», шифра "
             "«ДАХмО 315-1-8433», шлях теки або ім'я прогону"),
    where: str = typer.Option("decode", "--where",
                              help="decode | pages | records"),
    context: int = typer.Option(1, "--context",
                                help="рядків сусідства (0 — лише сам рядок)"),
    thresh: int = typer.Option(80, "--thresh", help="поріг схожості 50-100"),
    limit: int = typer.Option(40, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
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
                                "limit": limit})
    if _answer(env, as_json):
        return
    hits = env.data.get("hits") or []
    for h in hits:
        head = f"{h.get('name')} · {h.get('page')} · рядок {h.get('line_no')}"
        console.print(f"[bold]{h.get('score')}[/bold]  {head}")
        for b in (h.get("context") or {}).get("before") or []:
            console.print(f"      [muted]↑ {b}[/muted]")
        console.print(f"    [warn]»[/warn] {h.get('line')}")
        for a in (h.get("context") or {}).get("after") or []:
            console.print(f"      [muted]↓ {a}[/muted]")
        if h.get("alt"):
            console.print(f"      [accent]2-й голос:[/accent] [muted]{h['alt']['line']}[/muted]")
    # 🔴 Знаменник друкується завжди, і найважливіший він саме при нулі:
    # без нього «не знайшлось» читається як «цього не існує».
    _notes(env)
    console.print(f"[muted]показано {len(hits)} із {env.data.get('total', len(hits))}[/muted]")
    if hits:
        console.print("[muted]подивитись оком: гортач у `nysh serve` — і брати "
                      "line_index, не line_no[/muted]")


@app.command("review")
def review_cmd(
    source: str = typer.Option("", "--source", help="лише з цього джерела"),
    min_score: float = typer.Option(0.0, "--min-score"),
) -> None:
    """Людський gate: перебрати кандидатів із зовнішніх джерел.

    🔴 Жоден кандидат не потрапляє в канон машиною. Це не обережність, а
    вимірювана вартість: збіг прізвища й десятиліття дає правдоподібну, але
    чужу особу, і виявляється це через покоління дерева.

    Кандидатів пишуть fetcher'и зовнішніх сайтів, яких у цій версії ще немає
    (правове питання ToS чужих сервісів), тож на щойно створеному просторі
    черга буде порожня — це стан, а не поламка.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.matching.review import review_loop

    _need("research")
    review_loop(workspace().root, source=source or None, min_score=min_score,
                console=console)


cases_app = typer.Typer(help="Реєстр справ: що є, що прочитано, що прошукано.",
                        no_args_is_help=True)
app.add_typer(cases_app, name="cases")

# 🗺 Газетир: від села до справ по всіх фондах — зворотний напрям до реєстру
# опису. Модуль існував, але зареєстрований не був: команди `nysh geog …` не
# існувало, хоч код і повідомлення на неї вже посилались (глухий кут у сенсі
# `test_no_dead_ends`).
from nyshporka.geog.cli import app as geog_app  # noqa: E402

app.add_typer(geog_app, name="geog")

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


@cases_app.command("build")
def cases_build(
    rescan: bool = typer.Option(True, "--rescan/--no-rescan",
                                help="перечитати ще й диск (нові теки)"),
) -> None:
    """Зібрати реєстр справ.

    🔴 Реєстр — це зріз п'яти сховищ, а не сховище. Він старіє за хвилини, і
    застарілий зріз небезпечніший за відсутній: він виглядає як відповідь
    («декоду немає») там, де роботу зробили годину тому. Тому перезбирати його
    треба після кожного прогону, завантаження й занесення в облік — а команди
    для цього досі не існувало, хоч усі повідомлення на неї посилались.
    """
    from nyshporka.cases import db

    res = db.rebuild(rescan=rescan)
    if res["rescanned"]:
        console.print(f"[muted]бібліотеку перезібрано: {res['entries']} справ[/muted]")
    console.print(f"✅ реєстр: [bold]{res['cases']}[/bold] справ · "
                  f"нерозв'язаних прогонів: {res.get('orphans', 0)} · {res['path']}")


@cases_app.command("list")
def cases_list_cmd(
    q: str = typer.Option("", "--q", help="підрядок: шифра, назва, місце"),
    repo: str = typer.Option("", "--repo"),
    year: str = typer.Option("", "--year", help="рік або «1840-1860»"),
    kind: str = typer.Option("", "--kind",
                             help="case | bundle | unfiled (матеріал без шифри)"),
    limit: int = typer.Option(40, "--limit"),
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


@pages_app.command("status")
def pages_status_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    scans: str = typer.Option("", "--scans",
                              help="кома-список сканів: питати про ці аркуші, "
                                   "а не про справу цілком"),
    as_json: bool = typer.Option(False, "--json"),
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
    case: str = typer.Argument(...),
    scan: str = typer.Argument(..., help="голе ім'я файлу: 0030.JPG"),
    page_type: str = typer.Option(..., "--type", help=_PAGE_TYPES_HELP),
    surnames: str = typer.Option("", "--surnames", help="кома-список ЯК У джерелі"),
    places: str = typer.Option("", "--places"),
    years: str = typer.Option("", "--years"),
    sheet: str = typer.Option("", "--sheet"),
    status: str = typer.Option("full", "--status", help=_PAGE_STATUS_HELP),
    method: str = typer.Option("visual", "--method", help=_PAGE_METHOD_HELP),
    comment: str = typer.Option("", "--comment"),
    agent: str = typer.Option("", "--agent",
                              help="хто заносив: ім'я людини або сесії"),
    as_json: bool = typer.Option(False, "--json"),
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
    case: str = typer.Argument(...),
    file: Path = typer.Option(None, "-f", "--file",
                              help="JSON-масив анотацій; без -f — читаємо stdin"),
    replace: bool = typer.Option(False, "--replace",
                                 help="замінити наявні, а не домержити"),
    as_json: bool = typer.Option(False, "--json"),
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
    case: str = typer.Option("", "--case"),
    axis: str = typer.Option("name", "--axis",
                             help="name — по прізвищу · place — по місцю "
                                  "(лише pages|records)"),
    role: str = typer.Option("", "--role", help=_ROLES_HELP),
    rtype: str = typer.Option("", "--rtype", help=_RTYPES_HELP),
    thresh: int = typer.Option(80, "--thresh", help="поріг схожості 50-100"),
    limit: int = typer.Option(50, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Знайти прізвище в тому, що вже прочитано."""
    from nyshporka import ops as O

    env = O.call("search.run", {"q": q, "where": where, "case": case,
                                "axis": axis, "role": role, "rtype": rtype,
                                "thresh": thresh, "limit": limit})
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
    as_json: bool = typer.Option(False, "--json"),
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
    as_json: bool = typer.Option(False, "--json"),
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
    case: str = typer.Option("", "--case"),
    role: str = typer.Option("", "--role", help=_ROLES_HELP),
    rtype: str = typer.Option("", "--rtype", help=_RTYPES_HELP),
    axis: str = typer.Option("name", "--axis", help="name — по прізвищу · "
                                                   "place — по місцю"),
    thresh: int = typer.Option(80, "--thresh", help="поріг схожості 50-100"),
    limit: int = typer.Option(50, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Знайти прізвище серед розібраних записів — за роллю й типом акту."""
    pages_grep_cmd(q=q, where="records", case=case, axis=axis, role=role,
                   rtype=rtype, thresh=thresh, limit=limit, as_json=as_json)


@records_app.command("show")
def records_show_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    rid: str = typer.Argument(..., help="id запису — з `records grep`"),
    as_json: bool = typer.Option(False, "--json"),
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
    as_json: bool = typer.Option(False, "--json"),
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
    as_json: bool = typer.Option(False, "--json"),
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
    as_json: bool = typer.Option(False, "--json"),
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
    as_json: bool = typer.Option(False, "--json"),
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
    as_json: bool = typer.Option(False, "--json"),
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
def htr_env_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
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

    🔴 Окремий не для краси: сегментація йде на `kraken==7.0.2` з двома
    патчами приватних функцій, доведеними рівними оригіналу саме на цій версії.
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
    mark = {"ok": "✅", "absent": "▫️", "broken": "🔴"}
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
    want = [p for p in known if not which or p.id == which]
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


@app.command()
def serve(
    port: int = typer.Option(8788, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser",
                                    help="не відкривати вкладку самому"),
) -> None:
    """Підняти застосунок у браузері.

    🔴 Слухає лише 127.0.0.1, і опції це змінити немає. Тут архів однієї
    людини — канон про живих родичів, скани, нотатки; прапорець «слухати всюди»
    рано чи пізно вмикають «на хвилинку» й лишають.
    """
    try:
        from nyshporka.daemon import serve as _serve
    except (ImportError, RuntimeError) as exc:
        console.print(f"[err]{exc}[/err]")
        console.print(r"[muted]pip install 'nyshporka\[app]'[/muted]")
        raise typer.Exit(code=1) from None
    _serve(port=port, open_browser=not no_browser)


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
def sections_preset(name: str = typer.Argument(..., help="amateur | researcher | lab"),
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

    out = S.install(dest, version=__version__, force=force, names=names)
    if not out:
        console.print("[warn]![/warn] нічого не встановлено")
        raise typer.Exit(code=1)

    tally: dict[str, int] = {}
    for o in out:
        tally[o.verdict] = tally.get(o.verdict, 0) + 1
    word = {"new": "нових", "updated": "оновлено", "same": "без змін",
            "kept": "лишено (правлено руками)"}
    parts = [f"{word[k]} {v}" for k, v in tally.items() if k in word]
    console.print(f"✓ {dest} — " + " · ".join(parts))

    # 🔴 Правлене руками називається поіменно: зведене число тут читалось би як
    # «щось не поклалось», хоча це свідоме рішення інструмента не чіпати чужу
    # роботу. Мовчазний пропуск був би гіршим за помилку.
    if kept := [o.rel for o in out if o.verdict == "kept"]:
        console.print("  [muted]не чіпав (є ваші правки; --force перезапише):[/muted]")
        for rel in kept:
            console.print(f"    {rel}")

    where = "у будь-якому проєкті" if user else "у цьому проєкті"
    console.print(f"  [muted]видно агентові {where}; перезапустіть сесію[/muted]")


mcp_app = typer.Typer(help="Перелік tool'ів для Claude Code / Codex — коротший шлях до того, що вміє `nysh op`.",
                      no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Підняти MCP-сервер по stdio (так його запускає агент)."""
    from nyshporka.mcp import serve

    raise typer.Exit(code=serve())


@mcp_app.command("tools")
def mcp_tools() -> None:
    """Що саме бачить агент."""
    from nyshporka.mcp import tool_definitions

    defs = tool_definitions()
    for d in defs:
        console.print(f"  [bold]{d['name']:<22}[/bold] {d['description']}")
    console.print(f"\n[muted]усього {len(defs)}[/muted]")


@mcp_app.command("install")
def mcp_install(
    target: str = typer.Option(".mcp.json", help="куди дописати конфіг"),
    show: bool = typer.Option(False, "--show", help="лише показати, не писати"),
) -> None:
    """Прописати сервер у `.mcp.json` проєкту."""
    import json as _json

    from nyshporka.mcp import mcp_config

    cfg = mcp_config()
    if show:
        console.print_json(data=cfg)
        return
    path = Path(target)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = _json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            console.print(f"[warn]![/warn] {path} не є JSON — не чіпаю його")
            raise typer.Exit(code=1) from None
    # Дописуємо, а не заміщаємо: у файлі можуть бути чужі сервери, і затерти їх
    # означало б зламати налаштування, які людина робила руками.
    servers = dict(existing.get("mcpServers") or {})
    servers.update(cfg["mcpServers"])
    existing["mcpServers"] = servers
    path.write_text(_json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    console.print(f"✓ {path}: додано сервер «nyshporka»")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
