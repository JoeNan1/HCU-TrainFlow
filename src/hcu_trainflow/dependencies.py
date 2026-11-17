"""Selective, pinned thirdparty checkouts. Never publishes or resets their content."""
import os
import json
from pathlib import Path
import re
import subprocess

from .core import FlowError, read_json, write_json

# Bound automatic history repair; never make an existing target a depth-one root.
FORWARD_HISTORY_DEEPEN = 128

EXTERNAL_BINDING_KEYS = {
    'hcu-knowledge': 'hcu_knowledge_root',
    'cuda-optimized-skill': 'cuda_optimized_skill_root',
    'tracelens': 'tracelens_root',
}


def source_urls(item):
    """Registered equivalent origins; mirrors share the same pinned commit."""
    return [item['url'], *item.get('mirrors', {}).values()]


def matches_source(item, origin):
    return origin.removesuffix('.git') in {url.removesuffix('.git') for url in source_urls(item)}


def validate_external_origin(origin):
    if (not isinstance(origin, str) or not re.fullmatch(
            r'https?://[A-Za-z0-9.-]+(?::[0-9]+)?/(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)+[A-Za-z0-9_-][A-Za-z0-9_.-]*\.git', origin)):
        raise FlowError('External origin must be a credential-free HTTP(S) repository URL ending in .git')
    return origin


def external_origin(bindings, dependency, path):
    """An explicit source approval applies only to its selected checkout path."""
    sources = bindings.get('external_sources', {})
    if not isinstance(sources, dict):
        raise FlowError('external_sources must be an object')
    if dependency not in sources:
        return None
    entry = sources[dependency]
    if (not isinstance(entry, dict) or not isinstance(entry.get('path'), str)
            or not Path(entry['path']).is_absolute()):
        raise FlowError('External source approval needs an absolute checkout path')
    origin = validate_external_origin(entry.get('url'))
    return origin if Path(entry['path']).resolve() == path.resolve() else None


def fork_contains_baseline(path, item):
    return git(path, 'merge-base', '--is-ancestor', item['commit'], 'HEAD', check=False).returncode == 0


def knowledge_ready(result):
    """Accept the current checkout's usable index, never a rollback snapshot."""
    try:
        health=json.loads(result.stdout)
    except (AttributeError, TypeError, ValueError):
        return False
    return (result.returncode==0 and isinstance(health,dict)
            and health.get('local_ready') is True and health.get('index_current') is True
            and health.get('snapshot_mode')=='current')


def dependency_path(root, item):
    binding = root / 'thirdparty.local.json'
    key = EXTERNAL_BINDING_KEYS.get(item['id'])
    if key and binding.is_file():
        bindings = read_json(binding)
        if not isinstance(bindings, dict):
            raise FlowError('thirdparty.local.json must be an object')
        if key in bindings:
            value = bindings[key]
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise FlowError(item['id'] + ' binding must be an absolute checkout path')
            return Path(value).resolve(), True
    return root / item['path'], False


def _binding_requirements(dependency):
    if dependency == 'hcu-knowledge':
        return ('kb.py', 'tools/setup_workspace.py', 'knowledge/INDEX.md',
                'skills/hcu-knowledge-search/SKILL.md', 'skills/hcu-knowledge-update/SKILL.md')
    if dependency == 'cuda-optimized-skill':
        return ('skills/hygon-hip-baseline-generator/SKILL.md',
                'skills/hygon-hip-kernel-optimizer/SKILL.md',
                'skills/hygon-triton-kernel-optimizer/SKILL.md')
    if dependency == 'tracelens':
        return ('TraceLens/__init__.py', 'setup.py', 'README.md')
    raise FlowError('Dependency does not support an external binding: ' + dependency)


