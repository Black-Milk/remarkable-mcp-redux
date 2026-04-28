"""End-to-end tests for the remarkable MCP server via stdio subprocess.

Sends JSON-RPC messages over stdin/stdout to verify the full transport layer.
"""

import json
import os
import subprocess

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = {**os.environ, "DYLD_LIBRARY_PATH": "/opt/homebrew/lib"}


def _send_jsonrpc(proc, method, params=None, request_id=1):
    """Send a JSON-RPC request and read the response."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        request["params"] = params
    return request


def _start_server():
    """Start the MCP server as a subprocess via the package entry point."""
    return subprocess.Popen(
        ["uv", "run", "remarkable-mcp"],
        cwd=SERVER_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=ENV,
    )


def _exchange(proc, message: dict) -> dict:
    """Send a JSON-RPC message and read one response line."""
    data = json.dumps(message) + "\n"
    proc.stdin.write(data.encode())
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read().decode()
        raise RuntimeError(f"Server returned no output. stderr: {stderr}")
    return json.loads(line.decode())


class TestE2EStdio:
    @pytest.mark.e2e
    def test_initialize_and_list_tools(self):
        """Server should respond to initialize and list its 7 read-only tools by default."""
        proc = _start_server()
        try:
            # Initialize
            init_resp = _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            })
            assert "result" in init_resp

            # Send initialized notification
            proc.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
            )
            proc.stdin.flush()

            # List tools
            tools_resp = _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            })
            assert "result" in tools_resp
            tool_names = [t["name"] for t in tools_resp["result"]["tools"]]
            assert "remarkable_check_status" in tool_names
            assert "remarkable_list_documents" in tool_names
            assert "remarkable_list_folders" in tool_names
            assert "remarkable_render_pages" in tool_names
            assert "remarkable_render_document" in tool_names
            assert "remarkable_get_document_info" in tool_names
            assert "remarkable_cleanup_renders" in tool_names
            # Write tools must NOT be present without the env flag
            assert "remarkable_rename_document" not in tool_names
            assert "remarkable_create_folder" not in tool_names
            assert len(tool_names) == 7
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.e2e
    def test_write_tools_listed_when_enabled(self):
        """With REMARKABLE_ENABLE_WRITE_TOOLS=true, all 8 write tools register."""
        env = {**ENV, "REMARKABLE_ENABLE_WRITE_TOOLS": "true"}
        proc = subprocess.Popen(
            ["uv", "run", "remarkable-mcp"],
            cwd=SERVER_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            })
            proc.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
            )
            proc.stdin.flush()

            tools_resp = _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            })
            tool_names = [t["name"] for t in tools_resp["result"]["tools"]]
            for name in (
                "remarkable_rename_document",
                "remarkable_rename_folder",
                "remarkable_move_document",
                "remarkable_move_folder",
                "remarkable_create_folder",
                "remarkable_pin_document",
                "remarkable_restore_metadata",
                "remarkable_cleanup_metadata_backups",
            ):
                assert name in tool_names, f"Missing write tool: {name}"
            assert len(tool_names) == 15  # 7 read + 8 write
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.e2e
    def test_check_status_tool_call(self):
        """Calling remarkable_check_status should return a valid status dict."""
        proc = _start_server()
        try:
            # Initialize
            _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            })
            proc.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
            )
            proc.stdin.flush()

            # Call check_status
            resp = _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "remarkable_check_status",
                    "arguments": {},
                },
            })
            assert "result" in resp
            # The result content is a list of content blocks
            content = resp["result"]["content"]
            assert len(content) > 0
            # Parse the text content as JSON
            status = json.loads(content[0]["text"])
            assert "cache_exists" in status
            assert "rmc_available" in status
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.e2e
    def test_cleanup_renders_tool_call(self):
        """Calling remarkable_cleanup_renders should return files_removed and bytes_freed."""
        proc = _start_server()
        try:
            # Initialize
            _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            })
            proc.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
            )
            proc.stdin.flush()

            # Call cleanup
            resp = _exchange(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "remarkable_cleanup_renders",
                    "arguments": {},
                },
            })
            assert "result" in resp
            content = resp["result"]["content"]
            result = json.loads(content[0]["text"])
            assert "files_removed" in result
            assert "bytes_freed" in result
        finally:
            proc.terminate()
            proc.wait()
