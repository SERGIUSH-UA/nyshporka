"""Рушій карти (`nyshporka.karta`): книга → сучасні поселення.

Випадки — з заміру 19.10.2026 на бойових книгах і з заливки 28.10.2026: кожен
тест стереже пастку, на яку розбір уже раз наступив. Довідник — маленькі паки за
схемою клієнта. Ті самі випадки ганяє сервер Супряги через `app.heo`.
"""
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

from nyshporka import karta as heo


def _ruchni(f: Path) -> list[dict[str, Any]]:
    return [dict(x) for x in (yaml.safe_load(f.read_text(encoding="utf-8")) or {})["sela"]]


# qid, uk, ru, kind, admin, top, lat, lng
POSELENNIA = [
    ("Q1", "Летичів", "Летичев", "смт", "Летичівський район", "Хмельницька область", 49.38, 27.62),
    ("Q2", "Васьківці", "Васьковцы", "село", "Срібнянський район",
     "Чернігівська область", 50.66, 32.68),
    ("Q3", "Михайлівка", "Михайловка", "село", "Летичівський район",
     "Хмельницька область", 49.40, 27.70),
    ("Q4", "Михайлівка", "Михайловка", "село", "Бахмутський район",
     "Донецька область", 48.60, 38.00),
    ("Q5", "Літин", "Литин", "смт", "Літинський район", "Вінницька область", 49.32, 28.08),
    ("Q6", "Пилява", "Пилява", "село", "Літинський район", "Вінницька область", 49.35, 28.15),
    ("Q7", "Пилява", "Пилява", "село", "Старосинявський район",
     "Хмельницька область", 49.70, 27.50),
    ("Q8", "Чемериси-Барські", "Чемерисы-Барские", "село", "Барський район",
     "Вінницька область", 49.02, 27.75),
    ("Q9", "Каплинці", "Каплинцы", "село", "Пирятинський район",
     "Полтавська область", 50.20, 32.40),
    ("Q10", "Пирятин", "Пирятин", "місто", "Пирятинський район",
     "Полтавська область", 50.24, 32.51),
    # Ямпіль і Ямпільський район є і на Поділлі, і на Сумщині
    ("Q11", "Ямпіль", "Ямполь", "смт", "Ямпільський район", "Вінницька область", 48.24, 28.28),
    ("Q12", "Ямпіль", "Ямполь", "смт", "Ямпільський район | Шосткинський район",
     "Сумська область", 51.95, 33.79),
    ("Q13", "Антонівка", "Антоновка", "село", "Томашпільський район",
     "Вінницька область", 48.53, 28.43),
    ("Q14", "Антонівка", "Антоновка", "село", "Ямпільський район | Шосткинський район",
     "Сумська область", 52.00, 33.59),
    # два Бобрики в межах колишнього Лебединського повіту; газетир знає свій
    ("Q15", "Лебедин", "Лебедин", "місто", "Лебединський район", "Сумська область", 50.59, 34.48),
    ("Q16", "Бобрик", "Бобрик", "село", "Недригайлівський район", "Сумська область",
     50.96, 34.14),
    ("Q17", "Лебединий Бобрик", "Лебединый Бобрик", "село", "Лебединський район",
     "Сумська область", 50.43, 34.35),
    # Ольгопіль нині село — повітове місто мусить знаходитись і серед сіл
    ("Q18", "Ольгопіль", "Ольгополь", "село", "Чечельницький район", "Вінницька область",
     48.20, 29.50),
    ("Q19", "Демівка", "Демовка", "село", "Чечельницький район", "Вінницька область",
     48.30, 29.30),
    # «янів» — усередині назви, а не корінь
    ("Q21", "Мар'янівка", "Марьяновка", "село", "Вінницький район", "Вінницька область",
     49.03, 29.05),
    ("Q20", "Демівка", "Демовка", "село", "Бродівський район", "Львівська область",
     50.00, 25.10),
    # «Липовецького» ріжеться на «Липове» + «цького»: село Липове далеко, місто — Липовець
    ("Q30", "Липовець", "Липовец", "місто", "Липовецький район", "Вінницька область",
     49.22, 29.06),
    ("Q31", "Липове", "Липовое", "село", "Шишацький район", "Полтавська область", 49.80, 34.10),
    ("Q32", "Іллінці", "Ильинцы", "місто", "Іллінецький район", "Вінницька область",
     49.10, 29.21),
    ("Q33", "Деражня", "Деражня", "місто", "Деражнянський район", "Хмельницька область",
     49.27, 27.43),
    # дві Здовбиці на Рівненщині — розводить лише сусід за описом
    ("Q34", "Здовбиця", "Здовбица", "село", "Здолбунівський район", "Рівненська область",
     50.50, 26.20),
    ("Q35", "Здовбиця", "Здовбица", "село", "Сарненський район", "Рівненська область",
     51.20, 26.70),
    # латинка FamilySearch: Таужне Балтського повіту, дві Кам'янки в тому ж повіті
    ("Q40", "Балта", "Балта", "місто", "Подільський район", "Одеська область", 47.94, 29.62),
    ("Q41", "Таужне", "Таужное", "село", "Подільський район", "Одеська область", 47.95, 30.20),
    ("Q42", "Кам'янка", "Каменка", "село", "Подільський район", "Одеська область", 47.90, 29.80),
    ("Q43", "Кам'янка", "Каменка", "село", "Гайсинський район", "Вінницька область",
     48.20, 29.30),
    ("Q44", "Гайсин", "Гайсин", "місто", "Гайсинський район", "Вінницька область", 48.81, 29.39),
    ("Q45", "Погребище", "Погребище", "місто", "Вінницький район", "Вінницька область",
     49.48, 29.27),
]


