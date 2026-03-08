# Development

## Local docs preview

```bash
uv sync
python scripts/gen_ref_pages.py
zensical serve
```

`zensical` prints a local URL. Markdown and CSS changes reload automatically.

## Running tests

```bash
pytest
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. All test files follow the `test_*.py` naming convention under `tests/`.

## Linting

```bash
ruff check src/
ruff format src/
```

Rules: `E`, `F`, `I` (see `pyproject.toml`).

## Adding a new Spaces domain

1. Define `CONCEPT_TREE: dict[SkillLevel, list[str]]` and `TOOLS: list[ToolRecommendation]` in `src/sarthak/spaces/domains.py`
2. Register in `DOMAIN_REGISTRY`
3. Add `SpaceType` enum value in `src/sarthak/spaces/models.py`
4. Add CLI `--type` choice in `src/sarthak/cli/spaces_cli.py`
5. Optionally add workspace template in `src/sarthak/spaces/workspace_transformer.py`

## Adding a new agent

All AI agents live in `src/sarthak/agents/`. Agents must be stateless — all state is passed in via `AgentSpec` or injected context. Use `agents/runner.py` as the execution entry point.

## Style customization

Custom theme styling: `docs/stylesheets/extra.css`

Monokai code highlighting is configured in `mkdocs.yml` under `pymdownx.highlight`.
