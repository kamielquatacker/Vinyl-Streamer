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
        routes = {
            "/": "/static/index.html",
            "/manifest.webmanifest": "/static/manifest.webmanifest",
            "/apple-touch-icon.png": "/static/icons/apple-touch-icon.png",
            "/favicon.ico": "/static/icons/favicon.ico",
        }
        self.path = routes.get(self.path, self.path)
        super().do_GET()

    def log_message(self, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional path to a Chrome/Chromium executable")
    parser.add_argument("--engine", choices=("chromium", "webkit"), default="chromium")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "app")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = getattr(playwright, args.engine).launch(executable_path=args.browser, headless=True)
            context = browser.new_context(viewport={"width": 1100, "height": 1100}, device_scale_factor=1, color_scheme="light")
            page = context.new_page()
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
            flags = {"connect_error": False, "disconnect_error": False, "status_error": False, "volume_error": False, "eq_error": False}
            preset_bands = {"custom": [0]*6, "neutral": [0]*6, "warm": [3,2,1,0,-1.5,-4],
                            "bass": [6,4,2,0,-1,-2], "clear": [-2,-1.5,-1,0,3,2.5], "voices": [-4,-2.5,-1,3,3,-2]}
            status["equalizer"] = {
                "enabled": False, "preset": "neutral", "active": False, "available": True, "preamp_db": 0, "bands": [0]*6, "custom_bands": [0]*6,
                "presets": [{"id": key, "name": name, "description": description} for key, name, description in [
                    ("custom", "Custom", "Je eigen klankinstelling."), ("neutral", "Neutraal", "Geen tooncorrectie."), ("warm", "Warm", "Wat voller laag en zachter hoog."),
                    ("bass", "Meer bas", "Meer nadruk op de lage tonen."), ("clear", "Helder", "Meer nadruk op details."),
                    ("voices", "Stemmen", "Meer nadruk op stemmen.")]],
            }
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
                        status["equalizer"]["active"] = status["equalizer"]["enabled"]
                        data = status
                elif path == "disconnect":
                    if flags["disconnect_error"]:
                        code, data = 503, {"detail": "Stoppen mislukt. Probeer opnieuw."}
                    else:
                        status.update(running=False, volume=None, muted=None)
                        status["equalizer"]["active"] = False
                        data = status
                elif path == "equalizer":
                    if flags["eq_error"]:
                        code, data = 503, {"detail": "Equaliser kon niet starten"}
                    else:
                        status["equalizer"]["custom_bands"] = body.get("bands", status["equalizer"]["custom_bands"])
                        status["equalizer"]["bands"] = status["equalizer"]["custom_bands"] if body["preset"] == "custom" else preset_bands[body["preset"]]
                        status["equalizer"].update(enabled=body["enabled"], preset=body["preset"],
                            active=body["enabled"] and status["running"], preamp_db=-3 if body["preset"] == "warm" else 0)
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

            page.context.route("**/api/**", respond)
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            # Theme defaults follow the OS; an explicit choice persists across reloads/tabs.
            theme = page.locator("html")
            toggle = page.get_by_role("button", name="Donkere modus", exact=True)
            expect(theme).to_have_attribute("data-theme", "light")
            page.emulate_media(color_scheme="dark")
            expect(theme).to_have_attribute("data-theme", "dark")
            expect(toggle).to_have_attribute("aria-pressed", "true")
            assert page.locator('meta[name="theme-color"]').get_attribute("content") == "#151a18"
            toggle.click()
            expect(theme).to_have_attribute("data-theme", "light")
            page.emulate_media(color_scheme="light")
            page.emulate_media(color_scheme="dark")
            expect(theme).to_have_attribute("data-theme", "light")
            page.reload()
            expect(theme).to_have_attribute("data-theme", "light")
            other = page.context.new_page()
            other.goto(page.url)
            expect(other.locator("html")).to_have_attribute("data-theme", "light")
            toggle.focus()
            toggle.press("Enter")
            expect(theme).to_have_attribute("data-theme", "dark")
            expect(other.locator("html")).to_have_attribute("data-theme", "dark")
            other.close()
            page.evaluate("localStorage.setItem('vinyl-streamer-theme', 'invalid')")
            page.reload()
            expect(theme).to_have_attribute("data-theme", "dark")
            page.emulate_media(color_scheme="light")
            expect(theme).to_have_attribute("data-theme", "light")

            restricted = browser.new_context(color_scheme="dark")
            restricted.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('Blocked', 'SecurityError');}})")
            restricted.route("**/api/**", respond)
            restricted_page = restricted.new_page()
            restricted_page.on("pageerror", lambda error: errors.append(str(error)))
            restricted_page.goto(page.url)
            expect(restricted_page.locator("html")).to_have_attribute("data-theme", "dark")
            restricted_page.get_by_role("button", name="Donkere modus", exact=True).click()
            expect(restricted_page.locator("html")).to_have_attribute("data-theme", "light")
            restricted.close()

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

            # Presets can be changed on a live stream; failure preserves the old state.
            expect(page.locator(".eq-band input")).to_have_count(6)
            for index in range(6):
                expect(page.locator(f"#eqBand{index}")).to_have_attribute("min", "-10")
                expect(page.locator(f"#eqBand{index}")).to_have_attribute("max", "10")
            expect(page.locator("#eqEnabled")).to_be_enabled()
            page.locator("#eqPreset").select_option("warm")
            expect(page.locator("#eqPreset")).to_be_enabled()
            page.locator("#eqEnabled").check()
            expect(page.locator("#eqEnabled")).to_be_checked()
            expect(page.locator("#eqHint")).to_contain_text("zachter")
            flags["eq_error"] = True
            page.locator("#eqPreset").select_option("bass")
            expect(page.locator("#eqError")).to_have_text("Equaliser kon niet starten")
            expect(page.locator("#eqPreset")).to_have_value("warm")
            flags["eq_error"] = False
            page.locator("#eqPreset").select_option("clear")
            expect(page.locator("#eqPreset")).to_have_value("clear")
            expect(page.locator("#eqError")).to_be_hidden()
            expect(page.locator("#eqBand4")).to_have_value("3")
            before = len([call for call in calls if call[0] == "equalizer"])
            page.locator("#eqBand0").evaluate("""el => {
                el.value = 1; el.dispatchEvent(new Event('input', {bubbles:true}));
                el.value = 2.5; el.dispatchEvent(new Event('input', {bubbles:true}));
            }""")
            expect(page.locator("#eqPreset")).to_have_value("custom")
            expect(page.locator("#eqBandValue0")).to_have_text("+2.5 dB")
            assert len([call for call in calls if call[0] == "equalizer"]) == before
            page.locator("#eqBand0").dispatch_event("change")
            expect(page.locator("#eqBand0")).to_be_enabled()
            assert status["equalizer"]["bands"] == [2.5,-1.5,-1,0,3,2.5]
            assert len([call for call in calls if call[0] == "equalizer"]) == before + 1
            page.reload()
            expect(page.locator("#eqBand0")).to_have_value("2.5")
            page.locator("#eqBand0").focus()
            page.locator("#eqBand0").press("ArrowUp")
            expect(page.locator("#eqBand0")).to_have_value("3")
            expect(page.locator("#eqBand0")).to_be_enabled()
            # The full column accepts a drag beside the track and captures movement outside it.
            page.locator("#eqBand0").scroll_into_view_if_needed()
            rect = page.locator("#eqBand0").bounding_box()
            before = len([call for call in calls if call[0] == "equalizer"])
            page.mouse.move(rect["x"] + 3, rect["y"] + 140)
            page.mouse.down()
            page.mouse.move(rect["x"] - 30, rect["y"] + 59)
            expect(page.locator("#eqBand0")).to_have_value("4")
            assert len([call for call in calls if call[0] == "equalizer"]) == before
            page.mouse.up()
            expect(page.locator("#eqBand0")).to_be_enabled()
            assert status["equalizer"]["bands"][0] == 4
            assert len([call for call in calls if call[0] == "equalizer"]) == before + 1
            assert page.locator("#eqCurvePath").get_attribute("d").count(" C ") == 5
            page.locator("#eqEnabled").uncheck()
            expect(page.locator("#eqHint")).to_contain_text("rechtstreeks")

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
            expect(page.locator("#muteButton")).to_have_attribute("aria-label", "Dempen")
            page.locator("#muteButton").click()
            expect(page.locator("#muteButton")).to_have_attribute("aria-pressed", "true")
            expect(page.locator("#muteButton")).to_have_attribute("aria-label", "Geluid aan")
            expect(page.locator("#muteButton .sound-muted")).to_be_visible()
            page.screenshot(path=str(artifacts / "desktop-streaming.png"), full_page=True)
            toggle.click()
            expect(theme).to_have_attribute("data-theme", "dark")
            assert page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(21, 26, 24)"
            assert page.locator(".speaker.selected").evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(37, 58, 45)"
            page.screenshot(path=str(artifacts / "desktop-dark.png"), full_page=True)
            toggle.click()
            expect(theme).to_have_attribute("data-theme", "light")

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
            toggle.click()
            expect(theme).to_have_attribute("data-theme", "dark")
            page.screenshot(path=str(artifacts / "mobile-dark.png"), full_page=True)
            page.set_viewport_size({"width": 320, "height": 812})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.set_viewport_size({"width": 375, "height": 812})
            page.locator("#streamButton").click()
            expect(page.locator("#status")).to_have_text("Stream actief")
            flags["status_error"] = True
            expect(page.locator("#statusError")).to_have_text("Audioserver niet bereikbaar", timeout=6000)
            expect(page.locator("#streamButton")).to_be_disabled()
            flags["status_error"] = False
            expect(page.locator("#statusError")).to_be_hidden(timeout=6000)
            expect(page.locator("#streamButton")).to_be_enabled()
            # Home-screen metadata and touch layouts for iPhone and Android sizes.
            manifest = page.request.get(page.url + "manifest.webmanifest").json()
            assert manifest["name"] == "Vinyl Streamer"
            assert manifest["display"] == "standalone" and manifest["scope"] == "/"
            for label, device in [("iphone", "iPhone 13"), ("android", "Pixel 7")]:
                mobile_context = browser.new_context(**playwright.devices[device], color_scheme="dark")
                mobile_context.route("**/api/**", respond)
                mobile = mobile_context.new_page()
                mobile.on("pageerror", lambda error: errors.append(str(error)))
                mobile.goto(page.url)
                expect(mobile.locator("#streamButton")).to_have_text("Stop streaming")
                assert mobile.title() == "Vinyl Streamer"
                assert "viewport-fit=cover" in mobile.locator('meta[name="viewport"]').get_attribute("content")
                assert mobile.locator('meta[name="apple-mobile-web-app-capable"]').get_attribute("content") == "yes"
                icon = mobile.locator('link[rel="apple-touch-icon"]').get_attribute("href")
                assert mobile.request.get(page.url.rstrip("/") + icon).ok
                assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                for control in ["#streamButton", "#themeToggle", "#volumeUp", "#muteButton"]:
                    assert mobile.locator(control).bounding_box()["height"] >= 44
                band_box = mobile.locator("#eqBand0").bounding_box()
                assert band_box["width"] >= 44 and band_box["height"] > band_box["width"]
                assert mobile.locator("#eqBand0").evaluate("el => getComputedStyle(el).touchAction") == "none"
                mute_box = mobile.locator("#muteButton").bounding_box()
                output_box = mobile.locator("#volumeValue").bounding_box()
                assert abs(mute_box["y"] + mute_box["height"]/2 - output_box["y"] - output_box["height"]/2) < 2
                if args.engine == "chromium":
                    mobile.locator("#eqBand0").scroll_into_view_if_needed()
                    rect = mobile.locator("#eqBand0").bounding_box()
                    scroll_y = mobile.evaluate("window.scrollY")
                    cdp = mobile_context.new_cdp_session(mobile)
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": rect["x"]+3, "y": rect["y"]+140}]})
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": rect["x"]-10, "y": rect["y"]+59}]})
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    expect(mobile.locator("#eqBand0")).to_have_value("4")
                    expect(mobile.locator("#eqBand0")).to_be_enabled()
                    assert abs(mobile.evaluate("window.scrollY") - scroll_y) < 1
                    cdp.detach()
                mobile.locator(".advanced > summary").click()
                assert mobile.locator("#source").evaluate("el => getComputedStyle(el).fontSize") == "16px"
                mobile.locator(".advanced > summary").click()
                mobile.screenshot(path=str(artifacts / f"{label}-{args.engine}.png"), full_page=True)
                size = mobile.viewport_size
                mobile.set_viewport_size({"width": size["height"], "height": size["width"]})
                assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                mobile_context.close()
            assert not errors, errors
            browser.close()
            print("Browser checks passed: equalizer presets, themes, streaming, recovery, home-screen metadata and iPhone/Android touch layouts.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
