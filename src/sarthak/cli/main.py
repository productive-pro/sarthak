"""
Sarthak AI — CLI entrypoint.
Sub-commands:
  spaces    → cli/spaces_cli.py
  agents    → cli/agents_cli.py
  analytics → cli/analytics_cli.py
"""
from __future__ import annotations

import click

from sarthak.cli.spaces_cli import spaces
from sarthak.cli.agents_cli import agents
from sarthak.cli import analytics_cli
from sarthak.cli.storage_cli import storage_cli


@click.group()
@click.pass_context
def main(ctx: click.Context):
    """Sarthak AI — Privacy-first self-analytics intelligence platform."""
    # Bootstrap on first run (no-op after that — instant sentinel check)
    # Skip for 'uninstall' so the user can clean up a broken install too
    if ctx.invoked_subcommand not in ("uninstall", "reset"):
        from sarthak.core.setup import ensure_bootstrapped
        ensure_bootstrapped()


# ── Sub-groups ────────────────────────────────────────────────────────────────
main.add_command(spaces)
main.add_command(agents)
main.add_command(storage_cli)

main.add_command(analytics_cli.resume)


# ── Core commands ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("text")
def encrypt(text: str):
    """Encrypt a string (output prefixed with ENC:)."""
    from sarthak.storage.encrypt import encrypt_string
    click.echo(encrypt_string(text))


@main.command()
@click.argument("text")
def decrypt(text: str):
    """Decrypt an ENC:... string."""
    from sarthak.storage.encrypt import decrypt_string
    try:
        click.echo(decrypt_string(text))
    except Exception as e:
        click.echo(f"Decryption failed: {e}", err=True)


@main.command()
def tui():
    """Open the Sarthak TUI dashboard."""
    from sarthak.features.tui.app import main as run_tui
    run_tui()


@main.command()
def mcp():
    """Start the Sarthak MCP server (Standard I/O)."""
    from sarthak.features.mcp.server import main as run_mcp
    run_mcp()


@main.command()
@click.option("--date", help="Date to summarize (YYYY-MM-DD), defaults to today")
def summarize(date: str | None):
    """Generate an AI summary for a specific day using Spaces data."""
    import asyncio
    from datetime import datetime, date as dt
    from pathlib import Path

    from sarthak.core.config import load_config
    from sarthak.storage.helpers import get_daily_summary, write_daily_summary
    from sarthak.features.ai.agent import AgentDeps, generate_daily_summary

    target_date = date or str(dt.today())

    async def run():
        cfg  = load_config()
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()

        existing     = await get_daily_summary(parsed_date)
        prev_summary = existing.get("summary") if existing else None

        space_context = _collect_space_sessions_today(parsed_date)
        context = space_context

        if not context:
            click.secho(f"No activity found for {target_date}.", fg="yellow")
            return

        deps   = AgentDeps(pool=None, cwd=str(Path.home()), allow_web=False, allow_shell=False)
        result = await generate_daily_summary(
            context, target_date, deps, previous_summary=prev_summary
        )

        if result.summary.startswith("Summary unavailable"):
            click.echo(result.summary, err=True)
            return

        print()
        print(result.summary)
        if result.recommendation:
            print()
            print("── Recommendation ──────────────────────────────────────")
            print(result.recommendation)
        print()

        provider = cfg.get("ai", {}).get("default_provider", "ollama")
        await write_daily_summary(
            date=parsed_date, summary=result.summary,
            top_apps=[], productive_mins=0, idle_mins=0,
            model_used=provider,
        )

    asyncio.run(run())


def _collect_space_sessions_today(target_date) -> str:
    """Read today's SpaceSession records from all known spaces."""
    from pathlib import Path
    from sarthak.spaces.store import list_spaces
    from sarthak.spaces.session_tracker import load_sessions

    lines: list[str] = []
    try:
        for space in list_spaces():
            d = Path(space.get("directory", ""))
            if not d.exists():
                continue
            sessions = load_sessions(d, limit=20)
            today_sessions = [
                s for s in sessions
                if s.started_at and s.started_at.date() == target_date
            ]
            if today_sessions:
                total_active = sum(s.signals.active_seconds for s in today_sessions)
                lines.append(
                    f"- Space **{space.get('name', d.name)}**: "
                    f"{len(today_sessions)} session(s), "
                    f"{total_active // 60} active minutes, "
                    f"concepts: {', '.join(s.concept for s in today_sessions)}"
                )
    except Exception:
        pass
    if not lines:
        return ""
    return "## Space Learning Today\n" + "\n".join(lines)


