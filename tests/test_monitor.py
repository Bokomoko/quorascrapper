"""Tests for the qsbk monitor command (queue lag, consumers, health)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from confluent_kafka import TopicPartition

from quorascrapper.config import Settings
from quorascrapper.ops import monitor
from quorascrapper.ops.monitor import (
    HealthReport,
    format_group,
    format_health,
    format_queue,
    gather_consumer_group,
    gather_health,
    gather_queue_stats,
)


def _settings() -> Settings:
    return Settings(
        kafka_bootstrap="broker:19092",
        kafka_topic="quora-answers",
        kafka_group_id="quora-consumer-group",
        mongodb_uri="",
    )


# --------------------------------------------------------------------------- #
# Queue / lag
# --------------------------------------------------------------------------- #
def test_gather_queue_stats_no_bootstrap():
    report = gather_queue_stats(Settings(kafka_bootstrap=""))
    assert not report.ok
    assert "KAFKA_BOOTSTRAP" in (report.error or "")


def test_gather_queue_stats_computes_lag():
    topic = "quora-answers"
    topic_meta = SimpleNamespace(error=None, partitions={0: object(), 1: object()})
    meta = SimpleNamespace(topics={topic: topic_meta})

    consumer = MagicMock()
    consumer.list_topics.return_value = meta
    consumer.committed.return_value = [
        TopicPartition(topic, 0, 95),
        TopicPartition(topic, 1, 40),
    ]
    watermarks = {0: (0, 100), 1: (0, 50)}
    consumer.get_watermark_offsets.side_effect = lambda tp, timeout=None: watermarks[
        tp.partition
    ]

    report = gather_queue_stats(_settings(), consumer=consumer)

    assert report.ok
    assert report.total_end_offset == 150
    assert report.total_lag == 15  # (100-95) + (50-40)
    assert {p.partition: p.lag for p in report.partitions} == {0: 5, 1: 10}
    consumer.close.assert_not_called()  # caller-provided consumer is not closed


def test_gather_queue_stats_no_committed_offset():
    topic = "quora-answers"
    topic_meta = SimpleNamespace(error=None, partitions={0: object()})
    meta = SimpleNamespace(topics={topic: topic_meta})

    consumer = MagicMock()
    consumer.list_topics.return_value = meta
    # -1001 == OFFSET_INVALID: group has never committed.
    consumer.committed.return_value = [TopicPartition(topic, 0, -1001)]
    consumer.get_watermark_offsets.return_value = (0, 12)

    report = gather_queue_stats(_settings(), consumer=consumer)

    assert report.ok
    assert report.partitions[0].committed is None
    assert report.partitions[0].lag is None
    assert report.total_lag is None
    assert report.total_messages == 12


def test_gather_queue_stats_topic_missing():
    meta = SimpleNamespace(topics={})
    consumer = MagicMock()
    consumer.list_topics.return_value = meta

    report = gather_queue_stats(_settings(), consumer=consumer)
    assert not report.ok
    assert "not found" in (report.error or "")


# --------------------------------------------------------------------------- #
# Consumer group / members
# --------------------------------------------------------------------------- #
def test_gather_consumer_group_describes_members():
    assignment = SimpleNamespace(
        topic_partitions=[TopicPartition("quora-answers", 0), TopicPartition("quora-answers", 1)]
    )
    member = SimpleNamespace(
        member_id="m-1",
        client_id="rdkafka-sub",
        host="/10.0.0.5",
        assignment=assignment,
    )
    desc = SimpleNamespace(state=SimpleNamespace(name="STABLE"), members=[member])

    future = MagicMock()
    future.result.return_value = desc
    admin = MagicMock()
    admin.describe_consumer_groups.return_value = {"quora-consumer-group": future}

    report = gather_consumer_group(_settings(), admin=admin)

    assert report.ok
    assert report.state == "STABLE"
    assert len(report.members) == 1
    assert report.members[0].client_id == "rdkafka-sub"
    assert report.members[0].assignment == ["quora-answers[0]", "quora-answers[1]"]


def test_gather_consumer_group_error_is_caught():
    future = MagicMock()
    future.result.side_effect = RuntimeError("describe not supported")
    admin = MagicMock()
    admin.describe_consumer_groups.return_value = {"quora-consumer-group": future}

    report = gather_consumer_group(_settings(), admin=admin)
    assert not report.ok
    assert "describe not supported" in (report.error or "")


# --------------------------------------------------------------------------- #
# Health roll-up
# --------------------------------------------------------------------------- #
def test_gather_health_aggregates_probes():
    mongo_report = SimpleNamespace(ok=True, results=[])
    admin = MagicMock()
    admin.list_topics.return_value = SimpleNamespace(topics={"a": 1, "b": 2})

    with (
        patch("confluent_kafka.admin.AdminClient", return_value=admin),
        patch("quorascrapper.ops.mongo_check.run_mongo_checks", return_value=mongo_report),
        patch("quorascrapper.ops.healthcheck.check_serve_liveness", return_value=0),
    ):
        report = gather_health(_settings())

    names = {c.name: c for c in report.results}
    assert report.ok
    assert names["kafka"].ok
    assert names["mongo"].ok
    assert names["serve"].ok


def test_gather_health_reports_failures():
    failing = SimpleNamespace(name="mongo_ping", ok=False, detail="timeout")
    mongo_report = SimpleNamespace(ok=False, results=[failing])
    admin = MagicMock()
    admin.list_topics.side_effect = RuntimeError("no broker")

    with (
        patch("confluent_kafka.admin.AdminClient", return_value=admin),
        patch("quorascrapper.ops.mongo_check.run_mongo_checks", return_value=mongo_report),
        patch("quorascrapper.ops.healthcheck.check_serve_liveness", return_value=1),
    ):
        report = gather_health(_settings())

    names = {c.name: c for c in report.results}
    assert not report.ok
    assert not names["kafka"].ok
    assert not names["mongo"].ok
    assert not names["serve"].ok


def test_gather_health_can_skip_serve():
    mongo_report = SimpleNamespace(ok=True, results=[])
    admin = MagicMock()
    admin.list_topics.return_value = SimpleNamespace(topics={})

    with (
        patch("confluent_kafka.admin.AdminClient", return_value=admin),
        patch("quorascrapper.ops.mongo_check.run_mongo_checks", return_value=mongo_report),
    ):
        report = gather_health(_settings(), check_serve=False)

    assert {c.name for c in report.results} == {"kafka", "mongo"}


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def test_format_queue_includes_totals():
    from quorascrapper.ops.monitor import PartitionStat, QueueReport

    q = QueueReport(topic="t", group_id="g", bootstrap="b")
    q.partitions.append(PartitionStat(partition=0, low=0, high=100, committed=95, lag=5))
    lines = format_queue(q)
    assert any("lag=5" in line for line in lines)
    assert any("part" in line for line in lines)


def test_format_group_no_members():
    from quorascrapper.ops.monitor import GroupReport

    g = GroupReport(group_id="g", bootstrap="b", state="EMPTY", members=[])
    lines = format_group(g)
    assert any("no active members" in line for line in lines)


def test_format_health_marks_pass_fail():
    report = HealthReport()
    report.add("kafka", True, "ok")
    report.add("mongo", False, "down")
    lines = format_health(report)
    assert any("[PASS] kafka" in line for line in lines)
    assert any("[FAIL] mongo" in line for line in lines)


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #
def test_main_json_health_only(capsys):
    mongo_report = SimpleNamespace(ok=True, results=[])
    admin = MagicMock()
    admin.list_topics.return_value = SimpleNamespace(topics={"x": 1})

    with (
        patch("quorascrapper.ops.monitor.load_project_env"),
        patch("confluent_kafka.admin.AdminClient", return_value=admin),
        patch("quorascrapper.ops.mongo_check.run_mongo_checks", return_value=mongo_report),
        patch("quorascrapper.ops.healthcheck.check_serve_liveness", return_value=0),
        patch.object(Settings, "from_env", return_value=_settings()),
    ):
        code = monitor.main(["health", "--json"])

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "health" in out
    assert "queue" not in out
    assert out["health"]["ok"] is True


def test_main_queue_view_nonzero_on_error(capsys):
    bad = Settings(kafka_bootstrap="", kafka_topic="quora-answers")
    with (
        patch("quorascrapper.ops.monitor.load_project_env"),
        patch.object(Settings, "from_env", return_value=bad),
    ):
        code = monitor.main(["queue"])
    assert code == 1
    assert "KAFKA_BOOTSTRAP" in capsys.readouterr().out
