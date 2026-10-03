#!/usr/bin/env python3
"""Connect an existing local ComfyUI to Codex; Python 3.10-3.14."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import venv

PACKAGES = ("comfy-mcp==0.10.0", "comfy-cli==1.22.0")
OFFICIAL_SKILLS = ("comfy", "comfy-debug", "comfy-relay")
SERVER_NAME = "comfyui"
MARKER = ".comfyui-codex-managed.json"


def local_url(value: str) -> str:
    parts = urlsplit(value)
    try:
        loopback = parts.hostname == "localhost" or ipaddress.ip_address(parts.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if (parts.scheme != "http" or not loopback or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("Use a loopback HTTP URL, e.g. http://127.0.0.1:8188")
    if not parts.port or not 1 <= parts.port <= 65535:
        raise ValueError("Specify the ComfyUI port in --url")
    return value.rstrip("/")


def default_install_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "comfyui-codex"
    return Path.home() / "Library/Application Support/comfyui-codex"


def bin_path(env_dir: Path, name: str) -> Path:
    return env_dir / ("Scripts" if os.name == "nt" else "bin") / (name + ".exe" if os.name == "nt" else name)


def find_codex(explicit: str | None) -> str:
    found = explicit or shutil.which("codex")
    if not found and platform.system() == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "OpenAI/Codex/bin"
        candidates = sorted(root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        found = str(candidates[0]) if candidates else None
    if not found or not Path(found).is_file():
        raise RuntimeError("Codex CLI not found. Install Codex CLI or pass --codex /absolute/path/to/codex")
    return str(Path(found).resolve())


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(argv, check=True, env=env, **kwargs)


def fetch_stats(url: str) -> dict:
    req = Request(url + "/system_stats", headers={"User-Agent": "comfyui-codex-setup/1"})
    with urlopen(req, timeout=10) as response:
        data = json.load(response)
    if not isinstance(data.get("system"), dict) or not isinstance(data.get("devices"), list):
        raise RuntimeError("The endpoint does not look like ComfyUI /system_stats")
    return data


def valid_checkout(path: Path) -> bool:
    return (path / "main.py").is_file() and (path / "folder_paths.py").is_file()


def discover_checkout(url: str, stats: dict) -> tuple[Path | None, list[str]]:
    """Match the listening server's process; never choose an arbitrary old install."""
    import psutil
    port = urlsplit(url).port
    pid = None
    try:
        pids = {c.pid for c in psutil.net_connections(kind="tcp")
                if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid}
        if len(pids) == 1:
            pid = pids.pop()
    except (psutil.AccessDenied, OSError):
        pass
    api_args = stats["system"].get("argv", [])
    processes = [psutil.Process(pid)] if pid else psutil.process_iter()
    matches = []
    for proc in processes:
        try:
            args = proc.cmdline()
            main_args = [a for a in args if Path(a).name == "main.py"]
            if not main_args:
                continue
            # Without socket permissions require the API's exact launch arguments.
            if not pid and (not api_args or args[-len(api_args):] != api_args):
                continue
            path = (Path(proc.cwd()) / main_args[0]).resolve().parent
            if valid_checkout(path):
                matches.append((path, args))
        except (psutil.Error, OSError):
            continue
    unique = {str(path): (path, args) for path, args in matches}
    return next(iter(unique.values())) if len(unique) == 1 else (None, api_args)


def model_roots(checkout: Path, argv: list[str]) -> list[str]:
    import yaml
    roots = []
    configs = [checkout / "extra_model_paths.yaml"]
    for i, arg in enumerate(argv):
        if arg == "--extra-model-paths-config":
            for value in argv[i + 1:]:
                if value.startswith("--"):
                    break
                if Path(value).is_absolute():
                    configs.append(Path(value))
    for config in configs:
        if not config.is_file():
            continue
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        for item in data.values():
            if isinstance(item, dict) and item.get("base_path"):
                path = (config.parent / os.path.expanduser(item["base_path"])).resolve()
                if path.is_dir() and str(path) not in roots:
                    roots.append(str(path))
    if not roots:
        roots.append(str(checkout / "models"))
    return roots


