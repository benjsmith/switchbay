"""Generate image / video / voice via configured media providers.

Reads prefs from ``media_settings.effective`` (or explicit provider/model).
Saves bytes under the workspace for inspection. No auto-spend without an
explicit call — Settings choices alone do nothing.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import media_settings, secrets

log = logging.getLogger("switchbay.media_gen")

XAI_BASE = "https://api.x.ai/v1"
OPENAI_BASE = "https://api.openai.com/v1"


class MediaGenError(RuntimeError):
    pass


def _key(provider: str) -> str:
    k = secrets.get(provider)
    if k:
        return k
    import os
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    if env and os.environ.get(env):
        return os.environ[env]
    raise MediaGenError(f"no API key for {provider}")


def _http_json(
    method: str,
    url: str,
    *,
    key: str,
    body: dict[str, Any] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "switchbay-media-gen/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:800]
        raise MediaGenError(f"HTTP {e.code} {url}: {err}") from e
    if not raw.strip():
        return {}
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MediaGenError(f"non-JSON from {url}: {raw[:200]}") from e
    return out if isinstance(out, dict) else {"data": out}


def _download(url: str, dest: Path, *, timeout: float = 180) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "switchbay-media-gen/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dest.write_bytes(r.read())
    return dest


def media_outdir(workspace: Path) -> Path:
    p = workspace / "vault" / "exports" / "media-test"
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_image(
    workspace: Path,
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    filename: str = "test-image.png",
) -> dict[str, Any]:
    """xAI Imagine image → local PNG."""
    eff = media_settings.effective("image") if not provider else {
        "ok": True, "provider": provider,
        "model": model or "grok-imagine-image",
    }
    if not eff or not eff.get("ok"):
        # Fall back to xAI if keyed
        if media_settings.provider_has_key("xai"):
            pid, mid = "xai", model or "grok-imagine-image"
        else:
            raise MediaGenError(eff.get("error") if eff else "image not configured")
    else:
        pid = str(provider or eff["provider"])
        mid = str(model or eff["model"] or "grok-imagine-image")

    if pid != "xai":
        # OpenAI images also work; prefer xAI path for this product.
        if pid == "openai":
            return _openai_image(workspace, prompt, model=mid, filename=filename)
        raise MediaGenError(f"image gen not implemented for {pid}")

    key = _key("xai")
    body = _http_json(
        "POST", f"{XAI_BASE}/images/generations",
        key=key,
        body={
            "model": mid,
            "prompt": prompt,
            "n": 1,
            "response_format": "url",
        },
        timeout=180,
    )
    data = body.get("data") or []
    if not data:
        raise MediaGenError(f"no image data: {body}")
    url = str(data[0].get("url") or "")
    b64 = data[0].get("b64_json")
    dest = media_outdir(workspace) / filename
    if url:
        _download(url, dest)
    elif b64:
        import base64
        dest.write_bytes(base64.b64decode(b64))
    else:
        raise MediaGenError(f"no url/b64 in image response: {data[0]}")
    return {
        "ok": True,
        "modality": "image",
        "provider": pid,
        "model": mid,
        "path": str(dest),
        "prompt": prompt,
        "url": url or None,
    }


def _openai_image(
    workspace: Path, prompt: str, *, model: str, filename: str,
) -> dict[str, Any]:
    key = _key("openai")
    body = _http_json(
        "POST", f"{OPENAI_BASE}/images/generations",
        key=key,
        body={"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"},
        timeout=180,
    )
    data = body.get("data") or []
    if not data:
        raise MediaGenError(f"no openai image: {body}")
    dest = media_outdir(workspace) / filename
    url = str(data[0].get("url") or "")
    b64 = data[0].get("b64_json")
    if url:
        _download(url, dest)
    elif b64:
        import base64
        dest.write_bytes(base64.b64decode(b64))
    else:
        raise MediaGenError(f"no url/b64: {data[0]}")
    return {
        "ok": True, "modality": "image", "provider": "openai",
        "model": model, "path": str(dest), "prompt": prompt, "url": url or None,
    }


def generate_video(
    workspace: Path,
    prompt: str,
    *,
    duration: int = 6,
    provider: str | None = None,
    model: str | None = None,
    image_url: str | None = None,
    filename: str = "test-video.mp4",
    poll_s: float = 5.0,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    """xAI Imagine video (async poll) → local MP4."""
    pid = provider or "xai"
    mid = model or "grok-imagine-video"
    if pid != "xai":
        raise MediaGenError(f"video gen not implemented for {pid}")
    key = _key("xai")
    payload: dict[str, Any] = {
        "model": mid,
        "prompt": prompt,
        "duration": int(duration),
    }
    if image_url:
        payload["image"] = {"url": image_url}

    start = _http_json(
        "POST", f"{XAI_BASE}/videos/generations",
        key=key, body=payload, timeout=60,
    )
    request_id = str(
        start.get("request_id")
        or start.get("id")
        or (start.get("data") or {}).get("request_id")
        or ""
    )
    if not request_id:
        # Some responses return video immediately
        url = _extract_video_url(start)
        if url:
            dest = media_outdir(workspace) / filename
            _download(url, dest)
            return {
                "ok": True, "modality": "video", "provider": pid,
                "model": mid, "path": str(dest), "prompt": prompt,
                "duration": duration, "url": url, "request_id": None,
            }
        raise MediaGenError(f"no request_id from video start: {start}")

    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _http_json(
            "GET", f"{XAI_BASE}/videos/{request_id}",
            key=key, timeout=60,
        )
        status = str(last.get("status") or "").lower()
        if status in ("done", "completed", "succeeded", "success"):
            url = _extract_video_url(last)
            if not url:
                raise MediaGenError(f"video done but no url: {last}")
            dest = media_outdir(workspace) / filename
            _download(url, dest)
            return {
                "ok": True, "modality": "video", "provider": pid,
                "model": mid, "path": str(dest), "prompt": prompt,
                "duration": duration, "url": url, "request_id": request_id,
            }
        if status in ("failed", "expired", "error", "cancelled"):
            raise MediaGenError(f"video {status}: {last}")
        time.sleep(poll_s)
    raise MediaGenError(f"video timed out after {timeout_s}s: {last}")


def _extract_video_url(body: dict[str, Any]) -> str:
    v = body.get("video")
    if isinstance(v, dict) and v.get("url"):
        return str(v["url"])
    if body.get("url"):
        return str(body["url"])
    data = body.get("data")
    if isinstance(data, list) and data:
        d0 = data[0]
        if isinstance(d0, dict):
            if d0.get("url"):
                return str(d0["url"])
            if isinstance(d0.get("video"), dict) and d0["video"].get("url"):
                return str(d0["video"]["url"])
    return ""


def generate_voice(
    workspace: Path,
    text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    voice: str | None = None,
    filename: str = "test-voice.mp3",
) -> dict[str, Any]:
    """TTS → local audio. Prefers OpenAI; falls back to xAI /v1/tts."""
    pid = provider
    if not pid:
        if media_settings.provider_has_key("openai"):
            pid = "openai"
        elif media_settings.provider_has_key("xai"):
            pid = "xai"
        else:
            raise MediaGenError("no voice provider key (openai or xai)")

    if pid == "xai":
        return _xai_tts(
            workspace, text,
            voice=voice or "eve",
            filename=filename,
        )
    if pid != "openai":
        raise MediaGenError(f"voice gen not implemented for {pid}")

    mid = model or "tts-1"
    if "realtime" in mid or mid == "grok-voice":
        mid = "tts-1"
    key = _key("openai")
    payload = {
        "model": mid if mid.startswith("tts") or "tts" in mid else "tts-1",
        "input": text[:4096],
        "voice": voice or "alloy",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OPENAI_BASE}/audio/speech",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "switchbay-media-gen/1.0",
        },
    )
    dest = media_outdir(workspace) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:800]
        # Auto-fallback to xAI if OpenAI is out of quota
        if e.code in (429, 402) and media_settings.provider_has_key("xai"):
            log.warning("OpenAI TTS failed (%s) — falling back to xAI", e.code)
            return _xai_tts(
                workspace, text,
                voice="eve",
                filename=filename,
            )
        raise MediaGenError(f"TTS HTTP {e.code}: {err}") from e
    return {
        "ok": True,
        "modality": "voice",
        "provider": "openai",
        "model": payload["model"],
        "path": str(dest),
        "text": text[:200],
        "voice": payload["voice"],
    }


def _xai_tts(
    workspace: Path,
    text: str,
    *,
    voice: str = "eve",
    language: str = "en",
    filename: str = "test-voice.mp3",
) -> dict[str, Any]:
    """xAI Grok TTS: POST /v1/tts → audio/mpeg."""
    key = _key("xai")
    payload = {
        "text": text[:15000],
        "voice": voice.lower(),
        "language": language,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{XAI_BASE}/tts",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "switchbay-media-gen/1.0",
        },
    )
    dest = media_outdir(workspace) / filename
    if not dest.suffix:
        dest = dest.with_suffix(".mp3")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:800]
        raise MediaGenError(f"xAI TTS HTTP {e.code}: {err}") from e
    return {
        "ok": True,
        "modality": "voice",
        "provider": "xai",
        "model": "grok-voice",
        "path": str(dest),
        "text": text[:200],
        "voice": voice,
    }
