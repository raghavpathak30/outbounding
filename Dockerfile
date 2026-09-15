# Production Dockerfile for LangGraph Outbound Pipeline
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/staged_deliveries && \
    chown -R appuser:appuser /app

# Copy application source
COPY --chown=appuser:appuser . .

USER appuser

VOLUME ["/app/staged_deliveries"]

ENTRYPOINT ["python", "main.py"]
CMD ["--domain", "cyber-corp.com"]
