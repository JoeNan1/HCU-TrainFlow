"""The site generator validates a bundle with the same rules the runtime uses."""
import importlib.util
import json
from pathlib import Path

import pytest

from hcu_trainflow import flow
from hcu_trainflow.core import FlowError, Store, fingerprint

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'examples' / 'autonomous-site.json'


def generator():
    spec = importlib.util.spec_from_file_location('build_autonomous_task',
                                                  ROOT / 'scripts' / 'build_autonomous_task.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def site():
    return json.loads(TEMPLATE.read_text(encoding='utf-8'))


def test_shipped_template_builds_a_consistent_bundle(tmp_path):
    module = generator()
    bundle = module.build(site())
    assert bundle['admission']['context'] == fingerprint(bundle['task']['context'])
    assert set(bundle['cards']) == {'environment', 'train', 'profile'}
    assert all(card['schema_version'] == 1 and card['backend'] == 'ssh-docker'
               for card in bundle['cards'].values())
    assert bundle['leases'] == ['hcu:REPLACE-WITH-NODE:REPLACE-WITH-PCI-IDENTITY']


def test_bundle_is_accepted_by_the_real_runtime(tmp_path):
    module = generator()
    bundle = module.build(site())
    store = Store(tmp_path / 'workspace')
    task = store.create(bundle['task'])
    flow.start(store, task['id'], bundle['plan'])
    assert store.task(task['id'])['state'] == 'prepared'
    assert task['context'] == bundle['admission']['context']


@pytest.mark.parametrize('mutate', [
    lambda value: value['task'].update({'unknown_field': 1}),
    lambda value: value['site'].update({'unknown_section': 1}),
    lambda value: value.pop('autonomy'),
    lambda value: value['plan'].update({'acceptance': {'环境': '中文键不安全'}}),
    lambda value: value['site'].update({'leases': ['hcu:other-node:0000:00:00.0']}),
    lambda value: value['site']['commands'].update({'train': {'argv': [], 'timeout_seconds': 10,
                                                              'basis': 'empty argv'}}),
    lambda value: value['site']['commands'].update({'train': {'argv': ['bash'], 'basis': 'no timeout'}}),
    lambda value: value['site'].update({'devices': [{'node': 'n'}]}),
    lambda value: value['site'].update({'devices': []}),
    lambda value: value['autonomy'].update({'escalation': {'acceptance_edit': 'relax'}}),
])
def test_generator_rejects_invalid_or_unsafe_contracts(mutate):
    module = generator()
    value = site()
    mutate(value)
    with pytest.raises(FlowError):
        module.build(value)


def test_cli_writes_a_new_bundle_and_refuses_to_overwrite(tmp_path):
    module = generator()
    contract = tmp_path / 'site.json'
    contract.write_text(json.dumps(site()), encoding='utf-8')
    output = tmp_path / 'bundle'

    assert module.main([str(contract), '--output', str(output)]) == 0
    for name in ('task.json', 'plan.json', 'admission.json',
                 'cards/environment.json', 'cards/train.json', 'cards/profile.json'):
        assert (output / name).is_file()

    # A reviewed bundle is never replaced: the second run must fail.
    assert module.main([str(contract), '--output', str(output)]) == 1
    assert json.loads((output / 'task.json').read_text(encoding='utf-8')) == module.build(site())['task']


def test_cli_reports_contract_errors_on_stderr(tmp_path, capsys):
    module = generator()
    contract = tmp_path / 'site.json'
    broken = site()
    broken['plan']['acceptance'] = {}
    contract.write_text(json.dumps(broken), encoding='utf-8')
    assert module.main([str(contract), '--output', str(tmp_path / 'out')]) == 1
    assert json.loads(capsys.readouterr().err)['status'] == 'error'
    assert not (tmp_path / 'out').exists()
