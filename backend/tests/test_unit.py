"""Unit tests for configuration, validation, guardrails and chunking (no I/O)."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import FlowDefinition
from app.services.guardrails import redact_pii
from app.services.knowledge import chunk_text


def test_local_defaults_are_valid():
    settings = Settings(_env_file=None)
    assert settings.auth_mode == "dev"
    assert settings.llm_provider == "mock"


def test_production_refuses_dev_auth_and_mock_llm():
    with pytest.raises(ValidationError) as info:
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="dev",
            llm_provider="mock",
            cors_origins="https://ui.example.com",
        )
    message = str(info.value)
    assert "AUTH_MODE=google" in message
    assert "LLM_PROVIDER=gemini or claude" in message


def test_production_accepts_google_auth_with_vertex_gemini():
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_mode="google",
        google_client_id="client.apps.googleusercontent.com",
        llm_provider="gemini",
        genai_backend="vertex",
        gcp_project_id="my-project",
        cors_origins="https://ui.example.com",
    )
    assert settings.cors_origin_list == ["https://ui.example.com"]


def test_gemini_api_key_backend_requires_key():
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        Settings(_env_file=None, llm_provider="gemini", genai_backend="api_key")


def test_claude_requires_project_for_vertex():
    with pytest.raises(ValidationError, match="GCP_PROJECT_ID"):
        Settings(_env_file=None, llm_provider="claude", gemini_api_key="k")


def test_redacts_common_pii():
    text = "Mail a.b@corp.io, SSN 123-45-6789, card 4111 1111 1111 1111, phone +1 415 555 0100"
    redacted = redact_pii(text)
    assert "a.b@corp.io" not in redacted
    assert "123-45-6789" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert "415 555 0100" not in redacted
    assert "[EMAIL_REDACTED]" in redacted
    assert "[CREDIT_CARD_REDACTED]" in redacted


def test_plain_text_is_untouched():
    text = "Refunds are issued within 14 days."
    assert redact_pii(text) == text


def test_chunk_text_overlaps_and_covers_everything():
    text = "abcdefghij" * 50  # 500 chars
    chunks = chunk_text(text, size=200, overlap=50)
    assert chunks[0] == text[:200]
    assert chunks[1][:50] == chunks[0][-50:]
    assert chunks[-1] == text[-len(chunks[-1]) :]


def test_chunk_text_empty_input_returns_no_chunks():
    assert chunk_text("   ") == []


def test_chunk_size_must_exceed_overlap():
    with pytest.raises(ValueError):
        chunk_text("hello", size=10, overlap=10)


def _node(**overrides):
    base = {"id": "n", "type": "llm", "input_var": "q", "output_var": "a", "config": {}}
    base.update(overrides)
    return base


def test_flow_requires_single_output_node_last():
    definition = {
        "nodes": [
            {"id": "in", "type": "chat_input", "output_var": "q"},
            {"id": "out", "type": "output", "input_var": "q"},
            {"id": "out2", "type": "output", "input_var": "q"},
        ]
    }
    with pytest.raises(ValidationError, match="exactly one output node"):
        FlowDefinition.model_validate(definition)


def test_flow_rejects_variable_read_before_written():
    definition = {
        "nodes": [
            {"id": "in", "type": "chat_input", "output_var": "q"},
            _node(id="ask", input_var="later", output_var="a"),
            {"id": "out", "type": "output", "input_var": "a"},
        ]
    }
    with pytest.raises(ValidationError, match="before it is produced"):
        FlowDefinition.model_validate(definition)


def test_retriever_config_is_validated():
    definition = {
        "nodes": [
            {"id": "in", "type": "chat_input", "output_var": "q"},
            {
                "id": "kb",
                "type": "retriever",
                "input_var": "q",
                "output_var": "ctx",
                "config": {"collection": "Not Valid!"},
            },
            {"id": "out", "type": "output", "input_var": "ctx"},
        ]
    }
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(definition)


def test_unknown_config_keys_are_rejected():
    definition = {
        "nodes": [
            {"id": "in", "type": "chat_input", "output_var": "q"},
            _node(input_var="q", output_var="a", config={"temperature": 0.2}),
            {"id": "out", "type": "output", "input_var": "a"},
        ]
    }
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(definition)
