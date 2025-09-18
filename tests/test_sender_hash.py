import io
import json

from senders import StdoutSender


def test_stdout_sender_includes_16byte_hex_hash():
    buf = io.StringIO()
    s = StdoutSender(stream=buf)
    url = "https://example.com/answer/123"
    s.send({"url": url})
    line = buf.getvalue().strip()
    data = json.loads(line)
    assert data["url"] == url
    assert "hash" in data
    # 16 bytes -> 32 hex chars
    assert isinstance(data["hash"], str)
    assert len(data["hash"]) == 32
    int(data["hash"], 16)  # should parse as hex
