from quorascrapper.ops.preflight import run_preflight


def test_preflight_fails_without_mongodb(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "")
    report = run_preflight(mode="subscriber")
    names = {r.name for r in report.results}
    assert "env_required" in names
    assert not report.ok


def test_preflight_passes_env_with_valid_values(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "localhost:19092")
    monkeypatch.setenv(
        "MONGODB_URI",
        "mongodb+srv://user:realpass@cluster0.example.mongodb.net/quora_data",
    )
    report = run_preflight(mode="scraper")
    env_check = next(r for r in report.results if r.name == "env_required")
    assert env_check.status == "pass"
