#!/usr/bin/env python3
"""Check a reusable intake document without expanding or executing anything.

The intake is stated once and reused by several tasks, so a stale or
self-contradictory value would keep being reused. This reports what would block
an expansion (budget above the authority envelope, a task using a contract or
command that no longer exists, a lease on a device that is not admitted, a
profile that disagrees with the declared engine/model family) and what is worth
a second look (missing contract fields, no envelope, leases that must be
re-acquired per run).

Exit codes: 0 pass, 2 attention, 1 the document itself is malformed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hcu_trainflow import intake
from hcu_trainflow.core import FlowError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document', help='Reusable intake JSON')
    args = parser.parse_args(argv)
    try:
        document = json.loads(Path(args.document).read_text(encoding='utf-8'))
        result = intake.check(document)
    except (FlowError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