@main.command()
@click.option(
    "--mode",
    type=click.Choice(["full", "quick"], case_sensitive=False),
    default="full",
    show_default=True,
)
def configure(mode: str):
    """Interactive configuration wizard for Sarthak AI."""
    from sarthak.core.configure import run_quick_wizard, run_wizard
    handlers = {"full": run_wizard, "quick": run_quick_wizard}
    handlers[mode]()
    _print_next_steps()


@main.command()
def status():
    """Check the status of Sarthak services and configuration."""
    import asyncio
    import socket
    import subprocess
    import sys
    from pathlib import Path

    from sarthak.core.config import load_config
    from sarthak.storage.db import _db_path

    def _ok(label: str, detail: str = "") -> None:
        click.secho(f"{label} OK{' — ' + detail if detail else ''}", fg="green")

    def _bad(label: str, detail: str) -> None:
        click.secho(f"{label} FAIL — {detail}", fg="red")

    def _check_file(label: str, path: Path) -> None:
        if path.exists():
            _ok(label, str(path))
        else:
            _bad(label, f"missing {path}")

    def _check_web(cfg: dict) -> None:
        web_cfg = cfg["web"]
        if not web_cfg["enabled"]:
            click.secho("Web WARN — disabled", fg="yellow")
            return
        host, port = web_cfg["host"], int(web_cfg["port"])
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            _ok("Web", f"{host}:{port}")
        except Exception as exc:
            click.secho(f"Web WARN — {host}:{port} not reachable ({exc})", fg="yellow")
        finally:
            sock.close()

    def _check_db() -> None:
        _ok("SQLite", str(_db_path()))

    click.echo("Sarthak status")
    _check_file("Config",     Path.home() / ".sarthak_ai" / "config.toml")
    _check_file("Master key", Path.home() / ".sarthak_ai" / "master.key")

    try:
        _check_db()
    except Exception as exc:
        _bad("SQLite", str(exc))

    try:
        cfg = load_config()
        _check_web(cfg)
    except Exception as exc:
        _bad("Web", str(exc))


@main.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def reset(force: bool):
    """Wipe all production data and configuration."""
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    prod_dir   = Path.home() / ".sarthak_ai"
    plist_file = Path.home() / "Library/LaunchAgents/com.sarthak.orchestrator.plist"

    if not force:
        click.confirm(
            f"This will DESTROY all data in {prod_dir}. Continue?",
            abort=True,
        )

    if sys.platform.startswith("linux"):
        for svc in ("sarthak-orchestrator",):
            subprocess.run(["systemctl", "--user", "stop",    svc], stderr=subprocess.DEVNULL)
            subprocess.run(["systemctl", "--user", "disable", svc], stderr=subprocess.DEVNULL)

    if sys.platform == "darwin":
        subprocess.run(["launchctl", "unload", str(plist_file)], stderr=subprocess.DEVNULL)
        if plist_file.exists():
            plist_file.unlink()

    if sys.platform == "win32":
        subprocess.run(["schtasks", "/Delete", "/TN", "SarthakOrchestrator", "/F"],
                       stderr=subprocess.DEVNULL, shell=True)

    if prod_dir.exists():
        shutil.rmtree(prod_dir)

    click.echo("Sarthak AI reset. Run the install script to reinstall.")


