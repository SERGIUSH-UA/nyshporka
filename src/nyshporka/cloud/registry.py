"""🗂 Реєстр бекендів: вбудований SSH + сторонні через entry points.

Способів дістати чужу машину більше, ніж ми колись реалізуємо, і кожен тягне
свій SDK, свій акаунт і свою тарифікацію. Тому бекенд — плагін: сторонній
пакет оголошує групу `nyshporka.cloud` у своїх entry points, і його спосіб
оренди з'являється в застосунку без жодної правки тут.

🔴 Один бекенд у коробці все-таки є, і це не поступка симетрії. Реєстр, у
якому без стороннього пакета порожньо, робить `nysh cloud` обіцянкою без входу
— тим самим класом вад, проти якого написано `test_no_dead_ends`. Вбудований
`ssh` не орендує нічого: він працює з машиною, яку людина ВЖЕ має (свій
сервер, робоча станція в іншій кімнаті, вже орендований бокс), і саме тому не
потребує ані акаунта, ані ключа API, ані згоди провайдера.

🔴 Збій одного плагіна не гасить решту — дослівно з тієї ж причини, що й у
реєстрі джерел: чужий недописаний пакет інакше забирав би з собою SSH, тобто
головний шлях користувача.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from nyshporka.cloud.base import Capability, CloudBackend, supports

ENTRY_POINT_GROUP = "nyshporka.cloud"


@dataclass
class Registry:
    backends: dict[str, CloudBackend] = field(default_factory=dict)
    #: Плагіни, які не завантажились: (ім'я, причина). Ховати їх не можна —
    #: «мого способу немає в списку» інакше не має пояснення.
    broken: list[tuple[str, str]] = field(default_factory=list)

    def get(self, backend_id: str) -> CloudBackend | None:
        return self.backends.get(backend_id)

    def all(self) -> list[CloudBackend]:
        return [self.backends[k] for k in sorted(self.backends)]

    def with_cap(self, cap: Capability) -> list[CloudBackend]:
        return [b for b in self.all() if supports(b, cap)]


def _builtin() -> list[CloudBackend]:
    from nyshporka.cloud.ssh import SshBackend

    return [SshBackend()]


def _from_entry_points() -> tuple[list[CloudBackend], list[tuple[str, str]]]:
    out: list[CloudBackend] = []
    broken: list[tuple[str, str]] = []
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover — Python без importlib.metadata
        return out, broken
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:
        return out, [("<entry_points>", f"{type(exc).__name__}: {exc}")]
    for ep in eps:
        try:
            factory = ep.load()
            backend = factory() if callable(factory) else factory
            if not getattr(backend, "id", ""):
                raise ValueError("бекенд не має `id`")
            # 🔴 Перевіряємо форму ОДРАЗУ, а не при першому виклику. Плагін без
            # `release` виявився б інакше в найгіршу мить — коли машина вже
            # орендована й тарифікується, а звільнити її нічим.
            missing = [m for m in ("acquire", "connect", "release", "find")
                       if not callable(getattr(backend, m, None))]
            if missing:
                raise TypeError(f"немає методів: {', '.join(missing)}")
            out.append(backend)
        except Exception as exc:
            broken.append((ep.name, f"{type(exc).__name__}: {exc}"))
    return out, broken


def load() -> Registry:
    """Зібрати реєстр. Вбудований бекенд плагінами не перекривається.

    Плагін із тим самим `id` відкидається, а не заміщає вбудований: інакше
    сторонній пакет міг би мовчки підмінити SSH — шлях, яким людина працює зі
    своєю ж машиною.
    """
    reg = Registry()
    for backend in _builtin():
        reg.backends[backend.id] = backend
    plugins, broken = _from_entry_points()
    reg.broken.extend(broken)
    for backend in plugins:
        if backend.id in reg.backends:
            reg.broken.append(
                (backend.id, "збігається з іменем вбудованого бекенда"))
            continue
        reg.backends[backend.id] = backend
    return reg
