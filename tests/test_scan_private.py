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


def test_this_repository_is_clean():
    """Найважливіша перевірка: сам репозиторій не містить приватних даних."""
    findings = []
    for rel, text, where in scan.iter_worktree():
        findings += scan.scan_text(rel, text, where)
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


def test_this_repository_history_is_clean():
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
    findings = []
    for rel, text, where in scan.iter_history():
        findings += scan.scan_text(rel, text, where)
    assert not findings, "\n".join(
        f"{f.path}:{f.line_no} [{f.rule.id}] {f.excerpt}" for f in findings[:20])


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