@main.command()
def uninstall():
    """Remove Sarthak config or uninstall the package completely."""
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    # ── Palette (inline, no configure import needed) ──────────────────────
    OR  = "\033[38;5;214m"
    CY  = "\033[38;5;87m"
    GR  = "\033[38;5;82m"
    YL  = "\033[38;5;227m"
    RD  = "\033[38;5;196m"
    DM  = "\033[38;5;240m"
    BD  = "\033[1m"
    RS  = "\033[0m"

    def _ok(t):  click.echo(f"  {GR}+{RS} {t}")
    def _warn(t): click.echo(f"  {YL}!{RS} {t}")
    def _err(t):  click.echo(f"  {RD}x{RS} {t}")
    def _dim(t):  click.echo(f"  {DM}{t}{RS}")

    prod_dir   = Path.home() / ".sarthak_ai"
    bin_file   = Path(shutil.which("sarthak") or (Path.home() / ".local" / "bin" / "sarthak"))
    plist_file = Path.home() / "Library" / "LaunchAgents" / "com.sarthak.orchestrator.plist"

    click.echo(f"\n{OR}{BD}  Sarthak AI — Uninstall{RS}\n")

    choices = [
        ("1", "Reset config only   — wipe ~/.sarthak_ai, keep the package installed"),
        ("2", "Uninstall completely — wipe config AND remove the pip package"),
        ("q", "Quit"),
    ]
    for key, label in choices:
        click.echo(f"  {CY}{key}{RS}  {label}")
    click.echo()

    choice = click.prompt(
        f"  {OR}Choose{RS}",
        type=click.Choice(["1", "2", "q"], case_sensitive=False),
        default="q",
        show_choices=False,
    )

    if choice == "q":
        _dim("Aborted — nothing changed.")
        return

    # ── Shared: stop services ─────────────────────────────────────────────
    def _stop_services():
        if sys.platform.startswith("linux"):
            for svc in ("sarthak-orchestrator",):
                subprocess.run(["systemctl", "--user", "stop",    svc], stderr=subprocess.DEVNULL)
                subprocess.run(["systemctl", "--user", "disable", svc], stderr=subprocess.DEVNULL)
            _ok("systemd service stopped")
        elif sys.platform == "darwin":
            subprocess.run(["launchctl", "unload", str(plist_file)], stderr=subprocess.DEVNULL)
            if plist_file.exists():
                plist_file.unlink()
            _ok("launchd service unloaded")
        elif sys.platform == "win32":
            subprocess.run(
                ["schtasks", "/Delete", "/TN", "SarthakOrchestrator", "/F"],
                stderr=subprocess.DEVNULL, shell=True,
            )
            _ok("Scheduled task removed")

    # ── Option 1: reset config ────────────────────────────────────────────
    if choice == "1":
        click.echo()
        _warn(f"This will permanently delete {prod_dir}")
        if not click.confirm(f"  {OR}Continue?{RS}", default=False):
            _dim("Aborted.")
            return
        _stop_services()
        if prod_dir.exists():
            shutil.rmtree(prod_dir)
            _ok(f"Deleted {prod_dir}")
        else:
            _dim(f"{prod_dir} not found — nothing to delete")
        click.echo(f"\n  {GR}Done.{RS}  Run {OR}sarthak configure{RS} to set up again.\n")
        return

    # ── Option 2: full uninstall ──────────────────────────────────────────
    click.echo()
    _warn(f"This will delete {prod_dir} AND uninstall the sarthak package.")
    if not click.confirm(f"  {OR}Are you sure?{RS}", default=False):
        _dim("Aborted.")
        return

    _stop_services()

    if prod_dir.exists():
        shutil.rmtree(prod_dir)
        _ok(f"Deleted {prod_dir}")

    if bin_file.exists():
        bin_file.unlink()
        _ok(f"Deleted {bin_file}")

    # Detect uv/pip and run uninstall
    pip_cmd: list[str] | None = None
    import shutil as _sh
    if _sh.which("uv"):
        pip_cmd = ["uv", "tool", "uninstall", "sarthak"]
    elif _sh.which("pip3"):
        pip_cmd = ["pip3", "uninstall", "sarthak", "-y"]
    elif _sh.which("pip"):
        pip_cmd = ["pip", "uninstall", "sarthak", "-y"]

    if pip_cmd:
        click.echo()
        _dim(f"Running: {' '.join(pip_cmd)}")
        result = subprocess.run(pip_cmd)
        if result.returncode == 0:
            _ok("sarthak package removed")
        else:
            _err("pip uninstall reported an error — you may need to remove manually")
    else:
        _warn("pip not found in PATH — remove the package manually:")
        _dim("  pip uninstall sarthak  OR  uv tool uninstall sarthak")

    click.echo(f"\n  {GR}✓{RS}  Sarthak AI has been uninstalled. Goodbye!\n")


@main.group()
def channels():
    """Manage communication channels (Telegram, WhatsApp)."""


