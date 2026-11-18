FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY app ./app
RUN useradd -m appuser
USER appuser
ENV PORT=8000 ENV=production
# Behind Cloud Run / Render the client IP is in X-Forwarded-For: trust it ONLY because the platform proxy is the sole
# way in (otherwise anyone could spoof their IP and dodge the per-IP limits). Set to the proxy's address if you know it.
ENV FORWARDED_ALLOW_IPS=*
EXPOSE 8000
# ENV=production refuses to start without API_KEYS and / or JWT_SECRET (see docs/SECURITY.md); one process: the nesting
# worker processes are the parallelism, and the rate-limit counters live in this process (RATE_LIMIT_STORAGE=redis://
# if you ever run more than one instance).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
