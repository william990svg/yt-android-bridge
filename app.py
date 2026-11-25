"""yt-android-bridge — YouTube direct-URL bridge for the downloader site.

Why this exists: YouTube blocks anonymous downloads from datacenter IPs
(Render's shared IPs) with "Sign in to confirm you're not a bot"
(error.api.youtube.login). yt-dlp's default (web) client hits the same
wall, but the ANDROID player client still works without any login or
cookies, returning the muxed 360p MP4 (itag 18) for videos the web client
can't fetch at all. This service runs yt-dlp with that client and returns
a proxied download URL the site can save with a normal fetch.

Endpoints:
  GET  /            health check {"ok": true}
  POST /            {"url": "<youtube url>"} -> {"status": "stream", "url": "<proxy url>"}
                    or {"status": "error", "error": {"code": "error.api.youtube.unavailable"}}
  GET  /file?u=... streams the video bytes with CORS headers
                    (googlevideo URLs don't send Access-Control-Allow-Origin,
                    so a raw googlevideo URL can't be blob-downloaded from
                    the site — the proxy adds the header).

Only youtube.com / youtu.be URLs are accepted, and /file only proxies
googlevideo.com URLs, so the service can't be used as a general proxy.
"""

import os
import shutil
import subprocess
import urllib.parse

import requests
from flask import Flask, Response, jsonify, request, stream_with_context

app = Flask(__name__)

YTDLP = os.environ.get("YTDLP", "/usr/local/bin/yt-dlp")
# Optional YouTube session cookies (Render Secret File, added by the user
# himself in the dashboard — never shared with the agent). When present,
# yt-dlp sends them with every request, which is what YouTube demands
# from datacenter IPs ("Sign in to confirm you're not a bot").
# Env override COOKIES_FILE, default /etc/secrets/cookies.txt.
COOKIES_FILE = os.environ.get("COOKIES_FILE", "/etc/secrets/cookies.txt")
# Render mounts Secret Files under /etc/secrets READ-ONLY, but yt-dlp
# SAVES the cookie jar back to the file on exit (verified locally: the
# file's mtime/content change after every run). Pointing --cookies
# straight at the secret file therefore fails on every request with
# "OSError: [Errno 30] Read-only file system". Copy it to /tmp
# (writable) first and hand yt-dlp the copy instead. The copy is
# refreshed on every request, so a rotated secret is picked up.
WRITABLE_COOKIES = "/tmp/cookies.txt"


def get_cookies_path():
    """Copy the secret cookies file to a writable path and return it,
    or None when no cookies file is present."""
    if not os.path.exists(COOKIES_FILE):
        return None
    try:
        shutil.copyfile(COOKIES_FILE, WRITABLE_COOKIES)
        return WRITABLE_COOKIES
    except OSError:
        return None


# Android first (worked from a clean IP, blocked on Render's Oregon IPs),
# TV client next (uses the TV HTML5 API, sometimes bypasses the sign-in
# wall where the mobile clients don't), iOS last.
PLAYER_CLIENTS = ("android", "tv", "ios")


def get_direct_url(video_url):
    """Return (direct_url, diagnostics). diagnostics holds the last yt-dlp
    stderr line per client attempt (sanitized, no secrets) so a failure can
    be diagnosed from the API response without server logs."""
    diagnostics = []
    for client in PLAYER_CLIENTS:
        cmd = [
            YTDLP,
            "--no-playlist",
            "-q",
            "--no-warnings",
            "--get-url",
            "-f",
            "18/best",
            "--extractor-args",
            "youtube:player_client=%s" % client,
            video_url,
        ]
        cookies_path = get_cookies_path()
        if cookies_path:
            cmd[1:1] = ["--cookies", cookies_path]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception as exc:
            diagnostics.append("%s: %s" % (client, type(exc).__name__))
            continue
        lines = (proc.stdout or "").strip().splitlines()
        url = lines[0].strip() if lines else ""
        if url.startswith("http"):
            return url, diagnostics
        err_lines = (proc.stderr or "").strip().splitlines()
        last = err_lines[-1].strip() if err_lines else "no stderr"
        diagnostics.append("%s: %s" % (client, last[:160]))
    return None, diagnostics


@app.route("/", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/", methods=["POST"])
def download():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if "youtube.com" not in url and "youtu.be" not in url:
        return (
            jsonify(
                {"status": "error", "error": {"code": "error.api.youtube.unavailable"}}
            ),
            400,
        )
    direct, diagnostics = get_direct_url(url)
    if not direct:
        return jsonify(
            {
                "status": "error",
                "error": {"code": "error.api.youtube.unavailable"},
                "detail": "; ".join(diagnostics)[:500],
            }
        )
    proxy = request.host_url.rstrip("/") + "/file?u=" + urllib.parse.quote(
        direct, safe=""
    )
    return jsonify({"status": "stream", "url": proxy})


@app.route("/file", methods=["GET", "OPTIONS"])
def proxy_file():
    if request.method == "OPTIONS":
        return Response(
            "",
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            },
        )
    target = request.args.get("u", "")
    if not target.startswith("https://") or "googlevideo.com" not in target:
        return "bad url", 400
    try:
        upstream = requests.get(
            target,
            stream=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except Exception:
        return "upstream failed", 502
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": upstream.headers.get("Content-Type", "video/mp4"),
    }
    if upstream.headers.get("Content-Length"):
        headers["Content-Length"] = upstream.headers["Content-Length"]
    return Response(
        stream_with_context(upstream.iter_content(chunk_size=65536)),
        status=upstream.status_code,
        headers=headers,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