def _pak(tmp: Path, imia: str, domen: str) -> sqlite3.Connection:
    from nyshporka.catalog import schema

    con = sqlite3.connect(tmp / imia)
    schema.apply(con, domen)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("schema", str(schema.SCHEMA_VERSION)), ("domain", domen), ("pack_id", imia)])
    return con


@pytest.fixture
def dov(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> heo.Dovidnyk:
    from nyshporka.geog.gazetteer import norm_name

    con = _pak(tmp_path, "places-test.sqlite", "places")
    for qid, uk, ru, kind, admin, top, la, ln in POSELENNIA:
        con.execute(
            "INSERT INTO modern (qid, name_uk, name_ru, kind, admin, top, country, lat, lng, "
            "norm_uk, norm_ru, norm_alias, translit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, uk, ru, kind, admin, top, "UA", la, ln, norm_name(uk), norm_name(ru), "", ""))
    con.commit()
    con.close()
    con = _pak(tmp_path, "geog-test.sqlite", "geog")
    con.execute(
        "INSERT INTO places (card, village_uk, village_ru, uezd_gub, modern_place, norm_uk, "
        "norm_ru) VALUES (?,?,?,?,?,?,?)",
        ("k1", "Чемериси Волоські, с.", "Чемерисы Волоские, с.",
         "Могилівського пов. Подільської губ.", "Барського р-ну Вінницької обл.",
         "чемериси волоські", "чемерисы волоские"))
    for karta in (
            ("k2", "Дзигівка, с.", "Дзыговка, с.", "Ямпільського пов. Подільської губ.",
             "Ямпільського р-ну Вінницької обл.", "дзигівка", "дзыговка"),
            ("k3", "Бобрик, с.", "Бобрик, с.", "Лебединського пов. Харківської губ.",
             "Лебединського р-ну Сумської обл.", "бобрик", "бобрик"),
            # той самий «Кам'яне» — в іншому повіті: для Лебединського мовчати
            ("k5", "Янів, с.", "Янов, с.", "Вінницького пов. Подільської губ.",
             "Вінницького р-ну і обл.", "янів", "янов"),
            ("k4", "Кам'яне, с.", "Каменное, с.", "Балтського пов. Подільської губ.",
             "Савранського р-ну Одеської обл.", "камяне", "каменное")):
        con.execute(
            "INSERT INTO places (card, village_uk, village_ru, uezd_gub, modern_place, norm_uk, "
            "norm_ru) VALUES (?,?,?,?,?,?,?)", karta)
    con.commit()
    con.close()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path))
    d = heo.dovidnyk(pamiat=False)
    assert d is not None
    return d


