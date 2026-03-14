# MCP Server

The MCP server lets any compatible AI assistant — such as Claude Code, Claude Desktop, Gemini CLI, opencode, or Zed — read your Sarthak data as context. Once connected, your AI assistant can answer questions about your learning history, current Space, and activity without you having to copy anything across.

---

## What the server exposes today

The current MCP server is intentionally small. It exposes three tools:

| Tool | What it returns |
|:---|:---|
| `get_daily_summary` | Cached daily activity summary for a given `YYYY-MM-DD` date |
| `get_resume_card` | A short summary of the most recent Space session |
| `get_space_status` | Active Space plus a compact list of recent Spaces |

This means MCP clients do not get arbitrary database access. They receive narrow, pre-shaped summaries from the server.

---

## How it runs

Sarthak uses the standard MCP stdio transport. The client starts:

```bash
sarthak mcp
```

and communicates over stdin/stdout. There is no separate HTTP server to expose.

---

## Connecting Claude Code

In your project root or globally, add to your MCP config (`.claude/mcp.json` or `~/.config/claude/mcp.json`):

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

## Connecting Gemini CLI / opencode

Both tools follow the same MCP JSON format. Add to their respective config files:

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

Restart Claude Desktop. Sarthak will now appear as a context source and Claude can answer questions like "what was I learning yesterday?" or "what should I focus on today based on my progress?".

---

## Connecting Zed

In your Zed settings, add:

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

The MCP server only shares data with the AI client you have connected — nothing is sent anywhere by Sarthak on its own.

- Secrets and API keys are not exposed as MCP tools
- The server returns summaries, not raw activity tables
- The transport is local stdio, so data stays on your machine unless your connected AI client chooses to send it onward
