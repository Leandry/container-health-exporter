# Docker Health Check Exporter

A small **Python + Flask + Docker SDK** application that queries Docker for container **health check** statuses, **restarts** and **lifecycle state** and exposes them as **Prometheus metrics** on port **9066**.

## Overview

By default, Docker does **not** expose container health (`healthy`, `unhealthy`) as a native Prometheus metric. This exporter:

- Connects to the local Docker Engine (via `/var/run/docker.sock`).
- Lists all containers, checks their `State.Health.Status`.
- Skips containers that do **not** define a Docker health check (for the health metric only).
- Exposes restart and lifecycle metrics for **every** container, see [Metrics](#metrics).
- Serves a `/metrics` endpoint on port **9066**, returning metrics like:

docker_container_health_status{container=“my_app”,health_status=“healthy”} 1
docker_container_health_status{container=“other_app”,health_status=“unhealthy”} 0

Where:
- `1` = healthy
- `0` = unhealthy
- The label `health_status` indicates the textual Docker status (`"healthy"`, `"unhealthy"`, or `"none"`).

## Metrics

| Metric | Value | Source (`docker inspect`) |
|---|---|---|
| `docker_container_health_status` | 1 if healthy, else 0; only for containers with a health check | `State.Health.Status` |
| `docker_container_restart_count` | number of times the restart policy restarted the container since it was created | `RestartCount` |
| `docker_container_started_at_seconds` | Unix time of the last (re)start, 0 if never started | `State.StartedAt` |
| `docker_container_running` | 1 if running, else 0 | `State.Running`, `State.Restarting` |
| `docker_container_oom_killed` | 1 if the last exit was an OOM kill, else 0 | `State.OOMKilled` |
| `docker_container_exit_code` | exit code of the last exit, only exposed when the container is not running | `State.ExitCode` |

All metrics are gauges and come from the single container inspect the exporter performs per container, so a scrape makes no extra Docker API calls.

**Labels.** Every metric carries the label `container` (the container name). `docker_container_health_status` additionally carries its `health_status` label. The restart and lifecycle metrics deliberately do not: a series whose labels change with the health status would start over on every health transition, and `increase()` would miss the restarts of exactly the containers that are crashing. To combine metrics, join on the container name:

```
docker_container_restart_count * on(container) group_left(health_status) docker_container_health_status
```

**Semantics to keep in mind.**

- `docker_container_restart_count` counts only restarts done by the restart policy (`restart: always`, `unless-stopped`, `on-failure`), not a manual `docker restart`.
- It resets to 0 when the container is recreated, which every Compose deployment does. That is why it is a gauge and not a counter type, but `increase()` and `resets()` work on it as on a counter: a drop to 0 is treated as a counter reset.
- To see every (re)start, including manual ones, use `changes(docker_container_started_at_seconds[1h])`.
- While Docker waits to restart a crashed container (`docker ps` shows `Restarting`), `docker_container_running` is 0 and `docker_container_exit_code` shows the exit code of the last attempt, although Docker itself keeps `State.Running` true in that phase.
- `docker_container_exit_code` of a container that never started is 0.

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
  leandry/container-health-exporter:latest
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

The image has a built-in `HEALTHCHECK` that calls `/healthz` every 30 seconds. That endpoint makes one Docker ping (no container inspects) and fails when the Docker daemon cannot be reached, so `docker ps` shows the exporter itself as `healthy` or `unhealthy`, and the exporter appears in its own `docker_container_health_status`.

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

Rules for restarts, crash loops and OOM kills (add them to the same `rules` list):
```yaml
  - alert: ContainerRestarting
    expr: increase(docker_container_restart_count[15m]) >= 2
    labels: { severity: warning }
    annotations:
      summary: "{{ $labels.container }} restarted {{ $value | humanize }} times in 15 minutes"
  - alert: ContainerCrashLooping
    expr: increase(docker_container_restart_count[15m]) >= 5
    labels: { severity: critical }
    annotations:
      summary: "{{ $labels.container }} is crash looping"
  - alert: ContainerOOMKilled
    expr: docker_container_oom_killed == 1
    labels: { severity: warning }
```
5. Customizing
	1.	Labels: You can add or remove container attributes in the exporter (e.g., image name, container ID).
	2.	Health Check: Modify the logic to skip or handle containers differently if needed.
	3.	Production Server: The Dockerfile above uses Gunicorn for concurrency and better performance than Flask’s development server.

6. Tests

```bash
pip install -r requirements.txt
python -m unittest
```

7. Releasing

The image `leandry/container-health-exporter` is published to Docker Hub by the GitHub Actions workflow `.github/workflows/publish.yml`.

	1.	Bump the version: `__version__` in `docker_health_exporter.py` and a new entry in `CHANGELOG.md`. Dependencies are pinned in `requirements.txt` and the Python version in the `Dockerfile`; update them as part of a release.
	2.	Create a GitHub release with the tag `vX.Y.Z`.
	3.	The workflow runs the unit tests inside the image, then builds the image for `linux/amd64` and `linux/arm64`, pushes it with the tags `X.Y.Z`, `X.Y`, `sha-<commit>` and `latest`, and updates the Docker Hub description from this README.

To republish an existing tag, run the workflow manually (Actions → Publish image → Run workflow) and enter the tag, for example `v1.1.0`.

The workflow needs two repository secrets: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access token, not the account password). Give the token the `Read, Write, Delete` scope: `Read & Write` is enough to push the image, but the action that updates the Docker Hub description documents `read/write/delete` as required.

Known Limitations
	•	Health status is tracked only for containers with a defined Docker HEALTHCHECK; restart and lifecycle metrics cover all containers.
	•	Requires mounting /var/run/docker.sock for local Docker queries (ensure this is acceptable security-wise).
	•	Doesn’t track advanced metrics like CPU, memory usage, or network. Use cAdvisor or Docker Engine metrics for that.

License

MIT License 