@channels.command("status")
def channels_status():
    """Show connection status for all configured channels."""
    import socket
    from pathlib import Path

    GR = "\033[38;5;82m"; YL = "\033[38;5;227m"; RD = "\033[38;5;196m"
    CY = "\033[38;5;87m"; DM = "\033[38;5;240m"; BD = "\033[1m"; RS = "\033[0m"

    def _on(label, detail=""):  click.echo(f"  {GR}+{RS} {BD}{label}{RS}  {DM}{detail}{RS}")
    def _off(label, detail=""): click.echo(f"  {YL}-{RS} {BD}{label}{RS}  {DM}{detail}{RS}")
    def _err(label, detail=""): click.echo(f"  {RD}x{RS} {BD}{label}{RS}  {DM}{detail}{RS}")

    click.echo(f"\n{CY}{BD}  Sarthak — Channel Status{RS}\n")

    try:
        from sarthak.core.config import load_config
        cfg = load_config()
    except Exception as exc:
        _err("Config", str(exc))
        return

    # ── Web ──────────────────────────────────────────────────────────────────
    web = cfg.get("web", {})
    host, port = str(web.get("host", "127.0.0.1")), int(web.get("port", 4848))
    if web.get("enabled"):
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            _on("Web UI", f"http://localhost:{port}")
        except Exception:
            _off("Web UI", f"not reachable at {host}:{port} (orchestrator running?)")
        finally:
            sock.close()
    else:
        _off("Web UI", "disabled")

    # ── Telegram ─────────────────────────────────────────────────────────────
    tg = cfg.get("telegram", {})
    if tg.get("enabled"):
        from sarthak.storage.encrypt import decrypt_string
        raw = tg.get("bot_token", "")
        has_token = bool(raw)
        uid = tg.get("allowed_user_id", "")
        if has_token:
            _on("Telegram", f"user_id={uid}")
        else:
            _err("Telegram", "enabled but bot_token not set — run: sarthak configure")
    else:
        _off("Telegram", "disabled")

    # ── WhatsApp ─────────────────────────────────────────────────────────────
    wa = cfg.get("whatsapp", {})
    if wa.get("enabled"):
        jid = str(wa.get("jid", "")).strip()
        from sarthak.features.channels.whatsapp import SESSION_DB, is_connected
        session_ok = SESSION_DB.exists()
        connected  = is_connected()
        if connected:
            _on("WhatsApp", f"connected  jid={jid}")
        elif session_ok and jid:
            _off("WhatsApp", f"session on disk, bot not running  jid={jid}  (start: sarthak orchestrator)")
        elif jid:
            _off("WhatsApp", f"jid set but no session DB — run: sarthak configure → Channels → WhatsApp")
        else:
            _err("WhatsApp", "enabled but not paired — run: sarthak configure → Channels → WhatsApp")
    else:
        _off("WhatsApp", "disabled")

    click.echo()


main.add_command(channels)


@main.command()
def orchestrator():
    """Start all Sarthak services in the foreground."""
    from sarthak.orchestrator.service import main as run_orchestrator
    run_orchestrator()


# ── Service management (systemd / launchd / Task Scheduler) ──────────────────

@main.group()
def service():
    """Manage the Sarthak background orchestrator service."""


@service.command("install")
def service_install():
    """Install and start the orchestrator as a system service.

    Linux  → systemd user service
    macOS  → launchd LaunchAgent
    Windows → Task Scheduler
    """
    import subprocess
    import sys
    from pathlib import Path

    OR = "\033[38;5;214m"; CY = "\033[38;5;87m"; GR = "\033[38;5;82m"
    YL = "\033[38;5;227m"; BD = "\033[1m";        RS = "\033[0m"

    def _ok(t):   click.echo(f"  {GR}+{RS} {t}")
    def _info(t): click.echo(f"  {CY}>{RS} {t}")
    def _warn(t): click.echo(f"  {YL}!{RS} {t}")

    # Resolve the sarthak executable that is currently running
    sarthak_exe = _which_sarthak()

    install_dir = Path.home() / ".sarthak_ai"
    logs_dir    = install_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"\n{OR}{BD}  Installing Sarthak orchestrator service{RS}\n")

    if sys.platform.startswith("linux"):
        _install_systemd(sarthak_exe, install_dir)
        _ok("systemd user service installed and started")
        _info("Check status: systemctl --user status sarthak-orchestrator")

    elif sys.platform == "darwin":
        _install_launchd(sarthak_exe, install_dir, logs_dir)
        _ok("launchd agent installed and started")
        _info("Check status: launchctl list | grep sarthak")

    elif sys.platform == "win32":
        _install_task_scheduler(sarthak_exe, install_dir)
        _ok("Task Scheduler job installed and started")
        _info("Check status: schtasks /Query /TN SarthakOrchestrator")

    else:
        _warn(f"Unsupported platform: {sys.platform}")
        _info(f"Start manually: {sarthak_exe} orchestrator")
        return

    _print_next_steps()


