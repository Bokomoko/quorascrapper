import signal
import sys
from typing import Optional

from quorascrapper.logging_setup import init_logging
from quorascrapper.ops.gate import abort_startup
from quorascrapper.subscriber.consumer import KafkaMongoSubscriber

logger = init_logging("subscriber")

_active_subscriber: Optional[KafkaMongoSubscriber] = None


def signal_handler(signum, frame) -> None:
    logger.info("Received signal %s, shutting down...", signum)
    if _active_subscriber is not None:
        _active_subscriber.shutdown = True
    else:
        sys.exit(0)


def main() -> int:
    global _active_subscriber

    import argparse

    parser = argparse.ArgumentParser(description="Kafka to MongoDB subscriber")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip infrastructure preflight (dev/tests only)",
    )
    args = parser.parse_args()

    abort_startup("subscriber", cli_skip=args.skip_preflight)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        subscriber = KafkaMongoSubscriber()
        _active_subscriber = subscriber
        return subscriber.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
