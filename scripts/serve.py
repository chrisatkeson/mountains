#!/usr/bin/env python3
"""Serve the viewer with cache revalidation on every request.

Same as `python3 -m http.server` from the viewer folder, but every response
carries `Cache-Control: no-cache`, so the browser revalidates files (cheap 304s
for unchanged tiles) instead of reusing stale copies after a pyramid rebuild.
It also serves in multiple threads, which makes tile streaming much snappier.

    python3 scripts/serve.py [port]      # default 8000
"""
import os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "viewer")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):   # quiet: only report errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"serving {os.path.abspath(ROOT)} at http://localhost:{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
