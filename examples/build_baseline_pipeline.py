"""Generate a declarative baseline Pipeline from task-local site contracts.

This command prepares JSON only. Execution still uses pipeline-run and the
Task's real permission, resource lease, Operation and Flow checks.
"""
import argparse
import json
from pathlib import Path

from hcu_trainflow.services import baseline_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", help="JSON with environment, training, training_contract, profiling, project")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    site = json.loads(Path(args.site).read_text(encoding="utf-8"))
    plan = baseline_pipeline(**site)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a reviewed plan accidentally.
    with output.open("x", encoding="utf-8") as stream:
        json.dump({"pipeline": plan.to_dict()}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(str(output.resolve()))


if __name__ == "__main__":
    main()
