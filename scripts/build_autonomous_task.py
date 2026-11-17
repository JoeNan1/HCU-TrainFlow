#!/usr/bin/env python3
"""Compose one autonomous task from a private site contract. Nothing executes.

The contract carries everything a person has to state once: objective, context,
permissions, budget, autonomy policy, acceptance criteria, execution cards,
admitted devices and the leases they require. The generator validates it with
the same rules the runtime enforces, then writes ``task.json``, ``plan.json``,
``admission.json`` and ``cards/*.json`` into a private directory.

It never runs a command, never contacts a site, and never overwrites a file that
already exists, so a reviewed bundle cannot be replaced by accident.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hcu_trainflow import flow
from hcu_trainflow.core import FlowError, fingerprint, validate_spec
from hcu_trainflow.execution import command_plan


SECTIONS = {'task', 'autonomy', 'plan', 'site'}
TASK_KEYS = {'task_id', 'mode', 'objective', 'context', 'permissions',
             'recovery_owner', 'external_job', 'budget', 'profile'}
SITE_KEYS = {'ssh_target', 'container', 'cwd', 'commands', 'devices', 'occupancy', 'leases'}
COMMAND_KEYS = {'argv', 'env', 'timeout_seconds', 'basis', 'cwd', 'activation'}
DEVICE_KEYS = {'node', 'device', 'identity', 'idle_memory_bytes',
               'memory_tolerance_bytes', 'max_utilization_pct', 'basis'}
OCCUPANCY_KEYS = {'max_age_seconds', 'min_observations', 'quiet_period_seconds',
                  'max_sample_gap_seconds', 'shared_resources'}


def _object(value, name, allowed):
    if not isinstance(value, dict):
        raise FlowError(name + ' must be an object')
    unknown = set(value) - allowed
    if unknown:
        raise FlowError(name + ' has unknown fields: ' + ', '.join(sorted(unknown)))
    return value


def _card(name, command, site):
    _object(command, 'command ' + str(name), COMMAND_KEYS)
    card = {'schema_version': 1, 'backend': 'ssh-docker',
            'ssh_target': site.get('ssh_target'), 'container': site.get('container'),
            'cwd': command.get('cwd', site.get('cwd')), 'argv': command.get('argv'),
            'env': command.get('env', {}), 'timeout_seconds': command.get('timeout_seconds'),
            'basis': command.get('basis')}
    if command.get('activation'):
        card['activation'] = command['activation']
    # Validate the real execution-card contract instead of reporting it later.
    command_plan(card)
    if not isinstance(name, str) or not name.strip():
        raise FlowError('Command names must be nonempty')
    return card


def build(site):
    """Return the validated bundle without touching the filesystem."""
    _object(site, 'site contract', SECTIONS)
    task = _object(site.get('task'), 'task', TASK_KEYS)
    site_block = _object(site.get('site'), 'site', SITE_KEYS)
    if not isinstance(site.get('autonomy'), dict):
        raise FlowError('An autonomous bundle requires an autonomy policy')
    spec = {'schema_version': 1, **task, 'autonomy': site['autonomy']}
    validate_spec(spec)
    plan = flow.validate_plan(site.get('plan'))

    commands = site_block.get('commands')
    if not isinstance(commands, dict) or not commands:
        raise FlowError('At least one execution command is required')
    cards = {name: _card(name, command, site_block) for name, command in commands.items()}

    devices = site_block.get('devices')
    if not isinstance(devices, list) or not devices:
        raise FlowError('At least one admitted device is required')
    for device in devices:
        _object(device, 'device', DEVICE_KEYS)
        missing = DEVICE_KEYS - set(device)
        if missing:
            raise FlowError('device is missing fields: ' + ', '.join(sorted(missing)))
    occupancy = _object(site_block.get('occupancy') or {}, 'occupancy', OCCUPANCY_KEYS)
    context = fingerprint(spec['context'])
    admission = {'schema_version': 1, 'context': context, 'devices': devices, **occupancy}

    leases = site_block.get('leases')
    if not isinstance(leases, list) or not leases or any(not isinstance(item, str) or not item.strip() for item in leases):
        raise FlowError('Explicit lease resources are required')
    expected = {'hcu:' + str(device['node']) + ':' + str(device['identity']) for device in devices}
    unknown = set(leases) - expected
    if unknown:
        raise FlowError('Lease resources must match an admitted device: ' + ', '.join(sorted(unknown)))
    return {'task': spec, 'plan': plan, 'cards': cards, 'admission': admission,
            'leases': leases, 'context': context}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:  # never replace a reviewed bundle
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return str(path.resolve())


def next_steps(task_id, output):
    workspace = '<PRIVATE_WORKSPACE>'
    steps = ['hcu-trainflow --workspace ' + workspace + ' task-create ' + output + '/task.json',
             'hcu-trainflow --workspace ' + workspace + ' flow-start ' + task_id + ' ' + output + '/plan.json']
    steps += ['hcu-trainflow --workspace ' + workspace + ' lease-acquire <RESOURCE> <OWNER> --ttl <TTL>']
    steps.append('hcu-trainflow --workspace ' + workspace + ' flow-drive ' + task_id
                 + ' --worker <module:factory>')
    return steps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('site', help='Private JSON contract: task, autonomy, plan and site')
    parser.add_argument('--output', required=True, help='New private directory for the bundle')
    args = parser.parse_args(argv)
    try:
        site = json.loads(Path(args.site).read_text(encoding='utf-8'))
        bundle = build(site)
        output = Path(args.output)
        if output.exists() and any(output.iterdir()):
            raise FlowError('Output directory must be new or empty; preserve reviewed bundles')
        written = {'task.json': _write(output / 'task.json', bundle['task']),
                   'plan.json': _write(output / 'plan.json', bundle['plan']),
                   'admission.json': _write(output / 'admission.json', bundle['admission'])}
        for name, card in bundle['cards'].items():
            written['cards/' + name + '.json'] = _write(output / 'cards' / (name + '.json'), card)
    except (FlowError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({'status': 'prepared', 'output': str(output.resolve()), 'written': written,
                      'context': bundle['context'], 'leases': bundle['leases'],
                      'next': next_steps(bundle['task']['task_id'], str(output.resolve()))},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
