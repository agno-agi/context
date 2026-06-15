#!/usr/bin/env python3
"""
@context MCP connector — add @context to your local MCP clients in one command.

@context's MCP server (`use_context`) is one command to add to a CLI client, but
the desktop apps need a hand-edited config + an `mcp-remote` stdio bridge. This
script does all of it for you, safely:

  - Claude Code  — runs `claude mcp add -s user --transport http <name> <url>`,
                   then always-allows the `use_context` tool in ~/.claude/settings.json
                   (adds `mcp__<name>__use_context` to permissions.allow) so it never prompts
  - Codex        — runs `codex mcp add --url <url> <name>`
  - Claude Desktop — merges an `mcp-remote` bridge into claude_desktop_config.json
                     (absolute npx path, existing keys preserved, timestamped backup)

It only touches clients it finds, skips anything already wired up (idempotent),
and never sends or reads anything — it just writes local client config.

Not auto-configured: ChatGPT (desktop + web) has no local MCP config file — it
only reaches MCP servers as a remote HTTPS connector, so it needs a deployed /
tunnelled instance (see docs/MCP.md), not a localhost bridge. Windows is
best-effort: the config path is handled and the bridge is written in the
`cmd /c npx` form Claude Desktop expects there, but we develop on macOS and
haven't tested the Windows path end to end.

Usage (no venv needed — pure stdlib):

    python scripts/connect.py                      # local: add to every client found
    python scripts/connect.py --production         # deployed: resolve URL + JWT from .env.production
    python scripts/connect.py --dry-run            # show what would change, write nothing
    python scripts/connect.py --remove             # undo (remove the entries)
    python scripts/connect.py --clients claude-desktop
    python scripts/connect.py --url http://localhost:8000/mcp --name context

`--production` resolves the endpoint from `AGENTOS_URL` in `.env.production`
(→ `https://<domain>/mcp`) and threads `Authorization: Bearer <JWT>` into each
client. The JWT is the token os.agno.com mints for your AgentOS — read from
`CONTEXT_MCP_JWT` in `.env.production`, else `--token`, else you're prompted.
(Codex reads its token from the `CONTEXT_JWT` env var at run time, so it's
registered by reference — never written to its config; export it in your shell.)
For a deployed instance by hand, see docs/MCP.md.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_URL = "http://localhost:8000/mcp"
DEFAULT_NAME = "context"
SERVER_TOOL = "use_context"  # the single tool the server exposes; auto-allowed in Claude Code so it never prompts
CLIENTS = ("claude-code", "codex", "claude-desktop")

# Production (`--production`): where to find the endpoint + the client's bearer token.
ENV_FILE_DEFAULT = ".env.production"  # gitignored, so safe to hold the client JWT
AGENTOS_URL_KEY = "AGENTOS_URL"  # base URL in .env.production; we append /mcp
JWT_ENV_KEY = "CONTEXT_MCP_JWT"  # the bearer token (minted at os.agno.com), in .env.production
CODEX_TOKEN_ENV = "CONTEXT_JWT"  # env var Codex reads the bearer token from at run time

# Status glyphs for the summary line.
OK, SKIP, FAIL = "✓", "–", "✗"


def claude_desktop_config_path() -> Path:
    """Default Claude Desktop config path for this OS."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home)) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def claude_code_settings_path() -> Path:
    """Claude Code's user-scope settings file — where the always-allow rule lives.

    The MCP server is registered with `claude mcp add -s user`, so the matching
    permission belongs at user scope too (applies wherever you connect, not just
    this project — and stays out of any committed repo settings).
    """
    return Path.home() / ".claude" / "settings.json"


def bridge_entry(url: str, npx: str, header: str | None = None) -> dict:
    """The claude_desktop_config.json server entry — an mcp-remote stdio bridge.

    Claude Desktop's config-file MCP support is stdio-only, so mcp-remote
    bridges the streamable-HTTP endpoint. `http-only` matches our server (it
    speaks streamable HTTP, not SSE). A deployed instance needs auth, so
    `header` (e.g. "Authorization: Bearer <JWT>") is passed through to
    mcp-remote's `--header`; as a JSON args element it's one argv token, so the
    space in "Bearer <JWT>" survives (no shell to split it).

    Platform note: macOS/Linux GUI apps don't inherit the shell PATH, so we
    pin the absolute `npx`. Windows installs Node on the system PATH (which GUI
    apps do inherit) but Claude Desktop can't exec `npx.cmd` directly, so the
    documented form there is `cmd /c npx ...`. The Windows path is best-effort —
    untested by us (we develop on macOS); verify it connects after a restart.
    """
    args = ["-y", "mcp-remote", url, "--transport", "http-only"]
    if header:
        args += ["--header", header]
    if sys.platform.startswith("win"):
        return {"command": "cmd", "args": ["/c", "npx", *args]}
    return {"command": npx, "args": args}


