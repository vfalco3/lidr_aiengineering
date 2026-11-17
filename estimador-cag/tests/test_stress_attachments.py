"""Tests del generador de PDFs sintéticos. El analizador real es pypdf."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from evals.stress.attachments import body_lines, build_sized_pdf
from evals.stress.scenarios import ATTACHMENT_MARKERS


@pytest.mark.parametrize("size_kb", [5, 20, 50, 100])
def test_generated_pdf_size_is_within_two_percent_of_target(size_kb):
    data = build_sized_pdf(size_kb)
    target = size_kb * 1024

    assert abs(len(data) - target) <= target * 0.02


def test_generated_pdf_is_parsed_by_pypdf_with_both_markers():
    data = build_sized_pdf(20)

    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert len(reader.pages) >= 2
    for marker in ATTACHMENT_MARKERS:
        assert marker in text


def test_larger_sizes_produce_more_pages():
    small = PdfReader(io.BytesIO(build_sized_pdf(5)))
    large = PdfReader(io.BytesIO(build_sized_pdf(100)))

    assert len(large.pages) > len(small.pages)


def test_zero_and_negative_sizes_are_rejected():
    with pytest.raises(ValueError):
        build_sized_pdf(0)
    with pytest.raises(ValueError):
        build_sized_pdf(-5)


def test_body_lines_put_the_markers_at_both_ends():
    lines = body_lines(10)

    assert len(lines) == 10
    assert lines[0].startswith(ATTACHMENT_MARKERS[0])
    assert lines[-1].startswith(ATTACHMENT_MARKERS[1])


def test_body_lines_need_at_least_two_lines():
    with pytest.raises(ValueError):
        body_lines(1)
