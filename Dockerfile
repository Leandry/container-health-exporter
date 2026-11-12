# syntax=docker/dockerfile:1.4
FROM python:3.15-alpine

WORKDIR /app

COPY requirements.txt /app/
# pip is needed only to install the dependencies. It is removed afterwards, so
# that neither pip nor the libraries bundled inside it are in the running image.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pip

COPY docker_health_exporter.py gunicorn.conf.py /app/

# Expose port 9066 for Prometheus scraping
EXPOSE 9066

# Healthy while Gunicorn answers and the Docker daemon is reachable
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:9066/healthz"]

# Run Gunicorn, binding to 0.0.0.0:9066
CMD ["gunicorn", "-b", "0.0.0.0:9066", "docker_health_exporter:app"]