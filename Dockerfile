FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LEADLENS_DB=/data/leadlens.db
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
RUN mkdir -p /data && useradd -m leadlens && chown -R leadlens /app /data
USER leadlens

EXPOSE 8000
# Single worker on purpose: jobs run as in-process async tasks (see README, "Scaling").
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
