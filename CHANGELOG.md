# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-12

### Added

- Restart and lifecycle metrics for every container, with or without a health check:
  `docker_container_restart_count`, `docker_container_started_at_seconds`,
  `docker_container_running`, `docker_container_oom_killed` and
  `docker_container_exit_code`. They come from the container inspect the exporter
  already performs, so a scrape makes no additional Docker API calls.
- Example alert rules for restarting, crash-looping and OOM-killed containers.
- Metrics about the exporter itself: `docker_health_exporter_build_info`,
  `docker_health_exporter_scrape_duration_seconds` and
  `docker_health_exporter_scrape_errors_total`.
- `/healthz` endpoint (one Docker ping, no container inspects) and an image `HEALTHCHECK`
  that uses it, so the exporter reports its own health.
- The container runs with a read-only root filesystem and without Linux capabilities.
- Unit tests (`python -m unittest`).
- GitHub Actions workflow that tests and scans the image, publishes the multi-arch image
  (amd64, arm64) to Docker Hub on every published release and updates the Docker Hub
  description from the README. It rebuilds the newest release every week to pick up base
  image updates.
- CI on pull requests: unit tests, a hardened run of the image, a vulnerability scan and
  linters. Dependabot updates for Python dependencies, the base image and the Actions.

### Changed

- Base image is `python:3.15-alpine`; Python 3.10 reached end of life in October 2026.
- Dependencies are pinned in `requirements.txt` (`docker` 7.2.0, `Flask` 3.1.3,
  `gunicorn` 27.0.0).
- `pip` is removed from the image; its bundled libraries had known vulnerabilities.
- Requests to the Docker daemon time out after 10 seconds (was 60), and Gunicorn serves
  with two threads, so a daemon that stops answering fails the scrape instead of blocking
  the exporter.

### Fixed

- A scrape no longer fails with HTTP 500 when a container is removed while the scrape is
  in progress; that container is left out of the response.

`docker_container_health_status`, its labels, the port and the metrics path are unchanged.
