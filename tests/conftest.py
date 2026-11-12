"""Make the Checkmk API importable so this plugin's tests can run at all.

A Checkmk plugin imports `cmk.agent_based`, `cmk.graphing`, `cmk.rulesets` and
`cmk.server_side_calls`. None of them exist outside a Checkmk installation, so
without this file there is nothing to run pytest against.

The API comes from Checkmk itself, pinned to the version this plugin targets,
rather than from hand-written stubs. A stub only ever catches the API calls
somebody remembered to model. The real thing catches every one -- and raising
CMK_VERSION below is how you find out what a Checkmk upgrade breaks, before a
user does.

The four API packages are namespace packages, so putting their directories on
sys.path is enough; nothing is installed. This plugin has no bakery
part, so it needs no stub at all. Should one be added, copy `cmk_stubs/` from
the checkmk-plugin skill and keep it a namespace package (no `cmk/__init__.py`).
"""

import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

# The Checkmk release tag the tests run against, the same release as
# version.packaged in .mkp-builder.ini. A tag, not a branch: a branch moves,
# and the test results would change without a commit here. Raise it to find
# out what breaks.
CMK_VERSION = "v2.3.0p52"

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CACHE = ROOT / ".cmk-api" / CMK_VERSION
API_PACKAGES = ("cmk-agent-based", "cmk-graphing", "cmk-rulesets", "cmk-server-side-calls")


def _fetch_cmk_api(target):
    """A blobless sparse clone of just the API packages: ~7 MB, a second or two.

    Deliberately not `pip install "... @ git+https://...#subdirectory=..."`.
    That clones the whole Checkmk repository including a submodule the public
    cannot read, takes over a minute, and then fails.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse",
             "-b", CMK_VERSION, "https://github.com/Checkmk/checkmk.git", str(staging)],
            check=True)
        subprocess.run(
            ["git", "-C", str(staging), "sparse-checkout", "set",
             *(f"packages/{p}" for p in API_PACKAGES)],
            check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(
            f"could not fetch the Checkmk {CMK_VERSION} API from GitHub: {exc}\n"
            "The tests import cmk.* and cannot run without it. Check network access, "
            "or that CMK_VERSION in tests/conftest.py names a real Checkmk tag."
        ) from exc
    # Rename last, so an interrupted clone never leaves a half-populated cache
    # that later runs would treat as good.
    staging.rename(target)


if not CACHE.is_dir():
    _fetch_cmk_api(CACHE)

for package in API_PACKAGES:
    sys.path.insert(0, str(CACHE / "packages" / package))

# Helper modules under a plugin's libexec/ import each other by bare name --
# that is how Checkmk ships and runs them -- so every libexec directory goes on
# the path too. Without this, a plugin that splits its agent across several
# files cannot be imported at all.
for libexec in sorted(ROOT.glob("local/lib/python3/**/libexec")):
    if libexec.is_dir():
        sys.path.insert(0, str(libexec))

PLUGIN = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_pbs"


def load_module(relpath, name):
    """Load a plugin .py file by path, under a name of the test's choosing."""
    path = PLUGIN / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Dataclasses resolve deferred annotations through sys.modules.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def load():
    return load_module
