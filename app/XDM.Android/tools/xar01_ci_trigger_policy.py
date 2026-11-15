#!/usr/bin/env python3
"""XAR01 S01-11: strict release-tag/manual Android workflow event policy.

Pure source guard. Not a release grant, no GitHub write, no Git/Gradle/device action.
The old paths-based guard was superseded by manual dispatch and release tags.
"""
from __future__ import annotations
import re

SIGNED_IF = ("startsWith(github.ref, 'refs/tags/android-v') && "
             "(github.event_name == 'push' || "
             "(github.event_name == 'workflow_dispatch' && inputs.signed_release))")
INPUTS = ('arm64_translation_diagnostic', 'signed_release', 'x86_64_native_test')


def audit_android_triggers(workflow: str) -> list[str]:
    errors: list[str] = []
    def need(condition: bool, code: str) -> None:
        if not condition:
            errors.append('S01-11_' + code)
    # YAML's top-level `on` is a mapping, not an incidental comment or job text.
    heads = re.findall(r'(?m)^([A-Za-z][A-Za-z0-9_-]*):\s*$', workflow)
    need(heads.count('on') == 1 and heads.count('permissions') == 1,
         'TOP_LEVEL_TRIGGER_OR_PERMISSIONS_INVENTORY')
    if heads.count('on') != 1 or heads.count('permissions') != 1:
        return errors
    before, sep, after = workflow.partition('\non:\n')
    if not sep:
        need(False, 'ON_MAPPING_MISSING')
        return errors
    events, sep, rest = after.partition('\npermissions:\n')
    if not sep or '\non:\n' in rest:
        need(False, 'EVENT_SECTION_BOUNDARY')
        return errors
    event_names = re.findall(r'(?m)^  ([a-z_]+):\s*$', events)
    need(event_names == ['push', 'workflow_dispatch'], 'ONLY_TAG_PUSH_AND_MANUAL')
    push_match = re.search(r'(?ms)^  push:\n(.*?)(?=^  [a-z_]+:\s*$|\Z)', events)
    need(push_match is not None and push_match.group(1).strip() == "tags: ['android-v*']",
         'TAG_PUSH_EXACT_ONLY')
    dispatch = re.search(r'(?ms)^  workflow_dispatch:\n(.*?)(?=^  [a-z_]+:\s*$|\Z)', events)
    if dispatch is None:
        need(False, 'MANUAL_INPUTS_MISSING')
    else:
        body = dispatch.group(1)
        names = re.findall(r'(?m)^      ([a-z0-9_]+):\s*$', body)
        need(names == list(INPUTS), 'EXPLICIT_INPUT_INVENTORY')
        for name in INPUTS:
            match = re.search(r'(?ms)^      '+re.escape(name)+r':\n(.*?)(?=^      [a-z0-9_]+:\s*$|\Z)', body)
            fields = dict(re.findall(r'(?m)^        (required|type|default):\s*([^\s#]+)\s*$',
                                     match.group(1))) if match else {}
            need(fields == {'required': 'false', 'type': 'boolean', 'default': 'false'},
                 'INPUT_DEFAULT_OFF_'+name.upper())
    # Keep the tag+explicit-signed-release gate in the *actual* signed-release job.
    section = re.search(r'(?ms)^  signed-release:\n(.*?)(?=^  [A-Za-z][A-Za-z0-9_-]*:\s*$|\Z)', workflow)
    if section is None:
        need(False, 'SIGNED_JOB_MISSING')
    else:
        job = section.group(1)
        conditions = re.findall(r'(?m)^    if:\s*(.+?)\s*$', job)
        need(conditions == [SIGNED_IF], 'SIGNED_TAG_AND_OPT_IN_GUARD')
        need('continue-on-error: true' not in job and '|| true' not in job,
             'SIGNED_FAILURE_SUPPRESSION')
        need('XDM_XAR16_FULL_RELEASE_GATE: "1"' in job and
             'XDM_RELEASE_SIGNER_SHA256:' in job, 'SIGNED_PROVENANCE_GUARD')
    # Manual debug builds must stay separate from signed publication.
    need('name: xdm-android-physical-arm64-apk-pair' in workflow and
         'python3 -B scripts/xgo_hf16_apk_pair.py' in workflow,
         'UNSIGNED_APK_PAIR_RECIPE')
    need('  validate:\n    needs: hotfix-fast' in workflow,
         'DEBUG_BUILD_REQUIRES_PREFLIGHT')
    return errors
