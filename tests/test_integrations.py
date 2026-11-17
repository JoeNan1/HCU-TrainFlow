import json
from pathlib import Path
import subprocess
import sys

import pytest

from hcu_trainflow import dependencies, tracelens, wiki
from hcu_trainflow.core import FlowError, Store, write_json, digest


def manifest(tmp_path):
    root = tmp_path / 'project'
    items = [dict(id='public-tool', path='thirdparty/tool', url='https://github.com/example/tool.git', commit='a'*40, optional=False),
             dict(id='private-kb', path='thirdparty/kb', url='https://github.com/example/kb.git', commit='b'*40, optional=True)]
    write_json(root/'thirdparty/manifest.json', {'schema_version': 1, 'dependencies': items})
    return root, items


def test_manifest_optional_entries_are_skipped_and_status_does_not_fetch(tmp_path, monkeypatch):
    root, _ = manifest(tmp_path)
    monkeypatch.setattr(dependencies, 'git', lambda *a, **kw: pytest.fail('Unexpected Git network/mutation'))
    result = dependencies.sync_dependencies(root, status_only=True)
    assert [x['id'] for x in result['dependencies']] == ['public-tool']
    assert result['status'] == 'incomplete'


def test_permission_failure_is_explicit_and_retryable(tmp_path, monkeypatch):
    root, _ = manifest(tmp_path)
    monkeypatch.setattr(dependencies, 'git', lambda *a, **kw: (_ for _ in ()).throw(FlowError('Git fetch failed; check access')))
    result = dependencies.sync_dependencies(root, only=['private-kb'])
    assert result['status'] == 'incomplete' and result['dependencies'][0]['status'] == 'unavailable'
    assert not (root/'thirdparty/tool').exists()


def create_checkout(root, item):
    path = root/item['path']; path.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()
    git('init'); git('remote', 'add', 'origin', item['url'])
    (path/'file.txt').write_text('original')
    git('add', 'file.txt')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
    return path, git('rev-parse','HEAD')


def test_dirty_checkout_is_never_overwritten(tmp_path, monkeypatch):
    root, items = manifest(tmp_path)
    path, sha = create_checkout(root, items[0])
    (path/'file.txt').write_text('user changes')
    result = dependencies.sync_dependencies(root, only=['public-tool'])
    assert result['dependencies'][0]['status'] == 'dirty'
    assert (path/'file.txt').read_text() == 'user changes'
    assert subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip() == sha


def test_correct_revision_and_origin_are_required(tmp_path):
    root, items = manifest(tmp_path)
    path, sha = create_checkout(root, items[0])
    assert dependencies.inspect_checkout(root,items[0])['status'] == 'revision-mismatch'
    items[0]['commit'] = sha
    write_json(root/'thirdparty/manifest.json',{'schema_version':1,'dependencies':items})
    assert dependencies.require_checkout(root,'public-tool')[0] == path
    subprocess.check_call(['git','-C',str(path),'remote','set-url','origin','https://github.com/elsewhere/tool.git'])
    with pytest.raises(FlowError): dependencies.require_checkout(root,'public-tool')


def test_dependency_paths_cannot_escape(tmp_path):
    root, items = manifest(tmp_path)
    items[0]['path'] = 'thirdparty/../../outside'
    write_json(root/'thirdparty/manifest.json', {'schema_version':1,'dependencies':items})
    with pytest.raises(FlowError): dependencies.load_manifest(root)


def knowledge_mirror_fixture(tmp_path):
    root, items = manifest(tmp_path)
    item = items[0]
    item.update(id='hcu-knowledge', mirrors={'gitlab': 'http://gitlab.example:10068/group/subgroup/kb.git'})
    seed, sha = create_checkout(root, {**item, 'path': 'thirdparty/seed'})
    item['commit'] = sha
    write_json(root/'thirdparty/manifest.json', {'schema_version': 1, 'dependencies': items})
    return root, item, seed


