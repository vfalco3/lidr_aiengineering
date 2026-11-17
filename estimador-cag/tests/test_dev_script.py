"""Tests de las funciones puras de scripts/dev.py. No usan Docker ni arrancan uvicorn."""

from __future__ import annotations

from pathlib import Path

from scripts.dev import check_llm_key, has_llm_key, parse_env_file


def test_parse_env_file_ignores_comments_blanks_and_strips_quotes():
    text = "# comentario\n\nANTHROPIC_API_KEY=\"sk-test\"\nAPP_NAME='Estimador'\nSIN_IGUAL\n"

    values = parse_env_file(text)

    assert values == {"ANTHROPIC_API_KEY": "sk-test", "APP_NAME": "Estimador"}


def test_parse_env_file_keeps_empty_values():
    assert parse_env_file("ANTHROPIC_API_KEY=\n") == {"ANTHROPIC_API_KEY": ""}


def test_has_llm_key_requires_a_non_empty_value():
    assert has_llm_key({"ANTHROPIC_API_KEY": "sk-test"}) is True
    assert has_llm_key({"OPENAI_API_KEY": "sk-openai"}) is True
    assert has_llm_key({"ANTHROPIC_API_KEY": "   "}) is False
    assert has_llm_key({"APP_NAME": "x"}) is False


def test_check_llm_key_reads_dotenv_when_environment_is_empty(tmp_path: Path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-file\n", encoding="utf-8")

    assert check_llm_key(tmp_path, {}) is True


def test_check_llm_key_fails_with_empty_dotenv_value(tmp_path: Path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")

    assert check_llm_key(tmp_path, {}) is False


def test_environment_variable_overrides_empty_dotenv_value(tmp_path: Path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")

    assert check_llm_key(tmp_path, {"ANTHROPIC_API_KEY": "sk-from-env"}) is True


def test_check_llm_key_without_dotenv_or_environment_is_false(tmp_path: Path):
    assert check_llm_key(tmp_path, {}) is False
