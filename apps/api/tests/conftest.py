"""Tests remain offline even when a developer enables a real provider in .env."""

import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def offline_provider(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "app_mode", "demo")
    monkeypatch.setattr(cfg, "dialogue_mode", "classic")
    monkeypatch.setattr(cfg, "corpus_version", "synthetic-2026-10-v1")
    monkeypatch.setattr(cfg, "provider", "scripted")
    monkeypatch.setattr(cfg, "allow_external_ai", False)
    monkeypatch.setattr(cfg, "approved_external_corpus_version", "")
    monkeypatch.setattr(cfg, "gemini_api_key", "")
    monkeypatch.setattr(cfg, "openrouter_api_key", "")
    monkeypatch.setattr(cfg, "external_call_limit", 15)

    def forbidden(*args, **kwargs):
        raise AssertionError("Live provider transport is forbidden in tests; install an explicit double")

    monkeypatch.setattr("app.llm.httpx.post", forbidden)
