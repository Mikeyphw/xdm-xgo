"""X01 source-only contract: no Devtool, Gradle, network or device required."""
from __future__ import annotations

from pathlib import Path
import sys
import tomllib


def validate(root: Path) -> None:
    data = tomllib.loads((root / '.devtool.toml').read_text(encoding='utf-8'))
    targets = data['targets']
    assert len(targets) == 43, f'X01 expected 43 target identities; got {len(targets)}'
    for name, target in targets.items():
        assert target.get('affected_ownership') == 'inputs-only', name
        assert target.get('inputs'), name
        assert 'affected_ownership' not in target.get('metadata', {}), name
    script = (root / 'scripts/devtool_phase02_audit.py').read_text(encoding='utf-8')
    assert 'load_wrapper_project_config' in script
    assert 'analyze_affected_targets' in script
    assert "'unknown_file': 'workspace-wide'" in script
    workflow = (root / '.github/workflows/android.yml').read_text(encoding='utf-8')
    pinned_action = 'android-actions/setup-android@be39fa834029ff78f1a44aa3bb0819b8fc2bd8fd'
    # HF11: HF10 provisions SDK tools separately in validate, instrumentation,
    # and signed-release. Validate each job, not the obsolete total of two.
    import re
    for name in ("validate", "instrumentation", "signed-release"):
        match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z][\w-]*:\n|\Z)", workflow)
        assert match is not None, f"missing {name} Android job"
        job = match.group(1)
        assert job.count(pinned_action) == 1, f"{name} pinned Android setup action drift"
        assert "packages: 'platform-tools'" in job, f"{name} platform-tools provisioning drift"
    assert "startsWith(github.ref, 'refs/tags/android-v')" in workflow
    assert "inputs.signed_release" in workflow
    assert "github.event_name == 'workflow_dispatch' || startsWith" not in workflow
    go = (root / '.github/workflows/devtool-xgo-engine.yml').read_text(encoding='utf-8')
    assert go.count('python3 scripts/devtool_phase02_source_contract.py') == 1
    for path in ('tools/xgo/**', 'go.work', 'scripts/devtool_phase02_source_contract.py'):
        assert path in go


if __name__ == '__main__':
    try:
        validate(Path(__file__).resolve().parents[1])
    except (AssertionError, OSError, ValueError, KeyError) as exc:
        print(f'XDM_X01_SOURCE_REFUSED: {exc}', file=sys.stderr)
        raise SystemExit(2)
    print('XDM_X01_SOURCE_CONTRACT_PASS')
