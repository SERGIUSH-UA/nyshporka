"""Профіль Супряги й перелік неподіленого.

Два рішення, які легко зламати мовчки: типовий режим згоди й те, що
рахується неподіленим.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.share import journal
from nyshporka.share import profile as P
from nyshporka.share import suggest as S


@pytest.fixture
def space(tmp_path: Path) -> Any:
    """Свій простір на тест — профіль і журнал живуть саме в ньому."""
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def test_typovo_ne_dilytysia(space: Path) -> None:
    """🔴 Типово — НЕ ділитись автоматично.

    Серед аудиторії є люди, які платили за зйомку, і автоматична роздача
    відштовхнула б їх назавжди. Режим `zavzhdy` вмикає людина сама.
    """
    got = P.load()
    assert got.consent == P.PYTATY
    assert not got.auto
    assert got.shares, "«питати» — це все-таки згода вести перелік"


def test_profil_perezhyvaie_zapys(space: Path) -> None:
    prof = P.load()
    prof.handle = "sergiush"
    prof.contact = "nyshporka.online"
    prof.consent = P.ZAVZHDY
    P.save(prof)

    znovu = P.load()
    assert znovu.handle == "sergiush"
    assert znovu.consent == P.ZAVZHDY
    assert znovu.auto


def test_nevidomi_polia_ne_hubliatsia(space: Path) -> None:
    """Поле з майбутньої версії переживає запис старою.

    Інакше людина, яка ставить свіжий клієнт на інший компʼютер і повертає
    простір назад, тихо втрачає налаштування.
    """
    path = P.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ Значення в лапках: `@` на початку скаляра — зарезервований символ
    # YAML, і без лапок це не «поле з майбутнього», а битий файл. Саме так
    # його й записав би `yaml.safe_dump`.
    path.write_text('handle: hto\ntelegram: "@nova_fitcha"\n', encoding="utf-8")

    prof = P.load()
    assert prof.extra["telegram"] == "@nova_fitcha"
    P.save(prof)
    assert "telegram" in path.read_text(encoding="utf-8")


def test_bytyi_profil_ne_valyt(space: Path) -> None:
    """Конфіг, у який людина, може, й не заглядала, не спиняє прогін."""
    path = P.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("це не ямл: [[[", encoding="utf-8")
    assert P.load().consent == P.PYTATY


def test_nevidomyi_rezhym_zvodytsia_do_typovoho(space: Path) -> None:
    path = P.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("consent: vidraz_use\n", encoding="utf-8")
    assert P.load().consent == P.PYTATY


def test_defaulty_pakuvannia_z_profiliu(space: Path) -> None:
    """Ліцензія береться з профілю, а не з двох захардкоджених місць."""
    prof = P.load()
    prof.handle = "hto"
    prof.license = "CC-BY-4.0"
    P.save(prof)

    got = P.pack_defaults()
    assert got["publisher"] == "hto"
    assert got["license"] == "CC-BY-4.0"


def test_nepodileni_ne_berut_chuzhe(space: Path, monkeypatch: Any) -> None:
    """🔴 Чужий прогін перепаковувати не можна.

    Людина віддала його один раз, і другий раз за неї ніхто не вирішує.
    """
    rows = [
        {"case_key": "DAHMO/315/1", "shifra": "ДАХмО 315-1-1", "pages_done": 3,
         "shared": "", "updated": "2026-09-20", "frames": 3, "model": "m", "title": ""},
        {"case_key": "DAHMO/315/2", "shifra": "ДАХмО 315-1-2", "pages_done": 3,
         "shared": "hto-s", "updated": "2026-09-20", "frames": 3, "model": "m",
         "title": ""},
        {"case_key": "", "shifra": "", "pages_done": 5, "shared": "",
         "updated": "2026-09-20", "frames": 5, "model": "m", "title": ""},
        {"case_key": "DAHMO/315/4", "shifra": "ДАХмО 315-1-4", "pages_done": 0,
         "shared": "", "updated": "2026-09-20", "frames": 3, "model": "m", "title": ""},
    ]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)

    got = S.nepodileni()
    assert [r["case_key"] for r in got] == ["DAHMO/315/1"], (
        "чуже, безключове й порожнє не пропонуються"
    )


def test_vidmova_zapamiatovuietsia_poshtuchno(space: Path, monkeypatch: Any) -> None:
    """🔴 Сказав «цю не віддам» — більше про неї не питають ніколи.

    Без цього перелік щотижня показував би те саме, і людина перестала б
    його читати — тобто механізм зламався б тихо, лишаючись справним.
    """
    rows = [
        {"case_key": "DAHMO/315/1", "shifra": "ДАХмО 315-1-1", "pages_done": 3,
         "shared": "", "updated": "2026-09-20", "frames": 3, "model": "m", "title": ""},
        {"case_key": "DAHMO/315/2", "shifra": "ДАХмО 315-1-2", "pages_done": 3,
         "shared": "", "updated": "2026-09-19", "frames": 3, "model": "m", "title": ""},
    ]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)
    assert len(S.nepodileni()) == 2

    S.vidmovyty("DAHMO/315/2", "ДАХмО 315-1-2", "платив за зйомку")
    left = S.nepodileni()
    assert [r["case_key"] for r in left] == ["DAHMO/315/1"]

    # Причина лишається в журналі — через півроку має бути видно, чому.
    podii = journal.read(S.DECLINED)
    assert podii and podii[0]["why"] == "платив за зйомку"


def test_spakovane_znykaie_z_pereliku(space: Path, monkeypatch: Any) -> None:
    rows = [{"case_key": "DAHMO/315/1", "shifra": "ДАХмО 315-1-1", "pages_done": 3,
             "shared": "", "updated": "2026-09-20", "frames": 3, "model": "m",
             "title": ""}]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)
    assert len(S.nepodileni()) == 1

    journal.record(journal.PACKED, shifra="ДАХмО 315-1-1", case_key="DAHMO/315/1",
                   pages=3)
    assert S.nepodileni() == []


def test_nahaduvannia_movchyt_bez_pidstavy(space: Path, monkeypatch: Any) -> None:
    """Порожній перелік — порожній рядок. І жодної мережі."""
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: [])
    assert S.nudge() == ""


def test_nahaduvannia_movchyt_u_rezhymi_nikoly(space: Path, monkeypatch: Any) -> None:
    """Хто сказав «ніколи», того не чіпають узагалі."""
    rows = [{"case_key": "DAHMO/315/1", "shifra": "ДАХмО 315-1-1", "pages_done": 3,
             "shared": "", "updated": "2026-09-20", "frames": 3, "model": "m",
             "title": ""}]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)

    prof = P.load()
    prof.consent = P.NIKOLY
    P.save(prof)
    assert S.nudge() == ""


def test_nahaduvannia_ne_povtoriuietsia_shchodnia(space: Path, monkeypatch: Any) -> None:
    """Рядок, який зʼявляється щодня, перестають читати."""
    rows = [{"case_key": f"DAHMO/315/{i}", "shifra": f"ДАХмО 315-1-{i}",
             "pages_done": 3, "shared": "", "updated": "2026-09-20", "frames": 3,
             "model": "m", "title": ""} for i in range(1, 4)]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)

    pershyi = S.nudge()
    assert "3 прочитаних" in pershyi
    assert S.nudge() == "", "другого разу поспіль не нагадуємо"


def test_bahato_nepodilenoho_nahaduie_ranishe(space: Path, monkeypatch: Any) -> None:
    """Хто читає щодня, не мусить чекати тижня."""
    rows = [{"case_key": f"DAHMO/315/{i}", "shifra": f"ДАХмО 315-1-{i}",
             "pages_done": 3, "shared": "", "updated": "2026-09-20", "frames": 3,
             "model": "m", "title": ""} for i in range(1, 15)]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)

    assert S.nudge()
    assert S.nudge(), "понад поріг нагадуємо, не чекаючи строку"


def test_perelik_ne_khodyt_u_merezhu(space: Path, monkeypatch: Any) -> None:
    """🔴 PRIVACY обіцяє, що фонової активності в мережі немає.

    Перелік рахується з журналу й прогонів; у пул іде лише те, що людина
    покликала сама.

    🔴 Глушиться ТРАНСПОРТ, а не конкретний клас. Заборона на `Fetcher`
    ловила б рівно той шлях, який уже є, і мовчала б про прямий `httpx`,
    `urllib` чи сирий сокет. А прямий `httpx` тут не гіпотеза: профіль має
    `lookup`, тобто клієнт у пул ходить, і перша ж спроба «а може, це вже
    хтось виклав» усередині переліку пройшла б повз вужчий запобіжник —
    обіцянка зламалась би тихо.
    """
    import socket

    import httpx

    def _zaboronene(*_: Any, **__: Any) -> None:
        raise AssertionError("перелік неподіленого не сміє ходити в мережу")

    monkeypatch.setattr(httpx.Client, "send", _zaboronene)
    monkeypatch.setattr(httpx.AsyncClient, "send", _zaboronene)
    monkeypatch.setattr(socket.socket, "connect", _zaboronene)

    # Заборона мусить довести, що вона жива. Без цієї перевірки тест
    # лишався б зеленим і тоді, коли підміна промахнулась повз справжній
    # шлях, — тобто доводив би рівно нічого.
    with pytest.raises(AssertionError):
        httpx.Client().send(httpx.Request("GET", "https://nyshporka.online/"))
    with pytest.raises(AssertionError):
        socket.socket().connect(("127.0.0.1", 9))

    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: [])
    S.nepodileni()
    S.nudge()
    S.vidmovyty("DAHMO/315/1", "ДАХмО 315-1-1", "перевірка")
    S.viddani()
    S.vidmovleni()


def test_zhurnal_lyshaie_slid_prydatnyi_dlia_ochey(space: Path) -> None:
    """Подія відмови читається людиною, а не лише кодом."""
    S.vidmovyty("DAHMO/315/9", "ДАХмО 315-1-9", "приватна зйомка")
    row = journal.read(S.DECLINED)[0]
    assert json.dumps(row, ensure_ascii=False)
    assert row["shifra"] == "ДАХмО 315-1-9"
    assert row["event"] == S.DECLINED


# ── зріз пулу: «віддано» — те, що в пулі, а не те, що спаковано ──────────────

def _ryadok(key: str, shifra: str, pages: int = 3, frames: int = 3,
            name: str = "") -> dict[str, Any]:
    return {"case_key": key, "shifra": shifra, "pages_done": pages, "shared": "",
            "updated": "2026-09-20", "frames": frames, "model": "m", "title": "",
            "name": name or key.replace("/", "-")}


def test_zriz_pulu_vyrishuie_viddane(space: Path, monkeypatch: Any) -> None:
    """🔴 Спаковане ≠ віддане: зі зрізом пулу перелік вірить пулу, не журналу."""
    rows = [_ryadok("DAHMO/315/1", "ДАХмО 315-1-1"),
            _ryadok("DAHMO/315/2", "ДАХмО 315-1-2"),
            _ryadok("DAHMO/315/3", "ДАХмО 315-1-3"),
            _ryadok("DAHMO/315/4", "ДАХмО 315-1-4", pages=1, frames=10),
            _ryadok("DAHMO/315/5", "ДАХмО 315-1-5", frames=0)]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)
    journal.record(journal.PACKED, shifra="ДАХмО 315-1-1", case_key="DAHMO/315/1")
    stany = {"DAHMO/315/2": "text+geom", "DAHMO/315/3": "text"}
    monkeypatch.setattr("nyshporka.share.pool.meta", lambda: {"taken_at": "x"})
    monkeypatch.setattr(S, "_u_puli", lambda key: stany.get(key, "none"))
    monkeypatch.setattr(S, "_ye_ramky", lambda name: True)

    got = {r["case_key"]: r["status"] for r in S.nepodileni()}

    assert got == {"DAHMO/315/1": S.GOTOVA, "DAHMO/315/3": S.BEZ_RAMOK,
                   "DAHMO/315/4": S.NEPOVNA, "DAHMO/315/5": S.BEZ_KADRIV}


def test_bez_ramok_na_dysku_ne_pytaie(space: Path, monkeypatch: Any) -> None:
    """Текст у пулі, а рамок на диску немає — довозити нічого."""
    monkeypatch.setattr("nyshporka.htr_store.list_cases",
                        lambda: [_ryadok("DAHMO/315/3", "ДАХмО 315-1-3")])
    monkeypatch.setattr("nyshporka.share.pool.meta", lambda: {"taken_at": "x"})
    monkeypatch.setattr(S, "_u_puli", lambda key: "text")
    monkeypatch.setattr(S, "_ye_ramky", lambda name: False)
    assert S.nepodileni() == []


def test_synonimy_arkhivu(monkeypatch: Any) -> None:
    """Пул пише Вінницький архів `DAVIO`, простір може лишатись на `DAVO`."""
    from types import SimpleNamespace

    repos = {"DAVIO": SimpleNamespace(same_as="DAVO"), "DAVO": SimpleNamespace(same_as=""),
             "DAHMO": SimpleNamespace(same_as="")}
    monkeypatch.setattr("nyshporka.archives.active",
                        lambda: SimpleNamespace(repositories=repos))
    assert S._synonimy("DAVO") == ["DAVO", "DAVIO"]
    assert S._synonimy("DAVIO") == ["DAVIO", "DAVO"]
    assert S._synonimy("DAHMO") == ["DAHMO"]


def test_storinky_spravy_z_naipovnishoho_holosu(space: Path, monkeypatch: Any) -> None:
    """Дяк прочитав 10 аркушів, Писар — усі 89: справа готова, а не «неповна»."""
    rows = [_ryadok("DAHMO/230-1/230", "ДАХмО 230-1-230", pages=10, frames=89,
                    name="230-1-230-diak_v4"),
            _ryadok("DAHMO/230-1/230", "ДАХмО 230-1-230", pages=89, frames=89,
                    name="230-1-230")]
    monkeypatch.setattr("nyshporka.htr_store.list_cases", lambda: rows)
    got = S.nepodileni()
    assert [(r["pages"], r["status"]) for r in got] == [(89, S.GOTOVA)]