@pytest.mark.parametrize('source', [None, 'github', 'gitlab'])
def test_knowledge_clone_source_pin_and_existing_origin_are_preserved(tmp_path, monkeypatch, source):
    root, item, seed = knowledge_mirror_fixture(tmp_path)
    expected = item['mirrors']['gitlab'] if source == 'gitlab' else item['url']
    real_git = dependencies.git
    def local_fetch(path, *args, **kwargs):
        if args[0] == 'fetch':
            assert real_git(path, 'remote', 'get-url', 'origin').stdout.strip() == expected
            assert args == ('fetch', '--depth', '1', 'origin', item['commit'])
            return real_git(path, 'fetch', '--depth', '1', str(seed), item['commit'])
        return real_git(path, *args, **kwargs)
    monkeypatch.setattr(dependencies, 'git', local_fetch)
    state = dependencies.sync_dependencies(root, knowledge_source=source)
    assert state['status'] == 'ready'
    assert state['dependencies'][0]['origin'] == expected
    path, _ = dependencies.require_checkout(root, 'hcu-knowledge')
    assert (path/'file.txt').read_text() == 'original'
    def read_only(path, *args, **kwargs):
        assert args[0] in {'rev-parse', 'remote', 'status'}
        assert args[0] != 'remote' or args[1] == 'get-url'
        return real_git(path, *args, **kwargs)
    monkeypatch.setattr(dependencies, 'git', read_only)
    # The option is only a creation preference; repeated installs do not migrate origin.
    assert dependencies.sync_dependencies(root, knowledge_source='gitlab')['status'] == 'ready'
    (path/'file.txt').write_text('local edits')
    assert dependencies.sync_dependencies(root)['dependencies'][0]['status'] == 'dirty'
    assert (path/'file.txt').read_text() == 'local edits'


def test_external_gitlab_binding_preserves_revision_and_rejects_unknown_source(tmp_path, monkeypatch):
    root, item, seed = knowledge_mirror_fixture(tmp_path)
    for name in ('kb.py', 'tools/setup_workspace.py', 'knowledge/INDEX.md',
                 'skills/hcu-knowledge-search/SKILL.md', 'skills/hcu-knowledge-update/SKILL.md'):
        path = seed/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    dependencies.git(seed, 'remote', 'set-url', 'origin', item['mirrors']['gitlab'])
    dependencies.bind_knowledge(root, seed)
    real_git = dependencies.git
    def read_only(path, *args, **kwargs):
        assert args[0] in {'rev-parse', 'remote', 'status'}
        assert args[0] != 'remote' or args[1] == 'get-url'
        return real_git(path, *args, **kwargs)
    monkeypatch.setattr(dependencies, 'git', read_only)
    state = dependencies.sync_dependencies(root)['dependencies'][0]
    assert state['status'] == 'ready' and state['external'] and state['dirty']
    real_git(seed, 'remote', 'set-url', 'origin', 'http://gitlab.example:10068/other/kb.git')
    assert dependencies.inspect_checkout(root, item)['status'] == 'origin-mismatch'
    with pytest.raises(FlowError, match='identity'):
        dependencies.bind_knowledge(root, seed)


