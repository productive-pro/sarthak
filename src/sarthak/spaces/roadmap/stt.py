"""
Sarthak — Unified Speech-to-Text (STT) layer.

Provider selection is driven by config.toml [stt] section:

    [stt]
    provider = "whisper"    # whisper | openai | groq | deepgram | assemblyai
    language  = "auto"      # spoken language (en, fr, …) or "auto" / ""

Provider-specific sections (only the active one is used):

    [stt.whisper]
    model      = "base.en"
    model_path = ""
    device     = "CPU"
    beam_size  = 5
    threads    = 0

    [stt.openai]
    api_key    = ""          # or env OPENAI_API_KEY
    model      = "whisper-1"
    base_url   = ""

    [stt.groq]
    api_key    = ""          # or env GROQ_API_KEY
    model      = "whisper-large-v3-turbo"

    [stt.deepgram]
    api_key    = ""          # or env DEEPGRAM_API_KEY
    model      = "nova-2"
    tier       = ""

    [stt.assemblyai]
    api_key    = ""          # or env ASSEMBLYAI_API_KEY

Public surface
--------------
    is_stt_available() -> bool
    invalidate_stt_cache()
    transcribe(path) -> str
    transcribe_vtt(path) -> str
    stt_provider_name() -> str
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ── Whisper constants ──────────────────────────────────────────────────────────
_WHISPER_MODELS_DIR = Path.home() / ".sarthak_ai" / "whisper_models"
_MIN_MODEL_BYTES = 10 * 1024 * 1024  # 10 MB

# ── Availability cache ─────────────────────────────────────────────────────────
_available: bool | None = None


def invalidate_stt_cache() -> None:
    global _available
    _available = None


def is_stt_available() -> bool:
    global _available
    if _available is not None:
        return _available
    provider = _provider()
    try:
        if provider == "whisper":
            _whisper_find_cli()
            _whisper_find_model(_stt_cfg("whisper"))
            _available = True
        else:
            _available = bool(_api_key(provider, _PROVIDER_ENV[provider]))
    except Exception:
        _available = False
    return _available


def stt_provider_name() -> str:
    p = _provider()
    return p if is_stt_available() else "none"


# ── Config helpers ─────────────────────────────────────────────────────────────
_PROVIDER_ENV = {
    "openai":     "OPENAI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "deepgram":   "DEEPGRAM_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
}


def _full_cfg() -> dict[str, Any]:
    try:
        from sarthak.core.config import load_config
        return load_config()
    except Exception:
        return {}


def _provider() -> str:
    return _full_cfg().get("stt", {}).get("provider", "whisper").strip().lower()


def _stt_cfg(section: str) -> dict[str, Any]:
    cfg = _full_cfg()
    sub = cfg.get("stt", {}).get(section, {})
    # Legacy [whisper] fallback for existing installs
    if section == "whisper" and not sub:
        sub = cfg.get("whisper", {})
    return sub


def _language() -> str:
    cfg = _full_cfg()
    lang = cfg.get("stt", {}).get("language", "").strip()
    if not lang:
        lang = _stt_cfg(_provider()).get("language", "auto").strip()
    return lang or "auto"


def _api_key(provider: str, env_var: str) -> str:
    key = _stt_cfg(provider).get("api_key", "").strip()
    return key or os.environ.get(env_var, "").strip()


# ── Public API ─────────────────────────────────────────────────────────────────

async def transcribe(audio_path: Path) -> str:
    """Return plain-text transcript using the configured provider."""
    provider = _provider()
    if provider == "whisper":
        return await _whisper_transcribe(audio_path, vtt=False)
    if provider == "openai":
        return await _openai_transcribe(audio_path)
    if provider == "groq":
        return await _groq_transcribe(audio_path)
    if provider == "deepgram":
        return await _deepgram_transcribe(audio_path)
    if provider == "assemblyai":
        return await _assemblyai_transcribe(audio_path)
    raise RuntimeError(f"Unknown STT provider: {provider!r}")


async def transcribe_vtt(audio_path: Path) -> str:
    """Return WebVTT with timestamps; cloud providers produce a single cue."""
    if _provider() == "whisper":
        return await _whisper_transcribe_vtt(audio_path)
    plain = await transcribe(audio_path)
    if not plain.strip():
        return ""
    return f"WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n{plain.strip()}"


# ── Whisper (local) ────────────────────────────────────────────────────────────

def _whisper_find_cli() -> str:
    for name in ("whisper-cli", "whisper"):
        if shutil.which(name):
            return name
    raise FileNotFoundError(
        "whisper-cli not found in PATH. "
        "Install from: https://github.com/ggml-org/whisper.cpp"
    )


def _whisper_find_model(cfg: dict) -> str:
    explicit = cfg.get("model_path", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
        raise FileNotFoundError(f"whisper model_path not found: {p}")

    model_name = cfg.get("model", "base.en")
    for name in (f"ggml-{model_name}.bin", f"ggml-{model_name.split('.')[0]}.bin"):
        p = _WHISPER_MODELS_DIR / name
        if p.exists() and p.stat().st_size >= _MIN_MODEL_BYTES:
            return str(p)

    for f in sorted(_WHISPER_MODELS_DIR.glob("ggml-*.bin")):
        if f.stat().st_size >= _MIN_MODEL_BYTES:
            return str(f)

    raise FileNotFoundError(
        f"No whisper model found in {_WHISPER_MODELS_DIR}. "
        "Run: python scripts/install-whisper.py"
    )


async def _to_wav(src: Path) -> Path:
    """Convert audio/video to 16 kHz mono WAV via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = Path(f.name)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", "-f", "wav", str(wav),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0 or not wav.exists():
        raise RuntimeError(f"ffmpeg conversion failed for {src}")
    return wav


