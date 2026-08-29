"""
ElevenLabs speech in and out. The API key lives here, server-side, only.
Nothing in this file is ever sent to the browser.
"""
import json
import mimetypes
import os
import urllib.request
import urllib.error
import uuid

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
DEFAULT_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"  # "Daniel" — even, professional, British


class VoiceError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is not set in .env")
    return key


def text_to_speech(text: str) -> bytes:
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID)
    url = TTS_URL.format(voice_id=voice_id)
    payload = json.dumps(
        {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "xi-api-key": _api_key(),
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise VoiceError(f"ElevenLabs TTS failed ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise VoiceError(f"Can't reach ElevenLabs (network): {exc}") from exc


def _build_multipart(fields: dict, file_field: str, filename: str, file_bytes: bytes, content_type: str):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n")
    body = "".join(parts).encode("utf-8")
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    body += file_bytes
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, boundary


def speech_to_text(audio_bytes: bytes, content_type: str = "audio/webm") -> str:
    ext = mimetypes.guess_extension(content_type) or ".webm"
    body, boundary = _build_multipart(
        {"model_id": "scribe_v1"}, "file", f"audio{ext}", audio_bytes, content_type
    )
    req = urllib.request.Request(
        STT_URL,
        data=body,
        method="POST",
        headers={
            "xi-api-key": _api_key(),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise VoiceError(f"ElevenLabs Scribe failed ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise VoiceError(f"Can't reach ElevenLabs (network): {exc}") from exc
    return data.get("text", "")
