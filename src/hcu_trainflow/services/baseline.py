"""Build a baseline DAG; site launch/transfer commands remain caller inputs.

The step list lives in the module catalog as the declarative
``baseline-pipeline`` preset, so the same wiring feeds both this Python entry
point and ``module-run``.
"""
from ..kernel import PipelinePlan


def baseline_pipeline(*, environment, training, training_contract, profiling, project):
    """A single persisted run from live checks to scoped baseline qualification.

    Training stdout is a complete Megatron log. Profiling stdout is a JSON
    ``files`` receipt (including ``trace``), after the site's launcher has
    collected outputs locally. Each file has an absolute path and SHA-256.
    No path to a future output is used as an immutable Pipeline input.
    """
    from ..catalog import preset_plan
    return preset_plan("baseline-pipeline", {
        "environment": environment, "training": training,
        "training_contract": training_contract, "profiling": profiling,
        "project": str(project),
    })
