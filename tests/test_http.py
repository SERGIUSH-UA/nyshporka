"""🌐 Спільний HTTP-клієнт: ввічливість, ліміт і те, чим ми себе називаємо."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources import http as H


class _Resp:
    def __init__(self, status: int = 200, text: str = "", blocks: list[bytes] | None = None):
        self.status_code = status
        self.text = text
        self._blocks = blocks or []

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("несподівано", request=None,  # type: ignore[arg-type]
                                        response=None)  # type: ignore[arg-type]

    def iter_bytes(self, chunk: int = 0) -> list[bytes]:
        return self._blocks


class _Client:
    """Двійник із записаними відповідями: у мережу тести не ходять."""

    def __init__(self, answers: list[_Resp]) -> None:
        self.answers = answers
        self.gets: list[str] = []
        self.posts: list[tuple[str, Any, Any]] = []

    def get(self, url: str) -> _Resp:
        self.gets.append(url)
        return self.answers[min(len(self.gets) - 1, len(self.answers) - 1)]

    def post(self, url: str, data: Any = None, json: Any = None) -> _Resp:
        self.posts.append((url, data, json))
        return self.answers[min(len(self.posts) - 1, len(self.answers) - 1)]

    @contextmanager
    def stream(self, method: str, url: str) -> Any:
        self.gets.append(url)
        yield self.answers[0]


class _Limiter:
    """Лічильник тікетів — саме він і є предметом перевірки."""

    def __init__(self) -> None:
        self.tickets: list[str] = []

    def acquire(self, tag: str = "") -> float:
        self.tickets.append(tag)
        return 0.0


def test_the_user_agent_names_the_APPLICATION_not_the_person() -> None:
    """🔴 Попередник цього рядка ніс прізвище роду дослідника й особисту пошту —
    і їхав із ними в кожен запит до чужого сайту."""
    ua = H.app_ua()
    assert ua.startswith("nyshporka/")
    assert "@" not in ua, "у типовому UA не має бути жодної адреси"
    assert "github.com" in ua, "клієнт мусить давати на себе посилання"


def test_the_contact_is_added_only_when_a_person_writes_it(monkeypatch) -> None:
    """Автозаповнення тут не буває: адреса, взята з налаштувань git, поїхала б
    у чужі логи, а людина дізналась би про це звідти ж."""
    monkeypatch.setenv(H.ENV_CONTACT, "хтось@example.org")
    assert "хтось@example.org" in H.app_ua()


def test_a_retry_takes_its_own_ticket() -> None:
    """🔴 Для сервера повтор — такий самий запит. Серія ретраїв після 429 —
    найкоротший шлях від ввічливого клієнта до заблокованого."""
    lim = _Limiter()
    f = H.Fetcher(base="https://приклад", delay=0.0, limiter=lim)  # type: ignore[arg-type]
    client = _Client([_Resp(429), _Resp(429), _Resp(200, text="ок")])

    monkey = pytest.MonkeyPatch()
    monkey.setattr(H.time, "sleep", lambda s: None)   # не чекаємо відступів
    try:
        r = f.get("/шлях", client=client)
    finally:
        monkey.undo()

    assert r.text == "ок"
    assert len(client.gets) == 3
    assert len(lim.tickets) == 3, "повтори пройшли повз чергу"


def test_post_is_used_where_a_url_would_not_fit() -> None:
    """Батч на 50 назв кирилицею не влазить у GET: сервер відповідає 414."""
    f = H.Fetcher(base="https://приклад", delay=0.0)
    client = _Client([_Resp(200, text="{}")])
    f.post("/api", data={"titles": "а|б|в"}, client=client)
    assert client.posts and client.posts[0][1] == {"titles": "а|б|в"}


def test_a_download_lands_under_its_real_name_only_when_whole(tmp_path: Path) -> None:
    """🔴 Обірваний файл під правильним іменем наступний запуск порахує
    завантаженим, і виявиться це через тижні — коли по ньому вже щось
    вирішили."""
    f = H.Fetcher(delay=0.0)
    client = _Client([_Resp(200, blocks=["аб".encode(), "вг".encode()])])
    dest = tmp_path / "справа.pdf"

    seen: list[int] = []
    got = f.download("https://приклад/ф.pdf", dest, client=client, on_chunk=seen.append)

    assert got == 8 and dest.read_bytes() == "абвг".encode()
    assert not dest.with_name(dest.name + ".part").exists(), "часткового файла не прибрано"
    assert seen == [4, 8], "поступ не доповідався по ходу"