def atomic_write(path: Path, content: str, backup: bool = False) -> bool:
    """Preserve existing settings and leave no partial file after interruption."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + f".backup-{time.time_ns()}"))
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def update_config(path: Path, entry: dict, replace: bool = False) -> bool:
    import tomlkit
    doc = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    servers = doc.get("mcp_servers")
    if servers is None:
        servers = tomlkit.table()
        doc["mcp_servers"] = servers
    current = servers.get(SERVER_NAME)
    if current is not None and dict(current) != entry and not replace:
        # Reruns may change their own path/URL but must not replace someone else's server.
        if current.get("env", {}).get("COMFY_CODEX_SETUP") != "1":
            raise RuntimeError("An unmanaged 'comfyui' MCP already exists; inspect it or use --replace-mcp")
    if current is not None and dict(current) == entry:
        return False
    servers[SERVER_NAME] = entry
    return atomic_write(path, tomlkit.dumps(doc), backup=True)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != MARKER and "__pycache__" not in path.parts and path.suffix != ".pyc":
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def install_official_skills(dest: Path) -> None:
    import comfy_cli
    source = Path(comfy_cli.__file__).parent / "skills"
    for name in OFFICIAL_SKILLS:
        target = dest / name
        expected = tree_digest(source / name)
        if target.exists():
            if tree_digest(target) != expected:
                raise RuntimeError(f"Existing skill differs: {target}. Back it up and choose how to update it.")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=name + "-", dir=target.parent))
            try:
                shutil.copytree(source / name, staging / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                os.replace(staging / name, target)
            finally:
                shutil.rmtree(staging)
        atomic_write(target / MARKER, json.dumps({"source": "Comfy-Org/comfy-cli", "version": "1.22.0", "sha256": expected}, indent=2) + "\n")


def bridge_skill(state: dict) -> str:
    return """---
name: comfy-codex-local
description: Use this computer's existing local ComfyUI through the official Comfy MCP, with its Desktop paths and local execution settings.
---

Use the `comfyui` MCP tools for local ComfyUI tasks. Start with `server_info`,
then query the live nodes/models and validate an API-format workflow before running it.
Read [connection.json](connection.json) for this computer's URL, checkout,
CLI executable, model roots, and whether Desktop manages the server.

If MCP tools are not available yet, use the connection's absolute `comfy_bin`
with `--workspace <comfy_dir> --where local --json`, setting
`COMFY_LOCAL_URL` to the recorded URL and `PYTHONUTF8=1`.
This CLI is in an isolated tools environment; it is not ComfyUI's Python.
Use ComfyUI's own environment for custom-node dependencies.

For Desktop installations, keep Desktop responsible for launch/restart/update.
Its input/output and model folders can be outside the core checkout. Use the
recorded model roots when downloading weights; verify download destinations
against Desktop's extra-model-path configuration. MCP `download_model` writes
under the checkout by default, so inspect its destination before using it.
For shared folders use the official CLI's `comfy model download --help` to
choose an explicit destination, or download to the recorded category folder.