def _whisper_args(cfg: dict, cli: str, model: str, input_path: Path, vtt: bool) -> list[str]:
    args = [cli, "-m", model, "-f", str(input_path), "-np"]
    args.append("-ovtt" if vtt else "-nt")
    device = cfg.get("device", "").strip()
    if device and device.upper() != "CPU":
        args += ["--ov-e-device", device]
    beam = int(cfg.get("beam_size", 5))
    args += ["--beam-size", str(beam)]
    threads = int(cfg.get("threads", 0))
    if threads > 0:
        args += ["-t", str(threads)]
    lang = cfg.get("language", "auto").strip()
    if lang and lang != "auto":
        args += ["-l", lang]
    return args


async def _whisper_run(args: list[str], timeout: int = 300) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"whisper-cli failed (rc={proc.returncode}): {stderr.decode().strip()}")
    return stdout.decode().strip()


def _srt_to_vtt(srt: str) -> str:
    vtt = "WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", srt)
    return re.sub(r"(?m)^\d+\n(?=\d{2}:\d{2})", "", vtt).strip()


def _stdout_to_vtt(raw: str) -> str:
    """Parse whisper bracketed-timestamp stdout → WebVTT."""
    ts_re = re.compile(r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)")
    cues = [
        f"{m.group(1)} --> {m.group(2)}\n{m.group(3).strip()}"
        for line in raw.splitlines()
        if (m := ts_re.match(line.strip())) and m.group(3).strip()
    ]
    return ("WEBVTT\n\n" + "\n\n".join(cues)) if cues else ""


async def _whisper_transcribe(audio_path: Path, vtt: bool) -> str:
    cfg = _stt_cfg("whisper")
    cli = _whisper_find_cli()
    model = _whisper_find_model(cfg)
    wav_path: Path | None = None
    if audio_path.suffix.lower() != ".wav":
        wav_path = await _to_wav(audio_path)
        input_path = wav_path
    else:
        input_path = audio_path
    try:
        args = _whisper_args(cfg, cli, model, input_path, vtt=False)
        return await _whisper_run(args)
    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)


