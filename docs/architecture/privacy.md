# Privacy and Security

Sarthak is designed so that your activity data stays local, encrypted, and under your control. Privacy is enforced at the architecture level, not the policy level.

## Encryption at rest

Every sensitive value stored in `config.toml` is encrypted with AES-256-GCM before writing to disk. The master key lives at `~/.sarthak_ai/master.key` (permissions `0600`) and is generated locally at install time. It never leaves your machine.

Encrypt and decrypt values manually:

```bash
sarthak encrypt "my-api-key"    # prints ENC:...
sarthak decrypt "ENC:..."
```

## Redaction

Terminal capture runs a redaction filter before storage. Commands matching sensitive patterns (`password`, `token`, `secret`, `api_key`, and any custom patterns you define) are stripped before the event reaches the database.

Customize patterns in `~/.sarthak_ai/config.toml`:

```toml
[capture.terminal]
sensitive_patterns = ["password", "token", "secret", "api_key", "bearer"]
```

## Sandbox secret scrubbing

Every custom agent run is wrapped by `enforce_sandbox()`. It strips sensitive patterns from the agent prompt **before** the LLM sees them, and from the agent output **before** it is saved or delivered to Telegram. API keys never appear in agent prompts or run history.

## Images never stored

Snapshots captured by the vision module are piped directly to the AI model in memory. The image bytes are never written to disk at any point.

## Network behavior

- **Offline by default**: when using a local provider (Ollama, any custom endpoint), no network calls are made.
- **Cloud providers**: only the specific prompt or snapshot description goes out over TLS. Raw events, terminal commands, and file paths stay local.
- **No telemetry**: Sarthak sends no usage data anywhere.

## Data locations

| Data | Location |
|:---|:---|
| Activity events and summaries | `~/.sarthak_ai/sarthak.db` (SQLite) |
| Global agent specs | `~/.sarthak_ai/agents/` |
| Space registry | `~/.sarthak_ai/spaces.json` |
| AI roadmap database | `<workspace>/.spaces/sarthak.db` |
| Session records | `<workspace>/.spaces/sessions/` |
| RAG vector index | `<workspace>/.spaces/rag/` (includes `sarthak.vec` when using sqlite-vec) |
| Roadmap history (XP, streak) | `<workspace>/.spaces/roadmap.json` |
| Workspace analysis | `<workspace>/.spaces/Optimal_Learn.md` |
| Space memory files | `<workspace>/.spaces/{SOUL,USER,HEARTBEAT,MEMORY}.md` |
| Daily session logs | `<workspace>/.spaces/memory/YYYY-MM-DD.md` |

## Removing your data

Wipe everything:

```bash
sarthak reset          # prompts for confirmation
sarthak reset --force  # skips confirmation
```

This removes `~/.sarthak_ai/`, the CLI binary, and the system service. Spaces data inside your workspaces (`.spaces/`) is not touched — delete those directories manually if needed.
