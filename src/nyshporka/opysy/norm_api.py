"""🔑 Нормалізація назв справ ключем API учасника (Claude чи OpenAI) — поряд зі шляхом агента.

Пачки ті самі, що для агента (`batch_NNN.json`, поле `request` — увесь запит шаблону `b2-1`), і
відповідь лягає туди ж (`batch_NNN.out.txt`), тож ворота, `push` і обмін не знають, хто
нормалізував. Різниця одна: запит шле сам `nysh`, ключем людини, а не її агент.

**Згода, модель, бюджет і ключ — лише людина**, у своєму терміналі (`nysh opys api nalashtuvaty`):
команда без терміналу відмовляє, тож агент не може ні завести ключ, ні підняти бюджет. Агентові —
лише `stan` і прогін у межах бюджету.

🔴 Бюджет — жорстка межа, а не порада:

- перед кожним мережевим викликом — **резерв найгіршої ціни** під замком, записаний на диск ДО
  запиту: (байти UTF-8 запиту + запас) × ціна входу + `max_tokens` × ціна виходу. Токен покриває
  щонайменше байт, тож байти — верхня межа входу й для кирилиці, і для «ѣ»;
- автоповтори SDK вимкнено: запит, що впав за тайм-аутом, міг бути оплачений. Такий резерв
  списується повністю («невідомо»), а не відпускається;
- після відповіді резерв замінює фактична ціна з `usage`;
- `refusal` і `max_tokens` — оплачена невідповідь: пачка лишається без `.out.txt`, повторів на
  пачку щонайбільше `SPROB`;
- серверний `fallbacks` не шлеться: Batch його не приймає, і він платить іншою моделлю;
- модель без рядка в `data/api_ceny.json` — відмова: межу без ціни не порахувати.

🔴 Ключ — щоб не вкрали:

- живе в сховищі паролів ОС (`keyring`: Windows Credential Manager / DPAPI, Keychain, Secret
  Service), як ключ Супряги. У файлах, `.env` простору й git його немає;
- ключ із середовища (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) НЕ береться: той, що лежить у
  середовищі для агента, платив би без згоди людини;
- уводиться лише прихованим уведенням у терміналі; аргументом команди не приймається (історія
  оболонки, розмова з агентом);
- жодна функція модуля ключа не повертає назовні: клієнт SDK будується тут же, з ключем у пам'яті
  процесу; у підсумках — лише чотири останні знаки;
- назви справ ідуть від `nysh` прямо провайдерові, агент їх не читає, а модель-нормалізатор без
  інструментів — джейлбрейку в тексті справи нема кого «попросити»;
- головний запобіжник — межа витрат на боці провайдера (окремий ключ, окремий робочий простір чи
  проєкт): агент із оболонкою працює від імені тієї самої людини, і сховище ОС від нього технічно
  не закрите. Налаштування про це питає.
"""
from __future__ import annotations

import io
import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Protocol

#: Служба в сховищі паролів ОС; ім'я запису — провайдер.
KEYRING_SERVICE = "nyshporka-opysy-api"
PROVIDERS = ("anthropic", "openai")
PROVIDER_LABEL = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI (GPT)"}
#: Стеля відповіді: Sonnet 5.5 з effort low на 20 назвах заміряно з 8000 (думання входить у неї).
MAX_OUT = 8000
#: Запас до байтів запиту на службові токени повідомлення.
VKHID_ZAPAS = 300
#: Скільки разів пачку подаємо знову після оплаченої невідповіді (відмова, обрізано, не та довжина).
SPROB = 2
#: Версія тексту згоди: нова версія — згоду питають знову.
ZGODA = "1"
#: Заміряно на `b2-1` (Sonnet 5.5, Batch, 160 назв): токенів на назву — для кошторису, не для межі.
TOKENIV_NA_NAZVU = {"vkhid": 92, "vykhid": 56}

Rezhym = Literal["batch", "zaraz"]


class ApiError(RuntimeError):
    """Нормалізація ключем API зараз неможлива; текст — що зробити людині."""


class NeVystachaie(ApiError):
    """Резерв не вміщається в залишок бюджету."""


class KliuchError(ApiError):
    """Провайдер не прийняв ключ (немає, відкликано, без прав)."""


