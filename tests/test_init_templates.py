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

class TestTemplateRegression:
    """t-351: deep regression per shape — structural invariants + round-trip.

    Each test asserts that `smithy init --template=<shape>`:
    - seeds every theme/initiative verbatim (ids, ranks, statuses)
    - renders every intent bullet into identity.md in order
    - produces a state.json that round-trips through json.loads
    - uses unique theme/initiative ids within the template
    - wires every initiative's theme_id to a seeded theme
    """

    @pytest.mark.parametrize("name", ["lib", "cli", "web", "data-pipe", "mobile", "research"])
    def test_template_structural_integrity(self, tmp_path, name):
        runner = CliRunner(mix_stderr=False)
        r = runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path),
                                "--template", name])
        assert r.exit_code == 0, f"init failed for {name}: {r.output}"

        tpl = TEMPLATES[name]

        # state.json round-trip with exact payload
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["themes"] == tpl["themes"], f"themes drift for {name}"
        assert state["initiatives"] == tpl["initiatives"], f"initiatives drift for {name}"

        # IDs unique within the template
        theme_ids = [t["id"] for t in tpl["themes"]]
        ini_ids = [i["id"] for i in tpl["initiatives"]]
        assert len(theme_ids) == len(set(theme_ids)), f"duplicate theme ids in {name}"
        assert len(ini_ids) == len(set(ini_ids)), f"duplicate initiative ids in {name}"

        # Every initiative's theme_id resolves to a seeded theme
        theme_id_set = set(theme_ids)
        for ini in tpl["initiatives"]:
            assert ini["theme_id"] in theme_id_set, \
                f"{name}: initiative {ini['id']} references unknown theme {ini['theme_id']}"

        # Every intent bullet present in identity.md, in original order
        identity = (tmp_path / "identity.md").read_text()
        positions = [identity.find(b) for b in tpl["intent_bullets"]]
        assert all(p >= 0 for p in positions), \
            f"{name}: missing bullet(s) in identity.md"
        assert positions == sorted(positions), \
            f"{name}: bullets out of order in identity.md"

        # Template label appears in identity.md so a reader can see the shape
        assert tpl["label"] in identity, f"{name}: label '{tpl['label']}' missing"


class TestInitTemplatesReporting:
    def test_output_reports_template_and_counts(self, tmp_path):
        runner = CliRunner(mix_stderr=False)
        r = runner.invoke(cli, ["init", "myproj", "--target", str(tmp_path),
                                "--template", "web"])
        data = json.loads(r.stdout)
        assert data["template"] == "web"
        assert data["themes_seeded"] == 4
        assert data["initiatives_seeded"] == 4