# ---------------------------------------------------------------------------
# Claude Desktop (config-file bridge)
# ---------------------------------------------------------------------------
def connect_claude_desktop(
    url: str, name: str, config_path: Path, *, header: str | None = None, remove: bool, dry_run: bool
) -> tuple[str, str]:
    if not remove and not config_path.parent.exists():
        return SKIP, "claude-desktop: app not found (no config dir) — skipped"

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text() or "{}")
        except json.JSONDecodeError as exc:
            return FAIL, f"claude-desktop: {config_path} is not valid JSON ({exc}) — left untouched"

    servers = config.get("mcpServers", {})

    if remove:
        if name not in servers:
            return SKIP, f"claude-desktop: no '{name}' entry to remove"
        if dry_run:
            return OK, f"claude-desktop: would remove '{name}' from {config_path}"
        _backup(config_path)
        servers.pop(name, None)
        config["mcpServers"] = servers
        _write_json(config_path, config)
        return OK, f"claude-desktop: removed '{name}' (restart Claude Desktop)"

    npx = shutil.which("npx")
    if not npx:
        return FAIL, "claude-desktop: `npx` not found on PATH — install Node, then re-run"

    entry = bridge_entry(url, npx, header)
    if servers.get(name) == entry:
        return SKIP, f"claude-desktop: '{name}' already configured ({config_path})"

    if dry_run:
        action = "update" if name in servers else "add"
        return OK, f"claude-desktop: would {action} '{name}' in {config_path}\n      {json.dumps(entry)}"

    _backup(config_path)
    servers[name] = entry
    config["mcpServers"] = servers
    _write_json(config_path, config)
    return OK, f"claude-desktop: wrote '{name}' to {config_path} (restart Claude Desktop)"


def _backup(path: Path) -> None:
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(path.read_text())


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI clients (Claude Code, Codex)
# ---------------------------------------------------------------------------
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def connect_cli(
    client: str, url: str, name: str, *, header: str | None = None, remove: bool, dry_run: bool, force: bool
) -> tuple[str, str]:
    """Register/unregister with a CLI client whose binary is on PATH.

    For a deployed instance (`header` set), Claude Code takes the literal
    `Authorization: Bearer <JWT>` via `--header`; Codex has no inline-token flag,
    so it's registered with `--bearer-token-env-var CONTEXT_JWT` and reads the
    token from that env var at run time (the secret never lands in its config).
    """
    binary = "claude" if client == "claude-code" else "codex"
    if not shutil.which(binary):
        return SKIP, f"{client}: `{binary}` not found on PATH — skipped"

    get_cmd = [binary, "mcp", "get", name]
    if client == "claude-code":
        # `claude mcp add`'s --header is variadic (<header...>), so it must come
        # AFTER the positionals — placed before, it swallows name/url as extra
        # header values ("missing required argument 'name'"). This matches the
        # CLI's own documented example: `... <name> <url> --header "..."`.
        add_cmd = [binary, "mcp", "add", "-s", "user", "--transport", "http", name, url]
        if header:
            add_cmd += ["--header", header]
    else:
        add_cmd = [binary, "mcp", "add", "--url", url]
        if header:
            add_cmd += ["--bearer-token-env-var", CODEX_TOKEN_ENV]
        add_cmd += [name]
    remove_cmd = [binary, "mcp", "remove", name]

    if remove:
        if dry_run:
            return OK, f"{client}: would run `{' '.join(remove_cmd)}`"
        res = _run(remove_cmd)
        if res.returncode == 0:
            return OK, f"{client}: removed '{name}'"
        return SKIP, f"{client}: nothing to remove ({_first_line(res.stderr) or 'not configured'})"

    exists = _run(get_cmd).returncode == 0
    if exists and not force:
        return SKIP, f"{client}: '{name}' already connected (use --force to re-add)"

    if dry_run:
        return OK, f"{client}: would run `{' '.join(add_cmd)}`"

    if exists and force:
        _run(remove_cmd)
    res = _run(add_cmd)
    if res.returncode == 0:
        return OK, f"{client}: added '{name}' → {url}"
    return FAIL, f"{client}: `{binary} mcp add` failed — {_first_line(res.stderr) or 'see output'}"


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def allow_claude_code_tool(name: str, *, remove: bool, dry_run: bool) -> tuple[str, str]:
    """Always-allow the server's `use_context` tool in Claude Code's user settings.

    `claude mcp add` registers the server but doesn't grant it — without this,
    Claude Code prompts the owner on every call. We add the precise tool rule
    `mcp__<name>__use_context` to `permissions.allow` in ~/.claude/settings.json
    so it runs freely. Idempotent, preserves every other setting, and only ever
    touches `permissions.allow`. `--remove` takes the rule back out.

    (This governs only Claude Code's local prompt; the server stays JWT +
    owner-gated and fail-closed, so the production boundary is untouched.)
    """
    rule = f"mcp__{name}__{SERVER_TOOL}"
    path = claude_code_settings_path()

    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError as exc:
            return FAIL, f"claude-code: {path} is not valid JSON ({exc}) — allow rule left untouched"

    perms = settings.get("permissions") or {}
    allow = perms.get("allow") or []

    if remove:
        if rule not in allow:
            return SKIP, f"claude-code: no '{rule}' allow rule to remove"
        if dry_run:
            return OK, f"claude-code: would remove allow rule '{rule}' from {path}"
        perms["allow"] = [r for r in allow if r != rule]
        settings["permissions"] = perms
        _write_json(path, settings)
        return OK, f"claude-code: removed allow rule '{rule}'"

    if rule in allow:
        return SKIP, f"claude-code: '{rule}' already always-allowed ({path})"
    if dry_run:
        return OK, f"claude-code: would always-allow '{rule}' in {path}"
    allow.append(rule)
    perms["allow"] = allow
    settings["permissions"] = perms
    _write_json(path, settings)
    return OK, f"claude-code: always-allowed '{rule}' (no more prompts)"


