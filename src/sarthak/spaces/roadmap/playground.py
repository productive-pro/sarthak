"""
Code playground — sandboxed subprocess executor with per-space concurrency limits.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

TIMEOUT    = 10          # seconds before SIGKILL
MAX_OUTPUT = 32_768      # 32 KB
MAX_CONCURRENT = 2       # simultaneous runs per space
MAX_VMEM   = 512 * 1024 * 1024  # 512 MB virtual memory cap (Linux only)

_semaphores: dict[str, asyncio.Semaphore] = {}

def _sem(space: str) -> asyncio.Semaphore:
    if space not in _semaphores:
        _semaphores[space] = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphores[space]

def _avail(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def _lua_cmd() -> str:
    return shutil.which("lua") or shutil.which("lua5.4") or shutil.which("lua5.3") or "lua"

# ── Compiled runs ─────────────────────────────────────────────────────────────

def _c_run(src: str, d: str)   -> list: return [["gcc",  "-O0", "-o", f"{d}/a.out", src], [f"{d}/a.out"]]
def _cpp_run(src: str, d: str) -> list: return [["g++",  "-O0", "-std=c++17", "-o", f"{d}/a.out", src], [f"{d}/a.out"]]
def _java_run(src: str, d: str) -> list: return [["javac", src], ["java", "-cp", d, "Main"]]

# ── Language registry ─────────────────────────────────────────────────────────

LANGUAGES: dict[str, dict[str, Any]] = {
    "python":     {"label": "Python",            "ext": "py",   "avail": lambda: _avail("python3"),
                   "run": lambda f, d: ["python3", "-u", f]},
    "javascript": {"label": "JavaScript (Node)", "ext": "js",   "avail": lambda: _avail("node"),
                   "run": lambda f, d: ["node", f]},
    "typescript": {"label": "TypeScript",        "ext": "ts",   "avail": lambda: _avail("npx"),
                   "run": lambda f, d: ["npx", "--yes", "ts-node", "--transpile-only", "--cache", f]},
    "bash":       {"label": "Bash",              "ext": "sh",   "avail": lambda: _avail("bash"),
                   "run": lambda f, d: ["bash", f]},
    "perl":       {"label": "Perl",              "ext": "pl",   "avail": lambda: _avail("perl"),
                   "run": lambda f, d: ["perl", f]},
    "ruby":       {"label": "Ruby",              "ext": "rb",   "avail": lambda: _avail("ruby"),
                   "run": lambda f, d: ["ruby", f]},
    "php":        {"label": "PHP",               "ext": "php",  "avail": lambda: _avail("php"),
                   "run": lambda f, d: ["php", f]},
    "lua":        {"label": "Lua",               "ext": "lua",  "avail": lambda: _avail("lua") or _avail("lua5.4") or _avail("lua5.3"),
                   "run": lambda f, d: [_lua_cmd(), f]},
    "c":          {"label": "C (gcc)",           "ext": "c",    "avail": lambda: _avail("gcc"),   "run": _c_run},
    "cpp":        {"label": "C++ (g++)",         "ext": "cpp",  "avail": lambda: _avail("g++"),   "run": _cpp_run},
    "java":       {"label": "Java",              "ext": "java", "avail": lambda: _avail("java") and _avail("javac"), "run": _java_run},
}

# ── Java wrapper ──────────────────────────────────────────────────────────────

def _wrap_java(code: str) -> str:
    # Count public class declarations; only rename if exactly one
    pub_classes = re.findall(r'\bpublic\s+class\s+(\w+)', code)
    if pub_classes:
        if len(pub_classes) == 1:
            return re.sub(r'\bpublic\s+class\s+\w+', 'public class Main', code, count=1)
        return code  # multiple public classes — leave as-is, let javac error naturally
    return f"public class Main {{\n    public static void main(String[] args) throws Exception {{\n{code}\n    }}\n}}"

# ── Runner ────────────────────────────────────────────────────────────────────

async def _proc(cmd: list[str], cwd: str, stdin: str = "") -> tuple[str, str, int]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    def _limit():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (MAX_VMEM, MAX_VMEM))
        except Exception:
            pass

    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=_limit,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(stdin.encode() if stdin else b""), timeout=TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return "", f"Timed out after {TIMEOUT}s", 124
    return out.decode(errors="replace"), err.decode(errors="replace"), proc.returncode


def _trunc(s: str) -> str:
    if len(s) <= MAX_OUTPUT: return s
    h = MAX_OUTPUT // 2
    return s[:h] + f"\n…[truncated {len(s)-MAX_OUTPUT} bytes]…\n" + s[-h:]


async def execute(language: str, code: str, stdin: str = "", space: str = "default", helper_code: str = "") -> dict[str, Any]:
    lang = LANGUAGES.get(language)
    if not lang:
        return {"error": f"Unknown language: {language}", "stdout": "", "stderr": "", "exit_code": -1, "language": language}
    if not lang["avail"]():
        return {"error": f"{lang['label']} runtime not found.", "stdout": "", "stderr": "", "exit_code": -1, "language": language}

    sem = _sem(space)
    if sem._value == 0:  # noqa: SLF001
        return {"error": "Too many concurrent runs — try again shortly.", "stdout": "", "stderr": "", "exit_code": -1, "language": language}

    async with sem:
        with tempfile.TemporaryDirectory(prefix="sarthak_pg_") as wd:
            fname = f"Main.{lang['ext']}" if language == "java" else f"code.{lang['ext']}"
            src = os.path.join(wd, fname)
            Path(src).write_text(_wrap_java(code) if language == "java" else code, encoding="utf-8")

            # Write optional helper file alongside main
            if helper_code.strip():
                helper_name = f"helper.{lang['ext']}"
                Path(os.path.join(wd, helper_name)).write_text(helper_code, encoding="utf-8")

            spec = lang["run"](src, wd)
            if isinstance(spec[0], list):
                cout, cerr, crc = await _proc(spec[0], wd)
                if crc != 0:
                    return {"stdout": _trunc(cout), "stderr": _trunc(cerr),
                            "exit_code": crc, "language": language, "error": "Compilation failed"}
                stdout, stderr, rc = await _proc(spec[1], wd, stdin)
            else:
                stdout, stderr, rc = await _proc(spec, wd, stdin)

    return {"stdout": _trunc(stdout), "stderr": _trunc(stderr), "exit_code": rc, "language": language, "error": None}


def available_languages() -> list[dict[str, str]]:
    return [{"id": k, "label": v["label"]} for k, v in LANGUAGES.items() if v["avail"]()]


# ── AI error explainer ────────────────────────────────────────────────────────

async def explain_error(language: str, code: str, stderr: str, stdout: str) -> str:
    from sarthak.core.ai_utils.multi_provider import call_llm
    prompt = (
        f"A student wrote this {language} code and got an error. "
        f"Explain the bug clearly and show the fix.\n\n"
        f"CODE:\n```{language}\n{code[:2000]}\n```\n\n"
        f"STDERR:\n```\n{stderr[:1000]}\n```\n"
        + (f"\nSTDOUT:\n```\n{stdout[:500]}\n```" if stdout.strip() else "")
        + "\n\nBe concise. Show corrected code."
    )
    return await call_llm(prompt)


async def generate_concept_code(language: str, concept_title: str, concept_desc: str = "") -> str:
    from sarthak.core.ai_utils.multi_provider import call_llm
    prompt = (
        f"Write a short, runnable {language} example that demonstrates: **{concept_title}**.\n"
        + (f"Context: {concept_desc[:300]}\n" if concept_desc else "")
        + "Return only the code, no explanation, no markdown fences."
    )
    return await call_llm(prompt)
