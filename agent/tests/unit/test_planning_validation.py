import pytest

from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.validation import PlanValidationError, PlanValidator


def incident():
    return IncidentContext(
        incident_id="i1",
        tenant_id="t1",
        thread_id="th1",
        goal="test",
        trace_id="trace-1",
    )


@pytest.mark.parametrize(
    ("tasks", "code"),
    [
        (
            [
                TaskSpec(
                    task_id="a",
                    description="a",
                    required_role="diagnosis",
                    dependencies=["b"],
                ),
                TaskSpec(
                    task_id="b",
                    description="b",
                    required_role="diagnosis",
                    dependencies=["a"],
                ),
            ],
            "PLAN_CYCLE",
        ),
        (
            [
                TaskSpec(
                    task_id="a",
                    description="a",
                    required_role="diagnosis",
                    allowed_capabilities={"assignment.create"},
                )
            ],
            "PLAN_WRITE_CAPABILITY_DENIED",
        ),
    ],
)
def test_validator_rejects_unsafe_plans(tasks, code):
    with pytest.raises(PlanValidationError, match=code):
        PlanValidator().validate(incident(), PlanDraft(plan_id="p1", tasks=tasks))
