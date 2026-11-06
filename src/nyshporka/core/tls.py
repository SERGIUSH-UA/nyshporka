"""HTTPS довіряє сертифікатам системи — поверх власного списку `certifi`.

🔴 06.11.2026: у людини кожне пряме заливання в сховище Супряги падало
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` —
8 внесків поспіль, усі пішли запасним шляхом через сервер і без рамок рядків.
Так виглядає програма, що перевіряє HTTPS (антивірус, корпоративний проксі):
вона підставляє свій сертифікат і кладе свій корінь у сховище сертифікатів
Windows. Браузер і `pip` (з 24.2) йому вірять, бо питають систему; Нишпорка —
ні, бо `httpx` звіряв лише зі списком `certifi`, що їде разом із пакетом.

`truststore` вчить модуль `ssl` питати систему (Windows — CryptoAPI, macOS —
Security, Linux — OpenSSL зі шляхами системи). Список `certifi` лишається
запасним: `httpx` і далі вантажить його в той самий контекст, тож не
стане гірше там, де системне сховище бідніше.

⚠ `inject_into_ssl` міняє `ssl.SSLContext` на весь процес, тому кличеться лише
там, де процес — наш: точка входу `nysh` і воркер пачки віддачі. Чужа програма,
що імпортує `nyshporka.*` як бібліотеку, свого `ssl` від нас не дістає.
"""
from __future__ import annotations

import os

#: Вимикач: `0` — лише `certifi`, як було досі. Для діагностики, коли
#: системне сховище само зламане.
ENV = "NYSHPORKA_SYSTEM_CERTS"


def use_system_trust() -> bool:
    """Увімкнути довіру сертифікатам системи для цього процесу. `True` — увімкнено."""
    if os.environ.get(ENV, "").strip() == "0":
        return False
    try:
        import truststore
    except ImportError:         # стара установка без залежності — як було
        return False
    truststore.inject_into_ssl()
    return True
