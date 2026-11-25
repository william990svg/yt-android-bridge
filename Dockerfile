FROM python:3.12-slim

# yt-dlp standalone binary (no pip install needed for it)
ADD https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp /usr/local/bin/yt-dlp
RUN chmod +x /usr/local/bin/yt-dlp

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# Render sets $PORT; default 10000 for local runs
CMD gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 120 app:app
