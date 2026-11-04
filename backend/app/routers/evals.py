"""Evaluation criteria, taken from the metrics that the installed Google ADK defines.

The list comes from ``google.adk.evaluation.eval_metrics.PrebuiltMetrics``, so it matches the ADK
version that is actually installed. Descriptions and default thresholds are ours.
"""

from fastapi import APIRouter

from app.deps import User
from app.errors import AppError

router = APIRouter(prefix="/api/v1", tags=["evals"])

# What each criterion compares, and what the author must supply for it to run.
_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "tool_trajectory_avg_score": (
        "Compares the tools the agent called with the expected tool calls.",
        "expected_tools",
    ),
    "response_match_score": (
        "ROUGE-1 overlap between the reply and the expected reply.",
        "expected_response",
    ),
    "final_response_match_v2": (
        "LLM judge: does the final answer match the expected answer?",
        "expected_response",
    ),
    "response_evaluation_score": ("LLM judge: how good is the reply, without a reference?", "none"),
    "rubric_based_final_response_quality_v1": (
        "Scores the final reply against your rubrics.",
        "rubrics",
    ),
    "rubric_based_tool_use_quality_v1": ("Scores tool use against your rubrics.", "rubrics"),
    "hallucinations_v1": ("Checks the reply for claims the context does not support.", "none"),
    "safety_v1": ("Checks the reply for harmful content.", "none"),
    "tool_call_count_v1": ("Counts tool calls against a limit.", "none"),
    "token_usage_v1": ("Counts tokens used per invocation against a limit.", "none"),
}


def _default_threshold(key: str) -> float:
    # ADK's trajectory score is exact-match by default. Everything else starts at 0.8.
    return 1.0 if key == "tool_trajectory_avg_score" else 0.8


@router.get("/eval-metrics")
async def eval_metrics(user: User) -> list[dict]:
    try:
        from google.adk.evaluation.eval_metrics import PrebuiltMetrics
    except ImportError as exc:  # pragma: no cover - google-adk is a declared dependency
        raise AppError(503, "google-adk is not installed on the server") from exc

    metrics = []
    for metric in PrebuiltMetrics:
        key = metric.value
        description, requires = _DESCRIPTIONS.get(key, (key.replace("_", " "), "none"))
        metrics.append(
            {
                "key": key,
                "label": metric.name.replace("_", " ").lower().capitalize(),
                "description": description,
                "requires": requires,
                "default_threshold": _default_threshold(key),
            }
        )
    return metrics