# ---------------------------------------------------------------------------
# Server reachability (soft check)
# ---------------------------------------------------------------------------
def server_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Production (--production): resolve endpoint + bearer token from .env.production
# ---------------------------------------------------------------------------
def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader — single-line values, quotes stripped, comments skipped.

    AGENTOS_URL and the JWT are both single-line, so this doesn't need the PEM
    multi-line handling that scripts/railway/env-sync.sh has.
    """
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if key.strip():
            values[key.strip()] = val
    return values


def derive_mcp_url(agentos_url: str) -> str:
    """`https://host[/...]` → `https://host/mcp` (idempotent if it already ends in /mcp)."""
    base = agentos_url.strip().rstrip("/")
    return base if base.endswith("/mcp") else f"{base}/mcp"


def resolve_production(env_file: Path, token_arg: str | None, *, need_token: bool) -> tuple[str, str | None]:
    """Resolve the deployed MCP URL (and bearer header) from .env.production.

    Returns (url, header); header is None when need_token is False (e.g. --remove,
    which matches clients by name and needs neither URL nor token). Exits with a
    clear message if the file / AGENTOS_URL is missing, the URL looks local, or a
    token is required but can't be found.
    """
    if not env_file.exists():
        sys.exit(f"  {FAIL} {env_file} not found — deploy first (see README → 'Run in production').")
    env = parse_env_file(env_file)

    agentos_url = env.get(AGENTOS_URL_KEY, "").strip()
    if not agentos_url:
        sys.exit(f"  {FAIL} {AGENTOS_URL_KEY} is not set in {env_file} — can't derive the /mcp URL.")
    host = (urlparse(agentos_url).hostname or "").lower()
    if host in ("", "localhost", "127.0.0.1"):
        sys.exit(f"  {FAIL} {AGENTOS_URL_KEY}={agentos_url!r} looks local, not a deployed domain.")
    url = derive_mcp_url(agentos_url)

    if not need_token:
        return url, None

    token = (token_arg or os.environ.get(CODEX_TOKEN_ENV) or env.get(JWT_ENV_KEY) or "").strip()
    if not token:
        try:
            token = getpass.getpass("  Paste the AgentOS JWT (Bearer token, not echoed): ").strip()
        except (EOFError, KeyboardInterrupt):
            token = ""
    if not token:
        sys.exit(
            f"  {FAIL} No JWT found. Add {JWT_ENV_KEY}=<token> to {env_file}, pass --token, "
            f"or set ${CODEX_TOKEN_ENV}. Mint it at os.agno.com (see docs/MCP.md)."
        )
    return url, f"Authorization: Bearer {token}"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add @context's MCP server to your local MCP clients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help=f"deployed instance: read {AGENTOS_URL_KEY} from {ENV_FILE_DEFAULT} (→ /mcp) and add a Bearer JWT",
    )
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"MCP endpoint (default: {DEFAULT_URL}; ignored with --production)"
    )
    parser.add_argument(
        "--token", default=None, help="Bearer JWT for a deployed instance (else read from .env.production / prompted)"
    )
    parser.add_argument(
        "--env-file", default=ENV_FILE_DEFAULT, help=f"env file --production reads from (default: {ENV_FILE_DEFAULT})"
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"server name in each client (default: {DEFAULT_NAME})")
    parser.add_argument(
        "--clients", nargs="+", choices=CLIENTS, default=list(CLIENTS), help="limit to specific clients"
    )
    parser.add_argument("--remove", action="store_true", help="remove @context from the clients instead of adding")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    parser.add_argument("--force", action="store_true", help="re-add to CLI clients even if already present")
    parser.add_argument(
        "--config-path", type=Path, default=None, help="override the Claude Desktop config path (advanced/testing)"
    )
    args = parser.parse_args()

    # Resolve the endpoint + auth header. Production derives both from .env.production;
    # otherwise --url is used as-is, and --token (if given) authenticates a manual deploy.
    header: str | None = None
    if args.production:
        env_file = Path(args.env_file)
        if not env_file.is_absolute():
            env_file = _repo_root() / env_file
        url, header = resolve_production(env_file, args.token, need_token=not args.remove)
    else:
        url = args.url
        if args.token:
            header = f"Authorization: Bearer {args.token}"

    verb = "Removing" if args.remove else "Adding"
    target = "production" if args.production else "local"
    print(f"{verb} @context ('{args.name}' → {url}) [{target}]{' [dry-run]' if args.dry_run else ''}\n")

    if not args.remove and not args.dry_run and not server_reachable(url):
        if args.production:
            print(f"  note: can't reach {url} yet — is the deploy live? (writing client config anyway.)\n")
        else:
            print(f"  note: nothing is listening at {url} yet — start it with `docker compose up -d`.")
            print("        (writing client config anyway; it'll connect once the server is up.)\n")

    desktop_config = args.config_path or claude_desktop_config_path()
    results: list[tuple[str, str]] = []
    for client in args.clients:
        if client == "claude-desktop":
            results.append(
                connect_claude_desktop(
                    url, args.name, desktop_config, header=header, remove=args.remove, dry_run=args.dry_run
                )
            )
        else:
            results.append(
                connect_cli(
                    client, url, args.name, header=header, remove=args.remove, dry_run=args.dry_run, force=args.force
                )
            )

    # Claude Code prompts before each MCP call until the tool is allow-listed, so once the
    # server is registered, always-allow its `use_context` tool too (only when Claude Code is
    # actually present — mirrors connect_cli's own skip).
    if "claude-code" in args.clients and shutil.which("claude"):
        results.append(allow_claude_code_tool(args.name, remove=args.remove, dry_run=args.dry_run))

    for glyph, message in results:
        print(f"  {glyph} {message}")

    if not args.remove:
        if args.production:
            if "codex" in args.clients and header:
                print(
                    f"\n  Codex reads its token from ${CODEX_TOKEN_ENV} at run time (kept out of its config).\n"
                    f"  Add `export {CODEX_TOKEN_ENV}=<token>` to your shell profile so Codex can authenticate."
                )
            print(
                f"\n  ChatGPT web / Claude web: add {url} as a remote connector with header\n"
                "  'Authorization: Bearer <JWT>' (see docs/MCP.md)."
            )
            print(
                "\n  Switched a client from local to production? CLI clients match by name — re-run with\n"
                "  --force (or --remove first). Claude Desktop updates in place."
            )
        else:
            print(
                "\n  ChatGPT (desktop + web): no local config to write — it only reaches MCP servers as a\n"
                "  remote HTTPS connector. Deploy or tunnel, then add https://<domain>/mcp under\n"
                "  Settings → Connectors (see docs/MCP.md)."
            )
        if sys.platform.startswith("win") and "claude-desktop" in args.clients:
            print(
                "\n  Windows: the Claude Desktop bridge is best-effort/untested — after restarting the\n"
                "  app, confirm `context` connects; the npx invocation may need adjusting."
            )

    if not args.remove and not args.dry_run and any(g == OK for g, _ in results):
        print("\nDone. Restart the Claude Desktop app if you configured it; CLI clients pick it up immediately.")
    return 1 if any(glyph == FAIL for glyph, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
