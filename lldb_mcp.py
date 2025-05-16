"""
LLDB FastMCP *client/proxy* server that forwards LLDB commands to the LLDB server.
"""
import socket
import json
import os
import threading
from fastmcp import FastMCP

# LLDB TCP server configuration
LLDB_HOST = '127.0.0.1'
LLDB_PORT = 3003

# Persistent connection to LLDB TCP server and lock to serialize commands
_client_lock = threading.Lock()
_sock = None
_file = None

def _ensure_connection():
    global _sock, _file
    with _client_lock:
        if _file:
            try:
                # Quick check if connection is alive
                _sock.getpeername()
                return
            except (OSError, socket.error):
                # Connection is dead, close it
                _file.close()
                _sock.close()
                _file = _sock = None
                
        # Create a new connection
        try:
            _sock = socket.create_connection((LLDB_HOST, LLDB_PORT))
            _file = _sock.makefile(mode='rw', encoding='utf-8')
        except Exception as e:
            raise RuntimeError(f"Failed to connect to LLDB server at {LLDB_HOST}:{LLDB_PORT}: {e}")

# Initialize the FastMCP server
mcp = FastMCP(
    name="lldb_mcp",
    instructions="You can run most lldb commands, ALWAYS start with lldb_init unless specified otherwise"
)

@mcp.tool(name="lldb_init", description="Load executable and launch process with stop-at-entry")
def init(fullpath: str) -> str:
    """Start the given executable: load file then launch process and stop at entry."""
    if not os.path.isfile(fullpath):
        return f"ERROR: file {fullpath} does not exist"
    
    # For seamless restarts, silently discard output.
    _ = send("target delete --all")
    
    # load the executable
    out1 = send(f"file {fullpath}")
    if out1.startswith("ERROR"):
        return out1
    # launch the process and stop at entry
    out2 = send("process launch --stop-at-entry")
    return (out1 or '') + (out2 or '')

@mcp.tool(name="lldb", description="Send a single LLDB command and return its output")
def send(command: str) -> str:
    """Send a single LLDB command and return its output."""
    try:
        _ensure_connection()
        with _client_lock:
            _file.write(command.strip() + '\n')
            _file.flush()
            raw = _file.readline()
        if not raw:
            return ''
        data = json.loads(raw)
        err = data.get('error', '')
        out = data.get('output', '')
        # if LLDB reported an error, forward it
        if err:
            return err
        # if LLDB succeeded but printed nothing, return Executed successfully
        if not out:
            return 'Executed successfully'
        return out
    except Exception as e:
        return f"ERROR: Cannot send command: {e}"

if __name__ == '__main__':
    mcp.run(transport='stdio')