class Nevidomo(ApiError):
    """Запит міг бути оплачений, а відповіді немає (тайм-аут, обрив, 5xx)."""


# ── ціни ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Cina:
    model: str
    provider: str
    vkhid: float          # $ за 1M токенів входу, звичайний запит
    vykhid: float         # $ за 1M токенів виходу
    batch: float          # частка звичайної ціни в Batch
    effort: str
    riven: str
    rekomendovano: bool
    zamir: str

    def usd(self, vkhid: int, vykhid: int, *, batch: bool) -> float:
        k = self.batch if batch else 1.0
        return (vkhid * self.vkhid + vykhid * self.vykhid) / 1e6 * k

    def naihirshe(self, request: str, *, batch: bool) -> float:
        """Найгірша ціна одного запиту: вхід — байти UTF-8 + запас, вихід — уся стеля."""
        return self.usd(len(request.encode("utf-8")) + VKHID_ZAPAS, MAX_OUT, batch=batch)

    def na_1000(self) -> float:
        """Орієнтовна ціна 1 000 назв через Batch за заміром `b2-1` (не межа — межу тримає резерв)."""
        return 1000 * self.usd(TOKENIV_NA_NAZVU["vkhid"], TOKENIV_NA_NAZVU["vykhid"], batch=True)


def ceny() -> dict[str, Cina]:
    raw = json.loads(resources.files("nyshporka.opysy").joinpath("data", "api_ceny.json")
                     .read_text(encoding="utf-8"))
    return {m: Cina(model=m, provider=v["provider"], vkhid=float(v["vkhid"]), vykhid=float(v["vykhid"]),
                    batch=float(v.get("batch", 1.0)), effort=str(v.get("effort", "low")),
                    riven=str(v.get("riven", "")), rekomendovano=bool(v.get("rekomendovano")),
                    zamir=str(v.get("zamir", "")))
            for m, v in raw["models"].items()}


def cina(model: str) -> Cina:
    c = ceny().get(model)
    if c is None:
        raise ApiError(f"моделі «{model}» немає в таблиці цін — межу бюджету без ціни не порахувати. "
                       f"Є: {', '.join(ceny())}")
    return c


# ── налаштування, ключ, облік ────────────────────────────────────────────────


def teka() -> Path:
    from nyshporka.core.appdirs import data_dir

    d = data_dir() / "opysy_api"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _nalashtuvannia_path() -> Path:
    return teka() / "nalashtuvannia.json"


@dataclass(frozen=True)
class Nalashtuvannia:
    provider: str
    model: str
    biudzhet_usd: float
    zghoda_koly: str
    zghoda_versiia: str
    kliuch_kinets: str
    mezha_provaidera: bool


def zavantazhyty() -> Nalashtuvannia | None:
    p = _nalashtuvannia_path()
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return Nalashtuvannia(provider=d["provider"], model=d["model"], biudzhet_usd=float(d["biudzhet_usd"]),
                          zghoda_koly=d.get("zghoda_koly", ""), zghoda_versiia=d.get("zghoda_versiia", ""),
                          kliuch_kinets=d.get("kliuch_kinets", ""),
                          mezha_provaidera=bool(d.get("mezha_provaidera")))


def zberehty(n: Nalashtuvannia) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(_nalashtuvannia_path(), json.dumps(n.__dict__, ensure_ascii=False, indent=1),
                      newline="\n")


def _keyring() -> Any:
    import keyring

    return keyring


def kliuch(provider: str) -> str:
    """Ключ провайдера зі сховища паролів ОС. Лише для клієнта SDK у цьому процесі."""
    try:
        got = _keyring().get_password(KEYRING_SERVICE, provider)
    except Exception as exc:
        raise ApiError(f"сховище паролів системи недоступне ({type(exc).__name__}) — ключ API тут "
                       f"тримати ніде") from None
    if not got:
        raise ApiError("ключа API немає — людина заводить його сама: `nysh opys api nalashtuvaty` "
                       "у своєму терміналі")
    return str(got)


def zberehty_kliuch(provider: str, value: str) -> str:
    """Покласти ключ у сховище паролів ОС; повертає лише чотири останні знаки."""
    value = value.strip()
    _keyring().set_password(KEYRING_SERVICE, provider, value)
    return value[-4:]