def _qid(tochky: list[heo.Tochka], rol: str = "tytul") -> list[str]:
    return sorted(t.qid for t in tochky if t.rol == rol)


def test_povit_ne_puskaie_odnoimennoho_z_inshoho_kraiu(dov: heo.Dovidnyk) -> None:
    # Справжніх Васьківців Летичівського повіту в паку немає, а єдині
    # однойменні — на Чернігівщині. Краще без точки, ніж чужа.
    t = heo.pryviazaty(dov, repo="CDIAK", place="", places=[],
                       title="Метрична книга церкви св. Миколая с. Васьківці Летичівського повіту")
    assert t == []


def test_povit_rozvodyt_odnoimenni(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="CDIAK", place="", places=[],
                       title="Метрична книга церкви с. Михайлівка Летичівського повіту")
    assert _qid(t) == ["Q3"] and t[0].pevnist == "vysoka"


def test_hubernia_ne_pokryttia(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="RGIA", title="РГІА, фонд 592, опис 25, справа 958",
                       place="Подільська губернія, Гайсинський повіт", places=[])
    assert t == []


def test_familysearch_latynkoiu(dov: heo.Dovidnyk) -> None:
    # «Litin» — повіт латинкою: він і розводить дві Пиляви.
    t = heo.pryviazaty(dov, repo="DAHMO", place="", places=[],
                       title="Церковні записи · Pylyava, Litin (каталог FamilySearch)")
    assert _qid(t) == ["Q6"]


def test_hazetyr_lovyt_pereimenuvannia(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="CDIAK", place="", places=[],
                       title="Метрична книга церкви с. Чемериси Волоські Могилівського повіту")
    assert _qid(t) == ["Q8"] and t[0].sposib == "hazetyr"


def test_zghadka_starym_pravopysom(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DAPO", title="Метрична книга", place="",
                       places=["Каплинецъ"])
    assert _qid(t, "tekst") == ["Q9"] and _qid(t) == []


def test_nechitko_lyshe_v_poviti_i_z_nyzkoiu_pevnistiu(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DACHO", place="", places=["Пиритин"],
                       title="Сповідна книга церкви села Каплинці Пирятинського повіту")
    tekst = [x for x in t if x.rol == "tekst"]
    assert [x.qid for x in tekst] == ["Q10"] and tekst[0].pevnist == "nyzka"
    # без повіту одна літера різниці — не доказ
    assert heo.pryviazaty(dov, repo="DACHO", title="", place="", places=["Пиритин"]) == []


def test_hazetyr_bere_korin_lyshe_z_pochatku_slova(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DAHMO", place="", places=[],
                       title="Метрична книга костелу с. Янів Вінницького повіту")
    assert "Q21" not in _qid(t)


def test_perelik_vydavtsia_bez_mistsia_ide_v_nazvu(dov: heo.Dovidnyk) -> None:
    # збірна книга деканату: головного місця немає, парафії названо з повітом
    t = heo.pryviazaty(dov, repo="DAHMO", title="Метричні книги костелів деканату", place="",
                       places=["Каплинці, Пирятинський повіт, Полтавська губернія", "Каплинцы"])
    assert [(x.qid, x.rol) for x in t] == [("Q9", "tytul")]
    # з головним місцем той самий запис — лише згадка
    t = heo.pryviazaty(dov, repo="DAHMO", title="Метрична книга", place="Пирятин",
                       places=["Каплинці, Пирятинський повіт, Полтавська губернія"])
    assert ("Q9", "tekst") in [(x.qid, x.rol) for x in t]


