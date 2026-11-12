import re
import unittest
from types import SimpleNamespace
from unittest import mock

# The module creates its Docker client on import; no daemon is needed for tests.
with mock.patch('docker.from_env'):
    import docker_health_exporter as exporter

HEALTH_METRIC = 'docker_container_health_status'
LIFECYCLE_METRICS = [name for name, _ in exporter.LIFECYCLE_METRICS]

SAMPLE_RE = re.compile(r'^(?P<name>[a-z_]+)\{(?P<labels>[^}]*)\} (?P<value>\S+)$')
LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def container(name, restart_count=0, **state):
    """A container as docker-py returns it: a name plus trimmed inspect data."""
    return SimpleNamespace(name=name, attrs={
        'Name': '/' + name,
        'RestartCount': restart_count,
        'State': state,
    })


# Trimmed `docker inspect` responses, one per container state under test.
HEALTHY_WITH_RESTARTS = container(
    'web', restart_count=3,
    Status='running', Running=True, Paused=False, Restarting=False,
    OOMKilled=False, Dead=False, Pid=4242, ExitCode=0, Error='',
    StartedAt='2026-11-12T08:35:01.123456789Z',
    FinishedAt='2026-11-12T08:34:59.987654321Z',
    Health={'Status': 'healthy', 'FailingStreak': 0, 'Log': []},
)
RUNNING_WITHOUT_HEALTHCHECK = container(
    'worker',
    Status='running', Running=True, Paused=False, Restarting=False,
    OOMKilled=False, Dead=False, Pid=4243, ExitCode=0, Error='',
    StartedAt='2026-11-12T08:00:00Z',
    FinishedAt='0001-01-01T00:00:00Z',
)
EXITED_NON_ZERO = container(
    'migrate',
    Status='exited', Running=False, Paused=False, Restarting=False,
    OOMKilled=False, Dead=False, Pid=0, ExitCode=2, Error='',
    StartedAt='2026-11-12T07:00:00.5Z',
    FinishedAt='2026-11-12T07:00:03.25Z',
)
OOM_KILLED = container(
    'importer', restart_count=1,
    Status='exited', Running=False, Paused=False, Restarting=False,
    OOMKilled=True, Dead=False, Pid=0, ExitCode=137, Error='',
    StartedAt='2026-11-12T06:00:00Z',
    FinishedAt='2026-11-12T06:10:00Z',
    Health={'Status': 'unhealthy', 'FailingStreak': 4, 'Log': []},
)
NEVER_STARTED = container(
    'prepared',
    Status='created', Running=False, Paused=False, Restarting=False,
    OOMKilled=False, Dead=False, Pid=0, ExitCode=0, Error='',
    StartedAt='0001-01-01T00:00:00Z',
    FinishedAt='0001-01-01T00:00:00Z',
)
# What Docker reports between two attempts of a crash-looping container.
WAITING_FOR_RESTART = container(
    'crashme', restart_count=7,
    Status='restarting', Running=True, Paused=False, Restarting=True,
    OOMKilled=False, Dead=False, Pid=0, ExitCode=1, Error='',
    StartedAt='2026-11-12T09:00:00Z',
    FinishedAt='2026-11-12T09:00:00.1Z',
)

ALL_CONTAINERS = [
    HEALTHY_WITH_RESTARTS, RUNNING_WITHOUT_HEALTHCHECK, EXITED_NON_ZERO,
    OOM_KILLED, NEVER_STARTED, WAITING_FOR_RESTART,
]


def parse(text):
    """Parse exposition text into [(metric name, labels dict, value)]."""
    samples = []
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        match = SAMPLE_RE.match(line)
        assert match, f'not a valid sample line: {line!r}'
        labels = dict(LABEL_RE.findall(match.group('labels')))
        samples.append((match.group('name'), labels, float(match.group('value'))))
    return samples


