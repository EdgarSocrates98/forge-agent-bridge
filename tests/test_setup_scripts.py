"""cycle-16.1.1 wave-07c — `setup.sh` e paridade do kit UI vendored.

O defect do probe de python (vendored do kit canônico) saía `rc=1` em
silêncio sob `set -e` antes de `FORGE-PYTHON-NOT-FOUND`. Os três
arquivos `ui/{kit,i18n,wizard}.py` estavam derivados do canônico —
drift invisível ao gate do the-forge (bridge fora de KIT_PARITY_REPOS).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("bash"), reason="bash indisponivel")
def test_setup_sh_python_ausente_recusa_nomeada(tmp_path):
    bash = shutil.which("bash")
    assert bash is not None
    stub = tmp_path / "stubbin"
    stub.mkdir()
    real_dirname = shutil.which("dirname")
    if real_dirname:
        (stub / "dirname").symlink_to(real_dirname)
    out = subprocess.run(
        [bash, "setup.sh"],
        cwd=ROOT,
        env={"PATH": str(stub), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 2
    assert "FORGE-PYTHON-NOT-FOUND" in out.stderr


def test_vendored_ui_kit_parity_canonical():
    canonical_dir = ROOT.parent / "the-forge" / "src" / "theforge" / "ui"
    if not canonical_dir.is_dir():
        pytest.skip("sibling the-forge checkout ausente")
    for fname in ("kit.py", "i18n.py", "wizard.py"):
        expected = (canonical_dir / fname).read_text(encoding="utf-8").replace(
            "theforge.ui", "forge_agent_bridge.ui"
        )
        vendored = (ROOT / "src" / "forge_agent_bridge" / "ui" / fname).read_text(
            encoding="utf-8"
        )
        assert vendored == expected, f"ui/{fname} drifted from canonical"