def vydalyty_kliuch(provider: str) -> None:
    import contextlib

    with contextlib.suppress(Exception):
        _keyring().delete_password(KEYRING_SERVICE, provider)


@contextmanager
def _zamok() -> Iterator[None]:
    from nyshporka.core.xrate import _locked

    with _locked(teka() / "oblik.lock", timeout=60.0):
        yield


def _oblik_path() -> Path:
    return teka() / "oblik.jsonl"


def _rezervy_path() -> Path:
    return teka() / "rezervy.json"


def _rezervy() -> dict[str, dict[str, Any]]:
    p = _rezervy_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _zapysaty_rezervy(r: dict[str, dict[str, Any]]) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(_rezervy_path(), json.dumps(r, ensure_ascii=False, indent=1), newline="\n")


def vytracheno() -> float:
    p = _oblik_path()
    if not p.exists():
        return 0.0
    return sum(float(json.loads(x).get("usd") or 0) for x in p.read_text(encoding="utf-8").splitlines()
               if x.strip())


def _koly() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def zalyshok(n: Nalashtuvannia) -> float:
    return n.biudzhet_usd - vytracheno() - sum(float(r["usd"]) for r in _rezervy().values())


def rezervuvaty(n: Nalashtuvannia, usd: float, meta: dict[str, Any]) -> str:
    """Резерв під замком ДО мережі. Не вміщається — `NeVystachaie`, і запиту не буде."""
    with _zamok():
        rest = n.biudzhet_usd - vytracheno() - sum(float(r["usd"]) for r in _rezervy().values())
        if usd > rest + 1e-12:
            raise NeVystachaie(f"бюджет: лишилось ${max(0.0, rest):.4f}, а запит може коштувати до "
                               f"${usd:.4f}. Підняти бюджет — лише людина: `nysh opys api nalashtuvaty`")
        rid = uuid.uuid4().hex[:12]
        r = _rezervy()
        r[rid] = {"usd": round(usd, 6), "koly": _koly(), **meta}
        _zapysaty_rezervy(r)
        return rid


def zakryty(rid: str, *, usd: float, stan: str, **meta: Any) -> None:
    """Резерв → запис обліку з фактичною (або, при `stan="nevidomo"`, зарезервованою) ціною."""
    with _zamok():
        r = _rezervy()
        rez = r.pop(rid, None)
        zapys = {"koly": _koly(), "rid": rid, "usd": round(float(usd), 6), "stan": stan,
                 **({k: v for k, v in (rez or {}).items() if k not in ("usd", "koly")}), **meta}
        with _oblik_path().open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(zapys, ensure_ascii=False) + "\n")
        _zapysaty_rezervy(r)


def vidpustyty(rid: str) -> None:
    """Зняти резерв без оплати — лише коли провайдер точно не рахував (відмова до обробки)."""
    with _zamok():
        r = _rezervy()
        r.pop(rid, None)
        _zapysaty_rezervy(r)


# ── провайдери ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Vidpovid:
    """Одна відповідь моделі. `stan`: ok · obrizano (стеля виходу) · vidmova (refusal) · pomylka."""
    text: str
    vkhid: int
    vykhid: int
    stan: str
    oplacheno: bool = True


class Provider(Protocol):
    def perevirka(self) -> None: ...
    def zaraz(self, model: str, request: str, *, effort: str) -> Vidpovid: ...
    def podaty(self, model: str, items: list[tuple[str, str]], *, effort: str) -> str: ...
    def hotovo(self, job: str) -> bool: ...
    def rezultaty(self, job: str) -> dict[str, Vidpovid]: ...


