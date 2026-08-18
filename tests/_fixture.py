"""
Shared test fixture helper.

The committed fixture sitemap hardcodes :8099. Any test on another port then
sees every sitemap URL as off-host, which silently changes crawl coverage and
makes results depend on which port a test happened to get. Serving a
port-corrected COPY removes that entire class of flakiness — and lets every
test own a unique port, so they stop colliding when run in sequence.
"""
import functools, http.server, os, pathlib, re, shutil, socketserver, tempfile, threading

FIXTURE_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "fixture", "site")


def port_correct_fixture(port: int, src: str = None) -> str:
    dst = tempfile.mkdtemp(prefix=f"vici-fx-{port}-")
    shutil.copytree(src or FIXTURE_SRC, dst, dirs_exist_ok=True)
    for name in ("sitemap.xml", "robots.txt"):
        f = pathlib.Path(dst, name)
        if f.exists():
            f.write_text(re.sub(r"http://localhost:\d+", f"http://localhost:{port}",
                                f.read_text()))
    return dst


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(port: int, root: str = None):
    """Start a fixture server; returns (httpd, root). Call stop(httpd) after."""
    root = root or port_correct_fixture(port)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", port),
                                   functools.partial(Quiet, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, root


def stop(httpd):
    try:
        httpd.shutdown()
        httpd.server_close()      # release the port immediately for the next test
    except Exception:
        pass
