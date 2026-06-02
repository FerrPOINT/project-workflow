"""Интеграционные тесты CLI (Click CliRunner)."""

from click.testing import CliRunner

from wartz_workflow.cli import cli

runner = CliRunner()


class TestListPhases:
    def test_text_mode(self):
        result = runner.invoke(cli, ["list-phases"])
        assert result.exit_code == 0
        assert "Suite Verification" in result.output

    def test_json_mode(self):
        result = runner.invoke(cli, ["--json", "list-phases"])
        assert result.exit_code == 0
        assert '"phases"' in result.output
        assert '"blockers"' in result.output


class TestStatus:
    def test_nonexistent_json(self):
        """Несуществующая задача возвращает JSON ошибку."""
        result = runner.invoke(cli, ["--json", "status", "AAT-NONEXISTENT"])
        assert result.exit_code == 1
        assert '"ok": false' in result.output


class TestCheckEnv:
    def test_json_output(self):
        result = runner.invoke(cli, ["--json", "check-env"])
        # exit code зависит от окружения — проверяем только JSON формат
        assert '"checks"' in result.output
        assert "gitignore" in result.output


class TestNextStep:
    def test_nonexistent_json(self):
        result = runner.invoke(cli, ["--json", "next-step", "AAT-NONEXISTENT"])
        assert result.exit_code == 1
        assert '"ok": false' in result.output
        assert "error" in result.output
