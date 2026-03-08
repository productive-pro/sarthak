# Publishing to PyPI

Sarthak publishes automatically to PyPI on every version tag. This page explains how the release process works and how to do a manual release if needed.

## How releases work

Pushing a tag like `v0.2.0` triggers the release workflow, which:

1. Builds the source distribution and wheel with `uv build`
2. Publishes to PyPI using Trusted Publishing (no API token needed in CI)
3. Creates a GitHub Release with auto-generated release notes and the built packages attached

All of this is handled by `.github/workflows/release.yml`.

## Creating a release

```bash
# Update version in pyproject.toml first, then:
git tag v0.2.0
git push origin v0.2.0
```

The workflow runs automatically. You can watch it in the Actions tab on GitHub.

## Manual build and publish

```bash
uv build
uv publish
```

`uv publish` uses the `PYPI_TOKEN` environment variable or your keyring credentials.

## Installing from PyPI

```bash
pip install sarthak
# or
uv add sarthak
```

For cloud AI provider support (OpenAI, Anthropic):

```bash
pip install "sarthak[cloud]"
```

## Release notes format

GitHub auto-generates release notes from pull request labels. The categories are:

- **Features** — PRs labelled `feature` or `enhancement`
- **Fixes** — PRs labelled `bug` or `fix`
- **Docs** — PRs labelled `docs`
- **Other** — everything else

Label your PRs correctly so the changelog reads cleanly.
