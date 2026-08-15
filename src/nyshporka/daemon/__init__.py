"""Браузерне обличчя. Живе в extras `app` — без нього застосунок повний."""
from nyshporka.daemon.app import DEFAULT_HOST, DEFAULT_PORT, create_app, serve

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "create_app", "serve"]
