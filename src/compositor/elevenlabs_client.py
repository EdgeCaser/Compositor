from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request

from .secure_store import AppSettingsStore

BASE_URL = "https://api.elevenlabs.io/v1"


class ElevenLabsError(RuntimeError):
    pass


@dataclass
class ElevenLabsClient:
    api_key: str
    timeout_s: int = 20

    def get_subscription(self) -> dict[str, Any]:
        body = self._request_json("/user/subscription")
        return {
            "tier": body.get("tier"),
            "character_count": body.get("character_count"),
            "character_limit": body.get("character_limit"),
            "next_reset_unix": body.get("next_character_count_reset_unix"),
            "can_use_instant_voice_cloning": body.get("can_use_instant_voice_cloning"),
        }

    def list_voices(self) -> list[dict[str, Any]]:
        body = self._request_json("/voices")
        voices = body.get("voices") or []
        result: list[dict[str, Any]] = []
        for voice in voices:
            if not isinstance(voice, dict):
                continue
            labels = voice.get("labels") if isinstance(voice.get("labels"), dict) else {}
            result.append(
                {
                    "voice_id": voice.get("voice_id"),
                    "name": voice.get("name"),
                    "category": voice.get("category"),
                    "description": voice.get("description"),
                    "labels": labels,
                    "preview_url": voice.get("preview_url"),
                }
            )
        return result

    def _request_json(self, path: str) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        req = request.Request(
            url,
            headers={
                "xi-api-key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "Compositor/0.4",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ElevenLabsError(f"ElevenLabs HTTP {exc.code}: {body[:240]}") from exc
        except error.URLError as exc:
            raise ElevenLabsError(f"ElevenLabs request failed: {exc.reason}") from exc
        except OSError as exc:
            raise ElevenLabsError(f"ElevenLabs request failed: {exc}") from exc
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ElevenLabsError("ElevenLabs returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise ElevenLabsError("ElevenLabs returned an unexpected response shape.")
        return payload

    def synthesize(self, voice_id: str, text: str, *, model_id: str = "eleven_multilingual_v2") -> bytes:
        if not voice_id:
            raise ElevenLabsError("voice_id is required for synthesis")
        if not text or not text.strip():
            raise ElevenLabsError("text is required for synthesis")
        url = f"{BASE_URL}/text-to-speech/{voice_id}"
        body = json.dumps({"text": text, "model_id": model_id}).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
                "User-Agent": "Compositor/0.4",
            },
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                return response.read()
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise ElevenLabsError(f"ElevenLabs HTTP {exc.code}: {err_body[:240]}") from exc
        except error.URLError as exc:
            raise ElevenLabsError(f"ElevenLabs request failed: {exc.reason}") from exc
        except OSError as exc:
            raise ElevenLabsError(f"ElevenLabs request failed: {exc}") from exc


class ElevenLabsService:
    def __init__(self, settings: AppSettingsStore) -> None:
        self.settings = settings

    def public_settings(self) -> dict[str, Any]:
        return self.settings.public_settings()

    def configure_api_key(self, api_key: str, *, validate: bool = False) -> dict[str, Any]:
        api_key = str(api_key or "").strip()
        if not api_key:
            raise ValueError("api_key is required")
        self.settings.set_elevenlabs_api_key(api_key)
        if validate:
            try:
                return self.refresh()
            except ElevenLabsError as exc:
                return self.settings.update_elevenlabs_cache(last_error=str(exc))
        return self.settings.public_settings()

    def clear_api_key(self) -> dict[str, Any]:
        return self.settings.clear_elevenlabs_api_key()

    def refresh(self) -> dict[str, Any]:
        client = self._client()
        account = client.get_subscription()
        voices = client.list_voices()
        return self.settings.update_elevenlabs_cache(account=account, cached_voices=voices, last_error=None)

    def list_cached_or_live_voices(self, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            settings = self.refresh()
        else:
            settings = self.settings.public_settings()
        provider = settings.get("providers", {}).get("elevenlabs", {})
        return {
            "configured": bool(provider.get("configured")),
            "voices": list(provider.get("cached_voices") or []),
            "account": provider.get("account"),
            "last_validated_at": provider.get("last_validated_at"),
            "last_error": provider.get("last_error"),
        }

    def _client(self) -> ElevenLabsClient:
        api_key = self.settings.get_elevenlabs_api_key()
        if not api_key:
            raise ValueError("ElevenLabs API key is not configured.")
        return ElevenLabsClient(api_key=api_key)

    def synthesize(self, voice_id: str, text: str) -> bytes:
        return self._client().synthesize(voice_id, text)