def bind_dependency(project, dependency, path, *, origin=None):
    """Reuse an explicitly selected independent checkout; never pull/reset it."""
    root, entries = load_manifest(project)
    item = next((x for x in entries if x['id'] == dependency), None)
    if item is None:
        raise FlowError('Dependency is not registered: ' + dependency)
    if dependency not in EXTERNAL_BINDING_KEYS:
        raise FlowError('Dependency does not support an external binding: ' + dependency)
    path = Path(path).expanduser().resolve()
    if path == (root / item['path']).resolve():
        raise FlowError('Managed checkout needs no external binding: ' + dependency)
    for name in _binding_requirements(dependency):
        if not (path / name).is_file():
            raise FlowError('Incomplete ' + dependency + ' checkout: ' + name)
    binding_path = root / 'thirdparty.local.json'
    bindings = read_json(binding_path) if binding_path.is_file() else {}
    if not isinstance(bindings, dict):
        raise FlowError('thirdparty.local.json must be an object')
    approved = validate_external_origin(origin) if origin is not None else external_origin(bindings, dependency, path)
    top = git(path, 'rev-parse', '--show-toplevel').stdout.strip()
    actual_origin = git(path, 'remote', 'get-url', 'origin').stdout.strip()
    source_matches = actual_origin == approved if approved else matches_source(item, actual_origin)
    if Path(top).resolve() != path or not source_matches:
        raise FlowError(dependency + ' checkout identity differs from the registered or explicitly bound source')
    if approved and not matches_source(item, approved) and not fork_contains_baseline(path, item):
        raise FlowError('External fork must contain the manifest pinned commit; verify its history before binding')
    bindings[EXTERNAL_BINDING_KEYS[dependency]] = str(path)
    if approved:
        # Persist only the non-secret, path-specific approval, never credentials.
        sources = bindings.setdefault('external_sources', {})
        if not isinstance(sources, dict):
            raise FlowError('external_sources must be an object')
        sources[dependency] = {'path': str(path), 'url': approved}
    elif isinstance(bindings.get('external_sources'), dict):
        bindings['external_sources'].pop(dependency, None)
    write_json(binding_path, bindings)
    return path


def bind_knowledge(project, path):
    """Backward-compatible HCU-Knowledge binding helper."""

    return bind_dependency(project, 'hcu-knowledge', path)


def load_manifest(project):
    root = Path(project).resolve()
    manifest = read_json(root / 'thirdparty/manifest.json')
    if manifest.get('schema_version') != 1:
        raise FlowError('Unsupported thirdparty manifest')
    entries = manifest['dependencies']
    names, paths = set(), set()
    for item in entries:
        if not re.fullmatch(r'[a-z0-9-]+', item['id']) or item['id'] in names:
            raise FlowError('Invalid/duplicate dependency ID')
        relative = Path(item['path'])
        if relative.is_absolute() or len(relative.parts) != 2 or relative.parts[0] != 'thirdparty' or '..' in relative.parts:
            raise FlowError('Dependency checkout must be a direct child of thirdparty')
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.resolve().parent != (root / 'thirdparty').resolve():
            raise FlowError('Dependency checkout cannot escape thirdparty')
        if path in paths or not re.fullmatch(r'[0-9a-f]{40}', item['commit']):
            raise FlowError('Duplicate checkout or unpinned dependency')
        for url in [item['url']] + ([item['upstream_url']] if item.get('upstream_url') else []):
            if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git', url):
                raise FlowError('Expected credential-free GitHub HTTPS URL')
        mirrors = item.get('mirrors', {})
        if not isinstance(mirrors, dict):
            raise FlowError('Dependency mirrors must be named repository URLs')
        for name, url in mirrors.items():
            if (not re.fullmatch(r'[a-z0-9-]+', name) or name == 'github'
                    or not isinstance(url, str)
                    or not re.fullmatch(r'https?://[A-Za-z0-9.-]+(?::[0-9]+)?/(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)+[A-Za-z0-9_-][A-Za-z0-9_.-]*\.git', url)):
                raise FlowError('Expected a named, credential-free HTTP(S) mirror repository URL')
        if item.get('upstream_url') and not re.fullmatch(r'[0-9a-f]{40}', item.get('upstream_commit', '')):
            raise FlowError('Fork needs a pinned upstream baseline')
        for value in item.get('sparse_paths', []):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', value) or any(p in {'.', '..'} for p in value.split('/')):
                raise FlowError('Invalid sparse checkout directory')
        names.add(item['id']); paths.add(path)
    return root, entries


