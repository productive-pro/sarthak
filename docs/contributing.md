# Contributing

Thanks for helping improve Sarthak AI. This guide keeps contributions consistent and easy to review.

## Ways to contribute

- Report bugs and performance issues
- Improve documentation or examples
- Implement new features or integrations
- Add tests or improve coverage

## Development setup

```bash
uv sync
curl -fsSL https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install.sh | bash
```

## Running tests

```bash
pytest
```

## Linting

```bash
ruff check .
```

## Pull requests

- Keep PRs focused and small when possible.
- Include a clear summary and any relevant context.
- If you change CLI or TUI behavior, include screenshots or notes.
- Update documentation and tests for user-facing changes.

## Code style

- Python 3.14+ only
- 4-space indentation
- `snake_case` for functions/variables, `PascalCase` for classes
- Linting via Ruff (`E`, `F`, `I` rules)
