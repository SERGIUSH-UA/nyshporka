"""🏛 ARCHIUM як РУШІЙ, а не один архів.

Сайт-переглядач спільний для кількох архівів, а хости різні. Доки адреса була
константою модуля, джерело вміло рівно один архів; ЦДІАК — де лежить колекція
метричних книг на 2944 справи — не діставався взагалі.

⚠ Наявний `test_sources_archium.py` не змінювався жодним рядком, і це навмисно:
він і є доказ, що мультихостовість нічого не зламала в тому, що працювало.
"""
from __future__ import annotations

import pytest

from nyshporka.archives import active
from nyshporka.sources import archium as A
from nyshporka.sources.base import SourceError


def _cdiak() -> A.ArchiumSource:
    site = active().site("CDIAK", "archium")
    assert site is not None, "майданчик ЦДІАК зник із паку"
    return A.ArchiumSource(site=site, repo="CDIAK")


def test_each_site_is_its_own_source_with_its_own_name() -> None:
    """🔴 `id` їде в «де шукали» кожної відповіді. Спільне ім'я на два різні
    архіви зробило б знаменник пошуку неправдивим: «шукали в archium» не
    сказало б, у якому саме, а нуль читався б як відповідь про обидва."""
    dahmo, cdiak = A.ArchiumSource(), _cdiak()

    assert dahmo.id == "archium", "історичне ім'я ДАХмО має лишитись"
    assert cdiak.id == "archium-cdiak"
    assert dahmo.id != cdiak.id
    assert "ЦДІАК" in cdiak.label


def test_the_host_comes_from_the_pack_not_from_the_module() -> None:
    dahmo, cdiak = A.ArchiumSource(), _cdiak()
    assert dahmo.base == A.BASE
    assert cdiak.base != A.BASE and "cdiak" in cdiak.base


def test_frames_are_addressed_on_the_right_host() -> None:
    """Кадр качається з ТОГО хоста, де лежить справа: спільна формула шляху й
    різні хости — найтихіший спосіб піти по чужу сторінку."""
    cdiak = _cdiak()
    assert A.image_url(13943, cdiak.base).startswith(cdiak.base)
    assert A.image_url(13943).startswith(A.BASE), "дефолт зламано"


def test_each_site_keeps_its_own_catalogue() -> None:
    """Спільна тека каталогу означала б, що обхід одного архіву затирає обхід
    іншого, а пошук віддає суміш двох фондових просторів."""
    dahmo, cdiak = A.ArchiumSource(), _cdiak()
    assert dahmo.catalog_rel == A.ArchiumSource.CATALOG_REL, "шлях ДАХмО поїхав"
    assert cdiak.catalog_rel != dahmo.catalog_rel
    assert "cdiak_archium" in cdiak.catalog_rel.as_posix()


def test_a_site_without_a_group_tree_refuses_instead_of_showing_a_foreign_one() -> None:
    """🔴 Дві однаково погані відповіді, яких тут немає.

    Порожній список читався б як «архів порожній» — а це неправда: у цього
    майданчика просто немає ЗАПИТУ на дерево груп (він віддає 500). Показати ж
    чотири групи сусіднього архіву означало б чуже дерево під іменем цього.
    """
    with pytest.raises(SourceError) as exc:
        _cdiak().browse()
    assert "груп" in str(exc.value)
    assert "archium-cdiak" in str(exc.value), "відмова не каже, чим шукати далі"


def test_the_bundled_snapshot_belongs_to_its_own_site() -> None:
    """Зріз каталогу зібрано для ДАХмО; віддавати його від імені іншого архіву
    означало б показати чужі справи як свої."""
    assert A.ArchiumSource().catalog_source()[0] == "bundled"
    assert _cdiak().catalog_source()[0] == "none"
