# Changelog

All notable changes to ArxSource are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

Initial release of ArxSource: an MCP server that lets AI agents search, read and analyze arXiv papers, and find their code. ArxSource is derived from arxiv-mcp-server (Apache-2.0); see [NOTICE](NOTICE).

### Added

#### Tools (20)
- **Discovery:** `search_papers` (arXiv query syntax, category and date filters, compact paginated results) and `get_abstract`.
- **Full text:** `download_paper` (arXiv HTML first, optional PDF fallback), `list_papers`, `read_paper`, `get_paper_outline`, `read_paper_section`, and `search_paper_text`. Content responses are bounded to 12,000 characters by default and carry continuation metadata (`next_start`, `is_truncated`).
- **Original source:** `get_paper_latex`, `list_paper_latex_sections`, and `get_paper_latex_section` read author-submitted LaTeX one section at a time.
- **Citations:** `citation_graph` (references and citing papers via Semantic Scholar, cached on disk) and `export_citations` (BibTeX from arXiv metadata).
- **Monitoring:** `watch_topic`, `list_watches`, `check_alerts`, and `unwatch_topic` keep topic watches on disk.
- **Code discovery:** `find_paper_code` takes an arXiv ID and returns the paper's GitHub repository with its star count, plus the top Hugging Face models, datasets, and Spaces that reference the paper.
- **Local semantic search** (optional `[pro]` extra): `semantic_search` and `reindex` over downloaded papers.

#### Prompts
- Seven MCP prompt workflows: `research-discovery`, `deep-paper-analysis`, `summarize_paper`, `compare_papers`, `literature_review`, `literature-synthesis`, and `research-question`.

#### Transports
- stdio by default, plus Streamable HTTP (`TRANSPORT=http`) bound to `127.0.0.1` with DNS-rebinding protection and a `/healthz` probe.

#### Reliability and safety
- A process-wide arXiv request gate that respects arXiv's request spacing, a per-call time budget, bounded retries with exponential backoff, and minimal retries on HTTP 406 throttling.
- Hardened LaTeX archive handling: path and member-type validation, link and duplicate rejection, compressed and expanded size limits, include-depth caps, and atomic cache writes.

#### Configuration
- arXiv request tuning through `ARXSOURCE_REQUEST_TIMEOUT`, `ARXSOURCE_CONNECT_TIMEOUT`, `ARXSOURCE_MAX_TOTAL_TIME`, `ARXSOURCE_MAX_RETRIES`, `ARXSOURCE_HTTP_406_MAX_RETRIES`, `ARXSOURCE_INITIAL_BACKOFF`, and `ARXSOURCE_MAX_BACKOFF`.
- Papers, source caches, alerts, and indexes are stored under `~/.arxsource/papers` unless `--storage-path` is given.

#### Distribution
- PyPI package `arxsource-mcp` with the `arxsource-mcp` command (`uvx arxsource-mcp`), and `[pdf]` and `[pro]` extras.
- MCP Registry metadata (`io.github.nicolaiprodromov/arxsource`), a Claude Desktop MCPB bundle for macOS, Claude Code and OpenAI Codex plugins with a bundled research skill, a Kiro Power, and a Dockerfile.

[0.1.0]: https://github.com/nicolaiprodromov/arxsource/releases/tag/v0.1.0
