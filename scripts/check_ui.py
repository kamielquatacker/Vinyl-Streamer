"""Browser regression checks against simulated Pi responses; no audio is changed."""
from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.path = "/static/index.html"
        super().do_GET()

    def log_message(self, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional path to a Chrome/Chromium executable")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "app")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 1100}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            sink = "raop_sink.192.168.1.20"
            source = "alsa_input.usb-capture"
            devices = {
                "sinks": [], "sources": [{"name": source}],
                "airplay": [{"friendly_name": "SoundTouch Quatacker", "address": "192.168.1.20", "service_type": "_raop._tcp.local."},
                            {"friendly_name": "SoundTouch Quatacker", "address": "192.168.1.20", "service_type": "_airplay._tcp.local."}],
                "warnings": [], "discovering": False,
            }
            status = {"running": False, "sink": None, "source": None, "latency_ms": 80, "volume": None, "muted": None, "warnings": []}
            flags = {"connect_error": False, "disconnect_error": False, "status_error": False, "volume_error": False}
            calls = []

            def respond(route):
                path = route.request.url.split("/api/", 1)[-1]
                body = route.request.post_data_json if route.request.method == "POST" else None
                calls.append((path, body))
                code, data = 200, {"ok": True}
                if path == "devices":
                    data = devices
                elif path == "status":
                    code, data = (503, {"detail": "Audioserver niet bereikbaar"}) if flags["status_error"] else (200, status)
                elif path == "connect":
                    if flags["connect_error"]:
                        code, data = 503, {"detail": "Bose is niet bereikbaar"}
                    else:
                        status.update(running=True, sink=body["sink"], source=body["source"] or source,
                                      latency_ms=body["latency_ms"], volume=37, muted=False)
                        data = status
                elif path == "disconnect":
                    if flags["disconnect_error"]:
                        code, data = 503, {"detail": "Stoppen mislukt. Probeer opnieuw."}
                    else:
                        status.update(running=False, volume=None, muted=None)
                        data = status
                elif path == "volume":
                    if flags["volume_error"]:
                        code, data = 503, {"detail": "Volume kon niet worden aangepast"}
                    else:
                        assert body["sink"] == status["sink"]
                        status["volume"] = body["volume"]
                elif path == "mute":
                    assert body["sink"] == status["sink"]
                    status["muted"] = body["muted"]
                route.fulfill(status=code, content_type="application/json", body=json.dumps(data))

            page.route("**/api/**", respond)
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.locator(".speaker")).to_have_count(1)
            expect(page.locator(".speaker-state")).to_contain_text("audio-uitgang niet beschikbaar")
            expect(page.locator("#streamButton")).to_be_disabled()

            devices["sinks"] = [{"name": sink}]
            page.locator("#refreshButton").click()
            expect(page.locator("#streamButton")).to_be_enabled()
            expect(page.locator(".speaker")).to_have_count(1)
            expect(page.locator(".speaker-name")).to_have_text("SoundTouch Quatacker")
            assert not page.locator(".advanced").evaluate("element => element.open")
            artifacts = ROOT / "artifacts"
            artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts / "desktop-standby.png"), full_page=True)

            flags["connect_error"] = True
            page.locator("#streamButton").click()
            expect(page.locator("#actionError")).to_have_text("Bose is niet bereikbaar")
            page.wait_for_timeout(3300)
            expect(page.locator("#actionError")).to_be_visible()
            flags["connect_error"] = False
            page.locator("#streamButton").click()
            expect(page.locator("#status")).to_have_text("Stream actief")
            expect(page.locator("#streamButton")).to_have_text("Stop streaming")
            expect(page.locator("#actionError")).to_be_hidden()
            expect(page.locator("#volumeValue")).to_have_text("37%")
            expect(page.locator("#source")).to_be_disabled()
            expect(page.locator("#latency")).to_be_disabled()

            # A slow status read must not overwrite a newer volume change.
            page.evaluate("""() => {
              const original = window.fetch;
              let deferred = false;
              window.fetch = async (path, options) => {
                const response = await original(path, options);
                if (path === '/api/status' && !deferred) {
                  deferred = true;
                  const snapshot = await response.json();
                  await new Promise(resolve => { window.releaseStatus = resolve; });
                  return new Response(JSON.stringify(snapshot), {status: 200, headers: {'Content-Type': 'application/json'}});
                }
                return response;
              };
              document.dispatchEvent(new Event('visibilitychange'));
            }""")
            page.wait_for_function("typeof window.releaseStatus === 'function'")
            for _ in range(3):
                page.locator("#volumeUp").click()
            expect(page.locator("#volumeValue")).to_have_text("52%")
            page.wait_for_timeout(500)
            assert status["volume"] == 52
            assert len([call for call in calls if call[0] == "volume"]) <= 2
            page.evaluate("window.releaseStatus()")
            expect(page.locator("#volumeValue")).to_have_text("52%")
            page.locator("#muteButton").click()
            expect(page.locator("#muteButton")).to_have_attribute("aria-pressed", "true")
            page.screenshot(path=str(artifacts / "desktop-streaming.png"), full_page=True)

            flags["volume_error"] = True
            page.locator("#volumeDown").click()
            expect(page.locator("#volumeError")).to_have_text("Volume kon niet worden aangepast")
            flags["volume_error"] = False
            flags["disconnect_error"] = True
            page.locator("#streamButton").click()
            expect(page.locator("#actionError")).to_contain_text("Stoppen mislukt")
            expect(page.locator("#streamButton")).to_have_text("Stop streaming")
            flags["disconnect_error"] = False
            page.locator("#streamButton").click()
            expect(page.locator("#status")).to_have_text("Stand-by")
            expect(page.locator("#volume")).to_be_disabled()

            # An invalid buffer is revealed and focused even if Advanced is closed.
            page.locator(".advanced > summary").click()
            page.locator("#latency").fill("0")
            page.locator(".advanced > summary").click()
            page.locator("#streamButton").click()
            assert page.locator(".advanced").evaluate("element => element.open")
            page.locator("#latency").fill("80")
            page.locator(".advanced > summary").click()

            # Empty inputs must prevent starting; raw speaker names remain text.
            devices["sources"] = []
            devices["airplay"][0]["friendly_name"] = "<img src=x onerror=alert(1)>"
            devices["airplay"][1]["friendly_name"] = "<img src=x onerror=alert(1)>"
            page.locator("#refreshButton").click()
            expect(page.locator("#streamButton")).to_be_disabled()
            expect(page.locator("#startHint")).to_contain_text("audio-input")
            expect(page.locator("#speakers img")).to_have_count(0)
            devices["sources"] = [{"name": source}]
            devices["airplay"][0]["friendly_name"] = "SoundTouch Quatacker"
            devices["airplay"][1]["friendly_name"] = "SoundTouch Quatacker"
            page.locator("#refreshButton").click()
            expect(page.locator("#streamButton")).to_be_enabled()

            page.set_viewport_size({"width": 375, "height": 812})
            page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.locator("#streamButton").click()
            expect(page.locator("#status")).to_have_text("Stream actief")
            flags["status_error"] = True
            expect(page.locator("#statusError")).to_have_text("Audioserver niet bereikbaar", timeout=6000)
            expect(page.locator("#streamButton")).to_be_disabled()
            flags["status_error"] = False
            expect(page.locator("#statusError")).to_be_hidden(timeout=6000)
            expect(page.locator("#streamButton")).to_be_enabled()
            assert not errors, errors
            browser.close()
            print("Browser checks passed: discovery, errors, streaming, volume, mute, validation, mobile layout and recovery.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
