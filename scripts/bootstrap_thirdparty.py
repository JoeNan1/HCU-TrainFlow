"""Fetch required locked dependencies, including HCU-Knowledge; this is not full setup."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hcu_trainflow.core import FlowError
from hcu_trainflow.dependencies import sync_dependencies, bind_dependency


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--only', nargs='+', help='Targeted dependency repair; default: all required dependencies')
    p.add_argument('--include-knowledge', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--knowledge-root', type=Path, help='Explicitly reuse an existing HCU-Knowledge checkout without pulling or resetting it')
    p.add_argument('--knowledge-source', choices=['github', 'gitlab'], help='Source for a new managed knowledge checkout (default: github); existing origins are preserved')
    p.add_argument('--status', action='store_true', help='Inspect only; no fetch or checkout')
    p.add_argument('--migrate-origin', action='store_true', help='Explicitly migrate a clean registered upstream baseline to its fork, preserving an upstream remote')
    p.add_argument('--bind', action='append', metavar='DEPENDENCY=PATH', help='Bind an existing external checkout without copying or resetting it; repeatable')
    p.add_argument('--bind-origin', action='append', metavar='DEPENDENCY=URL', help='Explicitly approve a fork origin for a matching --bind/--knowledge-root; the checkout must contain the pinned commit')
    args = p.parse_args()
    try:
        bindings = list(args.bind or [])
        if args.knowledge_root:
            bindings.append('hcu-knowledge=' + str(args.knowledge_root))
        if args.status and (bindings or args.bind_origin):
            raise FlowError('--status cannot modify dependency bindings or source approvals')
        origins = {}
        for value in args.bind_origin or []:
            if '=' not in value:
                raise FlowError('--bind-origin requires DEPENDENCY=URL')
            dependency, url = value.split('=', 1)
            if not dependency or not url or dependency in origins:
                raise FlowError('--bind-origin requires one URL per dependency')
            origins[dependency] = url
        parsed = []
        for value in bindings:
            if '=' not in value:
                raise FlowError('--bind requires DEPENDENCY=PATH')
            dependency, path = value.split('=', 1)
            if not dependency or not path:
                raise FlowError('--bind requires DEPENDENCY=PATH')
            parsed.append((dependency, path))
        if origins.keys() - {dependency for dependency, _ in parsed}:
            raise FlowError('--bind-origin requires a matching --bind or --knowledge-root')
        for dependency, path in parsed:
            bind_dependency(ROOT, dependency, path, **({'origin': origins[dependency]} if dependency in origins else {}))
        # Historical --include-knowledge remains a no-op: HCU-Knowledge is required.
        # It must not accidentally opt users into newly registered optional tools.
        result = sync_dependencies(ROOT, args.only, False, args.status, args.migrate_origin,
                                   **({'knowledge_source': args.knowledge_source} if args.knowledge_source else {}))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'ready' else 2
    except (FlowError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
