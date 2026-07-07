import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUBS = Path(__file__).resolve().parent / "cmk_stubs"
PLUGIN = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_pbs"

# Offline cmk stubs must precede any real cmk on the path.
sys.path.insert(0, str(STUBS))
# libexec helper modules import each other by bare name.
sys.path.insert(0, str(PLUGIN / "libexec"))


def load_module(relpath: str, name: str):
    """Load a plugin .py file by path with cmk stubs already on sys.path."""
    path = PLUGIN / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # required for dataclasses to resolve deferred annotations
    spec.loader.exec_module(mod)
    return mod


import pytest


@pytest.fixture
def load():
    return load_module