def metrics_of(*containers):
    """Render the containers; return {metric name: {container name: value}}."""
    result = {}
    for name, labels, value in parse(exporter.render_metrics(containers)):
        result.setdefault(name, {})[labels['container']] = value
    return result


class LifecycleMetricsTest(unittest.TestCase):

    def test_healthy_running_container_with_restarts(self):
        metrics = metrics_of(HEALTHY_WITH_RESTARTS)

        self.assertEqual(metrics[HEALTH_METRIC], {'web': 1})
        self.assertEqual(metrics['docker_container_restart_count'], {'web': 3})
        self.assertEqual(metrics['docker_container_running'], {'web': 1})
        self.assertEqual(metrics['docker_container_oom_killed'], {'web': 0})
        # 2026-11-12T08:35:01Z plus the fraction, cut to float precision
        self.assertAlmostEqual(
            metrics['docker_container_started_at_seconds']['web'],
            1794472501.123456789, places=5,
        )
        self.assertNotIn('docker_container_exit_code', metrics)

    def test_running_container_without_health_check(self):
        metrics = metrics_of(RUNNING_WITHOUT_HEALTHCHECK)

        self.assertNotIn(HEALTH_METRIC, metrics)
        self.assertEqual(metrics['docker_container_restart_count'], {'worker': 0})
        self.assertEqual(metrics['docker_container_running'], {'worker': 1})
        self.assertEqual(metrics['docker_container_oom_killed'], {'worker': 0})
        self.assertEqual(
            metrics['docker_container_started_at_seconds'], {'worker': 1794470400},
        )
        self.assertNotIn('docker_container_exit_code', metrics)

    def test_exited_container_with_non_zero_exit_code(self):
        metrics = metrics_of(EXITED_NON_ZERO)

        self.assertEqual(metrics['docker_container_running'], {'migrate': 0})
        self.assertEqual(metrics['docker_container_exit_code'], {'migrate': 2})
        self.assertEqual(metrics['docker_container_oom_killed'], {'migrate': 0})
        self.assertEqual(
            metrics['docker_container_started_at_seconds'], {'migrate': 1794466800.5},
        )

    def test_oom_killed_container(self):
        metrics = metrics_of(OOM_KILLED)

        self.assertEqual(metrics[HEALTH_METRIC], {'importer': 0})
        self.assertEqual(metrics['docker_container_oom_killed'], {'importer': 1})
        self.assertEqual(metrics['docker_container_running'], {'importer': 0})
        self.assertEqual(metrics['docker_container_exit_code'], {'importer': 137})
        self.assertEqual(metrics['docker_container_restart_count'], {'importer': 1})

    def test_container_that_never_started(self):
        metrics = metrics_of(NEVER_STARTED)

        self.assertEqual(metrics['docker_container_started_at_seconds'], {'prepared': 0})
        self.assertEqual(metrics['docker_container_running'], {'prepared': 0})
        self.assertEqual(metrics['docker_container_restart_count'], {'prepared': 0})
        self.assertEqual(metrics['docker_container_oom_killed'], {'prepared': 0})
        self.assertEqual(metrics['docker_container_exit_code'], {'prepared': 0})

    def test_container_waiting_for_restart_is_not_running(self):
        metrics = metrics_of(WAITING_FOR_RESTART)

        self.assertEqual(metrics['docker_container_running'], {'crashme': 0})
        self.assertEqual(metrics['docker_container_exit_code'], {'crashme': 1})
        self.assertEqual(metrics['docker_container_restart_count'], {'crashme': 7})


