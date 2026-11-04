"""Model client wiring, checked with stub SDK clients (no network)."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import llm


class _StubModels:
    def __init__(self):
        self.calls = []

    async def generate_content(self, model, contents, config):
        self.calls.append(("generate", model, contents, config.system_instruction))
        return SimpleNamespace(text="stub reply")

    async def embed_content(self, model, contents, config):
        self.calls.append(("embed", model, list(contents), config.output_dimensionality))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2]) for _ in contents])


@pytest.fixture
def stub_models(monkeypatch):
    models = _StubModels()
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    monkeypatch.setattr(llm, "_build_genai_client", lambda settings: client)
    return models


async def test_gemini_provider_generates_with_system_prompt(stub_models):
    settings = Settings(
        _env_file=None, llm_provider="gemini", gemini_api_key="k", gemini_model="gemini-test"
    )
    client = llm.build_llm_client(settings)

    reply = await client.generate("hello", system_prompt="be brief")

    assert reply == "stub reply"
    assert stub_models.calls[0] == ("generate", "gemini-test", "hello", "be brief")


async def test_embeddings_request_configured_dimension(stub_models):
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key="k",
        embedding_model="text-embedding-test",
        embedding_dim=2,
    )
    client = llm.build_llm_client(settings)

    vectors = await client.embed(["a", "b"])

    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert stub_models.calls[0] == ("embed", "text-embedding-test", ["a", "b"], 2)


def test_mock_provider_is_deterministic_and_sized():
    client = llm.build_llm_client(Settings(_env_file=None, embedding_dim=16))
    first = client._hash_vector("same text")
    assert first == client._hash_vector("same text")
    assert len(first) == 16
