"""Tests for MarkItDown OCR + document-to-note pipeline in spaces/notes.py."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sarthak.spaces.notes import (
    _markitdown_ocr,
    document_to_note,
    file_to_note,
    image_to_note,
)

TESTS_DIR = Path(__file__).parent
TEST_IMAGE = TESTS_DIR / "IMG_20260306_170431.jpg"


# ── image / OCR ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_markitdown_ocr_returns_string():
    """_markitdown_ocr should return a non-empty string."""
    result = await _markitdown_ocr(TEST_IMAGE, "Permutations and Combinations")
    assert isinstance(result, str)
    assert len(result) > 10


@pytest.mark.asyncio
async def test_markitdown_ocr_starts_with_heading():
    """Output must start with a Markdown heading."""
    result = await _markitdown_ocr(TEST_IMAGE, "Combinations")
    assert result.lstrip().startswith("#"), f"Expected heading, got: {result[:60]!r}"


@pytest.mark.asyncio
async def test_image_to_note_no_save(tmp_path):
    """image_to_note without space_dir should return Markdown and not write files."""
    result = await image_to_note(TEST_IMAGE, "Circular Permutations")
    assert isinstance(result, str)
    assert result.strip()
    # No files should have been written (space_dir=None)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_image_to_note_saves_to_space(tmp_path):
    """image_to_note with space_dir should create a note file on disk."""
    await image_to_note(TEST_IMAGE, "Combinations", space_dir=tmp_path)
    notes_root = tmp_path / ".spaces" / "notes"
    assert notes_root.exists(), "Notes directory was not created"
    concept_dirs = list(notes_root.iterdir())
    assert len(concept_dirs) == 1
    note_files = list(concept_dirs[0].glob("*.md"))
    assert len(note_files) == 1
    content = note_files[0].read_text()
    assert "<!--" in content  # frontmatter comment


@pytest.mark.asyncio
async def test_image_to_note_missing_file():
    with pytest.raises(FileNotFoundError):
        await image_to_note(Path("/nonexistent/image.png"), "Test")


@pytest.mark.asyncio
async def test_image_to_note_unsupported_ext(tmp_path):
    bad = tmp_path / "doc.xyz"
    bad.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported image type"):
        await image_to_note(bad, "Test")


# ── document_to_note ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_document_to_note_txt(tmp_path):
    """A plain .txt file should produce a Markdown string."""
    txt = tmp_path / "sample.txt"
    txt.write_text("Circular permutation formula: (n-1)!\nCombinations: nCr = n! / r!(n-r)!")
    result = await document_to_note(txt, "Permutations")
    assert isinstance(result, str)
    assert len(result) > 10


@pytest.mark.asyncio
async def test_document_to_note_has_heading(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("Key idea: combinations don't consider order.")
    result = await document_to_note(txt, "Combinations")
    assert result.lstrip().startswith("#"), f"No heading found: {result[:80]!r}"


# ── file_to_note routing ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_to_note_routes_image():
    """file_to_note should delegate .jpg to image_to_note pipeline."""
    result = await file_to_note(TEST_IMAGE, "Combinations")
    assert isinstance(result, str)
    assert result.strip()


@pytest.mark.asyncio
async def test_file_to_note_routes_document(tmp_path):
    """file_to_note should delegate .txt to document_to_note pipeline."""
    txt = tmp_path / "theory.txt"
    txt.write_text("nCr = n! / (r! * (n-r)!)")
    result = await file_to_note(txt, "Combinations")
    assert isinstance(result, str)
    assert result.strip()