class _Anthropic:
    def __init__(self, key: str) -> None:
        import anthropic

        self._m = anthropic
        self._c = anthropic.Anthropic(api_key=key, max_retries=0, timeout=180.0)

    def _err(self, exc: Exception) -> ApiError:
        a = self._m
        if isinstance(exc, (a.AuthenticationError, a.PermissionDeniedError)):
            return KliuchError("провайдер не прийняв ключ — людина заводить новий: "
                               "`nysh opys api nalashtuvaty`")
        if isinstance(exc, (a.APITimeoutError, a.APIConnectionError)) or (
                isinstance(exc, a.APIStatusError) and exc.status_code >= 500):
            return Nevidomo(f"{type(exc).__name__}: запит міг бути оплачений")
        return ApiError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")

    @staticmethod
    def _vidpovid(msg: Any) -> Vidpovid:
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        stan = {"refusal": "vidmova", "max_tokens": "obrizano"}.get(str(msg.stop_reason), "ok")
        return Vidpovid(text=text, vkhid=int(msg.usage.input_tokens), vykhid=int(msg.usage.output_tokens),
                        stan=stan)

    def perevirka(self) -> None:
        try:
            next(iter(self._c.models.list(limit=1)), None)
        except Exception as exc:
            raise self._err(exc) from None

    def _params(self, model: str, request: str, effort: str) -> dict[str, Any]:
        return {"model": model, "max_tokens": MAX_OUT, "output_config": {"effort": effort},
                "messages": [{"role": "user", "content": request}]}

    def zaraz(self, model: str, request: str, *, effort: str) -> Vidpovid:
        try:
            return self._vidpovid(self._c.messages.create(**self._params(model, request, effort)))
        except Exception as exc:
            raise self._err(exc) from None

    def podaty(self, model: str, items: list[tuple[str, str]], *, effort: str) -> str:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        reqs = [Request(custom_id=cid, params=MessageCreateParamsNonStreaming(
            **self._params(model, text, effort)))  # type: ignore[typeddict-item]
            for cid, text in items]
        try:
            return str(self._c.messages.batches.create(requests=reqs).id)
        except Exception as exc:
            raise self._err(exc) from None

    def hotovo(self, job: str) -> bool:
        try:
            return self._c.messages.batches.retrieve(job).processing_status == "ended"
        except Exception as exc:
            raise self._err(exc) from None

    def rezultaty(self, job: str) -> dict[str, Vidpovid]:
        out: dict[str, Vidpovid] = {}
        try:
            for res in self._c.messages.batches.results(job):
                if res.result.type == "succeeded":
                    out[res.custom_id] = self._vidpovid(res.result.message)
                else:
                    # errored / canceled / expired — Batch за них не рахує
                    out[res.custom_id] = Vidpovid("", 0, 0, "pomylka", oplacheno=False)
        except Exception as exc:
            raise self._err(exc) from None
        return out