Local routing is intentional. Do not infer cloud execution from an existing
Comfy login. Paid partner nodes and cloud execution require the user's request.
Install requested models/nodes only; this integration setup alone does not
authorize large model downloads. Consult the installed official `comfy-debug`
or `comfy-relay` skill when troubleshooting or editing workflows.
"""


async def verify_mcp(command: str, env: dict, expected_workspace: Path, url: str) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=command, args=[], env=dict(os.environ, **env))
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            if "server_info" not in names:
                raise RuntimeError("MCP did not advertise server_info")
            result = await session.call_tool("server_info", {})
            if result.is_error:
                raise RuntimeError("MCP server_info failed: " + str(result.content)[:2000])
            data = result.structured_content
            if data is None:
                data = json.loads(next(block.text for block in result.content if hasattr(block, "text")))
            # SDK FastMCP may wrap structured results in a result key.
            data = data.get("result", data)
            if not data.get("server", {}).get("running"):
                raise RuntimeError("MCP could not reach the running ComfyUI server")
            if data["server"].get("url", "").rstrip("/") != url:
                raise RuntimeError("MCP is pointed at a different ComfyUI URL")
            actual = Path(data.get("workspace", {}).get("path", "")).resolve()
            if actual != expected_workspace.resolve():
                raise RuntimeError(f"MCP selected the wrong checkout: {actual}")
            return {"mcp_tools": len(names), "server_running": True, "workspace_verified": True}


def finish(args, root: Path, codex: str, stats: dict) -> None:
    discovered, argv = discover_checkout(args.url, stats)
    checkout = Path(args.comfy_dir).expanduser().resolve() if args.comfy_dir else discovered
    if checkout is None or not valid_checkout(checkout):
        raise RuntimeError("Cannot identify the active ComfyUI checkout. Pass --comfy-dir /path/to/ComfyUI (contains main.py).")
    roots = [str(Path(args.models_dir).expanduser().resolve())] if args.models_dir else model_roots(checkout, argv)
    tools_dir = root / "tools"
    env = {"COMFY_BIN": str(bin_path(tools_dir, "comfy")), "COMFY_PROJECT": str(checkout),
           "COMFY_LOCAL_URL": args.url, "COMFY_WHERE": "local", "PYTHONUTF8": "1",
           "PYTHONIOENCODING": "utf-8", "COMFYUI_URL": "", "COMFYUI_HOST": "",
           "COMFY_CODEX_SETUP": "1"}
    entry = {"command": str(bin_path(tools_dir, "comfy-mcp")), "args": [], "env": env,
             "startup_timeout_sec": 30, "tool_timeout_sec": 180}
    print("Verifying official MCP handshake and server_info...", flush=True)
    verification = asyncio.run(asyncio.wait_for(verify_mcp(entry["command"], env, checkout, args.url), timeout=150))
    state = {"schema": 1, "url": args.url, "comfy_dir": str(checkout), "model_roots": roots,
             "desktop_managed": any("--extra-model-paths-config" == a for a in argv),
             "comfy_bin": env["COMFY_BIN"], "mcp_command": entry["command"],
             "packages": list(PACKAGES), "verification": verification}
    codex_home = Path(args.codex_home).expanduser().resolve()
    skills = Path(args.skills_dir).expanduser().resolve() if args.skills_dir else codex_home / "skills"
    if not args.no_skills:
        install_official_skills(skills)
        bridge = skills / "comfy-codex-local"
        if bridge.exists() and not (bridge / MARKER).exists():
            raise RuntimeError(f"Unmanaged bridge skill exists: {bridge}")
        atomic_write(bridge / "SKILL.md", bridge_skill(state), backup=True)
        atomic_write(bridge / "connection.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        atomic_write(bridge / MARKER, '{"source":"comfyui-codex-setup","schema":1}\n')
    changed = update_config(codex_home / "config.toml", entry, args.replace_mcp)
    atomic_write(root / "connection.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    cli_env = dict(os.environ, CODEX_HOME=str(codex_home))
    subprocess.run([codex, "mcp", "get", SERVER_NAME, "--json"], check=True, env=cli_env, stdout=subprocess.DEVNULL)
    print(json.dumps({**verification, "config_changed": changed, "comfy_version": stats["system"].get("comfyui_version"),
                      "skills": [] if args.no_skills else [*OFFICIAL_SKILLS, "comfy-codex-local"]}, indent=2))
    print("Setup complete. Start a new Codex turn; reload Codex if the MCP tools do not appear.")
    print("Machine-only connection details: " + str(root / "connection.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--comfy-dir", help="Active ComfyUI checkout containing main.py; auto-detected when possible")
    parser.add_argument("--models-dir", help="Override the shared model root recorded for the agent")
    parser.add_argument("--install-dir", default=str(default_install_dir()))
    parser.add_argument("--codex", help="Absolute Codex CLI executable")
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--skills-dir", help="Override the Codex skill directory")
    parser.add_argument("--no-skills", action="store_true")
    parser.add_argument("--replace-mcp", action="store_true", help="Replace an existing unmanaged comfyui MCP entry")
    parser.add_argument("--finish", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if platform.system() not in ("Windows", "Darwin"):
        raise RuntimeError("This installer targets Windows and macOS")
    if not (3, 10) <= sys.version_info[:2] < (3, 15):
        raise RuntimeError("Use Python 3.10 through 3.14")
    args.url = local_url(args.url)
    codex = find_codex(args.codex)
    stats = fetch_stats(args.url)
    root = Path(args.install_dir).expanduser().resolve()
    if args.finish:
        finish(args, root, codex, stats)
        return
    env_dir = root / "tools"
    python = bin_path(env_dir, "python")
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(env_dir)
    run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *PACKAGES])
    run([str(python), str(Path(__file__).resolve()), *sys.argv[1:], "--finish"])


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        def describe(error):
            children = getattr(error, "exceptions", ())
            return "; ".join(describe(child) for child in children) if children else str(error)
        print(f"Setup failed: {describe(exc)}", file=sys.stderr)
        sys.exit(1)
