"""Tests for auth CLI commands."""

from click.testing import CliRunner

from ergane.main import cli


class TestAuthCommands:
    def test_auth_status_no_session(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "status", "--session-file", str(tmp_path / "none.json")]
        )
        assert result.exit_code == 0
        assert "No saved session" in result.output

    def test_auth_clear_no_session(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["auth", "clear", "--session-file", str(tmp_path / "none.json")]
        )
        assert result.exit_code == 0

    def test_auth_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "status" in result.output
        assert "clear" in result.output


class TestCrawlAuthMode:
    def test_auth_mode_flag_accepted(self):
        """Verify --auth-mode is a recognized option (doesn't error on parse)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["crawl", "--auth-mode", "manual", "--help"])
        assert result.exit_code == 0
