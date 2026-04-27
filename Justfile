set shell := ["bash", "-uc"]

repo_path := justfile_directory()

mcp-config:
    @python -c 'import json, shlex, sys; repo_path = sys.argv[1]; config = {"mcpServers": {"remarkable": {"type": "stdio", "command": "/bin/bash", "args": ["-c", f"cd {shlex.quote(repo_path)} && exec uv run remarkable-mcp"]}}}; print(json.dumps(config, indent=2))' "{{repo_path}}"
