# Installation

snowcite ships as a Python package and runs as an MCP server inside Claude Code. You need:

- [uv](https://docs.astral.sh/uv/) (ships `uvx`) — runs the server on demand.
- [Claude Code](https://claude.com/claude-code) — the client.
- At least one compile backend — [Typst](https://typst.app/) (recommended) or [tectonic](https://tectonic-typesetting.github.io/) (LaTeX).

## Register with Claude Code

```bash
claude mcp add snowcite -- uvx snowcite
```

With optional API keys (higher rate limits, faster searches):

```bash
claude mcp add snowcite \
  -e SNOWCITE_SEMANTIC_SCHOLAR_API_KEY=xxx \
  -e SNOWCITE_OPENALEX_EMAIL=you@example.com \
  -- uvx snowcite
```

## Install a compile backend

Typst is recommended — native Unicode, single static binary, fast incremental compilation.

=== "macOS"

    ```bash
    brew install typst
    # Optional LaTeX fallback
    brew install tectonic
    # For .docx export
    brew install pandoc
    ```

=== "Linux"

    ```bash
    # Typst: grab the static binary from https://github.com/typst/typst/releases
    curl -L https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz | tar -xJ
    sudo mv typst-*/typst /usr/local/bin/

    # tectonic is in most package managers
    sudo apt install tectonic
    ```

=== "Windows"

    ```powershell
    winget install --id Typst.Typst
    winget install --id tectonic.tectonic
    ```

## Verify the environment

After connecting the server in Claude Code, run:

```
Can you check_environment?
```

Claude calls the `check_environment` MCP tool; the report lists which binaries
and API endpoints are reachable. Anything flagged `error` is a blocker; `warn`
entries degrade a specific feature (e.g., missing pandoc → no `.docx` export).

## API keys

### Semantic Scholar

Unauthenticated: 100 req / 5 min. With an API key ([request one](https://www.semanticscholar.org/product/api)), 100 req / sec. Pass via `SNOWCITE_SEMANTIC_SCHOLAR_API_KEY`.

### OpenAlex

OpenAlex's polite pool gives stable rate limits in exchange for an email in the `mailto=` query param. Pass via `SNOWCITE_OPENALEX_EMAIL`.

### Crossref

Uses the same email as OpenAlex. No separate key.

### PubMed

No key required; NCBI asks for ≤3 requests per second, which the built-in semaphore enforces.
