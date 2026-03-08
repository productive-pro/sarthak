# Configuration

The easiest way to configure Sarthak is through the **Config** page in the web UI, or by running the setup wizard in the terminal:

```bash
sarthak configure
```

---

## AI provider

Sarthak supports local and cloud AI providers. You can switch between them any time in the Config page.

| Provider | Notes |
|:---|:---|
| **Ollama** | Fully local and offline. Free. Install from [ollama.com](https://ollama.com). |
| **GitHub Models** | Free tier using a GitHub personal access token. |
| **OpenAI** | GPT-4o and related models. Requires an OpenAI API key. |
| **Anthropic** | Claude models. Requires an Anthropic API key. Install with `pip install "sarthak[cloud]"`. |
| **Google Gemini** | Gemini 2.x models. |
| **Groq** | Fast inference for open-weight models. |
| **OpenRouter** | Access to many models through a single API key. |
| **Custom** | Any OpenAI-compatible endpoint, including self-hosted ones. |

---

## Adding API keys

API keys are encrypted before they are saved — they are never stored in plain text. To add a key, go to the **Config** page in the web UI and enter it in the Secrets section.

You can also encrypt a value from the terminal:

```bash
sarthak encrypt "your-api-key"
```

This prints an encrypted string that you can paste into the Config page or the secrets file.

---

## Telegram notifications

To receive Sarthak summaries and agent outputs on your phone via Telegram:

1. Create a bot using **@BotFather** on Telegram and copy the token
2. Get your chat ID from **@userinfobot** on Telegram
3. Go to **Config** in the web UI, find the Telegram section, and add your bot token and chat ID
4. Toggle Telegram on

Once enabled, agents you create can deliver their output to Telegram.

---

## Privacy settings


**Terminal history** — Sarthak reads your shell history to understand what you are working on. Sensitive patterns (passwords, tokens, keys) are automatically stripped. You can disable terminal capture or add custom patterns to strip.


**Data retention** — by default, raw activity events are kept for 24 hours and then rolled up into daily summaries. You can adjust this in Config.

---

## Web UI port

The web UI runs on port 4848 by default. To change it, update the port in **Config** under the Web section and restart Sarthak.
