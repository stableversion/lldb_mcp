"""
lldb_server.py: LLDB plugin to run a TCP server with full, reliable output capture.
"""

import lldb
import threading
import socketserver
import json
import sys
import re
import time

HOST = '127.0.0.1'
PORT = 3003
BLACKLIST = ['attach', 'gdb-remote', 'kdp-remote', 'gui', 'shell', 'platform', 'detach']
# regex to strip ANSI color codes
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')

class LLDBController:
    """Helper to run LLDB commands and synchronously collect every output via SBListener."""
    def __init__(self, debugger):
        self.debugger = debugger
        # run commands synchronously, so HandleCommand returns all output
        self.debugger.SetAsync(False)
        self.interp = debugger.GetCommandInterpreter()

    def run_command(self, command):
        """Run a single LLDB command synchronously and return its output and error."""
        result = lldb.SBCommandReturnObject()
        self.interp.HandleCommand(command, result)
        out = result.GetOutput() or ''
        err = result.GetError() or ''
        return out, err

class LLDBRequestHandler(socketserver.StreamRequestHandler):
    """Handle incoming TCP connections, run LLDB commands one at a time, and return JSON responses."""
    def handle(self):
        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            command = raw.decode('utf-8').strip()
            if not command:
                continue
            print(f"(mcp) >>> {command}")
            # reject multiple commands separated by a semicolon
            if ';' in command:
                err = 'Error, multiple commands not allowed'
                print(err)
                resp = {'command': command, 'output': '', 'error': err}
                self.wfile.write((json.dumps(resp) + '\n').encode('utf-8'))
                sys.stdout.write("\r(lldb) ")
                sys.stdout.flush()
                continue
            # reject by name
            cmd_name = command.split()[0]
            if cmd_name in BLACKLIST:
                err = 'Error, current command not allowed'
                print(err)
                resp = {'command': command, 'output': '', 'error': err}
                self.wfile.write((json.dumps(resp) + '\n').encode('utf-8'))
                sys.stdout.write("\r(lldb) ")
                sys.stdout.flush()
                continue
            # run through controller
            out, err = controller.run_command(command)
            # print locally in LLDB console
            if out:
                print(out, end='')
            if err:
                print(err, end='')
            # send JSON response
            resp = {
                'command': command,
                'output': ANSI_ESCAPE.sub('', out),
                'error': ANSI_ESCAPE.sub('', err)
            }
            self.wfile.write((json.dumps(resp) + '\n').encode('utf-8'))
            sys.stdout.write("\r(lldb) ")
            sys.stdout.flush()

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

# module init entrypoint for LLDB
controller = None

def __lldb_init_module(debugger, internal_dict):
    global controller
    controller = LLDBController(debugger)
    server = ThreadedTCPServer((HOST, PORT), LLDBRequestHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"fastmcp server started on {HOST}:{PORT}")
    print(f"Send LLDB commands by connecting, e.g.: echo 'thread list' | nc {HOST} {PORT}")
