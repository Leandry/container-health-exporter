# syntax=docker/dockerfile:1.4
FROM python:3.10-alpine

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY docker_health_exporter.py /app/

# Expose port 9066 for Prometheus scraping
EXPOSE 9066

# Run Gunicorn, binding to 0.0.0.0:9066
CMD ["gunicorn", "-b", "0.0.0.0:9066", "docker_health_exporter:app"]