def git(path, *args, check=True):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never', 'GIT_LFS_SKIP_SMUDGE': '1'}
    try:
        result = subprocess.run(['git', '-c', 'credential.interactive=never', '-C', str(path), *args],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise FlowError('Git operation timed out; inspect the checkout and retry explicitly') from exc
    if check and result.returncode:
        # Git diagnostics may include credential-helper output. Keep only actionable context here.
        raise FlowError(f'Git {args[0]} failed (exit {result.returncode}); check network, repository access and Git credentials')
    return result


def inspect_checkout(root, item):
    path, external = dependency_path(root, item)
    result = {'id': item['id'], 'path': str(path), 'expected_commit': item['commit'], 'optional': item.get('optional', False), 'external': external}
    if not path.exists():
        return {**result, 'status': 'missing'}
    top = git(path, 'rev-parse', '--show-toplevel', check=False)
    if top.returncode or Path(top.stdout.strip()).resolve() != path.resolve():
        return {**result, 'status': 'invalid-checkout'}
    origin = git(path, 'remote', 'get-url', 'origin', check=False)
    approved = external_origin(read_json(root / 'thirdparty.local.json'), item['id'], path) if external else None
    source_matches = origin.stdout.strip() == approved if approved else matches_source(item, origin.stdout.strip())
    if origin.returncode or not source_matches:
        return {**result, 'status': 'origin-mismatch'}
    result['origin'] = origin.stdout.strip()
    if approved:
        result['source_approval'] = 'explicit-local-binding'
        if not matches_source(item, approved) and not fork_contains_baseline(path, item):
            return {**result, 'status': 'fork-baseline-mismatch',
                    'action': 'Preserve the checkout; the approved fork must contain the manifest pinned commit'}
    head = git(path, 'rev-parse', '--verify', 'HEAD', check=False)
    dirty = git(path, 'status', '--porcelain', '--untracked-files=normal').stdout.strip()
    revision = head.stdout.strip() if not head.returncode else None
    if external:
        note = ('Independent knowledge revision preserved; setup must verify its local index and Skills'
                if item['id'] == 'hcu-knowledge' else
                'Independent checkout revision preserved; installation must verify its runtime or Skills')
        return {**result, 'commit': revision, 'dirty': bool(dirty),
                'status': 'ready' if revision else 'invalid-checkout',
                'note': note}
    return {**result, 'commit': revision, 'dirty': bool(dirty),
            'status': 'dirty' if dirty else 'ready' if revision == item['commit'] else 'revision-mismatch'}


def migrate_upstream_origin(root, item, state):
    """Explicitly migrate a clean, known upstream baseline to its registered fork."""
    path = root / item['path']
    origin = git(path, 'remote', 'get-url', 'origin').stdout.strip().removesuffix('.git')
    if not item.get('upstream_url') or origin != item['upstream_url'].removesuffix('.git'):
        return {**state, 'action': 'Only the manifest upstream origin can migrate; inspect this checkout manually'}
    if git(path, 'status', '--porcelain', '--untracked-files=normal').stdout.strip():
        return {**state, 'status': 'dirty', 'action': 'Preserve local changes before changing repository origin'}
    head = git(path, 'rev-parse', '--verify', 'HEAD', check=False)
    if head.returncode or head.stdout.strip() != item['upstream_commit']:
        return {**state, 'action': 'Unrecognized upstream revision; preserve local commits and migrate manually'}
    upstream = git(path, 'remote', 'get-url', 'upstream', check=False)
    if not upstream.returncode and upstream.stdout.strip().removesuffix('.git') != item['upstream_url'].removesuffix('.git'):
        return {**state, 'action': 'Existing upstream remote differs; preserve it and inspect manually'}
    if upstream.returncode:
        git(path, 'remote', 'add', 'upstream', item['upstream_url'])
    git(path, 'remote', 'set-url', 'origin', item['url'])
    return inspect_checkout(root, item)


def revision_relation(path, current, target):
    """Positive ancestry is proof; a shallow negative is only unknown history."""
    forward = git(path, 'merge-base', '--is-ancestor', current, target, check=False)
    if forward.returncode == 0:
        return 'forward'
    if forward.returncode != 1:
        return 'unknown'
    backward = git(path, 'merge-base', '--is-ancestor', target, current, check=False)
    if backward.returncode == 0:
        return 'ahead'
    if backward.returncode != 1:
        return 'unknown'
    shallow = git(path, 'rev-parse', '--is-shallow-repository').stdout.strip()
    return 'unknown' if shallow == 'true' else 'diverged'


def advance_managed_checkout(root, item, state):
    """Move an existing clean checkout only after proving a forward update."""
    path, current, target = root / item['path'], state.get('commit'), item['commit']
    unresolved = 'Cannot prove a forward update; preserve current HEAD. Fetch and verify the pinned history or review the manifest lock before retrying'
    if not current:
        return {**state, 'action': unresolved}
    relation = revision_relation(path, current, target)
    if relation == 'unknown':
        try:
            # --deepen extends existing shallow history instead of cutting the new
            # target into a depth-one root. Full checkouts keep their full history.
            filtering = ['--filter=blob:none'] if item.get('sparse_paths') else []
            git(path, 'fetch', '--no-tags', f'--deepen={FORWARD_HISTORY_DEEPEN}', *filtering, 'origin', target)
            relation = revision_relation(path, current, target)
        except (FlowError, OSError):
            return {**state, 'action': unresolved + '; the bounded history fetch was unavailable'}
    if relation != 'forward':
        action = {
            'ahead': 'Current HEAD is newer than the locked commit; preserve it. Review the installed source and advance the manifest lock before installing',
            'diverged': 'Current HEAD and the locked commit have divergent history; preserve this checkout and reconcile the source and manifest separately',
        }.get(relation, unresolved + f'; history remains incomplete after one deepen={FORWARD_HISTORY_DEEPEN} attempt')
        return {**state, 'action': action}
    # Fetching may take time. Do not act on an earlier clean/identity observation
    # if another user changed the checkout while ancestry was being established.
    latest = inspect_checkout(root, item)
    if latest['status'] != 'revision-mismatch' or latest.get('commit') != current:
        return {**latest, 'action': 'Checkout changed during verification; preserve its current state and inspect before retrying'}
    if item.get('sparse_paths'):
        git(path, 'sparse-checkout', 'set', '--cone', *item['sparse_paths'])
    git(path, 'checkout', '--detach', target)
    return inspect_checkout(root, item)


def sync_dependencies(project, only=None, include_optional=False, status_only=False, migrate_origin=False, *, knowledge_source=None):
    root, entries = load_manifest(project)
    requested = set(only or [])
    if requested - {x['id'] for x in entries}:
        raise FlowError('Unknown dependency ID')
    selected = [x for x in entries if x['id'] in requested] if requested else [x for x in entries if include_optional or not x.get('optional')]
    if knowledge_source is not None:
        knowledge = next((x for x in selected if x['id'] == 'hcu-knowledge'), None)
        if knowledge is None or knowledge_source not in {'github', *knowledge.get('mirrors', {})}:
            raise FlowError('Select hcu-knowledge and a registered knowledge source')
    results = []
    for item in selected:
        try:
            state = inspect_checkout(root, item)
            if not status_only and migrate_origin and not state.get('external') and state['status'] == 'origin-mismatch':
                state = migrate_upstream_origin(root, item, state)
            if not status_only and not state.get('external') and state['status'] == 'missing':
                path = root / item['path']
                path.mkdir(parents=True)
                git(path, 'init')
                url = item['url']
                if item['id'] == 'hcu-knowledge' and knowledge_source not in {None, 'github'}:
                    url = item['mirrors'][knowledge_source]
                git(path, 'remote', 'add', 'origin', url)
                # No reset/clean: Git refuses collisions. Local changes are caught before fetching.
                filtering = ['--filter=blob:none'] if item.get('sparse_paths') else []
                git(path, 'fetch', '--depth', '1', *filtering, 'origin', item['commit'])
                if item.get('sparse_paths'):
                    git(path, 'sparse-checkout', 'set', '--cone', *item['sparse_paths'])
                git(path, 'checkout', '--detach', item['commit'])
                state = inspect_checkout(root, item)
            elif not status_only and not state.get('external') and state['status'] == 'revision-mismatch':
                state = advance_managed_checkout(root, item, state)
            if state['status'] == 'dirty':
                state['action'] = 'Preserve local edits; use a separate development checkout or resolve them before sync'
            if state['status'] == 'origin-mismatch' and 'action' not in state:
                state['action'] = 'Inspect origin; use --migrate-origin only for the registered upstream baseline'
            if state['status'] == 'ready' and item.get('lfs'):
                state['materials'] = 'Checkout inspection does not verify LFS payloads or the search index; full setup runs knowledge bootstrap/doctor'
            results.append(state)
        except (FlowError, OSError) as exc:
            results.append({'id': item['id'], 'status': 'unavailable', 'message': str(exc),
                            'optional': item.get('optional', False), 'action': 'Authenticate Git for this repository or retry after network recovery'})
    return {'status': 'ready' if all(x['status'] == 'ready' for x in results) else 'incomplete', 'dependencies': results}


def require_checkout(project, dependency):
    root, entries = load_manifest(project)
    item = next((x for x in entries if x['id'] == dependency), None)
    if item is None:
        raise FlowError('Dependency is not registered')
    state = inspect_checkout(root, item)
    if state['status'] != 'ready':
        raise FlowError(f'{dependency}: {state["status"]}; run scripts/bootstrap_thirdparty.py --only {dependency}, preserving local changes')
    return dependency_path(root, item)[0], item
