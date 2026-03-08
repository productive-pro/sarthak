"""
Sarthak Spaces — Whisper transcription via the locally installed whisper-cli.

Two output modes:
  transcribe(path)           → plain text transcript
  transcribe_vtt(path)       → WebVTT string with timestamps for subtitle overlay
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from pathlib import Path

_MODELS_DIR = Path.home() / ".sarthak_ai" / "whisper_models"
_MIN_MODEL_BYTES = 10 * 1024 * 1024  # 10 MB minimum — rejects corrupt stubs


def _cfg() -> dict:
    try:
        from sarthak.core.config import load_config
        return load_config().get("whisper", {})
    except Exception:
        return {}


def _find_model(cfg: dict) -> str:
    explicit = cfg.get("model_path", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
        raise FileNotFoundError(f"whisper model_path not found: {p}")

    model_name = cfg.get("model", "base.en")
    candidates = [f"ggml-{model_name}.bin"]
    base = model_name.split(".")[0]
    if base != model_name:
        candidates.append(f"ggml-{base}.bin")
    for name in candidates:
        p = _MODELS_DIR / name
        if p.exists() and p.stat().st_size >= _MIN_MODEL_BYTES:
            return str(p)

    for f in sorted(_MODELS_DIR.glob("ggml-*.bin")):
        if f.stat().st_size >= _MIN_MODEL_BYTES:
            return str(f)

    raise FileNotFoundError(
        f"No whisper model found in {_MODELS_DIR}. "
        "Run: python scripts/install-whisper.py"
    )


def _find_cli() -> str:
    for name in ("whisper-cli", "whisper"):
        if shutil.which(name):
            return name
    raise FileNotFoundError(
        "whisper-cli not found in PATH. "
        "Install from: https://github.com/ggml-org/whisper.cpp"
    )


async def _to_wav(src: Path) -> Path:
    """Convert any audio/video to 16 kHz mono WAV via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = Path(f.name)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(src),
        "-ar", "16000", "-ac", "1", "-f", "wav", str(wav),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0 or not wav.exists():
        raise RuntimeError(f"ffmpeg conversion failed for {src}")
    return wav


def _build_args(cfg: dict, cli: str, model_path: str, input_path: Path, vtt: bool) -> list[str]:
    # -ovtt: output WebVTT with timestamps; -np: no progress; without -nt to keep timestamps
    args = [cli, "-m", model_path, "-f", str(input_path), "-np"]
    if vtt:
        args.append("-ovtt")
    else:
        args.append("-nt")  # no timestamps for plain text

    device = cfg.get("device", "").strip()
    if device and device.upper() != "CPU":
        args += ["--ov-e-device", device]

    beam_size = int(cfg.get("beam_size", 5))
    args += ["--beam-size", str(beam_size)]

    threads = int(cfg.get("threads", 0))
    if threads > 0:
        args += ["-t", str(threads)]

    language = cfg.get("language", "auto").strip()
    if language and language != "auto":
        args += ["-l", language]

    return args


async def _run_whisper(args: list[str], timeout: int = 300) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"whisper-cli failed (rc={proc.returncode}): {stderr.decode().strip()}"
        )
    return stdout.decode().strip()


def _srt_to_vtt(srt: str) -> str:
    """Convert SRT block format to WebVTT (commas → dots in timestamps)."""
    vtt = "WEBVTT\n\n"
    vtt += re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", srt)
    # Strip sequence numbers (lines that are purely digits before a timestamp block)
    vtt = re.sub(r"(?m)^\d+\n(?=\d{2}:\d{2})", "", vtt)
    return vtt.strip()


def _whisper_timestamps_to_vtt(raw: str) -> str:
    """
    Convert whisper-cli's default stdout timestamp format to WebVTT.
    whisper outputs lines like: [00:00:00.000 --> 00:00:05.000]  text here
    """
    lines = raw.splitlines()
    cues = []
    ts_re = re.compile(r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)")
    for line in lines:
        m = ts_re.match(line.strip())
        if m:
            start, end, text = m.group(1), m.group(2), m.group(3).strip()
            if text:
                cues.append(f"{start} --> {end}\n{text}")
    if not cues:
        return ""
    return "WEBVTT\n\n" + "\n\n".join(cues)


async def transcribe(audio_path: Path) -> str:
    """Return plain-text transcript (no timestamps)."""
    cfg        = _cfg()
    cli        = _find_cli()
    model_path = _find_model(cfg)

    wav_path: Path | None = None
    if audio_path.suffix.lower() != ".wav":
        wav_path = await _to_wav(audio_path)
        input_path = wav_path
    else:
        input_path = audio_path

    args = _build_args(cfg, cli, model_path, input_path, vtt=False)
    try:
        return await _run_whisper(args)
    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)


async def transcribe_vtt(audio_path: Path) -> str:
    """
    Return a WebVTT string with timestamps for subtitle overlay.

    Strategy:
    1. Try whisper-cli with -ovtt flag (writes <input>.vtt sidecar file).
    2. Fall back to parsing whisper-cli's bracketed timestamp stdout.
    3. Last resort: plain text wrapped as a single VTT cue.
    """
    cfg        = _cfg()
    cli        = _find_cli()
    model_path = _find_model(cfg)

    wav_path: Path | None = None
    if audio_path.suffix.lower() != ".wav":
        wav_path = await _to_wav(audio_path)
        input_path = wav_path
    else:
        input_path = audio_path

    try:
        # Attempt 1: -ovtt writes a sidecar .vtt next to input_path
        vtt_sidecar = input_path.with_suffix(".vtt")
        srt_sidecar = input_path.with_suffix(".srt")
        try:
            args = _build_args(cfg, cli, model_path, input_path, vtt=True)
            raw = await _run_whisper(args)
        except RuntimeError:
            raw = ""

        if vtt_sidecar.exists():
            vtt = vtt_sidecar.read_text(encoding="utf-8").strip()
            vtt_sidecar.unlink(missing_ok=True)
            if vtt.startswith("WEBVTT"):
                return vtt

        # Attempt 2: SRT sidecar (older whisper-cli builds may write -osrt but not -ovtt)
        if srt_sidecar.exists():
            srt = srt_sidecar.read_text(encoding="utf-8").strip()
            srt_sidecar.unlink(missing_ok=True)
            if srt:
                return _srt_to_vtt(srt)

        # Attempt 3: parse bracketed timestamps from stdout
        vtt = _whisper_timestamps_to_vtt(raw)
        if vtt:
            return vtt

        # Attempt 4: plain text without -ovtt flag
        if not raw:
            plain_args = _build_args(cfg, cli, model_path, input_path, vtt=False)
            try:
                raw = await _run_whisper(plain_args)
            except RuntimeError:
                return ""

        plain = raw.strip()
        if plain:
            return f"WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n{plain}"
        return ""

    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)
        # Clean up any stray sidecar whisper may have written next to original
        for ext in (".vtt", ".srt", ".txt", ".lrc"):
            try:
                input_path.with_suffix(ext).unlink(missing_ok=True)
            except Exception:
                pass
