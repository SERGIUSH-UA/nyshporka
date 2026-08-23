"""`python -m nyshporka` — той самий вхід, що `nysh`.

Потрібен там, де бінарника в PATH може не бути: підпроцес чужого
застосунку знає свій `sys.executable`, а де лежить `nysh.exe` — ні.
"""
from nyshporka.cli import app

if __name__ == "__main__":
    app()
