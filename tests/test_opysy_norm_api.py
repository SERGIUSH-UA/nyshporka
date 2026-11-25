"""Нормалізація ключем API людини: згода лише в терміналі, бюджет — жорстка межа, ключ ніде не видно.

Провайдер і сховище паролів підставні — мережі немає.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.opysy import norm_api as NA

KEY = "sk-test-0123456789abcdefghijklmnopQRST"


class FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, s: str, u: str) -> str | None:
        return self.store.get((s, u))

    def set_password(self, s: str, u: str, v: str) -> None:
        self.store[(s, u)] = v

    def delete_password(self, s: str, u: str) -> None:
        self.store.pop((s, u), None)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(NA, "teka", lambda: d)
    kr = FakeKeyring()
    monkeypatch.setattr(NA, "_keyring", lambda: kr)
    return kr


def _batches(d: Path, k: int, n: int = 3) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(k):
        titles = [f"Дело о {i}-{j}" for j in range(n)]
        (d / f"batch_{i:03d}.json").write_text(json.dumps(
            {"request": "Нормалізуй назви: " + json.dumps(titles, ensure_ascii=False), "titles": titles,
             "keys": [{"page": "0001", "part": 0, "row": j} for j in range(n)], "n": n},
            ensure_ascii=False), encoding="utf-8")
    return d


def _nal(budget: float = 1.0, model: str = "claude-sonnet-5-5", provider: str = "anthropic") -> NA.Nalashtuvannia:
    n = NA.Nalashtuvannia(provider=provider, model=model, biudzhet_usd=budget, zghoda_koly="2026-11-25",
                          zghoda_versiia=NA.ZGODA, kliuch_kinets="QRST", mezha_provaidera=True)
    NA.zberehty(n)
    return n


class FakeProv:
    """Відповідає масивом тієї самої довжини; `bad` — пачки, на які дає не ту довжину."""

    def __init__(self, *, bad: set[str] = frozenset(), refuse: bool = False,
                 nevidomo: bool = False) -> None:
        self.jobs: dict[str, list[tuple[str, str]]] = {}
        self.bad, self.refuse, self.nevidomo = set(bad), refuse, nevidomo
        self.calls = 0

    def perevirka(self) -> None:
        pass

    def _answer(self, request: str) -> NA.Vidpovid:
        titles = json.loads(request[request.index("["):])
        if self.refuse:
            return NA.Vidpovid("", 500, 40, "vidmova")
        if any(t.startswith(b) for b in self.bad for t in titles):
            return NA.Vidpovid(json.dumps(titles[:-1], ensure_ascii=False), 500, 40, "ok")
        return NA.Vidpovid(json.dumps([t.upper() for t in titles], ensure_ascii=False), 500, 40, "ok")

    def zaraz(self, model: str, request: str, *, effort: str) -> NA.Vidpovid:
        self.calls += 1
        if self.nevidomo:
            raise NA.Nevidomo("тайм-аут")
        return self._answer(request)

    def podaty(self, model: str, items: list[tuple[str, str]], *, effort: str) -> str:
        self.calls += 1
        if self.nevidomo:
            raise NA.Nevidomo("тайм-аут")
        job = f"job{len(self.jobs)}"
        self.jobs[job] = items
        return job

    def hotovo(self, job: str) -> bool:
        return True

    def rezultaty(self, job: str) -> dict[str, NA.Vidpovid]:
        return {cid: self._answer(req) for cid, req in self.jobs[job]}


def _run(d: Path, prov: FakeProv, n: NA.Nalashtuvannia | None = None, **kw: Any) -> dict[str, Any]:
    """Прогін batch із чеканням (сон підставний): подати й одразу забрати."""
    kw.setdefault("chekaty_s", 60.0)
    return NA.normalizuvaty(d, prov=prov, n=n, spaty=lambda _s: None, **kw)


def _vytraty() -> list[dict[str, Any]]:
    p = NA.teka() / "oblik.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ── налаштування ─────────────────────────────────────────────────────────────


def _setup(answers: list[str], *, terminal: bool = True, druk: list[str] | None = None) -> NA.Nalashtuvannia:
    it = iter(answers)
    out = druk if druk is not None else []
    return NA.nalashtuvaty_interaktyvno(vvid=lambda _p: next(it), pryhovano=lambda _p: KEY,
                                        druk=out.append, terminal=terminal,
                                        perevirka=lambda _p, _k: None)


def test_setup_refuses_without_terminal(env: FakeKeyring) -> None:
    with pytest.raises(NA.ApiError, match="терміналі"):
        _setup(["1", "1", "2", "так", "так"], terminal=False)
    assert not env.store
    assert NA.zavantazhyty() is None


def test_setup_needs_explicit_consent(env: FakeKeyring) -> None:
    with pytest.raises(NA.ApiError, match="згоди"):
        _setup(["1", "1", "2", "так", "ok"])
    assert not env.store


def test_setup_stores_key_only_in_keyring_and_never_prints_it(env: FakeKeyring) -> None:
    druk: list[str] = []
    n = _setup(["2", "1", "3,5", "так", "так"], druk=druk)
    assert (n.provider, n.model, n.biudzhet_usd) == ("openai", "gpt-6.1-terra", 3.5)
    assert env.store[(NA.KEYRING_SERVICE, "openai")] == KEY
    assert n.kliuch_kinets == KEY[-4:]
    disk = "".join(p.read_text(encoding="utf-8") for p in NA.teka().iterdir() if p.is_file())
    assert KEY not in disk
    assert KEY not in "\n".join(druk)
    assert KEY not in json.dumps(NA.stan(), ensure_ascii=False)


def test_env_key_is_not_used(env: FakeKeyring, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    with pytest.raises(NA.ApiError, match="nalashtuvaty"):
        NA.kliuch("anthropic")


# ── прогін і бюджет ──────────────────────────────────────────────────────────


def test_batch_writes_answers_and_books_actual_cost(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 3)
    prov = FakeProv()
    res = _run(d, prov, _nal(1.0))
    assert res["pryiniato"] == 3 and res["bez_vidpovidi"] == 0
    assert all((d / f"batch_{i:03d}.out.txt").exists() for i in range(3))
    assert (d / "model.txt").read_text(encoding="utf-8") == "claude-sonnet-5-5"
    c = NA.cina("claude-sonnet-5-5")
    assert _vytraty()[-1]["usd"] == pytest.approx(3 * c.usd(500, 40, batch=True), abs=1e-6)
    assert not json.loads((NA.teka() / "rezervy.json").read_text(encoding="utf-8"))


def test_budget_is_never_exceeded(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 10)
    c = NA.cina("claude-sonnet-5-5")
    one = c.naihirshe(json.loads((d / "batch_000.json").read_text(encoding="utf-8"))["request"], batch=True)
    n = _nal(one * 3.5)                     # найгірша ціна вміщає 3 пачки, не 4
    prov = FakeProv()
    res = _run(d, prov, n)
    assert res["podano"] == 3
    assert "вистачило на 3" in res["biudzhet"]
    assert NA.vytracheno() <= n.biudzhet_usd
    # повтор бере ще стільки, скільки дозволяє залишок, — і так само не перетинає межі
    _run(d, prov, n)
    assert NA.vytracheno() <= n.biudzhet_usd


def test_unknown_outcome_charges_the_whole_reserve(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 2)
    with pytest.raises(NA.Nevidomo):
        NA.normalizuvaty(d, prov=FakeProv(nevidomo=True), n=_nal(1.0))
    last = _vytraty()[-1]
    assert last["stan"] == "nevidomo" and last["usd"] > 0
    assert not list(d.glob("*.out.txt"))


def test_bad_answer_is_not_written_and_retries_are_capped(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 2)
    prov = FakeProv(bad={"Дело о 1-"})
    n = _nal(1.0)
    for _ in range(NA.SPROB + 2):
        _run(d, prov, n)
    assert (d / "batch_000.out.txt").exists()
    assert not (d / "batch_001.out.txt").exists()
    assert (d / "batch_001.out.bad.txt").exists()
    sproby = json.loads((d / NA.SPROBY).read_text(encoding="utf-8"))
    assert sproby["batch_001.json"] == NA.SPROB
    calls = prov.calls
    res = _run(d, prov, n)
    assert prov.calls == calls                          # більше не подається
    assert res["vycherpano_sproby"] == ["batch_001.json"]


def test_refusal_is_paid_non_answer(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 1)
    res = NA.normalizuvaty(d, prov=FakeProv(refuse=True), n=_nal(1.0), rezhym="zaraz")
    assert res["pryiniato"] == 0 and "відмовила" in res["ne_hodytsia"][0]
    assert _vytraty()[-1]["usd"] > 0
    assert not (d / "batch_000.out.txt").exists()


def test_zaraz_reserves_each_request(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 2)
    res = NA.normalizuvaty(d, prov=FakeProv(), n=_nal(1.0), rezhym="zaraz")
    assert res["pryiniato"] == 2 and len(_vytraty()) == 2


def test_requires_setup_and_known_model(env: FakeKeyring, tmp_path: Path) -> None:
    d = _batches(tmp_path / "norm", 1)
    with pytest.raises(NA.ApiError, match="nalashtuvaty"):
        NA.normalizuvaty(d, prov=FakeProv())
    with pytest.raises(NA.ApiError, match="таблиці цін"):
        NA.normalizuvaty(d, prov=FakeProv(), n=_nal(1.0, model="claude-unknown"))


def test_worst_case_bounds_input_by_utf8_bytes() -> None:
    c = NA.cina("claude-sonnet-5-5")
    req = "ѣѲі" * 1000
    assert c.naihirshe(req, batch=False) == pytest.approx(
        ((len(req.encode("utf-8")) + NA.VKHID_ZAPAS) * 2.0 + NA.MAX_OUT * 10.0) / 1e6)


# ── сито запобіжника агента ──────────────────────────────────────────────────


@pytest.mark.parametrize("cmd", [
    "python -c \"import keyring; print(keyring.get_password('nyshporka-opysy-api', 'openai'))\"",
    "cmdkey /list",
    "keyring get nyshporka-opysy-api anthropic",
    "security find-generic-password -s nyshporka-opysy-api -w",
    "[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime]",
])
def test_guard_blocks_key_store(cmd: str, tmp_path: Path) -> None:
    from nyshporka.skills import guard as G

    assert G.decide({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(tmp_path)})


def test_guard_lets_normal_work_through(tmp_path: Path) -> None:
    from nyshporka.skills import guard as G

    for cmd in ("nysh opys norm teka --api", "nysh opys api stan", "git status"):
        assert G.decide({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(tmp_path)}) is None
    assert G.decide({"tool_name": "Write", "tool_input": {
        "file_path": str(tmp_path / "x.py"), "content": "import keyring\nkeyring.get_password('a', 'b')"},
        "cwd": str(tmp_path)})


def test_collect_persists_each_closed_job_before_next_one_fails(env: FakeKeyring, tmp_path: Path) -> None:
    """Збій мережі на другій задачі не змушує наступний виклик знову облікувати першу."""
    d = _batches(tmp_path / "norm", 1)

    class Slow(FakeProv):
        ready = False
        boom: str | None = None

        def hotovo(self, job: str) -> bool:
            return self.ready

        def rezultaty(self, job: str) -> dict[str, NA.Vidpovid]:
            if job == self.boom:
                raise OSError("мережа")
            return super().rezultaty(job)

    prov = Slow()
    n = _nal(1.0)
    _run(d, prov, n, chekaty_s=0.0)
    # друга пачка — друга задача
    (d / "batch_001.json").write_text((d / "batch_000.json").read_text(encoding="utf-8"), encoding="utf-8")
    _run(d, prov, n, chekaty_s=0.0)
    assert len(prov.jobs) == 2
    prov.ready, prov.boom = True, "job1"
    with pytest.raises(OSError):
        _run(d, prov, n, chekaty_s=0.0)
    n_oblik = len(_vytraty())
    zbereg = json.loads((d / NA.ZAVDANNIA_API).read_text(encoding="utf-8"))
    assert [z["job"] for z in zbereg] == ["job1"]
    prov.boom = None
    _run(d, prov, n, chekaty_s=0.0)
    # перша задача вдруге не облікована: додався лише облік другої
    zakryti = [x for x in _vytraty()[n_oblik:] if x.get("job")]
    assert [x["job"] for x in zakryti] == ["job1"]
