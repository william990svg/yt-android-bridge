# yt-android-bridge

YouTube direct-URL bridge for the Social Media Video Downloader site
(https://william990svg.github.io/social-media-video-downloader/).

## Problem

YouTube blocks anonymous downloads from datacenter IPs (Render's shared
IPs) with "Sign in to confirm you're not a bot" (`error.api.youtube.login`).
yt-dlp's default web client hits the same wall, and Piped returns
`LOGIN_REQUIRED` for the same videos.

## Fix

yt-dlp's **Android player client** still works without any login or cookies.
It returns the muxed 360p MP4 (itag 18) for videos the web client can't
fetch at all. This service runs yt-dlp with that client (iOS as fallback)
and returns a proxied download URL.

## Why a proxy

Google's video servers don't send `Access-Control-Allow-Origin`, so a raw
googlevideo URL can't be downloaded with `fetch()` from the site. The
`/file` endpoint streams the bytes with `Access-Control-Allow-Origin: *`,
so the site's blob download (with real percent progress) works.

## Endpoints

- `GET /` — health check `{"ok": true}`
- `POST /` — `{"url": "<youtube url>"}` →
  `{"status": "stream", "url": "<proxy url>"}` or an error object
- `GET /file?u=<googlevideo url>` — streams the video with CORS headers

Only `youtube.com` / `youtu.be` URLs are accepted, and `/file` only proxies
`googlevideo.com` URLs.

## Deploy

Render (free plan), Docker, from this repo. Runs on `$PORT` (default 10000).
