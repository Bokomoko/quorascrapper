"""Runtime pipeline monitoring: Kafka queue depth + consumer-group lag,
consumer-group members/state, and aggregated health.

Unlike preflight (pre-deploy gate) and healthcheck (container pass/fail probe),
this surfaces *live* numbers: how many messages are queued, how far behind the
subscriber consumer group is, which consumers are connected, and a readable
roll-up of broker/Mongo/serve reachability.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from quorascrapper.config import Settings, load_project_env


# --------------------------------------------------------------------------- #
# Queue depth + consumer-group lag
# --------------------------------------------------------------------------- #
@dataclass
class PartitionStat:
    partition: int
    low: int
    high: int  # next offset to be produced == end offset
    committed: int | None  # None when the group has no committed offset
    lag: int | None  # None when committed is unknown

    @property
    def messages(self) -> int:
        """Messages currently retained in the partition (end - start)."""
        return max(self.high - self.low, 0)


@dataclass
class QueueReport:
    topic: str
    group_id: str
    bootstrap: str
    partitions: list[PartitionStat] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def total_messages(self) -> int:
        return sum(p.messages for p in self.partitions)

    @property
    def total_end_offset(self) -> int:
        return sum(p.high for p in self.partitions)

    @property
    def total_committed(self) -> int:
        return sum(p.committed for p in self.partitions if p.committed is not None)

    @property
    def total_lag(self) -> int | None:
        lags = [p.lag for p in self.partitions if p.lag is not None]
        if not lags:
            return None
        return sum(lags)


def gather_queue_stats(
    settings: Settings,
    *,
    consumer=None,
    timeout: float = 10.0,
) -> QueueReport:
    """Compute per-partition end offsets, committed offsets and lag.

    A single Consumer (bound to the subscriber group) yields both the queue
    depth (watermark offsets) and the group's committed position. Pass a
    pre-built ``consumer`` for testing; otherwise one is created and closed.
    """
    report = QueueReport(
        topic=settings.kafka_topic,
        group_id=settings.kafka_group_id,
        bootstrap=settings.kafka_bootstrap,
    )
    if not settings.kafka_bootstrap:
        report.error = "KAFKA_BOOTSTRAP not set"
        return report

    own_consumer = consumer is None
    if consumer is None:
        try:
            from confluent_kafka import Consumer  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency missing
            report.error = f"confluent-kafka unavailable: {exc}"
            return report
        consumer = Consumer(
            {
                "bootstrap.servers": settings.kafka_bootstrap,
                "group.id": settings.kafka_group_id,
                "enable.auto.commit": False,
            }
        )

    try:
        from confluent_kafka import TopicPartition  # type: ignore

        meta = consumer.list_topics(topic=settings.kafka_topic, timeout=timeout)
        topic_meta = meta.topics.get(settings.kafka_topic)
        if topic_meta is None:
            report.error = f"Topic '{settings.kafka_topic}' not found"
            return report
        if getattr(topic_meta, "error", None) is not None:
            report.error = f"Topic '{settings.kafka_topic}': {topic_meta.error}"
            return report

        partitions = sorted(topic_meta.partitions.keys())
        if not partitions:
            report.error = f"Topic '{settings.kafka_topic}' has no partitions"
            return report

        tps = [TopicPartition(settings.kafka_topic, p) for p in partitions]
        committed = consumer.committed(tps, timeout=timeout)
        committed_by_partition = {tp.partition: tp.offset for tp in committed}

        for partition in partitions:
            low, high = consumer.get_watermark_offsets(
                TopicPartition(settings.kafka_topic, partition), timeout=timeout
            )
            raw = committed_by_partition.get(partition)
            committed_offset = raw if (raw is not None and raw >= 0) else None
            lag = (high - committed_offset) if committed_offset is not None else None
            report.partitions.append(
                PartitionStat(
                    partition=partition,
                    low=low,
                    high=high,
                    committed=committed_offset,
                    lag=lag,
                )
            )
    except Exception as exc:
        report.error = str(exc)
    finally:
        if own_consumer:
            try:
                consumer.close()
            except Exception:
                pass

    return report


# --------------------------------------------------------------------------- #
# Consumer group state + members ("agents")
# --------------------------------------------------------------------------- #
@dataclass
class MemberInfo:
    member_id: str
    client_id: str
    host: str
    assignment: list[str] = field(default_factory=list)


@dataclass
class GroupReport:
    group_id: str
    bootstrap: str
    state: str | None = None
    members: list[MemberInfo] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def gather_consumer_group(
    settings: Settings,
    *,
    admin=None,
    timeout: float = 10.0,
) -> GroupReport:
    """Describe the subscriber consumer group: state + connected members.

    Best-effort: brokers/clients that do not support describe will report an
    error rather than raising. Pass a pre-built ``admin`` (AdminClient-like)
    for testing.
    """
    report = GroupReport(
        group_id=settings.kafka_group_id,
        bootstrap=settings.kafka_bootstrap,
    )
    if not settings.kafka_bootstrap:
        report.error = "KAFKA_BOOTSTRAP not set"
        return report

    if admin is None:
        try:
            from confluent_kafka.admin import AdminClient  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency missing
            report.error = f"confluent-kafka unavailable: {exc}"
            return report
        admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})

    try:
        futures = admin.describe_consumer_groups([settings.kafka_group_id])
        desc = futures[settings.kafka_group_id].result(timeout=timeout)
        state = getattr(desc, "state", None)
        report.state = getattr(state, "name", None) or str(state) if state is not None else None
        for member in getattr(desc, "members", []) or []:
            assignment: list[str] = []
            member_assignment = getattr(member, "assignment", None)
            if member_assignment is not None:
                for tp in getattr(member_assignment, "topic_partitions", []) or []:
                    assignment.append(f"{tp.topic}[{tp.partition}]")
            report.members.append(
                MemberInfo(
                    member_id=getattr(member, "member_id", "") or "",
                    client_id=getattr(member, "client_id", "") or "",
                    host=getattr(member, "host", "") or "",
                    assignment=assignment,
                )
            )
    except Exception as exc:
        report.error = str(exc)

    return report


# --------------------------------------------------------------------------- #
# Aggregated health roll-up
# --------------------------------------------------------------------------- #
@dataclass
class HealthCheck:
    name: str
    ok: bool
    detail: str


@dataclass
class HealthReport:
    results: list[HealthCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(HealthCheck(name=name, ok=ok, detail=detail))


def gather_health(
    settings: Settings,
    *,
    ping_url: str | None = None,
    check_serve: bool = True,
    timeout: float = 5.0,
) -> HealthReport:
    """Aggregate the existing probes (Kafka reachable, Mongo reachable,
    serve /ping) into one readable report."""
    report = HealthReport()

    # Kafka broker reachability.
    if not settings.kafka_bootstrap:
        report.add("kafka", False, "KAFKA_BOOTSTRAP not set")
    else:
        try:
            from confluent_kafka.admin import AdminClient  # type: ignore

            admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})
            meta = admin.list_topics(timeout=timeout)
            report.add(
                "kafka",
                True,
                f"{settings.kafka_bootstrap} reachable ({len(meta.topics)} topics)",
            )
        except Exception as exc:
            report.add("kafka", False, f"{settings.kafka_bootstrap}: {exc}")

    # MongoDB reachability (reuse the canonical probe).
    from quorascrapper.ops.mongo_check import run_mongo_checks

    mongo = run_mongo_checks(settings)
    failed = next((c for c in mongo.results if not c.ok), None)
    if mongo.ok:
        report.add("mongo", True, "DNS + ping OK")
    elif failed is not None:
        report.add("mongo", False, f"{failed.name}: {failed.detail}")
    else:
        report.add("mongo", False, "unknown failure")

    # serve HTTP liveness (best-effort; the broker host may not expose it).
    if check_serve:
        from quorascrapper.ops.healthcheck import DEFAULT_SERVE_PING, check_serve_liveness

        url = ping_url or DEFAULT_SERVE_PING
        code = check_serve_liveness(ping_url=url, timeout_sec=timeout)
        report.add(
            "serve",
            code == 0,
            f"/ping OK ({url})" if code == 0 else f"/ping unreachable ({url})",
        )

    return report


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def format_queue(report: QueueReport) -> list[str]:
    lines = [f"QUEUE  topic={report.topic}  group={report.group_id}"]
    if report.error:
        lines.append(f"  error: {report.error}")
        return lines
    lines.append(f"  {'part':>4}  {'end-offset':>12}  {'committed':>12}  {'lag':>10}")
    for p in report.partitions:
        committed = "-" if p.committed is None else str(p.committed)
        lag = "-" if p.lag is None else str(p.lag)
        lines.append(f"  {p.partition:>4}  {p.high:>12}  {committed:>12}  {lag:>10}")
    total_lag = "-" if report.total_lag is None else str(report.total_lag)
    lines.append(
        f"  total messages={report.total_messages}  "
        f"end={report.total_end_offset}  committed={report.total_committed}  "
        f"lag={total_lag}"
    )
    return lines


def format_group(report: GroupReport) -> list[str]:
    if report.error:
        return [f"CONSUMERS  group={report.group_id}", f"  error: {report.error}"]
    state = report.state or "unknown"
    lines = [
        f"CONSUMERS  group={report.group_id}  state={state}  members={len(report.members)}"
    ]
    if not report.members:
        lines.append("  (no active members)")
    for m in report.members:
        assigned = ", ".join(m.assignment) if m.assignment else "(none)"
        ident = m.client_id or m.member_id or "(unknown)"
        lines.append(f"  - {ident}  host={m.host or '?'}  assigned={assigned}")
    return lines


def format_health(report: HealthReport) -> list[str]:
    lines = ["HEALTH"]
    for c in report.results:
        lines.append(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    return lines


def _queue_json(report: QueueReport) -> dict:
    return {
        "ok": report.ok,
        "topic": report.topic,
        "group_id": report.group_id,
        "bootstrap": report.bootstrap,
        "error": report.error,
        "total_messages": report.total_messages,
        "total_end_offset": report.total_end_offset,
        "total_committed": report.total_committed,
        "total_lag": report.total_lag,
        "partitions": [
            {
                "partition": p.partition,
                "low": p.low,
                "high": p.high,
                "committed": p.committed,
                "lag": p.lag,
            }
            for p in report.partitions
        ],
    }


def _group_json(report: GroupReport) -> dict:
    return {
        "ok": report.ok,
        "group_id": report.group_id,
        "bootstrap": report.bootstrap,
        "state": report.state,
        "error": report.error,
        "members": [
            {
                "member_id": m.member_id,
                "client_id": m.client_id,
                "host": m.host,
                "assignment": m.assignment,
            }
            for m in report.members
        ],
    }


def _health_json(report: HealthReport) -> dict:
    return {
        "ok": report.ok,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.results],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qsbk monitor",
        description="Monitor the pipeline: Kafka queue depth + consumer-group lag, "
        "consumers, and aggregated health.",
    )
    parser.add_argument(
        "view",
        nargs="?",
        choices=["all", "queue", "consumers", "health"],
        default="all",
        help="Which view to show (default: all)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument(
        "--ping-url",
        default=None,
        help="Override serve /ping URL for the health view",
    )
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Skip the serve /ping probe in the health view",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds (default: 10)",
    )
    args = parser.parse_args(argv)

    load_project_env()
    settings = Settings.from_env()

    view = args.view
    want_queue = view in ("all", "queue")
    want_consumers = view in ("all", "consumers")
    want_health = view in ("all", "health")

    queue_report = (
        gather_queue_stats(settings, timeout=args.timeout) if want_queue else None
    )
    group_report = (
        gather_consumer_group(settings, timeout=args.timeout) if want_consumers else None
    )
    health_report = (
        gather_health(
            settings,
            ping_url=args.ping_url,
            check_serve=not args.no_serve,
            timeout=min(args.timeout, 10.0),
        )
        if want_health
        else None
    )

    if args.json:
        payload: dict = {}
        if queue_report is not None:
            payload["queue"] = _queue_json(queue_report)
        if group_report is not None:
            payload["consumers"] = _group_json(group_report)
        if health_report is not None:
            payload["health"] = _health_json(health_report)
        print(json.dumps(payload, indent=2))
    else:
        print(f"qsbk monitor — {settings.kafka_topic} @ {settings.kafka_bootstrap or '(unset)'}")
        blocks: list[list[str]] = []
        if queue_report is not None:
            blocks.append(format_queue(queue_report))
        if group_report is not None:
            blocks.append(format_group(group_report))
        if health_report is not None:
            blocks.append(format_health(health_report))
        for block in blocks:
            print()
            for line in block:
                print(line)

    # Exit non-zero when a requested view reports failure, so the command is
    # usable in scripts / cron monitors.
    failed = False
    if queue_report is not None and not queue_report.ok:
        failed = True
    if group_report is not None and not group_report.ok:
        failed = True
    if health_report is not None and not health_report.ok:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
