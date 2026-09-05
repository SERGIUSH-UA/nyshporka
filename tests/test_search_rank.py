"""⚖ Ранг замість фільтра: чуже слово опускає хіт, але не забирає його.

🔴 Головне твердження файлу — **позначений кандидат лишається у видачі**.
Провал у цей бік (зник) дорожчий за будь-який шум: хибний плюс людина відсіює
за секунди, а пропущений аркуш не відсівається нічим, бо його ніколи не буде в
списку.

Друге твердження, не менш важливе: профіль без правил не сміє змінити нічого.
Інакше правка поїхала б по всіх наявних просторах разом із оновленням.

⚠ Пара для перевірки взята з рахунку, а не навмання (rapidfuzz, поріг 80):

    «Сикорскаго» → рід 87.5 · конфузер  62.5 → чистий
    «Сокорскій»  → рід 88.9 · конфузер 100.0 → опускається

🔴 Числа підібрані так, що **чужий стоїть вище за балом**. Це і є той випадок,
заради якого ранг існує: інакше порядок «за балом» і порядок «за рангом»
збігаються, і тест проходив би однаково до правки й після, нічого не доводячи.
Замір приватного конвеєра саме про це: 60 сильних кандидатів, три верхні місця
за балом — рубрика книги, а самого роду серед них нуль.

⚠ Скрізь `profile=False`. Написання профілю піднімають «Сикорскаго» до 100 і
самі ставлять чисте першим — тобто перевіряли б уже не ранг. Два механізми
міряються окремо, інакше жоден із двох тестів нічого не доводить.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROFILE = """\
fallback: rid

profiles:
  rid:
    surname:
      display: Сікорський
      paradigm: adj_skyi
      stems:
        uk: Сікор
{extra}
"""


def _space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str = "") -> Path:
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "research_profile.yaml").write_text(
        PROFILE.format(extra=extra), encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.reset()

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    (run / "0001.txt").write_text("родился Сикорскаго сынъ\nсело Кривое\n",
                                  encoding="utf-8")
    (run / "0002.txt").write_text("восприемникъ Сокорскій Петръ\nтого же села\n",
                                  encoding="utf-8")
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {"0001.jpg": {"lines": 2}, "0002.jpg": {"lines": 2}},
    }), encoding="utf-8")

    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    return tmp_path


@pytest.fixture
def plain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Профіль без жодного правила рангу."""
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    yield _space(tmp_path, monkeypatch)
    P.reset()
    W.reset()


@pytest.fixture
def with_confuser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    yield _space(tmp_path, monkeypatch,
                 "      confusers:\n        - sokorski\n")
    P.reset()
    W.reset()


def _pages(res: dict) -> list[str]:
    return [h["page"] for h in res["hits"]]


def test_a_marked_hit_stays_in_the_answer(with_confuser) -> None:
    """🔴 Заради чого все: конфузер опускає, а не викидає."""
    from nyshporka import htr_store as S

    res = S.search("Сікорський", thresh=80, profile=False)
    assert "0002.jpg" in _pages(res), "хіт із конфузером зник — це найгірша вада"


def test_the_clean_hit_comes_first_even_with_a_lower_score(with_confuser) -> None:
    """🔴 Ось уся дія: чисте вгорі, хоч бал у нього НИЖЧИЙ."""
    from nyshporka import htr_store as S

    assert _pages(S.search("Сікорський", thresh=80, profile=False)) == ["0001.jpg", "0002.jpg"]


def test_without_the_rule_the_score_alone_decides(with_confuser) -> None:
    """Приймач самого тесту: без рангу порядок ЗВОРОТНИЙ.

    Без цієї перевірки попередній тест міг би проходити й до правки — просто
    тому, що бал і так поставив би чисте першим.
    """
    from nyshporka import htr_store as S

    res = S.search("Сікорський", thresh=80, rank=False, profile=False)
    assert _pages(res) == ["0002.jpg", "0001.jpg"]
    assert all(not h.get("rank") for h in res["hits"])


def test_the_hit_says_why_it_was_lowered(with_confuser) -> None:
    from nyshporka import htr_store as S

    low = next(h for h in S.search("Сікорський", thresh=80, profile=False)["hits"]
               if h["page"] == "0002.jpg")
    assert low["rank"] == "confuser"
    assert low["rank_why"], "опущено без причини — читач не має що перевірити"
    assert low["rank_penalty"] == 2


def test_a_profile_without_rules_changes_nothing(plain) -> None:
    """🔴 Оновлення не сміє переставити видачу в просторах, де правил немає."""
    from nyshporka import htr_store as S

    a = S.search("Сікорський", thresh=80, rank=True, profile=False)
    b = S.search("Сікорський", thresh=80, rank=False, profile=False)
    key = [(h["page"], h["line_no"], h["score"]) for h in a["hits"]]
    assert key, "перевірка беззмістовна: не знайшлось нічого"
    assert [(h["page"], h["line_no"], h["score"]) for h in b["hits"]] == key
    assert a["ranked"] == {"confuser": 0, "rank_down": 0}


def test_the_tally_travels_with_the_answer(with_confuser) -> None:
    """«Нічого не позначено» і «правил немає» — різні відповіді."""
    from nyshporka import htr_store as S

    res = S.search("Сікорський", thresh=80, profile=False)
    assert res["ranked"]["confuser"] == 1
    assert res["rank_confusers"] == 1


def test_a_cyrillic_rule_is_named_not_silently_dead(tmp_path, monkeypatch) -> None:
    """🔴 Правило, написане кирилицею, не спрацює НІКОЛИ — і мусить сказати це.

    Порівняння йде з нормалізованим текстом (щ→sc, и/і→i, кирилиця в латинку),
    тож кириличний регекс не збігається ні з чим. Профіль при цьому виглядає
    налаштованим — рівно той клас мовчазної вади, проти якого решта застосунку.
    """
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W
    from nyshporka.search import rank as R

    _space(tmp_path, monkeypatch,
           '      rank_down:\n        office: "должн|кладо"\n')
    try:
        rul = R.rules()
        assert rul.dead == ("office",)
        assert not rul.rank_down
    finally:
        P.reset()
        W.reset()


def test_a_latin_rule_works(tmp_path, monkeypatch) -> None:
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    _space(tmp_path, monkeypatch,
           '      rank_down:\n        office: "sokorsk"\n')
    try:
        from nyshporka import htr_store as S

        res = S.search("Сікорський", thresh=80, profile=False)
        low = next(h for h in res["hits"] if h["page"] == "0002.jpg")
        assert low["rank"] == "rank_down"
        assert low["rank_why"] == "office", "причина мусить називати правило"
        assert res["ranked"]["rank_down"] == 1
    finally:
        P.reset()
        W.reset()


def test_a_broken_regex_does_not_kill_the_search(tmp_path, monkeypatch) -> None:
    """Побите правило — привід сказати, а не впасти посеред пошуку."""
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W
    from nyshporka.search import rank as R

    _space(tmp_path, monkeypatch,
           '      rank_down:\n        bad: "sokor(sk"\n')
    try:
        rul = R.rules()
        assert rul.broken == ("bad",)
        from nyshporka import htr_store as S

        assert S.search("Сікорський", thresh=80, profile=False)["hits"]
    finally:
        P.reset()
        W.reset()


def test_no_profile_at_all_is_not_a_failure(tmp_path, monkeypatch) -> None:
    """На чужому просторі профілю може не бути — канал просто мовчить."""
    from nyshporka.core import workspace as W
    from nyshporka.search import rank as R

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    try:
        assert R.rules().empty
    finally:
        W.reset()
