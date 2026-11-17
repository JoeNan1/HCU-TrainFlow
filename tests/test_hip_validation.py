"""CPU checks for hardware admission and truthful HIP measurement conversion."""
import importlib.util
import json
from pathlib import Path

import pytest

from hcu_trainflow.core import FlowError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('validate_hip_runtime', ROOT / 'scripts/validate_hip_runtime.py')
hip = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hip)


def discovery(tmp_path, *, use=0, mem=100, processes='No KFD PIDs currently running!', stderr='', rc=0):
    data = {'card0': {'HCU use (%)': str(use), 'vram Total Used Memory (MiB)': str(mem),
                      'PCI Bus': '0000:a0:00.0 --> SN: example'}}
    snapshot = tmp_path / 'observation.json'
    snapshot.write_text(json.dumps(data))
    stdout_path, stderr_path = tmp_path / 'pids.stdout', tmp_path / 'pids.stderr'
    stdout_path.write_text(processes)
    stderr_path.write_text(stderr)
    return {'observation': {'returncode': 0, 'stdout': {'path': str(snapshot)}},
            'processes': {'returncode': rc, 'stdout': {'path': str(stdout_path)},
                          'stderr': {'path': str(stderr_path)}}}


def expectation():
    return {'identity': '0000:a0:00.0', 'max_utilization_pct': 0,
            'idle_memory_bytes': 100 * 2**20, 'memory_tolerance_bytes': 0}


def test_fresh_idle_requires_complete_device_and_process_scope(tmp_path):
    assert hip.fresh_device_check(discovery(tmp_path), 0, expectation()) == []
    assert 'device-observation-incomplete' in hip.fresh_device_check(discovery(tmp_path), 1, expectation())


@pytest.mark.parametrize('kwargs,reason', [
    ({'use': 40}, 'device-active'),
    ({'mem': 1000}, 'memory-above-idle-envelope'),
    ({'stderr': 'Unable to open process directory'}, 'process-coverage-unknown'),
    ({'processes': 'PID 1234'}, 'system-processes-present-or-unknown'),
    ({'processes': ''}, 'system-processes-present-or-unknown'),
    ({'rc': 1}, 'process-coverage-unknown'),
    ({'use': 'nan'}, 'device-observation-incomplete'),
])
def test_busy_or_unknown_cannot_be_admitted(tmp_path, kwargs, reason):
    assert reason in hip.fresh_device_check(discovery(tmp_path, **kwargs), 0, expectation())


def test_hip_records_preserve_kernel_scope_and_declared_protocol():
    contract = json.loads((ROOT / 'examples/hip-runtime/contract.json').read_text())
    raw = {'executed': 24, 'failures': 0, 'baseline_times': [1, 1, 1], 'candidate_times': [2, 2, 2]}
    record = hip.make_record(raw, 'ctx', ['retained-evidence'], contract)
    assert record['status'] == 'pass'
    assert record['profiler_off'] is True
    assert 'loss' not in record
    result = hip.assess_iteration(record, raw['baseline_times'], raw['candidate_times'], 'ctx')
    assert result['status'] == 'rejected'
    assert contract['measurement_protocol']['max_regression'] == 0


@pytest.mark.parametrize('change', [
    {'executed': 23}, {'executed': True}, {'failures': None},
    {'baseline_times': [1, 2]}, {'candidate_times': [1, float('nan'), 1]},
])
def test_partial_or_invalid_hardware_measurements_are_not_records(change):
    raw = {'executed': 24, 'failures': 0, 'baseline_times': [1, 1, 1], 'candidate_times': [1, 1, 1], **change}
    with pytest.raises(FlowError):
        hip.make_record(raw, 'ctx', ['evidence'], {'measurement_protocol': {}})


def test_execution_requires_admission_and_lease_before_creating_output(tmp_path):
    output = tmp_path / 'must-not-exist'
    with pytest.raises(SystemExit):
        hip.main(['--arch', 'gfx936', '--output', str(output), '--execute'])
    assert not output.exists()


def test_profile_requires_explicit_admitted_execution(tmp_path):
    output = tmp_path / 'must-not-exist'
    with pytest.raises(SystemExit):
        hip.main(['--arch', 'gfx936', '--output', str(output), '--profile'])
    assert not output.exists()
