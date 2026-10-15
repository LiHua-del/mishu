FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8001 \
    MISHU_DATA_DIR=/data

WORKDIR /app

COPY server.py ./server.py
COPY mishu ./mishu
COPY data ./data
COPY web ./web

RUN apk add --no-cache ca-certificates tzdata \
    && update-ca-certificates \
    && addgroup -S mishu && adduser -S -G mishu mishu \
    && mkdir -p /data \
    && chown -R mishu:mishu /app /data

USER mishu
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=2)"

CMD ["python", "server.py"]
