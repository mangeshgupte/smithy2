"""Tests for `smithy init --template` (t-347)."""

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
from smithy.cli import cli
from smithy.intent_templates import TEMPLATES, list_template_names


class TestInitTemplates:
    def test_list_templates_flag(self, tmp_path):
        runner = CliRunner()
        r = runner.invoke(cli, ["init", "--list-templates"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        names = {t["name"] for t in data["templates"]}
        assert names == set(list_template_names())
        assert "lib" in names and "research" in names

    def test_init_without_template_is_backwards_compat(self, tmp_path):
        runner = CliRunner()
        r = runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path)])
        assert r.exit_code == 0
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["themes"] == []
        assert state["initiatives"] == []
        # Identity doesn't leak a template label when none was chosen
        assert "seeded from" not in (tmp_path / "identity.md").read_text()

    @pytest.mark.parametrize("name", ["lib", "cli", "web", "data-pipe", "mobile", "research"])
    def test_init_with_template_seeds_state(self, tmp_path, name):
        runner = CliRunner()
        r = runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path),
                                "--template", name])
        assert r.exit_code == 0
        state = json.loads((tmp_path / "state.json").read_text())
        tpl = TEMPLATES[name]
        assert len(state["themes"]) == len(tpl["themes"])
        assert len(state["initiatives"]) == len(tpl["initiatives"])
        # Theme IDs round-trip exactly
        assert [t["id"] for t in state["themes"]] == [t["id"] for t in tpl["themes"]]

    def test_init_identity_contains_template_bullets(self, tmp_path):
        runner = CliRunner()
        runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path),
                            "--template", "cli"])
        text = (tmp_path / "identity.md").read_text()
        assert "CLI Tool" in text
        # First bullet should appear verbatim
        assert TEMPLATES["cli"]["intent_bullets"][0] in text

    def test_unknown_template_errors(self, tmp_path):
        runner = CliRunner(mix_stderr=True)
        r = runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path),
                                "--template", "quantum-blockchain"])
        assert r.exit_code != 0
        assert "Unknown template" in r.output

    def test_missing_project_name_errors(self, tmp_path):
        runner = CliRunner()
        r = runner.invoke(cli, ["init"])
        assert r.exit_code != 0

    def test_output_reports_template_and_counts(self, tmp_path):
        runner = CliRunner(mix_stderr=False)
        r = runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path),
                                "--template", "web"])
        data = json.loads(r.stdout)
        assert data["template"] == "web"
        assert data["themes_seeded"] == 4
        assert data["initiatives_seeded"] == 4
