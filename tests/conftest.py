"""Shared fixtures."""

from __future__ import annotations

import pytest
from helpers import CJK_FONT

from cardsmith import fonts, settings
from cardsmith.model import Printer


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    """Keep tests away from the developer's saved printer profiles."""
    d = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(d))
    monkeypatch.setattr(settings, "config_dir", lambda: d)


@pytest.fixture(scope="session")
def cjk_face():
    f = fonts.try_face(CJK_FONT)
    if f is None:
        pytest.skip(f"{CJK_FONT} not installed (apt install fonts-noto-cjk)")
    return f


@pytest.fixture
def printer() -> Printer:
    return Printer()