@service.command("uninstall")
def service_uninstall():
    """Stop and remove the orchestrator service."""
    import subprocess
    import sys
    from pathlib import Path

    GR = "\033[38;5;82m"; YL = "\033[38;5;227m"; RS = "\033[0m"

    def _ok(t):   click.echo(f"  {GR}+{RS} {t}")
    def _warn(t): click.echo(f"  {YL}!{RS} {t}")

    if sys.platform.startswith("linux"):
        for cmd in [
            ["systemctl", "--user", "stop",    "sarthak-orchestrator"],
            ["systemctl", "--user", "disable", "sarthak-orchestrator"],
        ]:
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        svc_file = Path.home() / ".config" / "systemd" / "user" / "sarthak-orchestrator.service"
        svc_file.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], stderr=subprocess.DEVNULL)
        _ok("systemd service removed")

    elif sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.sarthak.orchestrator.plist"
        subprocess.run(["launchctl", "unload", str(plist)], stderr=subprocess.DEVNULL)
        plist.unlink(missing_ok=True)
        _ok("launchd agent removed")

    elif sys.platform == "win32":
        subprocess.run(
            ["schtasks", "/Delete", "/TN", "SarthakOrchestrator", "/F"],
            stderr=subprocess.DEVNULL, shell=True,
        )
        wrapper = Path.home() / ".sarthak_ai" / "run_orchestrator.bat"
        wrapper.unlink(missing_ok=True)
        _ok("Task Scheduler job removed")

    else:
        _warn(f"Unsupported platform: {sys.platform}")


@service.command("status")
def service_status():
    """Show orchestrator service status."""
    import subprocess
    import sys

    if sys.platform.startswith("linux"):
        subprocess.run(["systemctl", "--user", "status", "sarthak-orchestrator"])
    elif sys.platform == "darwin":
        subprocess.run(["launchctl", "list", "com.sarthak.orchestrator"])
    elif sys.platform == "win32":
        subprocess.run(
            ["schtasks", "/Query", "/TN", "SarthakOrchestrator", "/FO", "LIST"],
            shell=True,
        )
    else:
        click.echo("Service management not supported on this platform.")


# ── Service install helpers ───────────────────────────────────────────────────

def _which_sarthak() -> str:
    """Find the sarthak executable — works for uv tool, pip, binary, and editable installs."""
    import os
    import shutil
    import sys
    from pathlib import Path

    exe = shutil.which("sarthak")
    if exe:
        return exe

    # uv tool installs:
    #   Linux/macOS  → ~/.local/bin/sarthak
    #   Windows      → %USERPROFILE%\.local\bin\sarthak.exe  (uv ≥0.4)
    #                  %APPDATA%\uv\bin\sarthak.exe           (older uv)
    #                  %LOCALAPPDATA%\uv\bin\sarthak.exe      (some versions)
    home = Path.home()
    if sys.platform == "win32":
        appdata  = Path(os.environ.get("APPDATA",      home / "AppData" / "Roaming"))
        localapp = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates: list[Path] = [
            home    / ".local"  / "bin"  / "sarthak.exe",
            appdata / "uv"      / "bin"  / "sarthak.exe",
            localapp / "uv"     / "bin"  / "sarthak.exe",
            localapp / "sarthak" / "bin" / "sarthak.exe",
        ]
    else:
        candidates = [
            home / ".local" / "bin" / "sarthak",
            home / ".cargo" / "bin" / "sarthak",
        ]

    for p in candidates:
        if p.is_file():
            return str(p)

    # Editable / dev install fallback — use sys.executable so the service unit
    # calls the right interpreter; callers must handle the space in the path.
    return f"{sys.executable} -m sarthak.cli"


def _install_systemd(sarthak_exe: str, install_dir) -> None:
    import subprocess
    from pathlib import Path
    import os

    # Handle "python -m sarthak.cli" fallback from editable installs
    if sarthak_exe.endswith(" -m sarthak.cli"):
        exec_start = f"{sarthak_exe} orchestrator"
    else:
        exec_start = f"{sarthak_exe} orchestrator"

    systemd_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    svc = systemd_dir / "sarthak-orchestrator.service"
    svc.write_text(f"""\
[Unit]
Description=Sarthak AI — Orchestrator
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=90
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory={install_dir}
ExecStart={exec_start}
Environment=SARTHAK_CONFIG={install_dir}/config.toml
Environment=SARTHAK_ORCHESTRATOR_SKIP_CAPTURE=1
Environment=HOME={Path.home()}
Environment=PATH={os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
""")
    for cmd in [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "sarthak-orchestrator"],
        ["systemctl", "--user", "restart", "sarthak-orchestrator"],
    ]:
        subprocess.run(cmd, check=False)