def test_selo_z_nazvy_ne_dubliuietsia_zghadkoiu(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DAPO", place="", places=["Каплинці", "Каплинцы"],
                       title="Метрична книга села Каплинці Пирятинського повіту")
    assert [(x.qid, x.rol) for x in t] == [("Q9", "tytul")]


def test_oblast_z_heometrii_a_ne_z_p131() -> None:
    # Ярмолинці: P131 Wikidata несе й колишню Вінницьку, а лежать вони на Хмельниччині.
    assert heo.oblast_tochky(49.19, 26.84, "Вінницька область | Хмельницька область") \
        == "Хмельницька область"
    assert heo.oblast_tochky(44.95, 34.10, "") == "Автономна Республіка Крим"
    assert heo.oblast_tochky(50.45, 30.52, "Київська область") == "Київ"
    # у морі — перша з паку, а не порожньо
    assert heo.oblast_tochky(44.0, 33.0, "Одеська область | Миколаївська область") \
        == "Одеська область"


def test_ruchnyi_dovidnyk_lovyt_vady() -> None:
    vady = heo.pereviryty_ruchni([
        {"id": "Holiivka", "nazva": "Голіївка", "lat": 26.0, "lng": 50.0,
         "tochnist": "десь", "stan": "зникле", "dzherelo": ""},
        {"id": "a1b", "nazva": "Б", "lat": 50.0, "lng": 26.0, "tochnist": "точно",
         "stan": "злите", "dzherelo": "карта", "zlyte_z": "123"},
        {"id": "a1b", "nazva": "В", "lat": 50.0, "lng": 26.0, "tochnist": "точно",
         "stan": "злите", "dzherelo": "карта"},
    ])
    tekst = " ".join(vady)
    for slovo in ("id — латинка", "переплутані", "tochnist", "без джерела", "zlyte_z",
                  "повторюється"):
        assert slovo in tekst, slovo


def test_ruchne_selo_staie_tochkoiu_i_rozvodytsia_povitom(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dov: heo.Dovidnyk) -> None:
    yaml_ = tmp_path / "ruchni.yaml"
    # Ручна «Михайлівка» Летичівського повіту — поруч із паковою Q3 того ж повіту
    # і далекою Q4 на Донеччині; «Голіївки» в паку немає зовсім.
    yaml_.write_text(
        "sela:\n"
        "- {id: holiivka-test, nazva: Голіївка, inshi_nazvy: [Голиевка], lat: 49.45, lng: 27.60,\n"
        "   tochnist: приблизно, stan: зникле, povit: Летичівський, dzherelo: тест}\n",
        encoding="utf-8")
    d = heo.dovidnyk(ruchni=_ruchni(yaml_), pamiat=False)
    assert d is not None
    t = heo.pryviazaty(d, repo="CDIAK", place="", places=["Голиевки"],
                       title="Метрична книга церкви с. Голіївка Летичівського повіту")
    assert [(x.qid, x.rol, x.oblast) for x in t] == [("r:holiivka-test", "tytul",
                                                     "Хмельницька область")]


def test_povit_z_namesakom_raionu_v_inshii_oblasti(dov: heo.Dovidnyk) -> None:
    # Аудит 19.10: «Антонівка Ямпільського повіту» лягала на Сумщину, бо там
    # теж є Ямпіль і Ямпільський район. Губернію повіту знає газетир.
    t = heo.pryviazaty(dov, repo="CDIAK", place="", places=[],
                       title="Метрична книга церкви с. Антонівка Ямпільського повіту")
    assert _qid(t) == ["Q13"]


def test_hazetyr_peremahaie_vybir_sered_odnoimennykh(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DASO", place="", places=[],
                       title="Метрична книга, Лебединський повіт, 1909 р. (Бобрик, Лебедин)")
    assert "Q17" in _qid(t) and "Q16" not in _qid(t)


