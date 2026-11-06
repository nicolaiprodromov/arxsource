"""Tests for rate limiter deadline checking and validation."""

import os
import pytest
from unittest.mock import MagicMock, patch


def test_rate_limiter_zero_pending_wait_proceeds():
    """With zero pending wait and 2.5s budget, the attempt proceeds."""
    from arxsource_mcp.tools import download

    # Mock rate limiter to say no wait needed
    with (
        patch.object(
            download.ARXIV_RATE_LIMITER, "seconds_until_next_slot", return_value=0.0
        ),
        patch.object(download.ARXIV_RATE_LIMITER, "run_sync") as mock_run_sync,
        patch("arxsource_mcp.tools.download.time.monotonic", return_value=0.0),
    ):
        # Deadline at 2.5s (0.0 + 2.5)
        deadline = 2.5

        # Mock the single attempt to return some HTML
        mock_run_sync.return_value = "<html>test</html>"

        # Should proceed since pending_wait (0) + min_attempt (1) = 1s < 2.5s remaining
        result = download._fetch_html_content("2103.12345", deadline)

        # Should have called run_sync (proceeded with attempt)
        assert mock_run_sync.called
        assert result == "<html>test</html>"


def test_rate_limiter_wait_exceeds_budget_returns_immediately():
    """When seconds_until_next_slot exceeds budget minus 1s, returns timeout without calling transport."""
    from arxsource_mcp.tools import download

    # Mock rate limiter to say 2s wait needed
    with (
        patch.object(
            download.ARXIV_RATE_LIMITER, "seconds_until_next_slot", return_value=2.0
        ),
        patch.object(download.ARXIV_RATE_LIMITER, "run_sync") as mock_run_sync,
        patch("arxsource_mcp.tools.download.time.monotonic", return_value=0.0),
    ):
        # Deadline at 2.5s (0.0 + 2.5)
        deadline = 2.5

        # Should skip since pending_wait (2) + min_attempt (1) = 3s > 2.5s remaining
        result = download._fetch_html_content("2103.12345", deadline)

        # Should NOT have called run_sync (skipped attempt)
        assert not mock_run_sync.called
        assert result is None  # Returns None to try PDF


def test_timeout_validation_clamps_to_defaults():
    """ARXSOURCE_REQUEST_TIMEOUT, ARXSOURCE_MAX_TOTAL_TIME, ARXSOURCE_MAX_BACKOFF at 0 or -1 clamp to defaults."""
    from arxsource_mcp.config import Settings

    # Test ARXSOURCE_REQUEST_TIMEOUT
    with patch.dict(os.environ, {"ARXSOURCE_REQUEST_TIMEOUT": "0"}, clear=False):
        settings = Settings()
        assert settings.ARXSOURCE_REQUEST_TIMEOUT == 30

    with patch.dict(os.environ, {"ARXSOURCE_REQUEST_TIMEOUT": "-1"}, clear=False):
        settings = Settings()
        assert settings.ARXSOURCE_REQUEST_TIMEOUT == 30

    # Test ARXSOURCE_MAX_TOTAL_TIME
    with patch.dict(os.environ, {"ARXSOURCE_MAX_TOTAL_TIME": "0"}, clear=False):
        settings = Settings()
        assert settings.ARXSOURCE_MAX_TOTAL_TIME == 50

    with patch.dict(os.environ, {"ARXSOURCE_MAX_TOTAL_TIME": "-5"}, clear=False):
        settings = Settings()
        assert settings.ARXSOURCE_MAX_TOTAL_TIME == 50

    # Test ARXSOURCE_MAX_BACKOFF
    with patch.dict(os.environ, {"ARXSOURCE_MAX_BACKOFF": "0"}, clear=False):
        settings = Settings()
        assert settings.ARXSOURCE_MAX_BACKOFF == 30.0

    with patch.dict(os.environ, {"ARXSOURCE_MAX_BACKOFF": "-10"}, clear=False):
        settings = Settings()
        assert settings.ARXSOURCE_MAX_BACKOFF == 30.0


def test_legacy_request_timeout_validation_clamps():
    """Legacy REQUEST_TIMEOUT at 0, -1, and lowercase clamps to default."""
    from arxsource_mcp.config import Settings

    # Test with 0
    env = os.environ.copy()
    if "ARXSOURCE_REQUEST_TIMEOUT" in env:
        del env["ARXSOURCE_REQUEST_TIMEOUT"]
    env["REQUEST_TIMEOUT"] = "0"
    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        assert settings.get_request_timeout() == 30

    # Test with -1
    env = os.environ.copy()
    if "ARXSOURCE_REQUEST_TIMEOUT" in env:
        del env["ARXSOURCE_REQUEST_TIMEOUT"]
    env["REQUEST_TIMEOUT"] = "-1"
    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        assert settings.get_request_timeout() == 30

    # Test lowercase
    env = os.environ.copy()
    if "ARXSOURCE_REQUEST_TIMEOUT" in env:
        del env["ARXSOURCE_REQUEST_TIMEOUT"]
    env["request_timeout"] = "-5"
    with patch.dict(os.environ, env, clear=True):
        settings = Settings()
        assert settings.get_request_timeout() == 30
