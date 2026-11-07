"""The release version stamps that Create release PR maintains."""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_pbs/agent_based/oposs_pbs.py"


def _released_version():
    """The newest released heading of CHANGES.md, the version the publish
    check expects in every version_files target between releases."""
    return re.search(r"^## (\d+\.\d+\.\d+)", (ROOT / "CHANGES.md").read_text(),
                     flags=re.MULTILINE).group(1)


def _spec(path):
    config = json.loads((ROOT / ".github/repo-infra.json").read_text())
    (spec,) = [f for f in config["version_files"] if (ROOT / f["path"]) == path]
    return spec


def _stamp(spec, text, version):
    stamped = re.sub(spec["pattern"], spec["replacement"].replace("$VERSION", version),
                     text, count=1, flags=re.MULTILINE)
    assert re.search(spec["verify"].replace("$VERSION", re.escape(version)), stamped,
                     flags=re.MULTILINE)
    return stamped


def test_check_carries_the_released_version():
    # The publish check fails on main when a version file disagrees with
    # the newest released CHANGES.md heading.
    assert re.search(rf'^__version__ = "{re.escape(_released_version())}"$',
                     CHECK.read_text(), flags=re.MULTILINE)


def test_release_writes_version_into_check(tmp_path):
    """Apply the version_files entry of .github/repo-infra.json to the check
    module, as Create release PR does (a multiline regex, first match)"""
    copy = tmp_path / "stamped_check.py"
    copy.write_text(_stamp(_spec(CHECK), CHECK.read_text(), "9.8.7"))
    module_spec = importlib.util.spec_from_file_location("stamped_check", copy)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    assert module.__version__ == "9.8.7"


AGENT = ROOT / "local/lib/python3/cmk_addons/plugins/oposs_pbs/libexec/agent_oposs_pbs"


def test_agent_carries_the_released_version():
    assert re.search(rf'^__version__ = "{re.escape(_released_version())}"$',
                     AGENT.read_text(), flags=re.MULTILINE)


def test_release_writes_version_into_agent(tmp_path):
    """The special agent has no .py suffix and imports its libexec helpers,
    which conftest.py puts on sys.path."""
    from importlib.machinery import SourceFileLoader
    copy = tmp_path / "agent_oposs_pbs"
    copy.write_text(_stamp(_spec(AGENT), AGENT.read_text(), "9.8.7"))
    loader = SourceFileLoader("stamped_agent", str(copy))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    assert module.__version__ == "9.8.7"


def test_agent_is_executable_in_git():
    # Checkmk runs the special agent as a program; without the executable
    # bit it fails with "Permission denied". The MKP build takes the mode
    # from git.
    out = subprocess.run(["git", "ls-files", "-s", AGENT.name], cwd=AGENT.parent,
                         capture_output=True, text=True, check=True).stdout
    assert out.split()[0] == "100755"
