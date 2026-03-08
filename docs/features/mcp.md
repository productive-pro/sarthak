# MCP Server

The MCP server lets any compatible AI assistant — such as Claude Desktop or Zed — read your Sarthak data as context. Once connected, your AI assistant can answer questions about your learning history, current Space, and activity without you having to copy anything across.

---

## What your AI assistant can see

- What you were working on in recent sessions
- Your active Space, current concept, recent mastery, and areas you are struggling with
- Today's focus time and top applications
- A searchable history of your activity

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

The MCP server only shares data with the AI client you have connected — nothing is sent to any external server. Secrets and API keys are never included in what is shared.
