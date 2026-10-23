"""Прогрів `nysh serve`: лише операції, що читають, з аргументами, які приймає схема."""
from __future__ import annotations

from nyshporka import ops as O
from nyshporka.core.ops import _only_shows
from nyshporka.daemon.app import WARM_OPS


def test_warm_up_only_reads_and_sends_valid_args() -> None:
    """Прогрів не сміє бити пульс: інакше кожен старт оголошував би дані зміненими."""
    for name, args in WARM_OPS:
        op = O.get(name)
        assert op is not None, name
        parsed = op.args(**args) if op.args is not None else None
        assert not op.mutates or _only_shows(parsed), f"{name} пише — не для прогріву"
        if op.args is not None:
            assert set(args) <= set(op.args.model_fields), f"{name}: зайві поля {set(args)}"
