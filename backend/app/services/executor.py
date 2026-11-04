"""Runs a flow: walks its nodes in order, passes values through named variables,
records a trace per step and stores the final status on the Run row.

The executor is idempotent: it only starts runs whose status is ``queued``, so a
Cloud Tasks redelivery of the same run is a harmless no-op.
"""

import logging
import time

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.errors import log_error, sanitize_error_for_user
from app.models import Flow, Run, utcnow
from app.schemas import FlowDefinition, LlmConfig, NodeDef, RetrieverConfig, StepTrace
from app.services import knowledge
from app.services.guardrails import redact_pii
from app.services.llm import LLMClient, get_llm_client

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("agentflow.executor")

PREVIEW_CHARS = 300


async def execute_run(run_id: str) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            logger.warning("Run %s no longer exists; nothing to execute", run_id)
            return
        if run.status != "queued":
            logger.info("Run %s is already %s; skipping", run_id, run.status)
            return

        run.status = "running"
        await session.commit()

        steps: list[StepTrace] = []
        try:
            flow = await session.get(Flow, run.flow_id)
            if flow is None:
                raise LookupError("flow for this run was deleted")
            definition = FlowDefinition.model_validate(flow.definition)
            result = await _run_pipeline(
                session, definition, run.input_message, run.owner_email, steps
            )
            run.output = {"result": result}
            run.status = "succeeded"
            run.error = None
        except Exception as exc:
            error_id = log_error(
                exc,
                context={"run_id": run_id, "flow_id": run.flow_id, "steps_completed": len(steps)},
            )
            run.status = "failed"
            run.error = sanitize_error_for_user(exc, error_id)

        run.steps = [step.model_dump() for step in steps]
        run.finished_at = utcnow()
        await session.commit()
        logger.info("Run %s finished with status=%s", run_id, run.status)


async def _run_pipeline(
    session: AsyncSession,
    definition: FlowDefinition,
    message: str,
    owner_email: str,
    steps: list[StepTrace],
) -> str:
    llm = get_llm_client()
    pii_enabled = get_settings().pii_redaction_enabled
    variables: dict[str, str] = {}

    for node in definition.nodes:
        started = time.perf_counter()
        try:
            with tracer.start_as_current_span(f"node.{node.type}") as span:
                span.set_attribute("agentflow.node.id", node.id)
                value = await _run_node(
                    node, message, variables, session, llm, owner_email, pii_enabled
                )
        except Exception:
            steps.append(_trace(node, "failed", started, ""))
            raise

        if node.output_var:
            variables[node.output_var] = value
        steps.append(_trace(node, "succeeded", started, value))
        if node.type == "output":
            return value

    raise RuntimeError("flow has no output node")  # guarded by FlowDefinition validation


async def _run_node(
    node: NodeDef,
    message: str,
    variables: dict[str, str],
    session: AsyncSession,
    llm: LLMClient,
    owner_email: str,
    pii_enabled: bool,
) -> str:
    if node.type == "chat_input":
        return message

    source = variables[node.input_var]  # validated: produced by an earlier node
    if node.type == "output":
        return source

    prompt = redact_pii(source) if pii_enabled else source

    if node.type == "llm":
        config = LlmConfig.model_validate(node.config)
        return await llm.generate(prompt, system_prompt=config.system_prompt)

    if node.type == "retriever":
        config = RetrieverConfig.model_validate(node.config)
        chunks = await knowledge.search(
            session,
            llm,
            owner_email=owner_email,
            collection=config.collection,
            query=prompt,
            top_k=config.top_k,
        )
        if pii_enabled:
            chunks = [redact_pii(chunk) for chunk in chunks]
        return "\n\n".join(chunks)

    raise ValueError(f"unsupported node type: {node.type}")


def _trace(node: NodeDef, status: str, started: float, value: str) -> StepTrace:
    return StepTrace(
        node_id=node.id,
        node_type=node.type,
        status=status,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        output_preview=value[:PREVIEW_CHARS],
    )
