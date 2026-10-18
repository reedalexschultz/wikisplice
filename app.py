"""
WikiSplice — point-and-click interface.

Starts a small web page on your own computer (nothing is put online) and opens
it in your browser. Fill in a search term, press Start, and watch the
screenshots appear. Under the hood it runs wikisplice.py for you.

    python app.py            # opens http://127.0.0.1:8765
    python app.py --port 9000 --no-browser
"""
from __future__ import annotations

import argparse
import glob
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "wikisplice.py")
UI_FILE = os.path.join(HERE, "ui", "index.html")

sys.path.insert(0, HERE)
from wikisplice import DEFAULT_SPORTS_SITES, OUTPUT_ROOT, default_run_dir  # noqa: E402
import updater  # noqa: E402

PORT = 8765  # set in main(); reused when restarting after an update


def restart_app() -> None:
    """Replace this process with a fresh copy of the app (same port), so an update takes effect."""
    os.execv(sys.executable, [sys.executable, os.path.join(HERE, "app.py"), "--port", str(PORT), "--no-browser"])


# ------------------------------
# One job at a time
# ------------------------------
class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.log: list[str] = []
        self.outdir = ""
        self.jsx = ""
        self.started = 0.0
        self.exit_code: int | None = None
        self.target = 0
        self.stopped = False
        self.warning = ""

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, argv: list[str], outdir: str, target: int) -> None:
        with self.lock:
            self.log = ["$ " + " ".join(_shell_quote(a) for a in argv[1:])]
            self.outdir = outdir
            self.jsx = ""
            self.exit_code = None
            self.target = target
            self.stopped = False
            self.warning = ""
            self.started = time.time()
            self.proc = subprocess.Popen(
                argv, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            with self.lock:
                self.log.append(line)
                m = re.match(r"\[ok\] JSX written: (.+)$", line)
                if m:
                    self.jsx = m.group(1).strip()
                if line.startswith("[warn] Only found"):
                    self.warning = line[len("[warn] "):]
        code = self.proc.wait()
        with self.lock:
            self.exit_code = code

    def stop(self) -> None:
        if self.running and self.proc:
            self.stopped = True
            self.proc.terminate()

    def images(self) -> list[str]:
        if not self.outdir:
            return []
        files = glob.glob(os.path.join(self.outdir, "screens", "*.png"))
        files = [f for f in files if os.path.getmtime(f) >= self.started - 1]
        files.sort(key=os.path.getmtime)
        return [os.path.relpath(f, OUTPUT_ROOT) for f in files]


JOB = Job()


def _shell_quote(s: str) -> str:
    return s if re.fullmatch(r"[\w./,:=+-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def find_after_effects() -> list[str]:
    """Installed After Effects apps, newest first (skips the headless Render Engine)."""
    names = set()
    for pattern in ("/Applications/Adobe After Effects*/Adobe After Effects*.app",
                    "/Applications/Adobe After Effects*.app"):
        for p in glob.glob(pattern):
            name = os.path.splitext(os.path.basename(p))[0]
            if "Render Engine" not in name:
                names.add(name)

    def newest_first(name: str):
        m = re.search(r"(\d{4})", name)
        return (0 if m else 1, -int(m.group(1)) if m else 0, name)  # dated releases first, Beta last
    return sorted(names, key=newest_first)


def build_argv(o: dict) -> tuple[list[str], str, int]:
    """Turn the form's settings into a wikisplice.py command line."""
    term = str(o.get("term", "")).strip()
    if not term:
        raise ValueError("Type something to search for first.")
    outdir = default_run_dir(term)  # new folder every run; nothing is cleared
    argv = [sys.executable, "-u", SCRIPT, "--term", term, "--out", outdir]

    source = o.get("source", "wikipedia")
    if source not in ("wikipedia", "sports", "both"):
        raise ValueError("Unknown source.")
    argv += ["--source", source]
    if source != "wikipedia":
        sites = ",".join(s.strip() for s in re.split(r"[,\n]", str(o.get("sports_sites", ""))) if s.strip())
        if sites:
            argv += ["--sports-sites", sites]

    exclude = ",".join(w.strip() for w in re.split(r"[,\n]", str(o.get("exclude", ""))) if w.strip())
    if exclude:
        argv += ["--exclude", exclude]

    def num(key: str, flag: str, cast=float) -> None:
        v = o.get(key)
        if v not in (None, ""):
            argv.extend([flag, str(cast(v))])

    num("width", "--width", int)
    num("height", "--height", int)
    num("max_total", "--max-total-matches", int)
    num("max_per_page", "--max-matches-per-page", int)
    num("max_articles", "--max-articles", int)
    num("speed", "--speed")
    num("fps", "--fps")
    num("dpr", "--dpr")
    num("target_word_px", "--target-word-px", int)
    num("framing_zoom", "--framing-zoom")
    num("scale", "--scale")
    num("ae_punch", "--ae-punch")
    num("center_max_iter", "--center-max-iter", int)
    num("settle_ms", "--settle-ms", int)
    num("limit", "--limit", int)
    if o.get("search_in") in ("text", "title", "both"):
        argv += ["--search-in", o["search_in"]]

    if not o.get("match_case", True):
        argv.append("--ignore-case")
    if not o.get("whole_word", True):
        argv.append("--no-whole-word")
    for key, flag in (("highlight_all", "--highlight-all"), ("pad_to_center", "--pad-to-center"),
                      ("no_math_map", "--no-math-map"), ("run_ae", "--run-ae"),
                      ("transparent", "--transparent")):
        if o.get(key):
            argv.append(flag)
    if o.get("run_ae"):
        versions = find_after_effects()
        ae = o.get("ae_version") if o.get("ae_version") in versions else (versions or ["Adobe After Effects 2026"])[0]
        argv += ["--ae-version", ae]

    return argv, outdir, int(o.get("max_total") or 50)


def reveal(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", path])


# ------------------------------
# HTTP
# ------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:  # keep the terminal quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _local_only(self) -> bool:
        # Only accept requests aimed at this machine (blocks DNS-rebinding tricks)
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self._json({"error": "forbidden"}, 403)
            return False
        return True

    def do_GET(self) -> None:
        if not self._local_only():
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            with open(UI_FILE, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/api/info":
            self._json({"sports_sites": DEFAULT_SPORTS_SITES, "ae_versions": find_after_effects(),
                        "output_root": OUTPUT_ROOT})
        elif path == "/api/update/check":
            try:
                self._json(updater.check())
            except Exception as e:  # offline, GitHub down, rate limited... just don't show a banner
                self._json({"available": False, "error": str(e)})
        elif path == "/api/status":
            since = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("since", ["0"])[0])
            with JOB.lock:
                self._json({
                    "running": JOB.running, "exit_code": JOB.exit_code, "stopped": JOB.stopped,
                    "log": JOB.log[since:], "log_len": len(JOB.log), "jsx": JOB.jsx,
                    "outdir": JOB.outdir, "target": JOB.target, "images": JOB.images(), "warning": JOB.warning,
                })
        elif path.startswith("/files/"):
            rel = urllib.parse.unquote(path[len("/files/"):])
            full = os.path.realpath(os.path.join(OUTPUT_ROOT, rel))
            if not full.startswith(os.path.realpath(OUTPUT_ROOT) + os.sep) or not os.path.isfile(full):
                self._json({"error": "not found"}, 404)
                return
            with open(full, "rb") as f:
                self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._local_only():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/run":
                if JOB.running:
                    return self._json({"error": "Already running — press Stop first."}, 409)
                argv, outdir, target = build_argv(body)
                JOB.start(argv, outdir, target)
                self._json({"ok": True})
            elif path == "/api/update/apply":
                # Only reached when the user clicked "Update now"
                if JOB.running:
                    return self._json({"error": "Wait for the current search to finish (or press Stop) first."}, 409)
                result = updater.apply()
                if result["requirements_changed"]:
                    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r",
                                    os.path.join(HERE, "requirements.txt")], check=False)
                self._json({"ok": True, **result})
                threading.Timer(1.0, restart_app).start()  # after the reply reaches the page
            elif path == "/api/stop":
                JOB.stop()
                self._json({"ok": True})
            elif path == "/api/open":
                what = body.get("what")
                if what == "folder" and JOB.outdir and os.path.isdir(JOB.outdir):
                    reveal(JOB.outdir)
                elif what == "ae" and JOB.jsx and os.path.isfile(JOB.jsx):
                    from wikisplice import maybe_run_after_effects
                    versions = find_after_effects()
                    ae = body.get("ae_version") if body.get("ae_version") in versions else (versions or ["Adobe After Effects 2026"])[0]
                    ok, msg = maybe_run_after_effects(JOB.jsx, ae_version=ae)
                    return self._json({"ok": ok, "message": msg}, 200 if ok else 500)
                else:
                    return self._json({"error": "Nothing to open yet."}, 400)
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # surface anything unexpected in the UI
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main() -> None:
    ap = argparse.ArgumentParser(description="WikiSplice point-and-click interface")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically")
    args = ap.parse_args()

    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    port = args.port
    for _ in range(20):  # find a free port if 8765 is taken
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        sys.exit("Could not find a free port.")

    global PORT
    PORT = port
    url = f"http://127.0.0.1:{port}"
    print(f"\n  WikiSplice is running at {url}\n  (Leave this window open. Close it or press Ctrl+C to quit.)\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        JOB.stop()


if __name__ == "__main__":
    main()
