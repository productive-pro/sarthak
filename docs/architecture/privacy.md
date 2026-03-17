# Privacy and Security

Sarthak is designed so that your data stays local, encrypted, and under your control. Privacy is enforced at the architecture level, not the policy level.

---

## Encryption at rest

Every sensitive value stored in `config.toml` is encrypted with AES-256-GCM before writing to disk. The master key lives at `~/.sarthak_ai/master.key` (permissions `0600`) and is generated locally at install time. It never leaves your machine.

Encrypt and decrypt values manually:

```bash
sarthak encrypt "my-api-key"    # prints ENC:...
sarthak decrypt "ENC:..."       # prints the original value
```

---

## Secret scrubbing

Terminal capture runs a redaction filter before storage. Commands matching sensitive patterns (`password`, `token`, `secret`, `api_key`, plus any custom patterns you define) are stripped before the event reaches the database.

Every custom agent run is wrapped by `enforce_sandbox()`. It strips sensitive patterns from the agent prompt **before** the LLM sees them, and from the agent output **before** it is stored or delivered to Telegram. API keys never appear in agent prompts or run history.

Customize redaction patterns in `config.toml`:

```toml
[capture.terminal]
sensitive_patterns = ["password", "token", "secret", "api_key", "bearer"]
```

---

## Network behavior

- **Offline by default** — when using a local provider (Ollama, any custom endpoint), no network calls leave your machine
- **Cloud providers** — only the specific prompt goes out over TLS. Raw events, terminal commands, and file paths stay local
- **No telemetry** — Sarthak sends zero usage data anywhere

---

## Images never stored

Snapshots captured by the vision module are piped directly to the AI model in memory. Image bytes are never written to disk.

---

## MCP data scope

The MCP server exposes only pre-shaped summaries (daily summary, resume card, space status). It does not expose raw activity tables, file paths, or secrets.

---

## Removing your data

Wipe everything:

```bash
sarthak reset          # prompts for confirmation
sarthak reset --force  # skips confirmation
```

This removes `~/.sarthak_ai/` and the system service. Spaces data inside your workspaces (`.spaces/` directories) is not touched — delete those manually if needed.

---

## Data locations

| Data | Location |
|---|---|
| Config and encrypted secrets | `~/.sarthak_ai/config.toml` |
| Encryption master key | `~/.sarthak_ai/master.key` (permissions 0600) |
| Activity events and summaries | `~/.sarthak_ai/sarthak.db` |
| Global agent specs | `~/.sarthak_ai/agents/` |
| Space registry | `~/.sarthak_ai/spaces.json` |
| AI roadmap database | `<workspace>/.spaces/sarthak.db` |
| Session records | `<workspace>/.spaces/sessions/` |
| RAG vector index | `<workspace>/.spaces/rag/` |
| Session history, XP, streak | `<workspace>/.spaces/roadmap.json` |
| Space memory files | `<workspace>/.spaces/{SOUL,USER,HEARTBEAT,MEMORY}.md` |
| Daily session logs | `<workspace>/.spaces/memory/YYYY-MM-DD.md` |