class _OpenAI:
    def __init__(self, key: str) -> None:
        import openai

        self._m = openai
        self._c = openai.OpenAI(api_key=key, max_retries=0, timeout=180.0)

    def _err(self, exc: Exception) -> ApiError:
        o = self._m
        if isinstance(exc, (o.AuthenticationError, o.PermissionDeniedError)):
            return KliuchError("провайдер не прийняв ключ — людина заводить новий: "
                               "`nysh opys api nalashtuvaty`")
        if isinstance(exc, (o.APITimeoutError, o.APIConnectionError)) or (
                isinstance(exc, o.APIStatusError) and exc.status_code >= 500):
            return Nevidomo(f"{type(exc).__name__}: запит міг бути оплачений")
        return ApiError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")

    @staticmethod
    def _z_body(body: dict[str, Any]) -> Vidpovid:
        parts, vidmova = [], False
        for item in body.get("output") or []:
            if item.get("type") != "message":
                continue
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text") or "")
                elif c.get("type") == "refusal":
                    vidmova = True
        u = body.get("usage") or {}
        stan = "vidmova" if vidmova else ("obrizano" if body.get("status") == "incomplete" else "ok")
        return Vidpovid(text="".join(parts), vkhid=int(u.get("input_tokens") or 0),
                        vykhid=int(u.get("output_tokens") or 0), stan=stan)

    def _body(self, model: str, request: str, effort: str) -> dict[str, Any]:
        return {"model": model, "input": [{"role": "user", "content": request}],
                "reasoning": {"effort": effort}, "max_output_tokens": MAX_OUT}

    def perevirka(self) -> None:
        try:
            next(iter(self._c.models.list()), None)
        except Exception as exc:
            raise self._err(exc) from None

    def zaraz(self, model: str, request: str, *, effort: str) -> Vidpovid:
        try:
            r = self._c.responses.create(**self._body(model, request, effort))
        except Exception as exc:
            raise self._err(exc) from None
        return self._z_body(r.model_dump())

    def podaty(self, model: str, items: list[tuple[str, str]], *, effort: str) -> str:
        lines = "\n".join(json.dumps({"custom_id": cid, "method": "POST", "url": "/v1/responses",
                                      "body": self._body(model, text, effort)}, ensure_ascii=False)
                          for cid, text in items)
        try:
            f = self._c.files.create(file=("nysh-opysy.jsonl", io.BytesIO(lines.encode("utf-8"))),
                                     purpose="batch")
            return str(self._c.batches.create(input_file_id=f.id, endpoint="/v1/responses",
                                              completion_window="24h").id)
        except Exception as exc:
            raise self._err(exc) from None

    def hotovo(self, job: str) -> bool:
        try:
            return self._c.batches.retrieve(job).status in ("completed", "failed", "expired", "cancelled")
        except Exception as exc:
            raise self._err(exc) from None

    def rezultaty(self, job: str) -> dict[str, Vidpovid]:
        out: dict[str, Vidpovid] = {}
        try:
            b = self._c.batches.retrieve(job)
            if b.output_file_id:
                for line in self._c.files.content(b.output_file_id).text.splitlines():
                    if not line.strip():
                        continue
                    o = json.loads(line)
                    resp = o.get("response") or {}
                    if resp.get("status_code") == 200:
                        out[o["custom_id"]] = self._z_body(resp.get("body") or {})
                    else:
                        out[o["custom_id"]] = Vidpovid("", 0, 0, "pomylka", oplacheno=False)
            if b.error_file_id:
                for line in self._c.files.content(b.error_file_id).text.splitlines():
                    if line.strip():
                        cid = json.loads(line).get("custom_id")
                        if cid and cid not in out:
                            out[cid] = Vidpovid("", 0, 0, "pomylka", oplacheno=False)
        except Exception as exc:
            raise self._err(exc) from None
        return out


def provider(name: str, key: str) -> Provider:
    if name == "anthropic":
        return _Anthropic(key)
    if name == "openai":
        return _OpenAI(key)
    raise ApiError(f"провайдер «{name}»: є {', '.join(PROVIDERS)}")


# ── прогін ───────────────────────────────────────────────────────────────────

ZAVDANNIA_API = "api_zavdannia.json"
SPROBY = "api_sproby.json"


def _json(p: Path, default: Any) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _zapys(p: Path, data: Any) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1), newline="\n")


def _pryiniaty(teka_p: Path, pachka: str, v: Vidpovid, sproby: dict[str, int]) -> str:
    """Відповідь на пачку → `.out.txt`, якщо вона годиться; інакше — спроба й причина."""
    from nyshporka.opysy import normalize as NZ

    p = teka_p / pachka
    if v.stan != "ok":
        sproby[pachka] = sproby.get(pachka, 0) + (1 if v.oplacheno else 0)
        return {"vidmova": "модель відмовила", "obrizano": "відповідь обрізано стелею",
                "pomylka": "провайдер не обробив"}.get(v.stan, v.stan)
    n = int(json.loads(p.read_text(encoding="utf-8"))["n"])
    try:
        NZ.parse(v.text, n)
    except NZ.NormError as exc:
        sproby[pachka] = sproby.get(pachka, 0) + 1
        (teka_p / f"{p.stem}.out.bad.txt").write_text(v.text, encoding="utf-8")
        return str(exc)
    (teka_p / f"{p.stem}.out.txt").write_text(v.text, encoding="utf-8", newline="\n")
    (teka_p / f"{p.stem}.out.bad.txt").unlink(missing_ok=True)
    return ""


def _model_file(teka_p: Path, model: str) -> None:
    """Модель нормалізації — у `model.txt` теки пачок (його читають `push` і `viddaty`)."""
    f = teka_p / "model.txt"
    bulo = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    if not bulo:
        f.write_text(model, encoding="utf-8")
    elif model not in [x.strip() for x in bulo.split("+")]:
        f.write_text(f"{bulo} + {model}", encoding="utf-8")


