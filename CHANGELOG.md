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
- Unit tests (`python -m unittest`).
- GitHub Actions workflow that publishes the multi-arch image (amd64, arm64) to Docker Hub
  on every published release and updates the Docker Hub description from the README.

`docker_container_health_status`, its labels, the port and the metrics path are unchanged.
