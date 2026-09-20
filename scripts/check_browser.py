"""Run real Chrome checks with a disposable database and browser profile."""

import os
import argparse
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import flask
from werkzeug.serving import WSGIRequestHandler, make_server

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
import app as labeling


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


def main():
    # This check always uses disposable SQLite storage, never a configured project.
    for name in ("DATABASE_URL", "EMAIL_HASH_KEY", "VERCEL"):
        os.environ.pop(name, None)
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    options = parser.parse_args()
    chrome = os.environ.get("CHROME_BINARY") or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).exists():
        raise SystemExit("Set CHROME_BINARY to an installed Chrome or Chromium executable.")

    with tempfile.TemporaryDirectory(prefix="labeler-browser-") as directory:
        temporary = Path(directory)
        labeling.DATABASE = temporary / "labels.db"
        labeling.HASH_KEY_FILE = temporary / ".email_hash_key"
        labeling.DATA_FILE = temporary / "tweets.csv"
        labeling.DATA_FILE.write_text(
            "id, tweet, emotion\n" + "".join(
                f"{index}, Example message for browser testing {index}, {index}\n"
                for index in range(6)
            ), encoding="utf-8"
        )
        labeling.configure_app()
        report = {}
        completed = threading.Event()

        @labeling.app.post("/__browser_report__")
        def browser_report():
            report.update(flask.request.get_json())
            completed.set()
            return "", 204

        @labeling.app.get("/__browser_checks__")
        def browser_checks():
            return Path(__file__).with_name("browser_checks.html").read_text(encoding="utf-8")

        @labeling.app.after_request
        def block_storage_for_test(response):
            if flask.request.args.get("blocked-storage") == "1":
                script = "<script>for (const name of ['localStorage', 'sessionStorage']) Object.defineProperty(window, name, {get() {throw new Error('Storage blocked');}});</script>"
                response.set_data(response.get_data(as_text=True).replace("<head>", "<head>" + script))
            return response

        server = make_server("127.0.0.1", 0, labeling.app, request_handler=QuietRequestHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryFile() as chrome_log:
                process = subprocess.Popen(
                    [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                     "--disable-background-networking", "--no-default-browser-check",
                     "--use-mock-keychain", "--password-store=basic",
                     "--disable-background-timer-throttling", "--remote-debugging-port=0",
                     f"--user-data-dir={temporary / 'chrome'}", "--window-size=1280,1000",
                     f"http://127.0.0.1:{server.server_port}/__browser_checks__"],
                    stdout=chrome_log, stderr=chrome_log, start_new_session=True,
                )
                try:
                    finished = completed.wait(timeout=30)
                    if finished and report.get("status") == "passed" and options.screenshots:
                        chrome_log.seek(0)
                        debug_port = re.search(rb"DevTools listening on ws://127\.0\.0\.1:(\d+)", chrome_log.read())
                        if not debug_port:
                            raise RuntimeError("Chrome did not expose its local debugging port.")
                        subprocess.run(
                            ["node", str(Path(__file__).with_name("capture_browser.mjs")),
                             "http://127.0.0.1:" + debug_port[1].decode(),
                             f"http://127.0.0.1:{server.server_port}", str(options.screenshots)],
                            check=True, timeout=45,
                        )
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                print(report.get("messages", "No browser report received."))
                if not finished or report.get("status") != "passed":
                    chrome_log.seek(0)
                    print(chrome_log.read().decode(errors="replace")[-2000:], file=sys.stderr)
                    raise SystemExit("Browser checks failed or did not finish within 30 seconds.")
            with labeling.get_db() as connection:
                rows = connection.execute("SELECT participant_id FROM responses").fetchall()
            assert len(rows) == 11 and all(len(row[0]) == 64 for row in rows)
            print("PASS: browser flow and persisted database checked using disposable storage.")
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    main()
