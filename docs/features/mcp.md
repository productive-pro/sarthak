# MCP Server

The MCP server lets any compatible AI assistant — Claude Code, Claude Desktop, Gemini CLI, opencode, Zed — read your Sarthak data as context. Once connected, your AI assistant can answer questions about your learning history, current Space, and recent activity without you having to copy anything across.

---

## What the server exposes

The MCP server exposes three tools:

| Tool | What it returns |
|---|---|
| `get_daily_summary` | Cached daily activity summary for a given `YYYY-MM-DD` date |
| `get_resume_card` | A short summary of the most recent Space session |
| `get_space_status` | Active Space plus a compact list of recent Spaces |

These are narrow, pre-shaped summaries — not arbitrary database access.

---

## How to start it

```bash
sarthak mcp
```

Sarthak uses the standard MCP stdio transport. The client starts this command and communicates over stdin/stdout. No separate HTTP server.

---

## Connecting Claude Code

In your project root (`.claude/mcp.json`) or globally (`~/.config/claude/mcp.json`):

```json
{
  "mcpServers": {
    "sarthak": {
      "command": "sarthak",
      "args": ["mcp"]
    }
  }
}
```

---

## Connecting Claude Desktop

Open your Claude Desktop configuration file and add:

```json
{
  "mcpServers": {
    "sarthak": {
      "command": "sarthak",
      "args": ["mcp"]
    }
  }
}
```

Restart Claude Desktop. Sarthak will appear as a context source. Claude can then answer questions like "what was I learning yesterday?" or "what should I focus on today based on my progress?".

---

## Connecting Gemini CLI / opencode

Both tools use the same MCP JSON format. Add to their respective config files:

```json
{
  "mcpServers": {
    "sarthak": {
      "command": "sarthak",
      "args": ["mcp"]
    }
  }
}
```

---

## Connecting Zed

In your Zed settings:

```json
{
  "context_servers": {
    "sarthak": {
      "command": {
        "path": "sarthak",
        "args": ["mcp"]
      }
    }
  }
}
```

---

## Privacy

The MCP server only shares data with the AI client you have connected — Sarthak sends nothing on its own.

- Secrets and API keys are not exposed as MCP tools
- The server returns summaries, not raw activity tables
- Transport is local stdio — data stays on your machine unless your connected AI client sends it onward
