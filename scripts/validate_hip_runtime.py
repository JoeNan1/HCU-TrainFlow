#!/usr/bin/env python3
"""Compile a bounded HIP smoke and execute only with fresh admission and a caller lease.

Default operation compiles and records read-only device discovery. Execution needs
an occupancy contract/observations, their retained evidence in --workspace, and a
lease owned by the caller. All outputs are retained in a new private --output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hcu_trainflow.admission import assess_occupancy
from hcu_trainflow.core import FlowError, Store, read_json, utc, write_json
from hcu_trainflow.quality import assess_iteration


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_command(argv, output, label, *, timeout=30, env=None):
    """Keep complete logs; local timeout kills the private child process group."""
    row = {'argv': list(map(str, argv)), 'started_at': utc(), 'timeout': timeout}
    started = time.monotonic()
    with (output / (label + '.stdout')).open('wb') as stdout, (output / (label + '.stderr')).open('wb') as stderr:
        try:
            proc = subprocess.Popen(argv, cwd=output, env=env, stdout=stdout, stderr=stderr,
                                    start_new_session=True)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                row['error'] = 'timeout; private local process group killed, direct child reaped'
            row['returncode'] = proc.returncode
        except OSError as exc:
            row.update(returncode=None, error=type(exc).__name__ + ': ' + str(exc))
    row['elapsed_seconds'] = time.monotonic() - started
    row['finished_at'] = utc()
    for stream in ('stdout', 'stderr'):
        path = output / (label + '.' + stream)
        row[stream] = {'path': str(path), 'sha256': sha(path)}
    write_json(output / (label + '.command.json'), row)
    return row


def discover(output, smi, label='discovery'):
    observation = run_command([smi, '--showuse', '--showmeminfo', 'vram', '--showbus', '--json'],
                              output, label, timeout=10)
    processes = run_command([smi, '--showpids'], output, label + '-pids', timeout=10)
    return {'observation': observation, 'processes': processes}


def fresh_device_check(discovery, device, expectation):
    """Conservative parser: unsupported/mixed/error output is never idle evidence."""
    reasons = []
    query = discovery['observation']
    procs = discovery['processes']
    if query['returncode'] != 0:
        reasons.append('device-query-failed')
    try:
        body = json.loads(Path(query['stdout']['path']).read_text())
        selected = body['card' + str(device)]
        utilization = float(selected['HCU use (%)'])
        memory = float(selected['vram Total Used Memory (MiB)']) * 2**20
        identity = selected['PCI Bus'].split(' --> ')[0].strip()
        if not math.isfinite(utilization) or not 0 <= utilization <= 100 or not math.isfinite(memory) or memory < 0:
            raise ValueError('invalid measured values')
        if utilization > expectation['max_utilization_pct']:
            reasons.append('device-active')
        if memory > expectation['idle_memory_bytes'] + expectation['memory_tolerance_bytes']:
            reasons.append('memory-above-idle-envelope')
        if identity != expectation['identity']:
            reasons.append('device-identity-mismatch')
    except (ValueError, KeyError, TypeError):
        reasons.append('device-observation-incomplete')
    process_text = '\n'.join(Path(procs[s]['path']).read_text(errors='replace') for s in ('stdout', 'stderr'))
    process_text = re.sub(r'\x1b\[[0-9;]*m', '', process_text)
    if procs['returncode'] != 0 or re.search(r'\b(error|failed|unable)\b', process_text, re.I):
        reasons.append('process-coverage-unknown')
    elif 'No KFD PIDs currently running!' not in process_text:
        # Any active system KFD process blocks this small smoke, even on another card.
        reasons.append('system-processes-present-or-unknown')
    return reasons


def make_record(raw, context, evidence, contract):
    if not isinstance(raw, dict) or type(raw.get('executed')) is not int or raw['executed'] != 24:
        raise FlowError('Expected every frozen HIP correctness case to execute')
    if type(raw.get('failures')) is not int or raw['failures'] < 0:
        raise FlowError('HIP correctness failure count is missing')
    for name in ('baseline_times', 'candidate_times'):
        values = raw.get(name)
        if not isinstance(values, list) or len(values) != 3 or any(
            type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in values
        ):
            raise FlowError('Expected three finite positive profiler-off timing pairs')
    return {'context': context, 'status': 'fail' if raw['failures'] else 'pass',
            'executed': raw['executed'], 'failures': raw['failures'],
            'candidate_path_exercised': True, 'profiler_off': True,
            'measurement_protocol': contract['measurement_protocol'], 'evidence': evidence,
            'limits': 'HIP correctness and local kernel timings; no training loss evidence'}


def discovery_blockers(discovery):
    reasons = []
    try:
        query = discovery['observation']
        data = json.loads(Path(query['stdout']['path']).read_text())
        usage = [float(row['HCU use (%)']) for key, row in data.items() if key.startswith('card')]
        if query['returncode'] != 0 or not usage or any(not math.isfinite(x) for x in usage):
            reasons.append('device-coverage-unknown')
        elif all(x > 0 for x in usage):
            reasons.append('all-observed-devices-active')
    except (ValueError, TypeError, KeyError):
        reasons.append('device-coverage-unknown')
    process = discovery['processes']
    text = '\n'.join(Path(process[s]['path']).read_text(errors='replace') for s in ('stdout', 'stderr'))
    if process['returncode'] != 0 or re.search(r'\b(error|failed|unable)\b', text, re.I):
        reasons.append('process-coverage-unknown')
    return reasons


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New task-private output directory')
    parser.add_argument('--hipcc', default=shutil.which('hipcc') or '/opt/dtk/bin/hipcc')
    parser.add_argument('--smi', default=shutil.which('hy-smi') or '/opt/hyhal/bin/hy-smi')
    parser.add_argument('--arch', required=True, help='Actual sysfs/tool-confirmed gfx target')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--device', type=int)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--admission-contract', type=Path)
    parser.add_argument('--admission-observations', type=Path)
    parser.add_argument('--lease', type=Path)
    parser.add_argument('--profile', action='store_true', help='Separate bounded hipprof run after profiler-off measurements')
    parser.add_argument('--hipprof', default=shutil.which('hipprof') or '/opt/dtk/bin/hipprof')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'gfx[0-9a-f]+', args.arch):
        parser.error('--arch must be a confirmed gfx target')
    if args.execute and (args.device is None or args.device < 0 or any(x is None for x in (
            args.workspace, args.admission_contract, args.admission_observations, args.lease))):
        parser.error('--execute requires device, workspace, admission inputs and lease')
    if args.profile and not args.execute:
        parser.error('--profile requires --execute and admission')
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error('--output must be new; preserve prior evidence')
    output.mkdir(parents=True)
    output = output.resolve()
    env = dict(os.environ, TMPDIR=str(output / 'tmp'), XDG_CACHE_HOME=str(output / 'cache'))
    (output / 'tmp').mkdir()
    (output / 'cache').mkdir()
    source = ROOT / 'examples/hip-runtime/axpy.hip'
    contract_path = ROOT / 'examples/hip-runtime/contract.json'
    shutil.copyfile(source, output / source.name)
    shutil.copyfile(contract_path, output / 'contract.json')
    contract = read_json(output / 'contract.json')
    result = {'schema_version': 1, 'status': 'incomplete', 'hardware_status': 'not-executed',
              'training_status': 'not-validated', 'output': str(output), 'started_at': utc(),
              'source_sha256': sha(output / source.name), 'contract_sha256': sha(output / 'contract.json'),
              'runner_sha256': sha(__file__), 'arch': args.arch}
    result['compiler'] = run_command([args.hipcc, '--version'], output, 'compiler-version', env=env)
    result['discovery'] = discover(output, args.smi)
    result['discovery_blockers'] = discovery_blockers(result['discovery'])
    binary = output / 'axpy'
    result['compile'] = run_command([args.hipcc, '-O2', '--offload-arch=' + args.arch,
                                     str(output / source.name), '-o', str(binary)],
                                    output, 'compile', timeout=120, env=env)
    if result['compile']['returncode'] != 0:
        result['status'] = 'fail'
        result['reason'] = 'compile-failed'
    elif not args.execute:
        result['compile']['binary_sha256'] = sha(binary)
        result['reason'] = 'compile-only; hardware execution requires fresh admission and caller lease'
        if result['discovery_blockers']:
            result.update(hardware_status='blocked', reason='; '.join(result['discovery_blockers']))
    else:
        try:
            store = Store(args.workspace)
            admission_contract = read_json(args.admission_contract)
            observations = read_json(args.admission_observations)
            admission = assess_occupancy(admission_contract, observations)
            result['admission'] = admission
            if admission['status'] != 'observed-idle':
                raise FlowError('Fresh occupancy admission did not pass')
            # The common checker validates hash syntax; this boundary verifies retained bytes.
            for evidence in admission['evidence']:
                store.artifact(evidence)
            expected = [d for d in admission_contract['devices'] if str(d['device']) == str(args.device)]
            if len(expected) != 1:
                raise FlowError('Select one unambiguous admitted device')
            if expected[0]['node'] != socket.gethostname():
                raise FlowError('Local smoke admission node must match socket.gethostname()')
            if any(env.get(k) for k in ('ROCR_VISIBLE_DEVICES', 'CUDA_VISIBLE_DEVICES')):
                raise FlowError('Existing device masks need an explicit verified physical mapping')
            lease = read_json(args.lease)
            resource = 'hcu:' + expected[0]['node'] + ':' + expected[0]['identity']
            if lease.get('resource') != resource:
                raise FlowError('Lease must cover ' + resource)
            with store.db() as db:
                store.check_lease(db, resource, lease['owner'], lease['token'])
            result['fresh_discovery'] = discover(output, args.smi, 'fresh-discovery')
            reasons = fresh_device_check(result['fresh_discovery'], args.device, expected[0])
            if reasons:
                raise FlowError('Fresh device check blocked: ' + ', '.join(reasons))
            # Compilation and discovery may have consumed the observation freshness window.
            if assess_occupancy(admission_contract, observations)['status'] != 'observed-idle':
                raise FlowError('Occupancy expired before launch; recollect evidence')
            with store.db() as db:
                store.check_lease(db, resource, lease['owner'], lease['token'])
            env['HIP_VISIBLE_DEVICES'] = str(args.device)
            result['execution_environment'] = {'HIP_VISIBLE_DEVICES': str(args.device),
                'TMPDIR': env['TMPDIR'], 'XDG_CACHE_HOME': env['XDG_CACHE_HOME'],
                'visibility': 'single physical device selected after matching PCI identity'}
            run = run_command([str(binary)], output, 'device-run', timeout=60, env=env)
            result['device_run'] = run
            if run['returncode'] != 0:
                result.update(status='fail', hardware_status='failed', reason='device-run-failed')
            else:
                raw = json.loads((output / 'device-run.stdout').read_text())
                evidence = [store.put((output / name).read_bytes()) for name in (
                    'device-run.stdout', 'device-run.stderr', 'device-run.command.json',
                    'compile.command.json', 'compiler-version.stdout', 'contract.json', source.name, 'axpy')]
                correctness = make_record(raw, admission_contract['context'], evidence, contract)
                result.update(hardware_status='pass', status='complete', correctness=correctness,
                              baseline_times=raw['baseline_times'], candidate_times=raw['candidate_times'])
                result['iteration'] = assess_iteration(correctness, raw['baseline_times'], raw['candidate_times'],
                    admission_contract['context'], contract['measurement_protocol']['max_regression'])
                if args.profile:
                    remaining = 60 - run['elapsed_seconds']
                    if remaining < 1:
                        result['profile'] = {'status': 'incomplete', 'reason': 'device budget consumed'}
                    else:
                        result['profile_discovery'] = discover(output, args.smi, 'profile-discovery')
                        reasons = fresh_device_check(result['profile_discovery'], args.device, expected[0])
                        if reasons or assess_occupancy(admission_contract, observations)['status'] != 'observed-idle':
                            raise FlowError('Profile needs fresh idle admission: ' + ', '.join(reasons))
                        with store.db() as db:
                            store.check_lease(db, resource, lease['owner'], lease['token'])
                        profile_dir = output / 'profile'
                        profile_dir.mkdir()
                        profile_tmp = profile_dir / 'tmp'
                        profile_tmp.mkdir()
                        profile = run_command([args.hipprof, '--hip-trace', '--output-type', '0',
                            '-d', str(profile_tmp), '-o', str(profile_dir / 'trace'), str(binary)],
                            output, 'profile-run', timeout=remaining, env=env)
                        profile['json_files'] = [dict(path=str(p), sha256=sha(p)) for p in profile_dir.rglob('*.json')]
                        profile['status'] = 'complete' if profile['returncode'] == 0 and profile['json_files'] else 'incomplete'
                        profile['limits'] = 'HIP trace only; CPU framework operator attribution requires separate evidence'
                        result['profile'] = profile
        except (FlowError, ValueError, KeyError, TypeError, OSError) as exc:
            result.update(status='blocked', hardware_status='blocked', reason=str(exc))
    result['finished_at'] = utc()
    write_json(output / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
