from quorascrapper.config import Settings


def test_validate_scraper_kafka_requires_bootstrap():
    s = Settings(sender="kafka", kafka_bootstrap="")
    assert "KAFKA_BOOTSTRAP" in " ".join(s.validate_scraper())