def test_hazetyr_inshoho_povitu_movchyt(dov: heo.Dovidnyk) -> None:
    kt = heo._kontekst(dov, "DASO", "Метрична книга, Лебединський повіт", "", [])
    assert heo._z_hazetyra(dov, "Кам'яне", kt) is None


def test_prykmetnyk_povitu_na_zkoho_ne_chastyna_nazvy() -> None:
    # «Білашів Острозького повіту»: «-зького» не розпізнавалось як повіт,
    # і село шукалось під назвою «Білашів Острозького».
    assert heo.z_nazvy("Метрична книга церкви с. Білашів Острозького повіту") == ["Білашів"]


def test_povitove_misto_na_ets(dov: heo.Dovidnyk) -> None:
    # 25.10.2026: «Липовецького» давало повітове місто Липове, і Іллінці за
    # 230 км від нього відкидались «поза повітом».
    kt = heo._kontekst(dov, "DAVIO", "м. Іллінці Липовецького пов. Київської губ.", "", [])
    assert [m["qid"] for m in kt.tsentry] == ["Q30"]
    t = heo.pryviazaty(dov, repo="DAVIO", place="", places=[],
                       title="Метрична книга, м. Іллінці Липовецького пов. Київської губ.")
    assert _qid(t) == ["Q32"]


def test_mistse_bez_khvosta_pereliku() -> None:
    # 95 книг ДАОО 914: назвою села бралось «Рені й села», а другою — «за користувачем».
    assert heo._varianty("Рені й села (за користувачем; FS місця не вказує)") == ["Рені"]
    assert heo._varianty("Мінжир (Mingir), Бессарабія") == ["Мінжир", "Mingir"]
    # головна назва з префіксом лишається: «м.» з малої — не привід її викинути
    assert heo._varianty("м-ко Іллінці, Липовецький пов., Київська губ.") == ["м-ко Іллінці"]


def test_druhe_selo_i_nazva_v_duzhkakh() -> None:
    assert heo.z_nazvy("Книга реєстрації актів по селах Лапинка і Довгалівка, 1924") \
        == ["Лапинка", "Довгалівка"]
    assert heo.z_nazvy("Метричні книги церков сіл Іванівка й Благовіщенка, 1915") \
        == ["Іванівка", "Благовіщенка"]
    assert "Шевченкове" in heo.z_nazvy("Метрична книга, с. Карамахмет (тепер Шевченкове), 1890")
    # присвята храму в дужках — не село
    assert heo.z_nazvy("Метрична книга м. Сокиряни (Успенська)") == ["Сокиряни"]


def test_mistse_prykmetnykom_pry_ustanovi(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DAHMO", place="", places=[],
                       title="Метрична книга Деражнянського костелу")
    assert _qid(t) == ["Q33"] and t[0].pevnist == "nyzka"
    t = heo.pryviazaty(dov, repo="DAVIO", place="", places=[],
                       title="Метрична книга Іллінецького костелу")
    assert _qid(t) == ["Q32"]
    # присвята церкви — не місце: «Миколаївська церква» не Миколаїв
    assert heo.z_prykmetnyka("Метрична книга Миколаївської церкви") == []


def test_odnoimenni_rozvodyt_seriia(dov: heo.Dovidnyk) -> None:
    title = "Метричні книги с. Здовбиця"
    assert heo.pryviazaty(dov, repo="DARO", title=title, place="", places=[]) == []
    # сусідня справа того самого опису лягла біля Здолбунова — береться ближча
    t = heo.pryviazaty(dov, repo="DARO", title=title, place="", places=[],
                       seriia=[{"lat": 50.55, "lng": 26.25}])
    assert _qid(t) == ["Q34"] and t[0].sposib == "seriia"


