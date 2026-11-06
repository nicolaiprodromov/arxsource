import base64
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_arxiv_dependency_are_synchronized():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    codex_plugin = json.loads(
        (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    claude_plugin = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    claude_marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    codex_marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    codex_mcp = json.loads((ROOT / ".codex-mcp.json").read_text(encoding="utf-8"))
    shared_mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    kiro_mcp = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
    kiro_power = (ROOT / "POWER.md").read_text(encoding="utf-8")
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    project = pyproject["project"]
    version = project["version"]
    arxiv_requirement = next(
        dependency
        for dependency in project["dependencies"]
        if dependency.startswith("arxiv")
    )

    lock_package = next(
        package
        for package in lock["package"]
        if package["name"] == project["name"]
        and package.get("source") == {"editable": "."}
    )

    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert server["$schema"] == (
        "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    )
    assert server["version"] == version
    assert server["packages"][0]["version"] == version
    assert manifest["version"] == version
    assert manifest["server"]["mcp_config"]["command"] == "python3.11"
    assert manifest["compatibility"]["runtimes"]["python"] == ">=3.11,<3.12"
    assert codex_plugin["version"] == version
    assert codex_plugin["name"] == project["name"]
    assert codex_plugin["mcpServers"] == "./.codex-mcp.json"
    assert codex_plugin["skills"] == "./skills/"
    assert claude_plugin["version"] == version
    assert claude_plugin["name"] == project["name"]
    assert claude_marketplace["name"] == "arxsource"
    assert claude_marketplace["plugins"][0]["name"] == project["name"]
    assert claude_marketplace["plugins"][0]["source"] == "./"
    assert codex_marketplace["name"] == claude_marketplace["name"]
    assert codex_marketplace["plugins"][0]["name"] == project["name"]
    assert codex_marketplace["plugins"][0]["source"] == {
        "source": "local",
        "path": "./",
    }
    assert codex_mcp == {
        "arxsource": {
            "command": "uvx",
            "args": ["arxsource-mcp"],
        }
    }
    assert shared_mcp["mcpServers"]["arxsource"] == {
        "type": "stdio",
        "command": "uvx",
        "args": ["arxsource-mcp"],
    }
    assert kiro_mcp["mcpServers"]["arxsource"] == {
        "command": "uvx",
        "args": ["arxsource-mcp"],
    }
    kiro_frontmatter = re.match(r"---\n(?P<body>.*?)\n---", kiro_power, re.DOTALL)
    assert kiro_frontmatter is not None
    assert 'name: "arxsource-mcp"' in kiro_frontmatter["body"]
    assert 'displayName: "ArxSource"' in kiro_frontmatter["body"]
    assert 'author: "nicolaiprodromov"' in kiro_frontmatter["body"]
    assert lock_package["version"] == version
    assert project["name"] == "arxsource-mcp"
    assert project["scripts"] == {"arxsource-mcp": "arxsource_mcp:main"}
    assert server["name"] == "io.github.nicolaiprodromov/arxsource"
    assert server["packages"][0]["identifier"] == project["name"]
    assert manifest["name"] == project["name"]
    assert manifest["server"]["entry_point"] == "server/arxsource_mcp/__main__.py"
    assert manifest["server"]["mcp_config"]["args"][:2] == ["-m", "arxsource_mcp"]
    assert project["authors"][0]["email"] == manifest["author"]["email"]
    assert arxiv_requirement == "arxiv>=2.1.0"


def test_mcp_dependency_excludes_incompatible_major_release():
    """mcp 2.0.0 removed the low-level ``Server`` registration decorators.

    ``server.py`` registers handlers with ``@server.list_prompts()`` and
    friends, which raise ``AttributeError`` at import time under 2.x. The
    requirement must stay below 2.0.0 until those call sites are migrated to
    the ``add_request_handler`` API.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    mcp_requirement = next(
        dependency
        for dependency in pyproject["project"]["dependencies"]
        if re.match(r"^mcp\b", dependency)
    )
    assert mcp_requirement == "mcp>=1.27.0,<2.0.0"

    locked_mcp = next(
        package for package in lock["package"] if package["name"] == "mcp"
    )
    assert tuple(int(part) for part in locked_mcp["version"].split(".")[:1]) < (2,)


def test_readme_exposes_supported_install_paths():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "<!-- mcp-name: io.github.nicolaiprodromov/arxsource -->" in readme
    assert "img.shields.io/pypi/v/arxsource-mcp" in readme
    assert "uvx arxsource-mcp" in readme
    assert (
        "claude mcp add --transport stdio --scope user arxsource -- uvx arxsource-mcp"
        in readme
    )
    assert "codex mcp add arxsource -- uvx arxsource-mcp" in readme
    assert "hermes mcp add arxsource --command uvx --args arxsource-mcp" in readme
    assert "hermes mcp test arxsource" in readme
    assert "uvx --python 3.11 --refresh-package arxsource-mcp arxsource-mcp" in readme
    assert "command -v uvx" in readme
    assert "Get-Command uvx" in readme
    assert "uv tool update-shell" in readme
    assert "claude plugin marketplace add nicolaiprodromov/arxsource" in readme
    assert "claude plugin install arxsource-mcp@arxsource" in readme
    assert "codex plugin add arxsource-mcp@arxsource" in readme
    assert "`find_paper_code`" in readme
    assert "not affiliated with or endorsed by arXiv" in readme
    assert '$env:TRANSPORT = "http"' in readme
    assert "clients that accept the `mcpServers` JSON shape" in readme
    assert "Smithery" not in readme
    assert "smithery" not in readme

    kiro_url = re.search(
        r"https://kiro\.dev/launch/mcp/add\?[^)]+",
        readme,
    )
    assert kiro_url is not None
    kiro_query = parse_qs(urlparse(kiro_url.group()).query)
    assert kiro_query["name"] == ["arxsource"]
    assert json.loads(kiro_query["config"][0]) == {
        "command": "uvx",
        "args": ["arxsource-mcp"],
        "disabled": False,
        "autoApprove": [],
    }

    vscode_url = re.search(
        r"https://vscode\.dev/redirect/mcp/install\?[^)]+",
        readme,
    )
    assert vscode_url is not None
    vscode_query = parse_qs(urlparse(vscode_url.group()).query)
    assert vscode_query["name"] == ["arxsource"]
    vscode_config = {
        "type": "stdio",
        "command": "uvx",
        "args": ["arxsource-mcp"],
    }
    assert json.loads(vscode_query["config"][0]) == vscode_config


def test_claude_manifests_reference_live_schemastore_schemas():
    plugin = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert plugin["$schema"] == (
        "https://www.schemastore.org/claude-code-plugin-manifest.json"
    )
    assert marketplace["$schema"] == (
        "https://www.schemastore.org/claude-code-marketplace.json"
    )


def test_mcpb_manual_release_dispatch_checks_out_and_validates_the_tag():
    workflow = (ROOT / ".github" / "workflows" / "build-mcpb.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "ref: ${{ inputs.release_tag || github.event.release.tag_name || github.sha }}"
        in workflow
    )
    assert (
        "RELEASE_TAG: ${{ github.event.release.tag_name || inputs.release_tag }}"
        in workflow
    )
    assert 'expected_tag = f"v{version}"' in workflow
    assert (
        'tag_commit = subprocess.check_output(["git", "rev-list", "-n", "1", tag]'
        in workflow
    )


def test_workflows_bound_protocol_smoke_runtime():
    workflows = {
        name: (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in ("tests.yml", "publish.yml", "build-mcpb.yml")
    }

    assert "timeout-minutes: 20" in workflows["tests.yml"]
    assert "timeout-minutes: 20" in workflows["publish.yml"]
    assert "timeout-minutes: 30" in workflows["build-mcpb.yml"]


def test_readme_cursor_deeplink_launches_arxsource():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    cursor_url = re.search(r"https://cursor\.com/en/install-mcp\?[^)]+", readme)
    assert cursor_url is not None
    cursor_query = parse_qs(urlparse(cursor_url.group()).query)
    assert cursor_query["name"] == ["arxsource"]
    assert json.loads(base64.b64decode(cursor_query["config"][0])) == {
        "type": "stdio",
        "command": "uvx",
        "args": ["arxsource-mcp"],
    }


def test_apache_license_attribution_is_preserved():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "Apache License" in license_text
    assert "Copyright 2024 Joseph Blazick" in license_text
    assert "derived from arxiv-mcp-server by Joseph Blazick" in notice
    assert "https://github.com/blazickjp/arxiv-mcp-server" in notice
    assert "has been modified" in notice
    assert pyproject["project"]["license-files"] == ["LICENSE", "NOTICE"]


def test_publish_workflow_requires_a_deliberate_trigger():
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    triggers = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]

    assert "release:\n    types: [published]" in triggers
    assert "workflow_dispatch:" in triggers
    assert "push:" not in triggers
    assert "pull_request" not in triggers
    assert "schedule:" not in triggers
    assert "if: github.repository == 'nicolaiprodromov/arxsource'" in workflow
    assert "default: false" in workflow
    assert "secrets.PYPI_API_TOKEN" not in workflow
    assert workflow.count("if: env.SHOULD_PUBLISH == 'true'") == 3