class LabelsTest(unittest.TestCase):

    def setUp(self):
        self.samples = parse(exporter.render_metrics(ALL_CONTAINERS))

    def label_sets(self, metric):
        return {frozenset(labels) for name, labels, _ in self.samples if name == metric}

    def test_lifecycle_metrics_share_one_label_set(self):
        for metric in LIFECYCLE_METRICS:
            self.assertEqual(self.label_sets(metric), {frozenset({'container'})}, metric)

    def test_health_metric_adds_only_its_status_label(self):
        self.assertEqual(
            self.label_sets(HEALTH_METRIC), {frozenset({'container', 'health_status'})},
        )

    def test_label_values_match_between_health_and_lifecycle_metrics(self):
        health = {labels['container'] for name, labels, _ in self.samples
                  if name == HEALTH_METRIC}
        restarts = {labels['container'] for name, labels, _ in self.samples
                    if name == 'docker_container_restart_count'}

        self.assertEqual(health, {'web', 'importer'})
        self.assertEqual(restarts, {c.name for c in ALL_CONTAINERS})

    def test_every_container_has_every_unconditional_metric(self):
        for metric in LIFECYCLE_METRICS:
            if metric == 'docker_container_exit_code':
                continue
            names = [labels['container'] for name, labels, _ in self.samples
                     if name == metric]
            self.assertEqual(names, [c.name for c in ALL_CONTAINERS], metric)


class ExpositionFormatTest(unittest.TestCase):

    def test_health_metric_lines_are_unchanged(self):
        lines = exporter.render_metrics(ALL_CONTAINERS).splitlines()

        self.assertEqual(lines[:2], [
            'docker_container_health_status{container="web", health_status="healthy"} 1',
            'docker_container_health_status{container="importer", health_status="unhealthy"} 0',
        ])

    def test_lifecycle_metrics_are_declared_as_gauges(self):
        text = exporter.render_metrics(ALL_CONTAINERS)

        for metric in LIFECYCLE_METRICS:
            self.assertEqual(text.count(f'# TYPE {metric} gauge\n'), 1, metric)
            self.assertEqual(text.count(f'# HELP {metric} '), 1, metric)

    def test_samples_of_one_metric_are_grouped(self):
        names = [name for name, _, _ in parse(exporter.render_metrics(ALL_CONTAINERS))]
        order = [name for i, name in enumerate(names) if i == 0 or names[i - 1] != name]

        self.assertEqual(order, [HEALTH_METRIC] + LIFECYCLE_METRICS)

    def test_no_containers_renders_an_empty_body(self):
        self.assertEqual(exporter.render_metrics([]), '\n')


class StartedAtSecondsTest(unittest.TestCase):

    def test_whole_seconds(self):
        self.assertEqual(exporter.started_at_seconds('2026-11-12T08:00:00Z'), 1794470400)

    def test_utc_offset(self):
        self.assertEqual(
            exporter.started_at_seconds('2026-11-12T10:00:00+02:00'), 1794470400,
        )

    def test_never_started_or_missing(self):
        for value in ('0001-01-01T00:00:00Z', '', None, 'garbage'):
            self.assertEqual(exporter.started_at_seconds(value), 0, value)


class MetricsEndpointTest(unittest.TestCase):

    def test_endpoint_lists_all_containers_once(self):
        exporter.client.containers.list.reset_mock()
        exporter.client.containers.list.return_value = ALL_CONTAINERS

        response = exporter.app.test_client().get('/metrics')

        exporter.client.containers.list.assert_called_once_with(
            all=True, ignore_removed=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/plain')
        self.assertEqual(response.get_data(as_text=True),
                         exporter.render_metrics(ALL_CONTAINERS))


class HealthzEndpointTest(unittest.TestCase):

    def setUp(self):
        exporter.client.reset_mock(side_effect=True)

    def tearDown(self):
        exporter.client.reset_mock(side_effect=True)

    def test_ok_when_docker_answers_without_inspecting_containers(self):
        response = exporter.app.test_client().get('/healthz')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'ok\n')
        exporter.client.ping.assert_called_once_with()
        exporter.client.containers.list.assert_not_called()

    def test_fails_when_docker_is_unreachable(self):
        exporter.client.ping.side_effect = ConnectionError('no docker socket')

        response = exporter.app.test_client().get('/healthz')

        self.assertEqual(response.status_code, 500)


if __name__ == '__main__':
    unittest.main()
