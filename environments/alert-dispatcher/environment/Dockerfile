FROM python:3.12.7-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY app/ /app/
RUN mkdir -p /app/var/standin /app/outbox && chmod 755 /app/var/standin /app/outbox