def test_explicit_fork_binding_is_local_path_scoped_and_survives_setup_rebind(tmp_path, monkeypatch):
    root, item, seed = knowledge_mirror_fixture(tmp_path)
    for name in ('kb.py', 'tools/setup_workspace.py', 'knowledge/INDEX.md',
                 'skills/hcu-knowledge-search/SKILL.md', 'skills/hcu-knowledge-update/SKILL.md'):
        path = seed/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    fork = 'http://gitlab.example:10068/my-team/kb.git'
    dependencies.git(seed, 'remote', 'set-url', 'origin', fork)
    write_json(root/'thirdparty.local.json', {'cuda_optimized_skill_root': str(tmp_path/'cuda')})
    with pytest.raises(FlowError, match='identity'):
        dependencies.bind_knowledge(root, seed)
    real_git = dependencies.git
    def read_only(path, *args, **kwargs):
        assert args[0] in {'rev-parse', 'remote', 'status', 'merge-base'}
        assert args[0] != 'remote' or args[1] == 'get-url'
        return real_git(path, *args, **kwargs)
    monkeypatch.setattr(dependencies, 'git', read_only)
    dependencies.bind_dependency(root, 'hcu-knowledge', seed, origin=fork)
    dependencies.bind_knowledge(root, seed)  # Full setup repeats this existing binding.
    bindings = json.loads((root/'thirdparty.local.json').read_text())
    assert bindings['cuda_optimized_skill_root'] == str(tmp_path/'cuda')
    assert bindings['external_sources'] == {'hcu-knowledge': {'path': str(seed), 'url': fork}}
    state = dependencies.sync_dependencies(root, only=['hcu-knowledge'])['dependencies'][0]
    assert state['status'] == 'ready' and state['source_approval'] == 'explicit-local-binding'
    assert state['commit'] == item['commit']
    assert dependencies.require_checkout(root, 'hcu-knowledge')[0] == seed
    # Selecting a different checkout never transfers the earlier source approval.
    different, _ = create_checkout(root, {**item, 'path': 'thirdparty/different'})
    for name in dependencies._binding_requirements('hcu-knowledge'):
        path = different/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    real_git(different, 'remote', 'set-url', 'origin', fork)
    with pytest.raises(FlowError, match='identity'):
        dependencies.bind_knowledge(root, different)
    # Changing the selected checkout's origin also invalidates the approval.
    real_git(seed, 'remote', 'set-url', 'origin', 'http://gitlab.example:10068/another/kb.git')
    assert dependencies.inspect_checkout(root, item)['status'] == 'origin-mismatch'


def test_external_fork_requires_the_pinned_baseline_at_binding_and_status(tmp_path):
    root, item, seed = knowledge_mirror_fixture(tmp_path)
    for name in dependencies._binding_requirements('hcu-knowledge'):
        path = seed/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    fork = 'https://gitlab.example/my-team/kb.git'
    dependencies.git(seed, 'remote', 'set-url', 'origin', fork)
    dependencies.bind_dependency(root, 'hcu-knowledge', seed, origin=fork)
    before = (root/'thirdparty.local.json').read_bytes()
    item['commit'] = 'a'*40
    write_json(root/'thirdparty/manifest.json', {'schema_version': 1, 'dependencies': [item]})
    assert dependencies.inspect_checkout(root, item)['status'] == 'fork-baseline-mismatch'
    with pytest.raises(FlowError, match='pinned commit'):
        dependencies.bind_dependency(root, 'hcu-knowledge', seed, origin=fork)
    assert (root/'thirdparty.local.json').read_bytes() == before


@pytest.mark.parametrize('origin', ['http://user:example-secret@gitlab.example/my/kb.git',
                                   'http://gitlab.example/my/kb.git?token=example-secret',
                                   'file:///tmp/kb.git', 'https://gitlab.example/../kb.git'])
def test_explicit_origin_rejects_credential_urls_and_invalid_sources(tmp_path, origin):
    root, _, seed = knowledge_mirror_fixture(tmp_path)
    for name in dependencies._binding_requirements('hcu-knowledge'):
        path = seed/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    with pytest.raises(FlowError, match='credential-free'):
        dependencies.bind_dependency(root, 'hcu-knowledge', seed, origin=origin)
    assert not (root/'thirdparty.local.json').exists()