async def _whisper_transcribe_vtt(audio_path: Path) -> str:
    cfg = _stt_cfg("whisper")
    cli = _whisper_find_cli()
    model = _whisper_find_model(cfg)
    wav_path: Path | None = None
    if audio_path.suffix.lower() != ".wav":
        wav_path = await _to_wav(audio_path)
        input_path = wav_path
    else:
        input_path = audio_path
    try:
        vtt_side = input_path.with_suffix(".vtt")
        srt_side = input_path.with_suffix(".srt")
        try:
            raw = await _whisper_run(_whisper_args(cfg, cli, model, input_path, vtt=True))
        except RuntimeError:
            raw = ""

        for side, fn in ((vtt_side, lambda t: t if t.startswith("WEBVTT") else ""),
                         (srt_side, _srt_to_vtt)):
            if side.exists():
                content = side.read_text(encoding="utf-8").strip()
                side.unlink(missing_ok=True)
                result = fn(content)
                if result:
                    return result

        vtt = _stdout_to_vtt(raw)
        if vtt:
            return vtt

        if not raw:
            try:
                raw = await _whisper_run(_whisper_args(cfg, cli, model, input_path, vtt=False))
            except RuntimeError:
                return ""

        return f"WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n{raw.strip()}" if raw.strip() else ""
    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)
        for ext in (".vtt", ".srt", ".txt", ".lrc"):
            try:
                input_path.with_suffix(ext).unlink(missing_ok=True)
            except Exception:
                pass


# ── Cloud providers ────────────────────────────────────────────────────────────

def _mime(path: Path) -> str:
    return {
        ".webm": "audio/webm", ".mp3": "audio/mpeg", ".mp4": "video/mp4",
        ".wav": "audio/wav",   ".ogg": "audio/ogg",  ".m4a": "audio/mp4",
        ".flac": "audio/flac",
    }.get(path.suffix.lower(), "audio/webm")


async def _openai_transcribe(audio_path: Path) -> str:
    try:
        import openai
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    cfg = _stt_cfg("openai")
    client = openai.AsyncOpenAI(
        api_key=_api_key("openai", "OPENAI_API_KEY"),
        base_url=cfg.get("base_url", "").strip() or None,
    )
    lang = _language()
    with audio_path.open("rb") as f:
        kwargs: dict[str, Any] = {"model": cfg.get("model", "whisper-1").strip(), "file": f}
        if lang and lang != "auto":
            kwargs["language"] = lang
        resp = await client.audio.transcriptions.create(**kwargs)
    return resp.text.strip()


async def _groq_transcribe(audio_path: Path) -> str:
    try:
        from groq import AsyncGroq
    except ImportError:
        raise RuntimeError("groq package not installed. Run: pip install groq")
    cfg = _stt_cfg("groq")
    lang = _language()
    client = AsyncGroq(api_key=_api_key("groq", "GROQ_API_KEY"))
    with audio_path.open("rb") as f:
        kwargs: dict[str, Any] = {
            "model": cfg.get("model", "whisper-large-v3-turbo").strip(),
            "file": (audio_path.name, f),
        }
        if lang and lang != "auto":
            kwargs["language"] = lang
        resp = await client.audio.transcriptions.create(**kwargs)
    return resp.text.strip()


async def _deepgram_transcribe(audio_path: Path) -> str:
    try:
        from deepgram import DeepgramClient, PrerecordedOptions
    except ImportError:
        raise RuntimeError("deepgram-sdk not installed. Run: pip install deepgram-sdk")
    cfg = _stt_cfg("deepgram")
    lang = _language()
    client = DeepgramClient(_api_key("deepgram", "DEEPGRAM_API_KEY"))
    options = PrerecordedOptions(
        model=cfg.get("model", "nova-2").strip(),
        language=lang if lang != "auto" else None,
        tier=cfg.get("tier", "").strip() or None,
        smart_format=True,
    )
    audio_data = audio_path.read_bytes()
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.listen.prerecorded.v("1").transcribe_file(
            {"buffer": audio_data, "mimetype": _mime(audio_path)}, options,
        ),
    )
    alts = (response.results.channels[0].alternatives
            if response.results and response.results.channels else [])
    return alts[0].transcript.strip() if alts else ""


async def _assemblyai_transcribe(audio_path: Path) -> str:
    try:
        import assemblyai as aai
    except ImportError:
        raise RuntimeError("assemblyai not installed. Run: pip install assemblyai")
    cfg = _stt_cfg("assemblyai")
    lang = _language()
    aai.settings.api_key = _api_key("assemblyai", "ASSEMBLYAI_API_KEY")
    config = aai.TranscriptionConfig(language_code=lang if lang != "auto" else None)
    loop = asyncio.get_event_loop()
    transcript = await loop.run_in_executor(
        None, lambda: aai.Transcriber().transcribe(str(audio_path), config=config),
    )
    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {transcript.error}")
    return (transcript.text or "").strip()