def test_povitove_misto_shcho_nyni_selo(dov: heo.Dovidnyk) -> None:
    kt = heo._kontekst(dov, "CDIAK", "Метрична книга с. Демівка Ольгопільського повіту", "", [])
    assert [m["qid"] for m in kt.tsentry] == ["Q18"]
    t = heo.pryviazaty(dov, repo="CDIAK", place="", places=[],
                       title="Метрична книга с. Демівка Ольгопільського повіту")
    assert _qid(t) == ["Q19"]


def test_mistse_ne_kraina_i_ne_povit() -> None:
    # « Бессарабія» з пробілом не ловилась `^бессарабія$` (13 книг ДАОО, 25.10.2026);
    # «Бендерський», «Харківський полк», «Королівська канцелярія» — теж не села.
    assert heo._varianty("Аккерманський повіт, Бессарабія, Румунія") == []
    assert heo._varianty("Бендерський") == []
    assert heo._varianty("Харківський полк") == []
    assert "Королівська канцелярія" not in heo._varianty("Королівська канцелярія, Варшава")
    assert heo._varianty("Болград і задунайські колонії Бессарабії") == ["Болград"]
    assert heo._varianty("Дракула (Ізмаїльщина)") == ["Дракула"]
    assert heo._varianty("Варшава / Краків / Львів") == []
    assert heo._chystyty("кол. Кирнички") == "кирнички"
    assert heo._varianty("передмістя Чернівців-Ленківці") == [
        "Чернівців-Ленківці", "Ленківці", "Чернівці"]
    assert heo.z_nazvy("Метрична книга. Літинський костьол, м. Літин Державний архів") \
        == ["Літин"]
    assert "Прилуцька" not in heo.z_nazvy("Метричні книги, м. Прилуки і Прилуцька протопопія")


def test_orudnyi_vidminok(dov: heo.Dovidnyk) -> None:
    # «благочиння з Клокушною, Окницею, Єдинцями» — орудний відмінок.
    assert {"Q6", "Q7"} <= set(heo._kandydaty(dov, "Пилявою"))
    assert "Q9" in heo._kandydaty(dov, "Каплинцями")


def test_nechitko_z_inshym_poriadkom_sliv(dov: heo.Dovidnyk) -> None:
    # «Мечетна Велика» Балтського повіту — у паку «Велика Мечетня».
    d = heo.Dovidnyk()
    for x in dov.vsi:
        d.dodaty(dict(x))
    d.dodaty({"qid": "Q90", "name_uk": "Велика Мечетня", "kind": "село", "top": "Вінницька область",
              "admin": "Літинський район", "country": "UA", "lat": 49.33, "lng": 28.10,
              "norm_uk": "велика мечетня", "norm_ru": "", "norm_alias": "", "translit": ""})
    t = heo.pryviazaty(d, repo="CDIAK", place="", places=[],
                       title="Метрична книга церкви с. Мечетна Велика Літинського повіту")
    assert _qid(t) == ["Q90"]


def test_ruchna_stara_nazva_lyahaie_na_selo_paku(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dov: heo.Dovidnyk) -> None:
    # Стара назва села, яке пак знає під сучасною: точка — та сама, що в паку,
    # а не друга поруч.
    yaml_ = tmp_path / "ruchni.yaml"
    yaml_.write_text(
        "sela:\n"
        "- {id: pylyava-stara, nazva: Старопилявка, qid: Q6, stan: перейменоване,\n"
        "   povit: Літинський, dzherelo: тест}\n", encoding="utf-8")
    d = heo.dovidnyk(ruchni=_ruchni(yaml_), pamiat=False)
    assert d is not None
    t = heo.pryviazaty(d, repo="CDIAK", place="", places=[],
                       title="Метрична книга церкви с. Старопилявка Літинського повіту")
    assert [(x.qid, x.rol) for x in t] == [("Q6", "tytul")]
    assert heo.pereviryty_ruchni([{"id": "abc", "nazva": "А", "qid": "6", "lat": 1,
                                   "stan": "злите", "dzherelo": "x"}]) == [
        "запис 1 (abc): qid — Q-ідентифікатор Wikidata",
        "запис 1 (abc): з qid координати беруться з паку — lat/lng зайві"]