def test_multiple_external_bindings_preserve_revisions_edits_and_other_bindings(tmp_path, monkeypatch):
    root, _ = manifest(tmp_path)
    requirements = {
        'hcu-knowledge': ('kb.py', 'tools/setup_workspace.py', 'knowledge/INDEX.md',
                          'skills/hcu-knowledge-search/SKILL.md', 'skills/hcu-knowledge-update/SKILL.md'),
        'cuda-optimized-skill': ('skills/hygon-hip-baseline-generator/SKILL.md',
                                 'skills/hygon-hip-kernel-optimizer/SKILL.md',
                                 'skills/hygon-triton-kernel-optimizer/SKILL.md'),
        'tracelens': ('TraceLens/__init__.py', 'setup.py', 'README.md'),
    }
    items = [dict(id=name, path='thirdparty/'+name, url='https://github.com/example/'+name+'.git',
                  commit='a'*40) for name in requirements]
    write_json(root/'thirdparty/manifest.json', {'schema_version': 1, 'dependencies': items})
    checkouts = {}
    for item in items:
        path, sha = create_checkout(root, {**item, 'path': 'thirdparty/seed-'+item['id']})
        for name in requirements[item['id']]:
            resource = path/name
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_text('fixture')
        (path/'file.txt').write_text('user changes')
        checkouts[item['id']] = (path, sha)
    real_git = dependencies.git
    def read_only(path, *args, **kwargs):
        assert args[0] in {'rev-parse', 'remote', 'status'}
        assert args[0] != 'remote' or args[1] == 'get-url'
        return real_git(path, *args, **kwargs)
    monkeypatch.setattr(dependencies, 'git', read_only)
    for item in items:
        dependencies.bind_dependency(root, item['id'], checkouts[item['id']][0])
    bindings = json.loads((root/'thirdparty.local.json').read_text())
    assert bindings == {'hcu_knowledge_root': str(checkouts['hcu-knowledge'][0]),
                        'cuda_optimized_skill_root': str(checkouts['cuda-optimized-skill'][0]),
                        'tracelens_root': str(checkouts['tracelens'][0])}
    result = dependencies.sync_dependencies(root)
    assert result['status'] == 'ready'
    for row, item in zip(result['dependencies'], items):
        path, sha = checkouts[item['id']]
        assert row['external'] and row['dirty'] and row['commit'] == sha
        assert row['commit'] != row['expected_commit']
        assert dependencies.require_checkout(root, item['id'])[0] == path
        assert (path/'file.txt').read_text() == 'user changes'
        assert not (root/item['path']).exists()


@pytest.mark.parametrize('bindings', [[], None, {'cuda_optimized_skill_root': None},
                                      {'cuda_optimized_skill_root': 'relative/path'}])
def test_malformed_binding_cannot_silently_fall_back_to_managed_checkout(tmp_path, bindings):
    root, items = manifest(tmp_path)
    item = {**items[0], 'id': 'cuda-optimized-skill'}
    write_json(root/'thirdparty.local.json', bindings)
    with pytest.raises(FlowError, match='binding|object'):
        dependencies.dependency_path(root, item)


@pytest.mark.parametrize('url', ['http://user:secret@gitlab.example/g/kb.git',
                                'http://gitlab.example/g/kb.git?token=secret',
                                'file:///tmp/kb.git', 'http://gitlab.example/../kb.git'])
def test_mirror_urls_reject_credentials_and_unsupported_addresses(tmp_path, url):
    root, items = manifest(tmp_path)
    items[0]['mirrors'] = {'gitlab': url}
    write_json(root/'thirdparty/manifest.json', {'schema_version': 1, 'dependencies': items})
    with pytest.raises(FlowError, match='mirror'):
        dependencies.load_manifest(root)


@pytest.mark.parametrize('condition', ['clean', 'dirty', 'unknown-head', 'upstream-conflict', 'status-only'])
def test_fork_origin_migration_preserves_unrecognized_state(tmp_path,condition):
    root,items=manifest(tmp_path)
    path,sha=create_checkout(root,items[0])
    old_url=items[0]['url'];new_url='https://github.com/example/fork.git'
    items[0].update(url=new_url,commit=sha,upstream_url=old_url,upstream_commit=sha)
    if condition=='dirty':(path/'file.txt').write_text('local edits')
    if condition=='unknown-head':items[0]['upstream_commit']='b'*40
    if condition=='upstream-conflict':subprocess.check_call(['git','-C',str(path),'remote','add','upstream','https://github.com/other/repo.git'])
    write_json(root/'thirdparty/manifest.json',{'schema_version':1,'dependencies':items})
    assert dependencies.sync_dependencies(root,only=['public-tool'])['status']=='incomplete'
    result=dependencies.sync_dependencies(root,only=['public-tool'],migrate_origin=True,status_only=condition=='status-only')
    origin=subprocess.check_output(['git','-C',str(path),'remote','get-url','origin'],text=True).strip()
    assert origin==(new_url if condition=='clean' else old_url)
    assert result['status']==('ready' if condition=='clean' else 'incomplete')
    if condition=='clean':
        assert subprocess.check_output(['git','-C',str(path),'remote','get-url','upstream'],text=True).strip()==old_url
    if condition=='dirty':assert (path/'file.txt').read_text()=='local edits'


