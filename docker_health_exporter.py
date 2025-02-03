#!/usr/bin/env python3
import docker
from flask import Flask, Response

app = Flask(__name__)
client = docker.from_env()

@app.route('/metrics')
def metrics():
    output = []
    containers = client.containers.list(all=True)
    for c in containers:
        # Get the 'Health' dictionary if present
        health_data = c.attrs.get('State', {}).get('Health')
        if not health_data:
            continue  # Skip containers without health checks

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

    # Join all metrics with newlines; add a final newline
    return Response("\n".join(output) + "\n", mimetype='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9066)