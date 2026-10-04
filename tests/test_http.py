"""🌐 Спільний HTTP-клієнт: ввічливість, ліміт і те, чим ми себе називаємо."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

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


# ── аудит 29.09.2026: стеля тіла у `get` ────────────────────────────────────

def _mock_client(body: Any, headers: dict[str, str] | None = None) -> Any:
    import httpx

    return httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=body, headers=headers or {})))


@pytest.mark.parametrize("body", [
    b"x" * 5000,                                   # із Content-Length
    (b"x" * 1000 for _ in range(5)),               # потоком, без довжини
])
def test_get_zi_steleiu_obryvaie_velyke_tilo(body: Any) -> None:
    """🔴 Без стелі `get` читав у пам'ять скільки пришле сервер."""
    with pytest.raises(H.TooLarge):
        H.Fetcher(client=_mock_client(body), delay=0.0).get(
            "https://x/tree.json.gz", max_bytes=100)


def test_get_zi_steleiu_viddaie_zvychainu_vidpovid() -> None:
    import gzip

    raw = '{"a": "дерево"}'.encode()
    # Транспортний gzip знімається один раз: тіло приходить уже розпакованим.
    client = _mock_client(gzip.compress(raw), {"Content-Encoding": "gzip"})
    r = H.Fetcher(client=client, delay=0.0).get("https://x/t", max_bytes=1000)
    assert r.content == raw and r.json() == {"a": "дерево"}


# ── 04.10.2026: дочитування через Range і пауза за Retry-After ──────────────

_FILE = bytes(range(256)) * 40                      # 10 240 байт «справи»


def _range_server(script: list[str], seen: list[dict[str, str]]) -> Any:
    """Сервер справи за сценарієм: кожен запит бере наступний крок.

    `break` — віддати половину й обірвати з'єднання; `ok` — повно, з
    урахуванням `Range`; `ignore` — повно з початку, `Range` не помітити;
    `429:<с>` — блок із `Retry-After`; `404` — відмова.
    """
    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.headers))
        step = script[min(len(seen) - 1, len(script) - 1)]
        start = 0
        rng = req.headers.get("Range")
        if rng and step != "ignore":
            start = int(rng.split("=")[1].split("-")[0])
        if step.startswith("429"):
            return httpx.Response(429, headers={"Retry-After": step.split(":")[1]},
                                  content=b"slow down")
        if step == "404":
            return httpx.Response(404, content=b"not found")
        body = _FILE[start:]
        code = 206 if start else 200
        hdr = ({"Content-Range": f"bytes {start}-{len(_FILE) - 1}/{len(_FILE)}"}
               if start else {})
        if step == "break":
            half = body[: len(body) // 2]

            def obryv():  # type: ignore[no-untyped-def]
                yield half
                raise httpx.ReadError("з'єднання обірвано")
            return httpx.Response(code, headers=hdr, content=obryv())
        return httpx.Response(code, headers=hdr, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture()
def naps(monkeypatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(H.time, "sleep", slept.append)
    return slept


def test_obryv_poseredyni_doTCHYTUIETSIA_a_ne_pochynaietsia_z_nulia(
        tmp_path: Path, naps: list[float]) -> None:
    """🔴 Справа 2.4 ГБ, з'єднання від 0.8 МБ/с: обрив посередині — звичайна
    подія. Доти він стирав `.part`, і гігабайт узятого пропадав."""
    seen: list[dict[str, str]] = []
    dest = tmp_path / "справа.pdf"
    got = H.Fetcher(delay=0.0).download("https://x/f.pdf", dest,
                                        client=_range_server(["break", "ok"], seen),
                                        max_bytes=len(_FILE), chunk=512)
    assert got == len(_FILE) and dest.read_bytes() == _FILE
    assert "range" not in seen[0]
    assert seen[1].get("range") == f"bytes={len(_FILE) // 2}-", \
        "друга спроба не дочитувала, а качала знову"


def test_part_poperednoho_zapusku_doTCHYTUIETSIA(tmp_path: Path, naps: list[float]) -> None:
    """Обірваний запуск лишає `.part` — наступний запуск продовжує з нього."""
    dest = tmp_path / "справа.pdf"
    dest.with_name(dest.name + ".part").write_bytes(_FILE[:3000])
    seen: list[dict[str, str]] = []
    H.Fetcher(delay=0.0).download("https://x/f.pdf", dest,
                                  client=_range_server(["ok"], seen), max_bytes=len(_FILE))
    assert seen[0].get("range") == "bytes=3000-"
    assert dest.read_bytes() == _FILE


def test_server_bez_range_daie_tsilyi_fail_a_ne_skleiku(tmp_path: Path,
                                                         naps: list[float]) -> None:
    """200 на запит із `Range` — файл з початку; дописати його до `.part`
    означало б дублювати перші байти."""
    dest = tmp_path / "справа.pdf"
    dest.with_name(dest.name + ".part").write_bytes(_FILE[:3000])
    H.Fetcher(delay=0.0).download("https://x/f.pdf", dest,
                                  client=_range_server(["ignore"], []), max_bytes=len(_FILE))
    assert dest.read_bytes() == _FILE


def test_429_chekaie_rivno_retry_after(tmp_path: Path, naps: list[float]) -> None:
    """🔴 Wikimedia блокує на 600 с, і кожна спроба в блоці його продовжує:
    свій відступ 1–60 с тут лише поглиблює яму."""
    dest = tmp_path / "справа.pdf"
    H.Fetcher(delay=0.0).download("https://x/f.pdf", dest,
                                  client=_range_server(["429:30", "ok"], []))
    assert naps == [30 + H.RETRY_AFTER_PAD_S]
    assert dest.read_bytes() == _FILE


def test_dovhyi_retry_after_ce_pomylka_z_chyslom_a_part_lyshaietsia(
        tmp_path: Path, naps: list[float]) -> None:
    """Годину мовчки не чекаємо: людина бачить, скільки просить сервер, а
    взяте лишається для повторного запуску."""
    dest = tmp_path / "справа.pdf"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(_FILE[:3000])
    with pytest.raises(H.HttpError) as e:
        H.Fetcher(delay=0.0).download("https://x/f.pdf", dest,
                                      client=_range_server(["429:3600"], []))
    assert e.value.status == 429 and e.value.retry_after == 3600
    assert part.read_bytes() == _FILE[:3000], "узяте стерто"
    assert naps == []


def test_vidmova_404_stiraie_part(tmp_path: Path, naps: list[float]) -> None:
    """Остаточна відмова: дочитувати нічого, недокачок не лишаємо."""
    dest = tmp_path / "справа.pdf"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"x" * 10)
    with pytest.raises(H.HttpError) as e:
        H.Fetcher(delay=0.0).download("https://x/f.pdf", dest,
                                      client=_range_server(["404"], []))
    assert e.value.status == 404 and not part.exists() and not dest.exists()


def test_get_na_429_chekaie_retry_after(naps: list[float]) -> None:
    f = H.Fetcher(base="https://приклад", delay=0.0)

    class _R(_Resp):
        headers: ClassVar[dict[str, str]] = {"Retry-After": "20"}

    client = _Client([_R(429), _Resp(200, text="ок")])
    assert f.get("/шлях", client=client).text == "ок"
    assert naps == [20 + H.RETRY_AFTER_PAD_S]
