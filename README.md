# Docker Health Check Exporter

A small **Python + Flask + Docker SDK** application that queries Docker for container **health check** statuses and exposes them as **Prometheus metrics** on port **9066**.

## Overview

By default, Docker does **not** expose container health (`healthy`, `unhealthy`) as a native Prometheus metric. This exporter:

- Connects to the local Docker Engine (via `/var/run/docker.sock`).
- Lists all containers, checks their `State.Health.Status`.
- Skips containers that do **not** define a Docker health check.
- Serves a `/metrics` endpoint on port **9066**, returning metrics like:

docker_container_health_status{container=“my_app”,health_status=“healthy”} 1
docker_container_health_status{container=“other_app”,health_status=“unhealthy”} 0

Where:
- `1` = healthy
- `0` = unhealthy
- The label `health_status` indicates the textual Docker status (`"healthy"`, `"unhealthy"`, or `"none"`).

## Features

- **Simple**: A few lines of Python + Flask + Docker SDK.
- **Extensible**: Modify to include more Docker container properties as labels (like `image`, `id`, etc.).
- **Prometheus**: Output follows the standard text-based exposition format.
- **Docker**: You can run this exporter itself as a Docker container.

## Requirements

- Python 3.7+
- `docker` (Python library)
- `Flask`
- (Optionally) `gunicorn` if you want a production-grade WSGI server

## Usage

### 1. Running Locally (Without Docker)

1. **Install dependencies**:

   ```bash
   pip install docker flask

or from a requirements.txt that includes:
```
docker
Flask
```
2.	Run the exporter:
```
python docker_health_exporter.py
```
This listens on 0.0.0.0:9066.

3.	Docker Access:
	•	Ensure your user can talk to Docker. You might need sudo or to be in the docker group.
	•	Mounting the Docker socket isn’t needed here if you run the script on the same host that has Docker installed.
4.	Check:
```
curl http://localhost:9066/metrics
```
You should see lines like:
```
docker_container_health_status{container="my_app",health_status="healthy"} 1
```


2. Running as a Docker Container

2.1 Pull image
```bash
docker pull leandry/container-health-exporter:latest
```

2.2	Docker Run:
```bash
docker run -d \
  --name docker-health-exporter \
  -p 9066:9066 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  docker-health-exporter:latest
```
2.3 Docker compose
```yaml
  monitoring_health_check_exporter:
    container_name: HEALTCHECK_EXPORTER
    image: leandry/container-health-exporter:latest
    volumes:
      # Allows the exporter to query Docker for container health
      - /var/run/docker.sock:/var/run/docker.sock
    restart: always
```
3.	Verify:
```bash
curl http://localhost:9066/metrics
```
You should see the same metrics describing Docker container health.

3. Configuring Prometheus

Add or update a scrape config in your prometheus.yml:
```
scrape_configs:
  - job_name: 'docker-health-exporter'
    static_configs:
      - targets: ['localhost:9066']
```

(Replace localhost with your host or container name as needed.)  `monitoring_health_check_exporter:9066` docker compose service example
When Prometheus starts (or reloads), it will scrape http://host:9066/metrics to retrieve the health metrics.

4. Alerting

Here’s an example Alertmanager rule that fires if any container is 0 (unhealthy) for more than 5 minutes:
```
groups:
- name: docker-container-rules
  rules:
  - alert: DockerContainerUnhealthy
    expr: docker_container_health_status == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Container unhealthy: {{ $labels.container }}"
      description: "Docker container has been unhealthy for over 5 minutes."
```
5. Customizing
	1.	Labels: You can add or remove container attributes in the exporter (e.g., image name, container ID).
	2.	Health Check: Modify the logic to skip or handle containers differently if needed.
	3.	Production Server: The Dockerfile above uses Gunicorn for concurrency and better performance than Flask’s development server.

Known Limitations
	•	Only tracks containers with a defined Docker HEALTHCHECK.
	•	Requires mounting /var/run/docker.sock for local Docker queries (ensure this is acceptable security-wise).
	•	Doesn’t track advanced metrics like CPU, memory usage, or network. Use cAdvisor or Docker Engine metrics for that.

License

MIT License 

