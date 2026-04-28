set shell := ["bash", "-uc"]

repo_path := justfile_directory()

mcp-config:
    @python -c 'import json, shlex, sys; repo_path = sys.argv[1]; config = {"mcpServers": {"remarkable": {"type": "stdio", "command": "/bin/bash", "args": ["-c", f"cd {shlex.quote(repo_path)} && exec uv run remarkable-mcp"]}}}; print(json.dumps(config, indent=2))' "{{repo_path}}"

mcp-config-write-tools-enabled backup_retention="":
    @python -c 'import json, shlex, sys; repo_path, backup_retention = sys.argv[1], sys.argv[2]; env = {"REMARKABLE_ENABLE_WRITE_TOOLS": "true"}; config = {"mcpServers": {"remarkable": {"type": "stdio", "command": "/bin/bash", "args": ["-c", f"cd {shlex.quote(repo_path)} && exec uv run remarkable-mcp"], "env": env}}}; env.update({"REMARKABLE_BACKUP_RETENTION_COUNT": backup_retention} if backup_retention else {}); print(json.dumps(config, indent=2))' "{{repo_path}}" "{{backup_retention}}"

mcp-config-cowork project_name:
    @python -c 'import json, os, shlex, sys; repo_path, project_name = sys.argv[1], sys.argv[2]; render_dir = os.path.expanduser(f"~/Documents/Claude/Projects/{project_name}/renders"); env = {"REMARKABLE_RENDER_DIR": render_dir}; config = {"mcpServers": {"remarkable": {"type": "stdio", "command": "/bin/bash", "args": ["-c", f"cd {shlex.quote(repo_path)} && exec uv run remarkable-mcp"], "env": env}}}; print(json.dumps(config, indent=2))' "{{repo_path}}" "{{project_name}}"

mcp-config-cowork-write-tools-enabled project_name backup_retention="":
    @python -c 'import json, os, shlex, sys; repo_path, project_name, backup_retention = sys.argv[1], sys.argv[2], sys.argv[3]; render_dir = os.path.expanduser(f"~/Documents/Claude/Projects/{project_name}/renders"); env = {"REMARKABLE_RENDER_DIR": render_dir, "REMARKABLE_ENABLE_WRITE_TOOLS": "true"}; env.update({"REMARKABLE_BACKUP_RETENTION_COUNT": backup_retention} if backup_retention else {}); config = {"mcpServers": {"remarkable": {"type": "stdio", "command": "/bin/bash", "args": ["-c", f"cd {shlex.quote(repo_path)} && exec uv run remarkable-mcp"], "env": env}}}; print(json.dumps(config, indent=2))' "{{repo_path}}" "{{project_name}}" "{{backup_retention}}"
