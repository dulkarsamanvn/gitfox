"""Local provider configuration; public views never contain API keys."""

import json
import os
import re
import tempfile
from pathlib import Path
from threading import RLock
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.core.config import BACKEND_DIR, Settings

Provider = Literal["openai", "anthropic", "gemini"]
PROVIDERS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic Claude",
    "gemini": "Google Gemini",
}
LLM_SETTINGS_PATH = BACKEND_DIR / ".llm-settings.json"


class LlmError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code, self.status = code, status
        super().__init__(message)


class LlmDraft(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    provider: Provider
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=2048, repr=False)

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("models/"):
            value = value.removeprefix("models/")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", value) is None:
            raise ValueError("Enter a model ID without URLs, query strings, or path segments")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if any(ord(char) < 33 or ord(char) > 126 for char in value):
                raise ValueError("API key must contain printable characters without whitespace")
        return value

    @model_validator(mode="after")
    def provider_model(self) -> Self:
        if self.provider != "openai" and ":" in self.model:
            raise ValueError("Invalid model ID for this provider")
        return self


class _Profile(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    model: str = Field(default="", max_length=200)
    api_key: SecretStr | None = Field(default=None, repr=False)


class _SavedConfiguration(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    version: Literal[1] = 1
    active_provider: Provider
    profiles: dict[Provider, _Profile]


class ProviderConfiguration(BaseModel):
    id: Provider
    label: str
    model: str
    key_configured: bool


class LlmConfiguration(BaseModel):
    active_provider: Provider
    providers: list[ProviderConfiguration]


class LlmConfigurationStore:
    def __init__(self, settings: Settings, path: Path = LLM_SETTINGS_PATH) -> None:
        self._path = path
        self._lock = RLock()
        self._initial = {
            provider: _Profile(
                model=getattr(settings, f"{provider}_model") or "",
                api_key=getattr(settings, f"{provider}_api_key"),
            )
            for provider in PROVIDERS
        }
        self._default_provider = settings.llm_provider

    def _load(self) -> _SavedConfiguration:
        state = _SavedConfiguration(
            active_provider=self._default_provider,
            profiles={
                provider: _Profile(model=profile.model)
                for provider, profile in self._initial.items()
            },
        )
        try:
            if self._path.exists():
                with self._path.open("rb") as stream:
                    raw = stream.read(16_385)
                if len(raw) > 16_384:
                    raise ValueError
                saved = _SavedConfiguration.model_validate_json(raw)
                for provider, profile in saved.profiles.items():
                    state.profiles[provider] = profile
                state.active_provider = saved.active_provider
            return state
        except (OSError, ValueError, RecursionError):
            raise LlmError(
                "llm_config_unavailable", "LLM settings could not be loaded.", 503
            ) from None

    def _public(self, state: _SavedConfiguration) -> LlmConfiguration:
        return LlmConfiguration(
            active_provider=state.active_provider,
            providers=[
                ProviderConfiguration(
                    id=provider,
                    label=label,
                    model=state.profiles[provider].model,
                    key_configured=bool(
                        state.profiles[provider].api_key or self._initial[provider].api_key
                    ),
                )
                for provider, label in PROVIDERS.items()
            ],
        )

    def catalog(self) -> LlmConfiguration:
        with self._lock:
            return self._public(self._load())

    def resolve(self, draft: LlmDraft) -> tuple[str, SecretStr]:
        with self._lock:
            key = (
                draft.api_key
                or self._load().profiles[draft.provider].api_key
                or self._initial[draft.provider].api_key
            )
        if key is None or not key.get_secret_value():
            raise LlmError("llm_key_missing", "Enter an API key for this provider.")
        return draft.model, key

    def save(self, draft: LlmDraft) -> LlmConfiguration:
        with self._lock:
            state = self._load()
            state.profiles[draft.provider] = _Profile(
                model=draft.model, api_key=draft.api_key or state.profiles[draft.provider].api_key
            )
            state.active_provider = draft.provider
            # Only this private serialization path unwraps keys. API responses use _public.
            payload = {
                "version": 1,
                "active_provider": state.active_provider,
                "profiles": {
                    provider: {
                        "model": profile.model,
                        "api_key": profile.api_key.get_secret_value() if profile.api_key else None,
                    }
                    for provider, profile in state.profiles.items()
                },
            }
            temporary: str | None = None
            try:
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".llm-settings-", suffix=".tmp", dir=self._path.parent
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._path)
            except OSError:
                raise LlmError(
                    "llm_config_unavailable", "LLM settings could not be saved.", 503
                ) from None
            finally:
                if temporary:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
            return self._public(state)
