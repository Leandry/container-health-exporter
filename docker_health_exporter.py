#!/usr/bin/env python3
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import docker
from flask import Flask, Response

__version__ = '1.1.0'

# Seconds to wait for the Docker daemon before a request to it fails. Kept well
# below Gunicorn's worker timeout, so that a hung daemon fails the scrape and
# does not get the worker killed.
DOCKER_TIMEOUT_SECONDS = 10

app = Flask(__name__)
client = docker.from_env(timeout=DOCKER_TIMEOUT_SECONDS)

# Scrapes that failed because Docker could not be queried, since process start
scrape_errors = 0
scrape_errors_lock = threading.Lock()

# Lifecycle gauges, in output order: (metric name, help text)
LIFECYCLE_METRICS = [
    ('docker_container_restart_count',
     'Number of times the restart policy restarted the container since it was created.'),
    ('docker_container_started_at_seconds',
     'Unix time of the last (re)start of the container, 0 if it never started.'),
    ('docker_container_running',
     '1 if the container is running, else 0.'),
    ('docker_container_oom_killed',
     '1 if the last exit of the container was an OOM kill, else 0.'),
    ('docker_container_exit_code',
     'Exit code of the last exit, only exposed when the container is not running.'),
]

# Docker timestamps are RFC 3339 with up to nanosecond precision
TIMESTAMP_RE = re.compile(
    r'^(?P<datetime>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'
    r'(?P<fraction>\.\d+)?'
    r'(?P<zone>Z|[+-]\d{2}:\d{2})$'
)


def started_at_seconds(started_at):
    """Convert State.StartedAt to Unix time; 0 if the container never started."""
    match = TIMESTAMP_RE.match(started_at or '')
    # Docker reports '0001-01-01T00:00:00Z' for a container that never started
    if not match or match.group('datetime').startswith('0001-'):
        return 0

    moment = datetime.strptime(match.group('datetime'), '%Y-%m-%dT%H:%M:%S')
    zone = match.group('zone')
    if zone != 'Z':
        sign = -1 if zone[0] == '-' else 1
        hours, minutes = zone[1:].split(':')
        moment -= sign * timedelta(hours=int(hours), minutes=int(minutes))

    seconds = int(moment.replace(tzinfo=timezone.utc).timestamp())
    return seconds + float('0' + (match.group('fraction') or '.0'))


def lifecycle_values(attrs):
    """Values of the lifecycle gauges for one container, from its inspect data."""
    state = attrs.get('State', {})
    # Docker keeps State.Running true while it waits to restart a crashed
    # container, although no process exists then; that is not running.
    running = bool(state.get('Running')) and not state.get('Restarting')

    values = {
        'docker_container_restart_count': attrs.get('RestartCount', 0),
        'docker_container_started_at_seconds': started_at_seconds(state.get('StartedAt')),
        'docker_container_running': int(running),
        'docker_container_oom_killed': int(bool(state.get('OOMKilled'))),
    }
    if not running:
        values['docker_container_exit_code'] = state.get('ExitCode', 0)
    return values


def format_value(value):
    """Render a sample value; whole numbers without a decimal point."""
    return str(int(value)) if value == int(value) else repr(value)


def container_metric_lines(containers):
    """Exposition lines of the health and lifecycle metrics of the containers."""
    output = []
    lifecycle = {name: [] for name, _ in LIFECYCLE_METRICS}

    for c in containers:
        for name, value in lifecycle_values(c.attrs).items():
            lifecycle[name].append(
                f'{name}{{container="{c.name}"}} {format_value(value)}'
            )

        # Get the 'Health' dictionary if present
        health_data = c.attrs.get('State', {}).get('Health')
        if not health_data:
            continue  # No health status for containers without health checks

        status_str = health_data.get('Status', 'none')  # 'healthy', 'unhealthy', 'none'
        status_val = 1 if status_str == 'healthy' else 0

        # We embed the actual status string as a label in the metric,
        # so it’s visible in Prometheus queries.
        metric_line = (
            f'docker_container_health_status{{'
            f'container="{c.name}", '
            f'health_status="{status_str}"'
            f'}} {status_val}'
        )

        output.append(metric_line)

    for name, help_text in LIFECYCLE_METRICS:
        if lifecycle[name]:
            output.append(f'# HELP {name} {help_text}')
            output.append(f'# TYPE {name} gauge')
            output.extend(lifecycle[name])

    return output


def exporter_metric_lines(scrape_duration):
    """Exposition lines of the metrics about the exporter itself."""
    prefix = 'docker_health_exporter'
    return [
        f'# HELP {prefix}_build_info Version of the exporter; the value is always 1.',
        f'# TYPE {prefix}_build_info gauge',
        f'{prefix}_build_info{{version="{__version__}"}} 1',
        f'# HELP {prefix}_scrape_duration_seconds Time this scrape spent querying Docker.',
        f'# TYPE {prefix}_scrape_duration_seconds gauge',
        f'{prefix}_scrape_duration_seconds {scrape_duration:.6f}',
        f'# HELP {prefix}_scrape_errors_total Scrapes that failed because Docker'
        ' could not be queried, since the exporter started.',
        f'# TYPE {prefix}_scrape_errors_total counter',
        f'{prefix}_scrape_errors_total {scrape_errors}',
    ]


def render(lines):
    # Join all metrics with newlines; add a final newline
    return "\n".join(lines) + "\n"


def render_metrics(containers):
    """Render the metrics of the given containers in the text exposition format."""
    return render(container_metric_lines(containers))


@app.route('/metrics')
def metrics():
    global scrape_errors
    started = time.monotonic()
    try:
        # list() inspects every container once; all metrics come from that data.
        # A container removed between the listing and its inspect is left out.
        containers = client.containers.list(all=True, ignore_removed=True)
    except Exception:
        # The scrape still fails with HTTP 500, so `up` turns 0 in Prometheus
        with scrape_errors_lock:
            scrape_errors += 1
        raise
    duration = time.monotonic() - started

    lines = container_metric_lines(containers) + exporter_metric_lines(duration)
    return Response(render(lines), mimetype='text/plain')


@app.route('/healthz')
def healthz():
    # For the image's HEALTHCHECK: one Docker ping, no container inspects.
    # Fails with HTTP 500 when the Docker daemon cannot be reached.
    client.ping()
    return Response("ok\n", mimetype='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9066)