def setup_trace(tmp_path, monkeypatch, cpu=True):
    root=tmp_path/'dependency'; root.mkdir()
    monkeypatch.setattr(tracelens,'require_checkout',lambda *a:(root,{'commit':'a'*40}))
    path=tmp_path/'rank0.json'
    events=[{'ph':'X','cat':'kernel','dur':4}]
    if cpu: events.append({'ph':'X','cat':'cpu_op','dur':10})
    write_json(path,{'traceEvents':events})
    return Store(tmp_path/'state'),path


def test_trace_report_keeps_native_tables_and_provenance(tmp_path,monkeypatch):
    store,path=setup_trace(tmp_path,monkeypatch)
    def run(argv,**kw):
        request=json.loads(Path(argv[-1]).read_text())
        assert 'gpu_arch_json_path' not in request  # No guessed AMD/NV peak model.
        tables=Path(request['output_csvs_dir']);tables.mkdir()
        (tables/'ops.csv').write_text('name,time\nmm,4\n')
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(tracelens.subprocess,'run',run)
    result=tracelens.run_report(store,'.',trace=path,rank=7)
    assert result['status']=='generated' and result['inputs'][0]['rank']==7
    assert result['inputs'][0]['sha256']==digest(path.read_bytes())
    assert result['tables'][0]['rows']==1 and result['gpu_arch'] is None
    assert result['training_assessment'].startswith('unassessed')


@pytest.mark.parametrize('outcome,expected',[('empty','incomplete'),('failure','failed'),('timeout','failed')])
def test_trace_failures_are_not_success(tmp_path,monkeypatch,outcome,expected):
    store,path=setup_trace(tmp_path,monkeypatch)
    def run(argv,**kw):
        if outcome=='timeout':raise subprocess.TimeoutExpired(argv,1)
        return subprocess.CompletedProcess(argv,1 if outcome=='failure' else 0)
    monkeypatch.setattr(tracelens.subprocess,'run',run)
    result=tracelens.run_report(store,'.',trace=path)
    assert result['status']==expected
    assert Path(result['output_directory'],'report.json').is_file()


def test_partial_ranks_do_not_relabel_world(tmp_path,monkeypatch):
    store,path=setup_trace(tmp_path,monkeypatch)
    monkeypatch.setattr(tracelens.subprocess,'run',lambda *a,**kw:pytest.fail('Should not execute with missing ranks'))
    with pytest.raises(FlowError,match='every rank'):
        tracelens.run_report(store,'.',trace_pattern=str(tmp_path/'rank*.json'),world_size=2)


def test_truncated_table_retains_failure_report(tmp_path,monkeypatch):
    store,path=setup_trace(tmp_path,monkeypatch)
    def run(argv,**kw):
        request=json.loads(Path(argv[-1]).read_text())
        tables=Path(request['output_csvs_dir']);tables.mkdir()
        (tables/'partial.csv').write_text('name,time\n"truncated')
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(tracelens.subprocess,'run',run)
    result=tracelens.run_report(store,'.',trace=path)
    assert result['status']=='failed' and result['tables'][0]['status']=='unreadable'
    assert Path(result['output_directory'],'report.json').is_file()


def test_empty_trace_rejected(tmp_path):
    path=tmp_path/'empty.json';write_json(path,{'traceEvents':[]})
    with pytest.raises(FlowError):tracelens.trace_inventory(path)


