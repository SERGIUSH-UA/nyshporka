#!/usr/bin/env python3
"""🔒 Ворота проти приватних даних у публічному репозиторії.

Цей пакет виділяється з приватного дослідницького репо однієї родини. Небезпека
тут не в тому, що хтось свідомо закомітить канон живих осіб, а в тому, що це
станеться ВИПАДКОВО: один `git add -A` у розгоні, скопійований для прикладу
шматок коду з реальним ID особи, шлях `E:\\Projects\\MeGen\\...` у докстрінгу.

🔴 Головне: git не забуває. Файл, закомічений і видалений наступним комітом,
лишається в історії назавжди, і «прибрати» його означає переписати історію вже
опублікованого репозиторію. Тому перевірка мусить стояти ДО коміту, а не після.

    python tools/scan_private.py                # робоче дерево
    python tools/scan_private.py --staged       # те, що зараз у git add (pre-commit)
    python tools/scan_private.py --history      # УСЯ історія (перед першим push)

Вихід 0 — чисто, 1 — знайдено, 2 — помилка запуску.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Розширення, які взагалі має сенс читати як текст.
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
    ".html", ".css", ".js", ".ts", ".sh", ".ps1", ".jsonl", ".tsv", ".csv", "",
}
#: Каталоги, у які не заходимо ніколи.
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
             ".ruff_cache", ".pytest_cache", "dist", "build", ".idea", ".vscode"}
#: 🔴 Імена, які бувають ФАЙЛОМ, а не текою. `SKIP_DIRS` підрізає лише обхід
#: каталогів, тож `.git` у git-worktree і в субмодулі (там це файл із рядком
#: `gitdir: <абсолютний шлях>`) проходив повз і давав ХИБНУ тривогу на правило
#: абсолютного шляху. Ворота, які кричать на службовий файл git, привчають
#: розробника відмахуватись від них — а це рівно те, чого вони мають не
#: допустити. Розширення тут не рятує: `Path(".git").suffix` порожній, а
#: порожній суфікс у `TEXT_SUFFIXES` є навмисно (LICENSE, Dockerfile).
SKIP_NAMES = {".git"}
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Rule:
    id: str
    why: str
    pattern: re.Pattern[str]


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


RULES: tuple[Rule, ...] = (
    # ── ідентифікатори канону ────────────────────────────────────────────────
    # Особи/родини/місця приватного дослідження. Саме вони найлегше приїжджають
    # разом зі скопійованим прикладом чи тестовою фікстурою.
    Rule("canon-person", "ID особи з приватного канону (I0123)",
         re.compile(r"\bI0\d{3}\b")),
    Rule("canon-family", "ID родини з приватного канону (F0123)",
         re.compile(r"\bF0\d{3}\b")),
    Rule("canon-place", "ID місця з приватного канону (PL0123)",
         re.compile(r"\bPL0\d{3}\b")),
    Rule("canon-source", "ID джерела з приватного канону (S_DAHMO_F315_...)",
         re.compile(r"\bS_[A-Z]{2,}_F\d+")),

    # ── прізвище роду в усіх написаннях ──────────────────────────────────────
    # 🔴 Не одна форма, а корінь із варіантами: декод і транслітерація дають
    # десяток написань, і фільтр на єдине «Долищинський» пропустив би більшість.
    # ⚠ Перша редакція вимагала `c`/`s` після кореня (`doli[sș][cs]`) і через це
    # не бачила голого румунського `doliş` — тобто саме тієї форми, заради якої
    # варіанти й перелічуються.
    Rule("clan-surname", "прізвище роду з приватного дослідження",
         _rx(r"д[оаі]л[иіы]щ[иі]н|d[oa]li[sșş]")),

    # 🔴 СПОТВОРЕНІ ФОРМИ того самого прізвища — окреме правило, бо в жодній з
    # них немає складу, за яким ловить попереднє: рушій калічить саме СЕРЕДИНУ
    # слова. Ці форми виглядають як шум машинного читання, а насправді це
    # перелік того, що шукає одна родина, — і саме тому вони найлегше проїдуть
    # повз ока в скопійованому прикладі чи в тексті інструкції для агента.
    # ⚠ Свідомо НЕ ловляться «Доманський» і «Долинський»: обидва — поширені
    # самостійні прізвища, і правило на них заважало б чужому дослідженню в
    # пакеті, яким користуються інші люди. Ціна пропуску тут менша за ціну
    # правила, що бореться з користувачем.
    Rule("clan-misread", "спотворена форма прізвища роду (як її калічить рушій)",
         _rx(r"дом[иі]н[сc]к|дем[иі]ц[иі]н|дон[иі]ц[иі]н|домб[иі]н|дом[іи]ан[сc]к")),

    # ── особистий контакт ────────────────────────────────────────────────────
    # 🔴 Пошта дослідника — не «майже те саме», що прізвище: вона їде В КОЖНОМУ
    # HTTP-ЗАПИТІ, якщо потрапила в User-Agent, і осідає в логах чужих сайтів,
    # звідки її вже не прибрати. Знайдено при перенесенні завантажувачів: два
    # скрипти несли адресу автора в UA, і жодне з наявних правил її не бачило —
    # перевірено підкладеним файлом, ворота пройшли повз.
    # ⚠ Ловиться будь-яка адреса, а не одна конкретна: у пакеті, який ставлять
    # чужі люди, зашита особиста пошта — завжди питання, чия вона й навіщо там.
    # Законний виняток — файли, де адреса є ДАНИМИ (контакт архіву в доці).
    Rule("contact-email", "особиста поштова адреса в коді",
         _rx(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b")),

    # ── локальні шляхи ───────────────────────────────────────────────────────
    # Абсолютний шлях машини автора — не секрет, але він робить код непереносним
    # і видає структуру приватного архіву.
    # 🔴 Перелік тек тут НЕ вичерпний, і саме тому друга альтернатива ловить
    # будь-який `<літера>:/megen*`. Спіймано перед першим push: приклади в
    # докстрінгах несли `E:/megen_stage/…` і `T:/megen_spotter_out/…` — обидва
    # проходили повз, бо після літери диска стояла не «Projects» і не «Temp».
    # Правило, яке перелічує ЗНАЙОМІ випадки, ловить лише знайомі.
    Rule("abs-path-win", "абсолютний шлях Windows із машини автора",
         _rx(r"[A-Z]:[\\/](?:Projects|Users|Temp|megen[\w-]*)[\\/]")),
    Rule("abs-path-nix", "абсолютний шлях із чужої машини/VPS",
         re.compile(r"(?:^|[\"'\s=])/(?:root|home)/[a-z0-9_.-]+/")),
    Rule("private-repo", "ім'я приватного репозиторію дослідження",
         _rx(r"\bmegen\b|megen_archive|SERGIUSH-UA/domus")),

    # ── секрети ──────────────────────────────────────────────────────────────
    Rule("aws-presigned", "presigned-URL з креденшелом (X-Amz-...)",
         _rx(r"X-Amz-(?:Credential|Signature|Security-Token)")),
    Rule("bearer", "захардкоджений токен/ключ",
         _rx(r"(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}")),
    Rule("private-host", "приватний хост/тунель автора",
         _rx(r"easykey-backup|itdeo\.tech")),
)

#: Свідомі винятки: файл (glob) → які правила там дозволені.
#: 🔴 Виняток завжди ТОЧКОВИЙ — правило × шлях. Глобальне «ігнорувати цей файл»
#: перетворює ворота на декорацію: наступна людина допише туди що завгодно.
ALLOW: tuple[tuple[str, str], ...] = (
    # Сам сканер містить усі патерни за визначенням.
    ("tools/scan_private.py", "*"),
    # README пояснює, звідки походить проєкт, і називає приватний репо.
    ("README.md", "private-repo"),
    # Тест воріт мусить містити зразки того, що вони ловлять.
    ("tests/test_scan_private.py", "*"),
    # 🔴 Атрибуція автора — НЕ приватні дані, хоч і збігається з прізвищем, яке
    # шукає дослідження. Межа тут проходить не по слову, а по ролі: ім'я автора
    # у метаданих пакета публічне за призначенням, а те саме прізвище всередині
    # КОДУ (у списку форм пошуку, у фікстурі, у тестових даних) — ознака, що
    # сюди приїхав шматок приватного конвеєра. Виняток точковий саме тому.
    ("pyproject.toml", "clan-surname"),
    # Та сама роль, що рядком вище, лише в іншому файлі: ліцензія ваг мусить
    # називати, кого атрибутувати, — без імені автора вимога CC BY не виконувана
    # в принципі. Знову точково: ім'я в АТРИБУЦІЇ публічне за призначенням, те
    # саме прізвище у списку форм пошуку — ознака приватного конвеєра.
    ("LICENSE-MODELS.md", "clan-surname"),
    # 🔴 Токен у тесті демона — навмисна константа, і саме тому виняток
    # ТОЧКОВИЙ (правило × файл), а не «не перевіряти tests/». Перевірка «мутація
    # без токена → 403» без токена в коді неможлива, але сусідній тест, який
    # випадково принесе справжній ключ, мусить упертись у ті самі ворота.
    ("tests/test_daemon.py", "bearer"),
    # 🔴 ТРЕТЯ РОЛЬ прізвища, і межа проходить так само по ролі, а не по слову.
    # Вкладена зразкова справа — це ЦИТАТА З ПЕРШОДЖЕРЕЛА: машинний декод трьох
    # аркушів ДАХмО ф.315 оп.1 спр.159 (1821-1822), документа, що зберігається в
    # держархіві й доступний будь-кому за шифрою. Прізвище стоїть там, де його
    # написав писар 1822 року, а не в списку форм пошуку й не в фікстурі з
    # ідентифікаторами живих осіб — тобто це не ознака, що сюди приїхав шматок
    # приватного конвеєра. Рішення дослідника 2026-08-17.
    #
    # ⚠ Виняток ТОЧКОВИЙ саме тому, що роль вирішує все: той самий корінь у
    # будь-якому іншому файлі пакета лишається знахідкою й валить ворота.
    ("src/nyshporka/setup/data/sample/*", "clan-surname"),
    ("src/nyshporka/setup/data/sample/*/*", "clan-surname"),
    ("src/nyshporka/setup/data/sample/*/*/*", "clan-surname"),
    # 🔴 Правило ловить ФОРМУ ID, а не конкретний архів, тож навіть вигаданий
    # «S_XYZ_F1_D2» його вмикає. А приймач розбору ID без жодного ID неможливий:
    # саме він стереже, що нова група під літерний префікс радянського фонду не
    # зламала звичайні, суто числові. Виняток ТОЧКОВИЙ (правило × файл) — якщо в
    # цей же тест колись приїде справжній ID канону, ворота його вже не спинять,
    # тож ID тут мусять лишатися вигаданими свідомо.
    ("tests/test_case_key_builder.py", "canon-source"),
    # Тест зразка мусить шукати саме те слово, яке в зразку є: приймач ланцюга
    # «пошук у декоді → гортач показує ТОЙ САМИЙ рядок» інакше нічого не
    # доводить (див. `test_sample_deploys_a_working_chain`).
    ("tests/test_setup.py", "clan-surname"),
    # Приклад у тесті UA: перевіряється, що контакт додається ЛИШЕ коли його
    # вписали руками. Домен `example.org` зарезервований саме для прикладів,
    # тож це не чиясь адреса, а зразок форми.
    ("tests/test_http.py", "contact-email"),
    # 🔴 `cases/cli.py` обслуговує ОБА конвеєри й у публічному пакеті нікуди не
    # підключений (до `nysh` ведуть власні `cases build|list|bind`). Команд
    # `take`/`show` у `nysh` немає, тож підказка про сусідній інструмент тут
    # ПРАВДИВА — а замінити її на `nysh` означало б повернути ту саму пораду в
    # нікуди, яку паралельна сесія щойно й виправляла.
    ("src/nyshporka/cases/cli.py", "private-repo"),
    # 🔴 Ім'я старої теки стану — це АДРЕСА НА ДИСКУ, а не згадка репозиторію.
    # Ліміт запитів спільний на машину; доки поруч працюють і пакет, і скрипти
    # того репозиторію, різні теки означають дві черги на один IP, тобто
    # подвоєний темп рівно тим механізмом, який мав його стримати. Виняток
    # зникне разом із фолбеком, коли перехід завершиться.
    ("src/nyshporka/core/xrate.py", "private-repo"),
)


def _allowed(rel: str, rule_id: str) -> bool:
    rel = rel.replace("\\", "/")
    for pat, allowed in ALLOW:
        if (rel == pat or Path(rel).match(pat)) and allowed in ("*", rule_id):
            return True
    return False


@dataclass
class Finding:
    path: str
    line_no: int
    rule: Rule
    excerpt: str


def scan_text(rel: str, text: str, where: str | None = None) -> list[Finding]:
    """`rel` — шлях ДЛЯ ЗВІРКИ з винятками, `where` — підпис для показу.

    🔴 Ці дві речі мусять бути розділені, і це не педантизм. Перша редакція
    режиму `--history` віддавала шлях у вигляді `tests/foo.py @26d20e22`, щоб у
    виводі було видно коміт, — і через приліплений sha жоден виняток не
    збігався. Ворота при цьому не мовчали, а навпаки: сипали 27 «знахідками» у
    власних тестах, тобто в CI стояли б вічно червоними. Ворота, які завжди
    червоні, вимикають — і тоді вони не ловлять уже нічого.
    """
    out: list[Finding] = []
    label = where or rel
    # 🔴 Винятки залежать від ФАЙЛА, не від рядка, тож рахуються один раз. У
    # першій редакції `_allowed` стояв усередині подвійного циклу й конструював
    # `Path` для glob-матчингу на кожну пару (рядок × правило): на історії це
    # 1.65 млн викликів і 49 секунд там, де роботи на секунду.
    rules = [r for r in RULES if not _allowed(rel, r.id)]
    if not rules:
        return out
    for i, line in enumerate(text.splitlines(), 1):
        for rule in rules:
            m = rule.pattern.search(line)
            if m:
                frag = line.strip()
                if len(frag) > 120:
                    lo = max(0, m.start() - 50)
                    frag = ("…" if lo else "") + line[lo:lo + 120].strip() + "…"
                out.append(Finding(label, i, rule, frag))
    return out


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


#: (шлях для звірки з винятками, текст, підпис для показу)
Item = tuple[str, str, str]


def iter_worktree() -> list[Item]:
    """🔴 `SKIP_DIRS` підрізає ОБХІД, а не відсіює результат.

    `rglob("*")` із перевіркою після факту все одно заходить усередину `.venv` і
    `node_modules` — а це десятки тисяч файлів, тобто 34 секунди на кожен запуск
    воріт, які стоять у pre-commit. Тут дешевше не «не читати», а «не заходити».
    """
    out: list[Item] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        base = Path(dirpath)
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            p = base / fn
            if p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = p.relative_to(ROOT).as_posix()
            out.append((rel, text, rel))
    return out


def iter_staged() -> list[Item]:
    """Вміст, який ЗАРАЗ у індексі — саме він потрапить у коміт.

    Читаємо з `git show :file`, а не з диска: інакше перевірка дивилась би на
    робоче дерево, тоді як закомітиться індекс, і `git add -p` пройшов би повз.
    """
    names = [n for n in _git("diff", "--cached", "--name-only", "-z").split("\0") if n]
    out: list[Item] = []
    for rel in names:
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            out.append((rel, _git("show", f":{rel}"), rel))
        except RuntimeError:
            continue  # видалений файл
    return out


def _git_bytes(*args: str, stdin: bytes = b"") -> bytes:
    res = subprocess.run(["git", *args], cwd=ROOT, input=stdin, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.decode(errors='replace')}")
    return res.stdout


def _batch_read(shas: list[str]) -> dict[str, bytes]:
    """Вміст блобів одним викликом `git cat-file --batch`.

    🔴 Не мікрооптимізація. Наївний варіант (`cat-file -s` + `cat-file -p` на
    кожен об'єкт) — це два процеси на блоб, і на Windows, де запуск процесу
    коштує дорого, весь режим `--history` займав 171 секунду. Тест, який стільки
    думає, розробник вимикає — а це рівно ті ворота, ціна пропуску яких
    незворотна.

    Формат `--batch`: рядок `<sha> <type> <size>`, далі рівно `size` байтів
    вмісту і `\\n`. Читаємо саме за лічильником, а не за роздільником: у
    текстовому файлі трапляється будь-що, і розбір «до наступного порожнього
    рядка» тихо з'їхав би на першому ж файлі з такою послідовністю.
    """
    if not shas:
        return {}
    buf = _git_bytes("cat-file", "--batch", stdin=("\n".join(shas) + "\n").encode())
    out: dict[str, bytes] = {}
    i = 0
    while i < len(buf):
        nl = buf.find(b"\n", i)
        if nl < 0:
            break
        head = buf[i:nl].decode(errors="replace").split()
        i = nl + 1
        if len(head) != 3:          # `<sha> missing` — об'єкт зник між викликами
            continue
        sha, size = head[0], int(head[2])
        out[sha] = buf[i:i + size]
        i += size + 1               # +1 — перевід рядка після вмісту
    return out


def iter_history() -> list[Item]:
    """Усі версії всіх текстових файлів в історії.

    Потрібно перед кожним `push`: після нього прибрати знахідку означає
    переписати опубліковану історію. Один об'єкт може лежати під кількома
    іменами — беремо перше, бо виняток звіряється зі шляхом.
    """
    names: dict[str, str] = {}
    for line in _git("rev-list", "--objects", "--all").splitlines():
        sha, _, name = line.partition(" ")
        if not name or Path(name).suffix.lower() not in TEXT_SUFFIXES:
            continue
        names.setdefault(sha, name)
    # Розміри — окремим пакетом: `--batch-check` віддає лише заголовки, тож
    # величезний блоб не доводиться тягти в пам'ять, щоб дізнатись, що він завеликий.
    small: list[str] = []
    head = _git_bytes("cat-file", "--batch-check",
                      stdin=("\n".join(names) + "\n").encode()).decode(errors="replace")
    for line in head.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob" and int(parts[2]) <= MAX_BYTES:
            small.append(parts[0])
    # Шлях для звірки — чистий; коміт-об'єкт іде лише в підпис. Змішавши їх, ми
    # зробили б винятки недієвими саме тут (див. `scan_text`).
    return [(names[sha], blob.decode("utf-8", errors="replace"), f"{names[sha]} @{sha[:8]}")
            for sha, blob in _batch_read(small).items()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="лише те, що в git add")
    g.add_argument("--history", action="store_true", help="уся історія (перед першим push)")
    ap.add_argument("--list-rules", action="store_true", help="показати правила й вийти")
    a = ap.parse_args()

    if a.list_rules:
        for r in RULES:
            print(f"  {r.id:16s} {r.why}")
        return 0

    try:
        if a.staged:
            items, what = iter_staged(), "індекс"
        elif a.history:
            items, what = iter_history(), "історія"
        else:
            items, what = iter_worktree(), "робоче дерево"
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for rel, text, where in items:
        findings += scan_text(rel, text, where)

    if not findings:
        print(f"✅ приватних даних не знайдено ({what}: {len(items)} файлів, "
              f"{len(RULES)} правил)")
        return 0

    print(f"🔴 ЗНАЙДЕНО ПРИВАТНІ ДАНІ ({what}) — {len(findings)} збігів:\n")
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule.id, []).append(f)
    for rid, group in sorted(by_rule.items()):
        print(f"  ▸ {rid} — {group[0].rule.why}  ({len(group)})")
        for f in group[:8]:
            print(f"      {f.path}:{f.line_no}  {f.excerpt}")
        if len(group) > 8:
            print(f"      … ще {len(group) - 8}")
    print("\nЩо робити: прибрати дані або, якщо це свідомий приклад, додати "
          "ТОЧКОВИЙ виняток у `ALLOW` (правило × шлях, не «ігнорувати файл»).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
