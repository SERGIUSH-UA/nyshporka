"""🔒 Ворота проти приватних даних мусять ловити те, заради чого стоять.

Тест, який лише перевіряє «сканер запускається», нічого не вартий: ворота
цінні рівно настільки, наскільки вони спрацьовують на реальних зразках. Тому
нижче — зразки саме тих рядків, які реально траплялись у приватному репо.

⚠ Цей файл свідомо містить приклади приватних даних, і саме тому він доданий
у `ALLOW` сканера цілком. Це єдиний файл із таким винятком.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("scan_private", ROOT / "tools" / "scan_private.py")
scan = importlib.util.module_from_spec(_spec)
# 🔴 Реєстрація в `sys.modules` до виконання обов'язкова, а не косметична:
# з Python 3.14 `@dataclass` резолвить `cls.__module__` через `sys.modules`, і
# для незареєстрованого модуля це `None` → AttributeError на самому імпорті.
# На 3.12/3.13 те саме працює й без цього рядка, тобто пастка спрацьовує рівно
# в того, хто прийде з новішим інтерпретатором.
sys.modules[_spec.name] = scan
_spec.loader.exec_module(scan)


@pytest.mark.parametrize("rule_id, sample", [
    ("canon-person", 'ANCHORS = {"I0175": (1803, "З віку", "…")}'),
    ("canon-family", "родина F0099 злита з F0021"),
    ("canon-place", "place_id: PL0044"),
    ("canon-source", "S_DAHMO_F315_D8433"),
    ("clan-surname", "VARIANTS = [(\"Долищинский\", 0.28)]"),
    ("clan-surname", 'FULL_FORMS = ["Doliszczynski"]'),
    ("clan-surname", "roots = doliş"),
    # 🔴 Форми, у яких шуканого складу немає: рушій калічить середину слова,
    # тож попереднє правило їх не бачить, а разом вони називають рід не гірше
    # за канонічне написання.
    ("clan-misread", 'MISREADS = ["доминскій", "демицинскій"]'),
    ("clan-misread", "варіант декоду: Домбинскій"),
    # 🔴 Пошта в User-Agent їде в кожен запит до чужого сайту й осідає в його
    # логах — прибрати її звідти вже не можна. Саме так вона й трапилась: два
    # перенесені завантажувачі несли адресу автора, і жодне з тодішніх правил
    # її не бачило.
    ("contact-email", 'UA = "MeGen/0.1 (research; hidden.person@gmail.com)"'),
    ("contact-email", "контакт: someone.else@ukr.net"),
    ("abs-path-win", 'ROOT = Path("E:/Projects/MeGen")'),
    ("abs-path-win", r'cache = "T:\megen_archive\dahmo_196"'),
    ("abs-path-nix", 'deploy_to = "/root/projects/site"'),
    ("private-repo", "git clone https://github.com/SERGIUSH-UA/domus.git"),
    ("aws-presigned", "https://r2/assets.tgz?X-Amz-Credential=abc%2F20260813"),
    ("bearer", 'api_key = "sk_live_0123456789abcdef"'),
    ("private-host", "ssh easykey-backup -D 1080"),
])
def test_rule_catches_real_sample(rule_id, sample):
    hits = scan.scan_text("some/file.py", sample)
    assert rule_id in {h.rule.id for h in hits}, (
        f"правило «{rule_id}» пропустило свій же зразок: {sample!r}")


@pytest.mark.parametrize("clean", [
    "def load_case(ref: CaseRef) -> CaseFile | None:",
    "ROOT = Path(__file__).resolve().parents[3]",
    "уточни опис (напр. «ДАХмО 315-1-8433»)",
    "import torch  # noqa",
    "surname = profile.stems['uk']",
    "https://github.com/SERGIUSH-UA/nyshporka",
    "I0 та F0 без цифр — не ідентифікатори",
    "PL0 — теж ні",
])
def test_ordinary_code_is_not_flagged(clean):
    """Ворота з хибними спрацюваннями вимикають, і тоді вони не ловлять нічого."""
    assert not scan.scan_text("some/file.py", clean), (
        f"хибне спрацювання на звичайному рядку: {clean!r}")


def test_allow_is_pointwise_not_blanket():
    """🔴 Виняток — правило × шлях. «Ігнорувати цей файл» перетворює ворота на
    декорацію: наступна людина допише туди що завгодно."""
    assert scan._allowed("README.md", "private-repo")
    assert not scan._allowed("README.md", "canon-person")
    assert not scan._allowed("src/nyshporka/cli.py", "clan-surname")


def _rules_stamp() -> str:
    """Відбиток правил, винятків і самого сканера: змінене правило чи логіка
    звірки (`scan_text`, `_allowed`, ліміт розміру) не знайде старого кешу —
    інакше блоб, «чистий» під старою логікою, лишився б чистим і під новою
    (рецензія 20.10.2026)."""
    import hashlib
    import inspect
    import json

    rules = [(r.id, r.pattern.pattern, r.pattern.flags) for r in scan.RULES]
    code = [inspect.getsource(scan.scan_text), inspect.getsource(scan._allowed),
            str(scan.MAX_BYTES)]
    return hashlib.sha1(json.dumps([rules, list(scan.ALLOW), code]).encode()).hexdigest()[:16]


def _scan_remembering_clean(items, pytestconfig: pytest.Config) -> list:
    """`scan_text` по всіх `items`, але вже чисті (шлях, вміст) не переглядаються.

    Регекси по 61 МБ історії — ~35 с на кожен прогін, хоча історія не
    змінюється: той самий блоб під тими самими правилами дає той самий
    результат. Пам'ятаються ЛИШЕ чисті; файл зі знахідкою перевіряється щоразу.
    Ключ кешу — відбиток усіх правил і винятків, тож змінене правило чи виняток
    не знайде старого кешу й перегляне все. Без `cacheprovider` — повний прохід.
    """
    import hashlib

    cache = getattr(pytestconfig, "cache", None)
    slot = f"scan_private/clean/{_rules_stamp()}"
    clean = set(cache.get(slot, [])) if cache is not None else set()
    findings, seen_clean = [], set()
    for rel, text, where in items:
        key = hashlib.sha1(f"{rel}\0{text}".encode("utf-8", "surrogatepass")).hexdigest()
        if key in clean:
            seen_clean.add(key)
            continue
        got = scan.scan_text(rel, text, where)
        findings += got
        if not got:
            seen_clean.add(key)
    if cache is not None:
        cache.set(slot, sorted(seen_clean | clean))
    return findings


def test_this_repository_is_clean(pytestconfig):
    """Найважливіша перевірка: сам репозиторій не містить приватних даних."""
    findings = _scan_remembering_clean(scan.iter_worktree(), pytestconfig)
    assert not findings, "\n".join(
        f"{f.path}:{f.line_no} [{f.rule.id}] {f.excerpt}" for f in findings[:20])


def test_git_ignored_files_are_not_scanned_in_the_worktree(tmp_path, monkeypatch):
    """Ігнорований файл у репозиторій не потрапить ніколи — і не має червонити.

    🔴 Це не послаблення воріт, а умова того, щоб вони лишались увімкненими:
    один особистий чернетковий файл у корені робив прогін вічно червоним, і
    кожен прогін доводилось запускати з `--ignore`. Те, що справді може поїхати
    в коміт, ловлять інші два режими — індекс і історія, — і саме вони тут
    лишаються недоторканими.
    """
    secret = 'ROOT = Path("E:/Projects/MeGen")'
    (tmp_path / ".gitignore").write_text("draft.md\n", encoding="utf-8")
    (tmp_path / "draft.md").write_text(secret, encoding="utf-8")
    (tmp_path / "kept.md").write_text(secret, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    monkeypatch.setattr(scan, "ROOT", tmp_path)
    seen = {rel for rel, _text, _where in scan.iter_worktree()}
    assert "draft.md" not in seen, "ігнороване git'ом не сканується в дереві"
    assert "kept.md" in seen, "неігнороване лишається під перевіркою"
    # А сам рядок і далі є приватним — ворота не «навчились» його пропускати.
    assert scan.scan_text("draft.md", secret)


@pytest.mark.timeout(900)
def test_this_repository_history_is_clean(pytestconfig):
    """🔴 Історія — не копія робочого дерева, і чистого дерева недостатньо.

    Git не забуває: рядок, доданий і виправлений наступним комітом, лишається в
    історії назавжди. Доти, доки гілка не опублікована, це коштує один
    `filter-branch`; після push — переписування чужих клонів.

    Перевірено на живому випадку: стара назва CLI (`megen geog build`) лишалась
    у чотирьох блобах двох комітів, тоді як обидва файли в дереві були вже
    виправлені. `test_this_repository_is_clean` цього не бачив за побудовою, і
    єдиним місцем, де провал спливав, був джоб CI — тобто вже після push, коли
    дешевого виправлення не лишається.
    """
    findings = _scan_history_remembering_clean(pytestconfig)
    assert not findings, "\n".join(
        f"{f.path}:{f.line_no} [{f.rule.id}] {f.excerpt}" for f in findings[:20])


def _scan_history_remembering_clean(pytestconfig: pytest.Config) -> list:
    """Те саме, що `_scan_remembering_clean`, але перевіряється лише НОВЕ.

    Коміт незмінний, тож історія, видима з уже перевірених вершин, чистою й
    лишається. Кеш тримає ці вершини (кілька sha на гілку), і наступний прохід
    бере лише блоби, яких із них не видно (`since`). Нових між прогонами —
    одиниці, тож прохід триває секунди, а не дві хвилини.

    Перелік чистих блобів живе лише під час холодного проходу (нові правила,
    свіжий клон): прогрес пишеться в кеш ПО ДОРОЗІ, бо прохід під навантаженням
    паку триває хвилини, а тайм-аут, що його вбивав, не давав кешу записатись
    ніколи — і кожен наступний пак знову стартував з холоду (pytest-timeout на
    Windows гасить воркер xdist цілком; пак 21.10.2026 тричі лягав на 99 %
    каскадом «node down»). Щойно прохід завершився чистим, вершини стають
    кешем, а перелік блобів стирається.

    Вершини пишуться лише після чистого проходу: блоб зі знахідкою інакше
    сховався б за вершиною й більше не перевірявся б."""
    cache = getattr(pytestconfig, "cache", None)
    stamp = _rules_stamp()
    tips_slot = f"scan_private/clean_tips/{stamp}"
    blobs_slot = f"scan_private/clean_blobs/{stamp}"
    since = cache.get(tips_slot, []) if cache is not None else []
    clean = set(cache.get(blobs_slot, [])) if cache is not None else set()
    tips = scan.history_tips()
    findings, seen_clean = [], set()
    saved_at = time.monotonic()
    for name, sha, text in scan.iter_history_blobs(
            skip=lambda n, s: f"{n}\0{s}" in clean, since=since):
        got = scan.scan_text(name, text, f"{name} @{sha[:8]}")
        findings += got
        if not got:
            seen_clean.add(f"{name}\0{sha}")
        if cache is not None and time.monotonic() - saved_at > SAVE_EVERY_SEC:
            cache.set(blobs_slot, sorted(seen_clean | clean))
            saved_at = time.monotonic()
    if cache is not None:
        if findings:
            cache.set(blobs_slot, sorted(seen_clean | clean))
        else:
            cache.set(tips_slot, tips)
            cache.set(blobs_slot, [])
    return findings


#: Як часто холодний прохід історії скидає прогрес у кеш.
SAVE_EVERY_SEC = 20.0


def test_history_mode_still_applies_the_allowlist():
    """🔴 Ворота, які завжди червоні, вимикають — і тоді вони не ловлять нічого.

    Перша редакція `--history` віддавала шлях як `tests/foo.py @26d20e22`, щоб у
    виводі було видно коміт. Через приліплений sha жоден виняток не збігався, і
    режим сипав 27 «знахідками» у власних тестах. Тобто джоб CI, який мав би
    стерегти найдорожчу помилку, стояв би червоним із першого дня.
    """
    hits = scan.scan_text("tests/test_scan_private.py",
                          'приклад: I0175 і "Долищинский"',
                          where="tests/test_scan_private.py @deadbeef")
    assert hits == [], "виняток перестав діяти, щойно до шляху додали коміт"

    # А підпис при цьому мусить лишатись інформативним для НЕдозволеного файлу.
    hits = scan.scan_text("src/nyshporka/foo.py", "I0175",
                          where="src/nyshporka/foo.py @deadbeef")
    assert hits and hits[0].path.endswith("@deadbeef")


def test_every_rule_has_a_sample_in_this_file():
    """Правило без зразка — правило, про яке ніхто не знає, чи воно працює."""
    covered = {"canon-person", "canon-family", "canon-place", "canon-source",
               "clan-surname", "clan-misread",
               "contact-email", "abs-path-win", "abs-path-nix",
               "private-repo", "aws-presigned", "bearer", "private-host"}
    assert {r.id for r in scan.RULES} == covered


def test_a_dirty_blob_is_reported_on_every_run_not_only_the_first(tmp_path, monkeypatch):
    """🔴 Кеш пам'ятає лише ЧИСТІ блоби: блоб зі знахідкою читається й червонить
    щоразу, а не лише на холодному кеші."""

    class Cache(dict):
        def get(self, key, default):
            return super().get(key, default)

        def set(self, key, value):
            self[key] = value

    class Config:
        cache = Cache()

    secret = 'ROOT = Path("E:/Projects/MeGen")'
    (tmp_path / "clean.md").write_text("нічого приватного\n", encoding="utf-8")
    (tmp_path / "leak.md").write_text(secret + "\n", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([*git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    first = _scan_history_remembering_clean(Config())
    second = _scan_history_remembering_clean(Config())
    assert [f.path for f in first] == [f.path for f in second] != []
    assert any(k.startswith("clean.md\0") for v in Config.cache.values() for k in v)


def test_clean_history_is_remembered_by_tips_and_only_new_commits_are_read(
        tmp_path, monkeypatch):
    """Після чистого проходу в кеші — вершини гілок, а не перелік блобів, і
    наступний прохід читає лише те, чого з них не видно. Витік у новому коміті
    при цьому ловиться."""

    class Cache(dict):
        def get(self, key, default):
            return super().get(key, default)

        def set(self, key, value):
            self[key] = value

    class Config:
        cache = Cache()

    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.md").write_text("нічого приватного\n", encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "a"], cwd=tmp_path, check=True)
    monkeypatch.setattr(scan, "ROOT", tmp_path)

    assert _scan_history_remembering_clean(Config()) == []
    tips = [v for k, v in Config.cache.items() if k.startswith("scan_private/clean_tips/")]
    blobs = [v for k, v in Config.cache.items() if k.startswith("scan_private/clean_blobs/")]
    assert tips and tips[0] and blobs == [[]], "чиста історія — це вершини, не блоби"

    read: list[str] = []
    real = scan.iter_history_blobs

    def spy(**kw):
        got = real(**kw)
        read.extend(n for n, _s, _t in got)
        return got

    monkeypatch.setattr(scan, "iter_history_blobs", spy)
    (tmp_path / "b.md").write_text('ROOT = Path("E:/Projects/MeGen")\n', encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "b"], cwd=tmp_path, check=True)

    found = _scan_history_remembering_clean(Config())
    assert read == ["b.md"], "перевірене раніше вдруге не читається"
    assert {f.path.split(" @")[0] for f in found} == {"b.md"}
    again = _scan_history_remembering_clean(Config())
    assert {f.path.split(" @")[0] for f in again} == {"b.md"}, "вершина з витоком чистою не стає"