def web_source(tmp_path):
    root=tmp_path/'wiki';(root/'knowledge').mkdir(parents=True)
    source={'id':'official-docs','kind':'web','repository':'https://docs.nvidia.com/example/',
            'paths':['guide'],'documents':{'guide':'https://docs.nvidia.com/example/guide.html'}}
    write_json(root/'knowledge/sources.json',[source])
    (root/'knowledge/topic.md').write_text('---\nid: topic\nsources:\n- source: official-docs\n  path: guide\n---\n# Guide',encoding='utf-8')
    return root,source


def test_web_refresh_hashes_body_tracks_impact_and_requires_review(tmp_path,monkeypatch):
    root,source=web_source(tmp_path);store=Store(tmp_path/'state')
    class Response:
        headers={'Content-Type':'text/html; charset=utf-8'}
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):return ('<html><script>ignored</script><article>'+('Official training guide. '*25)+'</article></html>').encode()
    class Opener:
        def open(self,request,**kw):
            assert not request.has_header('Authorization')
            return Response()
    monkeypatch.setattr(wiki.urllib.request,'build_opener',lambda *a:Opener())
    result=wiki.refresh_source(store,root,'official-docs',token='must-not-be-forwarded')
    assert result['revision_kind']=='web-content-fingerprint' and len(result['commit'])==64
    assert result['affected_pages'] and result['files']['guide']['raw_sha256']
    body=store.artifact(result['files']['guide']['sha256'])
    assert b'ignored' not in body
    with pytest.raises(FlowError):wiki.review_refresh(store,result['stage_id'],{},root)
    decisions={'knowledge/topic.md':{'decision':'updated','note':'Verified tutorial and API change','page_sha256':digest((root/'knowledge/topic.md').read_bytes()),'source_commit':result['commit']}}
    wiki.review_refresh(store,result['stage_id'],decisions,root)
    assert not wiki.refresh_source(store,root,'official-docs')['changed_paths']


def test_web_failure_preserves_reviewed_cursor(tmp_path,monkeypatch):
    root,source=web_source(tmp_path);store=Store(tmp_path/'state')
    cursor=store.root/'wiki/sources/official-docs.json';write_json(cursor,{'commit':'previous'})
    class Opener:
        def open(self,*a,**kw):raise OSError('unavailable')
    monkeypatch.setattr(wiki.urllib.request,'build_opener',lambda *a:Opener())
    result=wiki.refresh_source(store,root,'official-docs')
    assert result['status']=='partial' and json.loads(cursor.read_text())['commit']=='previous'
    with pytest.raises(FlowError):wiki.review_refresh(store,result['stage_id'],{},root)


def test_web_source_cannot_send_tokens_to_other_hosts(tmp_path):
    _,source=web_source(tmp_path);source['documents']['guide']='https://example.invalid/guide'
    with pytest.raises(FlowError):wiki.collect_web_documents(Store(tmp_path/'state'),source)


def test_web_moved_source_requires_provenance_review(tmp_path):
    root,source=web_source(tmp_path);store=Store(tmp_path/'state')
    source['baseline_files']={'guide':{'sha256':'a'*64,'url':'https://docs.nvidia.com/old.html'}}
    files={'guide':{'sha256':'a'*64,'url':'https://docs.nvidia.com/new.html'}}
    result=wiki.stage_source_refresh(store,root,source,'b'*64,files,[],'registered-official-pages')
    assert result['changed_paths']==['guide'] and result['affected_pages']


def test_workflow_only_install_is_explicit_and_preserves_edits(tmp_path):
    root=Path(__file__).resolve().parents[1]
    target=tmp_path/'skills'
    result=subprocess.run([sys.executable,str(root/'scripts/install_skills.py'),'--workflow-only','--target',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert len(list(target.glob('*/SKILL.md')))==6
    (target/'hcu-train-check-and-adapt/SKILL.md').write_text('local edits')
    result=subprocess.run([sys.executable,str(root/'scripts/install_skills.py'),'--workflow-only','--target',str(target)],capture_output=True,text=True)
    assert result.returncode!=0 and (target/'hcu-train-check-and-adapt/SKILL.md').read_text()=='local edits'
