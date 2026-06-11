from unittest.mock import MagicMock, patch

from quorascrapper.ops.discover_mongo import check_mongo_dns, hostname_from_uri


def test_hostname_from_srv_uri():
    uri = "mongodb+srv://user:pass@cluster0.ed03k.mongodb.net/?appName=Cluster0"
    assert hostname_from_uri(uri) == "cluster0.ed03k.mongodb.net"


def test_check_mongo_dns_srv():
    uri = "mongodb+srv://user:pass@cluster0.ed03k.mongodb.net/?appName=Cluster0"
    record = MagicMock()
    record.target = "cluster0-shard-00-00.ed03k.mongodb.net."
    with patch("dns.resolver.resolve", return_value=[record]):
        ok, msg = check_mongo_dns(uri)
    assert ok is True
    assert "SRV OK" in msg


def test_check_mongo_dns_standard():
    uri = "mongodb://user:pass@mongo.example.net:27017/db"
    with patch("socket.gethostbyname", return_value="10.0.0.5"):
        ok, msg = check_mongo_dns(uri)
    assert ok is True
    assert "mongo.example.net" in msg