def test_ruchne_selo_poza_ukrainoiu_prokhodyt_filtr_huberniieiu(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dov: heo.Dovidnyk) -> None:
    # Лопазна Мглинського повіту — нині Брянщина: області в паку немає, і книга
    # ДАЧО (область — Чернігівська) відкидала точку як «поза областю».
    yaml_ = tmp_path / "ruchni.yaml"
    yaml_.write_text(
        "sela:\n"
        "- {id: lopazna-test, nazva: Лопазна, lat: 53.03, lng: 32.63, tochnist: точно,\n"
        "   stan: існує, povit: Мглинський, huberniia: Чернігівська, dzherelo: тест}\n",
        encoding="utf-8")
    d = heo.dovidnyk(ruchni=_ruchni(yaml_), pamiat=False)
    assert d is not None
    t = heo.pryviazaty(d, repo="DACHO", place="", places=[],
                       title="Сповідна книга Архангело-Михайлівської церкви села Лопазна")
    assert [x.qid for x in t] == ["r:lopazna-test"]


def test_dubl_wikidata_ne_robyt_selo_dvoznachnym() -> None:
    """Яланець Бершадського району — двічі в паку за 2 км, третій — за 77 км.

    Крок «до 60 км від повітового міста» лишає два записи того самого села, і
    це одне поселення, а не двозначність (28.10.2026).
    """
    def selo(qid: str, lat: float, lng: float, adm: str) -> dict[str, object]:
        return {"qid": qid, "name_uk": "Яланець", "lat": lat, "lng": lng,
                "adm": adm, "obl": "вінницька область"}

    tsentr = {"qid": "Q0", "name_uk": "Ольгопіль", "lat": 48.21, "lng": 29.50}
    c = {"a": selo("a", 48.30, 29.60, "бершадський район"),
         "b": selo("b", 48.31, 29.62, "бершадський район"),
         "c": selo("c", 48.40, 28.50, "томашпільський район")}
    kt = heo._Kontekst(obl=["вінниц"], povit=["ольгоп"], tsentry=[tsentr])
    d, sposib = heo._vybraty(c, kt)
    assert d is not None and d["qid"] in ("a", "b") and sposib == "povit"


@pytest.mark.parametrize("title, place", [
    ("Religious Records — taujna, Balta, Podolia", "Подільська губ."),
    ("", "taujna, Balta, Podolia, Russian Empire"),
])
def test_selo_fs_latynkoiu_v_poviti(dov: heo.Dovidnyk, title: str, place: str) -> None:
    """Обхід FS: село латинкою з повітом — поселення паку в межах повіту (28.10.2026)."""
    t = heo.pryviazaty(dov, repo="DAHMO", title=title, place=place, places=[place])
    assert _qid(t) == ["Q41"] and t[0].sposib.startswith("latynka")


def test_polska_nazva_v_duzhkakh(dov: heo.Dovidnyk) -> None:
    t = heo.pryviazaty(dov, repo="DAHMO", place="", places=[],
                       title="Метрична книга костелу (Pohrebyszcze): смерті")
    assert _qid(t) == ["Q45"] and t[0].sposib == "latynka" and t[0].pevnist == "vysoka"


def test_latynka_odnoimenni_i_chuzhyi_povit_bez_tochky(dov: heo.Dovidnyk) -> None:
    # дві Кам'янки в межах Балтського повіту — не вгадуємо
    assert heo.pryviazaty(dov, repo="DAHMO", place="", places=[],
                          title="Court Records — kamianka, Balta, Podolia") == []
    # Таужне за 113 км від Гайсина — не в Гайсинському повіті
    assert heo.pryviazaty(dov, repo="DAHMO", place="", places=[],
                          title="Court Records — taujna, Gaysin, Podolia") == []