def normalizuvaty(teka_p: Path, *, rezhym: Rezhym = "batch", chekaty_s: float = 0.0,
                  prov: Provider | None = None, n: Nalashtuvannia | None = None,
                  say: Callable[[str], None] = lambda _m: None,
                  spaty: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Пачки теки без відповіді → відповіді моделі ключем людини, у межах бюджету.

    Повтор продовжує: подані задачі Batch забираються, нові пачки подаються. Пачка, на яку модель
    уже `SPROB` разів дала оплачену невідповідь, більше не подається (лишається агентові).
    """
    from nyshporka.opysy import norm_batches as NB

    teka_p = Path(teka_p)
    n = n or zavantazhyty()
    if n is None or n.zghoda_versiia != ZGODA:
        raise ApiError("ключ API не налаштовано (чи змінилась згода) — це робить людина у своєму "
                       "терміналі: `nysh opys api nalashtuvaty`")
    c = cina(n.model)
    if c.provider != n.provider:
        raise ApiError(f"модель {n.model} — не {n.provider}")
    prov = prov or provider(n.provider, kliuch(n.provider))
    zavd: list[dict[str, Any]] = _json(teka_p / ZAVDANNIA_API, [])
    sproby: dict[str, int] = _json(teka_p / SPROBY, {})
    vytrata = 0.0
    pidsumok: dict[str, Any] = {"model": n.model, "pryiniato": 0, "ne_hodytsia": [], "podano": 0}

    def zibraty() -> None:
        nonlocal zavd, vytrata
        lyshylos = []
        for z in zavd:
            if not prov.hotovo(z["job"]):
                lyshylos.append(z)
                continue
            got = prov.rezultaty(z["job"])
            usd = 0.0
            vkh = vykh = 0
            for cid, pachka in z["pachky"].items():
                v = got.get(cid) or Vidpovid("", 0, 0, "pomylka", oplacheno=False)
                if v.oplacheno:
                    usd += c.usd(v.vkhid, v.vykhid, batch=True)
                    vkh += v.vkhid
                    vykh += v.vykhid
                why = _pryiniaty(teka_p, pachka, v, sproby)
                if why:
                    pidsumok["ne_hodytsia"].append(f"{pachka}: {why}")
                else:
                    pidsumok["pryiniato"] += 1
            zakryty(z["rid"], usd=usd, stan="faktychno", vkhid=vkh, vykhid=vykh, job=z["job"])
            vytrata += usd
        zavd = lyshylos
        _zapys(teka_p / ZAVDANNIA_API, zavd)
        _zapys(teka_p / SPROBY, sproby)

    zibraty()
    u_roboti = {p for z in zavd for p in z["pachky"].values()}
    cherha = [p.name for p in NB.bez_vidpovidi(teka_p)
              if p.name not in u_roboti and sproby.get(p.name, 0) < SPROB]
    zvershyly_sproby = [p.name for p in NB.bez_vidpovidi(teka_p) if sproby.get(p.name, 0) >= SPROB]
    meta = {"provider": n.provider, "model": n.model, "rezhym": rezhym, "teka": str(teka_p.resolve())}
    biudzhet_vycherpano = ""
    if rezhym == "batch" and cherha:
        items: list[tuple[str, str]] = []
        vzialy: list[tuple[str, str]] = []
        suma = 0.0
        rest = zalyshok(n)
        for name in cherha:
            req = json.loads((teka_p / name).read_text(encoding="utf-8"))["request"]
            w = c.naihirshe(req, batch=True)
            if suma + w > rest:
                biudzhet_vycherpano = (f"бюджету вистачило на {len(vzialy)} пачок із {len(cherha)}: "
                                       f"лишилось ${max(0.0, rest):.4f}")
                break
            cid = f"p{len(items):04d}"
            items.append((cid, req))
            vzialy.append((cid, name))
            suma += w
        if items:
            rid = rezervuvaty(n, suma, {**meta, "pachok": len(items)})
            try:
                job = prov.podaty(n.model, items, effort=c.effort)
            except Nevidomo:
                zakryty(rid, usd=suma, stan="nevidomo")
                raise
            except Exception:
                vidpustyty(rid)
                raise
            zavd.append({"job": job, "rid": rid, "provider": n.provider, "model": n.model,
                         "pachky": dict(vzialy), "podano": _koly()})
            _zapys(teka_p / ZAVDANNIA_API, zavd)
            pidsumok["podano"] = len(items)
            say(f"подано {len(items)} пачок задачею {job} (резерв до ${suma:.4f})")
        if chekaty_s > 0 and zavd:
            kinets = time.monotonic() + chekaty_s
            while zavd and time.monotonic() < kinets:
                spaty(min(30.0, max(1.0, kinets - time.monotonic())))
                zibraty()
    elif rezhym == "zaraz":
        for name in cherha:
            req = json.loads((teka_p / name).read_text(encoding="utf-8"))["request"]
            w = c.naihirshe(req, batch=False)
            try:
                rid = rezervuvaty(n, w, {**meta, "pachka": name})
            except NeVystachaie as exc:
                biudzhet_vycherpano = str(exc)
                break
            try:
                v = prov.zaraz(n.model, req, effort=c.effort)
            except Nevidomo:
                zakryty(rid, usd=w, stan="nevidomo", pachka=name)
                raise
            except Exception:
                vidpustyty(rid)
                raise
            usd = c.usd(v.vkhid, v.vykhid, batch=False) if v.oplacheno else 0.0
            zakryty(rid, usd=usd, stan="faktychno", vkhid=v.vkhid, vykhid=v.vykhid, pachka=name)
            vytrata += usd
            pidsumok["podano"] += 1
            why = _pryiniaty(teka_p, name, v, sproby)
            _zapys(teka_p / SPROBY, sproby)
            if why:
                pidsumok["ne_hodytsia"].append(f"{name}: {why}")
            else:
                pidsumok["pryiniato"] += 1
    if pidsumok["pryiniato"]:
        _model_file(teka_p, n.model)
    pidsumok.update({
        "vytracheno_zaraz_usd": round(vytrata, 6), "zalyshok_usd": round(zalyshok(n), 6),
        "v_roboti": sum(len(z["pachky"]) for z in zavd),
        "bez_vidpovidi": len(NB.bez_vidpovidi(teka_p)),
        "vycherpano_sproby": zvershyly_sproby,
        "biudzhet": biudzhet_vycherpano})
    return pidsumok


def stan() -> dict[str, Any]:
    """Що бачить агент: модель, бюджет, витрачено, лишилось. Ключа — лише чотири останні знаки."""
    n = zavantazhyty()
    if n is None:
        return {"nalashtovano": False,
                "how": "ключ API заводить людина у своєму терміналі: `nysh opys api nalashtuvaty`"}
    rez = _rezervy()
    return {"nalashtovano": n.zghoda_versiia == ZGODA, "provider": n.provider, "model": n.model,
            "biudzhet_usd": n.biudzhet_usd, "vytracheno_usd": round(vytracheno(), 6),
            "rezervy_usd": round(sum(float(r["usd"]) for r in rez.values()), 6),
            "zalyshok_usd": round(zalyshok(n), 6), "kliuch": f"…{n.kliuch_kinets}",
            "mezha_provaidera": n.mezha_provaidera, "zghoda": n.zghoda_koly}


# ── налаштування — лише людина, у терміналі ──────────────────────────────────

#: Що людина має знати до згоди. Нова редакція — нова `ZGODA`.
TEKST_ZGODY = """\
Нормалізація назв ключем API — що це означає:
  • Нишпорка сама надсилатиме провайдерові назви справ опису (публічний текст архівного опису) і
    нічого більше: ні ваших файлів, ні сканів, ні канону.
  • Платите ви, своїм ключем, за цінами провайдера. Нишпорка не перевищить бюджет, який ви зараз
    назвете: перед кожним запитом вона резервує найгіршу можливу ціну.
  • Ключ ляже в сховище паролів системи (не у файл). Нишпорка його ніде не показує, і агент не може
    ні завести ключ, ні підняти бюджет — лише ця команда у вашому терміналі.
  • Чесна межа: програма, що працює від вашого імені (зокрема агент із доступом до оболонки),
    технічно може дістатися сховища паролів. Тому ДУЖЕ раджу окремий ключ лише під Нишпорку з
    межею витрат у самого провайдера — тоді навіть украдений ключ не витратить більше, і його
    відкликають одним кліком:
      Claude — console.anthropic.com → окремий Workspace → Limits (spend limit) → ключ у ньому;
      OpenAI — platform.openai.com → окремий Project → Limits (budget) → ключ у ньому.
"""


def nalashtuvaty_interaktyvno(*, vvid: Callable[[str], str], pryhovano: Callable[[str], str],
                              druk: Callable[[str], None], terminal: bool,
                              perevirka: Callable[[str, str], None] | None = None) -> Nalashtuvannia:
    """Згода, модель, бюджет і ключ — з терміналу людини. Без терміналу — відмова.

    `perevirka(provider, key)` — пробний безоплатний запит (перелік моделей); у тестах підмінюється.
    """
    if not terminal:
        raise ApiError("ключ API, згоду й бюджет заводить лише людина у своєму терміналі: відкрийте "
                       "PowerShell чи Термінал і виконайте `nysh opys api nalashtuvaty`. Агентові "
                       "ця команда недоступна навмисно")
    druk(TEKST_ZGODY)
    druk("Провайдер: 1 — " + PROVIDER_LABEL["anthropic"] + " · 2 — " + PROVIDER_LABEL["openai"])
    vyb = vvid("Номер провайдера [1]: ").strip() or "1"
    prov_name = {"1": "anthropic", "2": "openai"}.get(vyb)
    if prov_name is None:
        raise ApiError("провайдер — 1 або 2")
    modeli = sorted((c for c in ceny().values() if c.provider == prov_name),
                    key=lambda c: (not c.rekomendovano, c.vkhid))
    druk("Модель (ціна 1 000 назв — орієнтовно, за заміром шаблону; межу тримає бюджет):")
    for i, c in enumerate(modeli, 1):
        druk(f"  {i} — {c.model} · {c.riven}{' · радимо' if c.rekomendovano else ''} · "
             f"~${c.na_1000():.2f} за 1 000 назв · {c.zamir}")
    vyb = vvid("Номер моделі [1]: ").strip() or "1"
    if not vyb.isdigit() or not 1 <= int(vyb) <= len(modeli):
        raise ApiError("номер моделі зі списку")
    model = modeli[int(vyb) - 1]
    raw = vvid("Бюджет на нормалізацію, у доларах (наприклад 2): ").strip().replace(",", ".")
    try:
        biudzhet = float(raw)
    except ValueError:
        raise ApiError("бюджет — число в доларах") from None
    if not 0 < biudzhet <= 1000:
        raise ApiError("бюджет — від 0 до 1000 доларів")
    mezha = vvid("Ключ окремий, з межею витрат у провайдера? (так/ні): ").strip().lower() in (
        "так", "т", "yes", "y")
    if not mezha:
        druk("⚠ Без межі в провайдера украдений ключ витрачатиме без обмежень. Можна продовжити, "
             "але раджу спершу зробити окремий ключ із межею.")
    zgoda = vvid("Погоджуєтесь надсилати назви справ провайдерові за свій рахунок у межах бюджету? "
                 "Напишіть «так»: ").strip().lower()
    if zgoda != "так":
        raise ApiError("без згоди нормалізація ключем API не вмикається")
    key = pryhovano(f"Ключ API {PROVIDER_LABEL[prov_name]} (уведення не видно): ").strip()
    if len(key) < 20:
        raise ApiError("це не схоже на ключ API — нічого не збережено")
    (perevirka or (lambda p, k: provider(p, k).perevirka()))(prov_name, key)
    kinets = zberehty_kliuch(prov_name, key)
    del key
    n = Nalashtuvannia(provider=prov_name, model=model.model, biudzhet_usd=biudzhet, zghoda_koly=_koly(),
                       zghoda_versiia=ZGODA, kliuch_kinets=kinets, mezha_provaidera=mezha)
    zberehty(n)
    return n


def vymknuty() -> None:
    """Прибрати ключ зі сховища паролів і налаштування (облік витрат лишається)."""
    n = zavantazhyty()
    for p in PROVIDERS:
        vydalyty_kliuch(p)
    if n is not None:
        _nalashtuvannia_path().unlink(missing_ok=True)