def _install_launchd(sarthak_exe: str, install_dir, logs_dir) -> None:
    import subprocess
    from pathlib import Path

    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist = agents_dir / "com.sarthak.orchestrator.plist"
    plist.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sarthak.orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sarthak_exe}</string>
    <string>orchestrator</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SARTHAK_CONFIG</key><string>{install_dir}/config.toml</string>
    <key>SARTHAK_ORCHESTRATOR_SKIP_CAPTURE</key><string>1</string>
  </dict>
  <key>WorkingDirectory</key><string>{install_dir}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{logs_dir}/orchestrator.log</string>
  <key>StandardErrorPath</key><string>{logs_dir}/orchestrator.err</string>
</dict>
</plist>
""")
    subprocess.run(["launchctl", "unload", str(plist)], stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "load", str(plist)], check=False)


def _install_task_scheduler(sarthak_exe: str, install_dir) -> None:
    """Install the orchestrator as a Windows Task Scheduler job.

    Environment variables are injected via a small wrapper .bat file because
    schtasks /Create does not support per-task environment variables directly.

    Rules:
    - Write the .bat with cp1252 (Windows ANSI) so cmd.exe can read it.
    - Use shell=False with a full schtasks command string built via subprocess
      list form to avoid shell quoting issues with spaces in paths.
    - Always /F (force overwrite) at the end of /Create, not in the middle.
    """
    import os
    import subprocess
    from pathlib import Path

    install_dir = Path(install_dir)
    config_path = install_dir / "config.toml"
    wrapper = install_dir / "run_orchestrator.bat"

    # Write .bat in Windows ANSI (cp1252) — cmd.exe cannot read UTF-8 without BOM
    bat_content = (
        "@echo off\r\n"
        f"set SARTHAK_CONFIG={config_path}\r\n"
        "set SARTHAK_ORCHESTRATOR_SKIP_CAPTURE=1\r\n"
        f'"{sarthak_exe}" orchestrator\r\n'
    )
    wrapper.write_bytes(bat_content.encode("cp1252", errors="replace"))

    task_name = "SarthakOrchestrator"
    wrapper_str = str(wrapper)

    # Delete any existing task first (ignore errors — task may not exist)
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        shell=False,  # Never use shell=True with schtasks — it swallows exit codes
    )

    # Create: shell=False avoids cmd.exe re-quoting the /TR value.
    # Wrap wrapper path in double quotes inside the /TR value so schtasks
    # passes it correctly to the Task Scheduler COM API.
    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", task_name,
            "/TR", f'"{wrapper_str}"',
            "/SC", "ONLOGON",
            "/RL", "LIMITED",
            "/F",
        ],
        shell=False, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode != 0:
        # Surface the actual schtasks error message so users can diagnose it
        import click
        click.echo(f"  [!] schtasks /Create returned {result.returncode}: {result.stderr.strip()}", err=True)

    subprocess.run(
        ["schtasks", "/Run", "/TN", task_name],
        shell=False, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _print_next_steps() -> None:
    """Print the web URL and next steps after configure / service install."""
    from pathlib import Path
    import tomlkit

    OR = "\033[38;5;214m"; CY = "\033[38;5;87m"; GR = "\033[38;5;82m"
    DM = "\033[38;5;240m"; BD = "\033[1m";        RS = "\033[0m"

    host, port = "127.0.0.1", 4848
    try:
        cfg_path = Path.home() / ".sarthak_ai" / "config.toml"
        if cfg_path.exists():
            cfg = tomlkit.parse(cfg_path.read_text())
            w = cfg.get("web", {})
            host = str(w.get("host", host))
            port = int(w.get("port", port))
    except Exception:
        pass

    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"http://{display_host}:{port}"

    print(f"\n{OR}{BD}  ✓  Sarthak AI is ready!{RS}")
    print(f"\n  {GR}Open the Web UI:{RS}")
    print(f"    {CY}{BD}{url}{RS}")
    print(f"\n  {DM}Commands:{RS}")
    print(f"    {OR}sarthak service install{RS}  install background orchestrator")
    print(f"    {OR}sarthak orchestrator{RS}     run orchestrator in foreground")
    print(f"    {OR}sarthak --help{RS}           show all commands\n")


if __name__ == "__main__":
    main()
