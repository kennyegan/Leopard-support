from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = "postgresql://techspot:local-demo-only@127.0.0.1:55432/techspot"
    provider: str = "scripted"
    allow_external_ai: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    external_call_limit: int = 15
    dialogue_mode: str = "conversational"
    corpus_version: str = "synthetic-2026-10-v3"
    approved_external_corpus_version: str = ""
    admin_token: str = ""
    web_origin: str = "http://127.0.0.1:3000"
    embed_cache: str = str(ROOT / ".cache/fastembed")
    high_score: float = 0.75
    low_score: float = 0.55
    app_mode: Literal["demo", "pilot"] = "demo"
    session_secret: str = ""
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    pilot_support_contact: str = ""
    pilot_qualification: bool = False
    retention_days: int = Field(default=30, ge=1, le=90)
    login_hours: int = Field(default=8, ge=1, le=24)
    user_requests_per_minute: int = Field(default=60, ge=1, le=240)
    user_turns_per_hour: int = Field(default=20, ge=1, le=200)
    global_turns_per_hour: int = Field(default=200, ge=1, le=2000)
    inference_concurrency: int = Field(default=10, ge=1, le=20)
    inference_enabled: bool = True
    pool_size: int = Field(default=12, ge=2, le=40)
    openrouter_zdr: bool = True
    retrieval_ranking: Literal["dense", "hybrid"] = "dense"
    embed_model_path: str = ""

    def validate_pilot(self):
        if self.app_mode != "pilot":
            return
        for value in (self.web_origin, self.oidc_issuer):
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("Pilot requires fixed HTTPS origin and OIDC issuer")
        if urlsplit(self.web_origin).path not in ("", "/"):
            raise ValueError("Pilot WEB_ORIGIN must not include a path")
        if len(self.session_secret) < 32 or not self.oidc_client_id or not self.oidc_client_secret:
            raise ValueError("Pilot requires a strong session secret and OIDC client configuration")
        if not self.pilot_support_contact or "local-demo-only" in self.database_url:
            raise ValueError("Pilot requires support contact and separate database credentials")
        if self.dialogue_mode != "conversational":
            raise ValueError("Pilot requires conversational policy mode")
        if self.provider == "scripted" and self.pilot_qualification:
            return
        if self.provider != "openrouter" or not self.openrouter_zdr:
            raise ValueError("Pilot requires qualified OpenRouter configuration with ZDR")
        if (
            not self.allow_external_ai
            or not self.openrouter_api_key
            or self.approved_external_corpus_version != self.corpus_version
        ):
            raise ValueError("Pilot external processing must be explicitly configured for this corpus")


@lru_cache
def settings():
    return Settings()


@lru_cache
def build_revision():
    path = ROOT / "BUILD_REVISION"
    return path.read_text().strip() if path.exists() else "workspace"
