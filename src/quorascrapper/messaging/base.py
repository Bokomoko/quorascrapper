import hashlib
from typing import Any, Optional


class BaseSender:
    def send(self, obj: dict[str, Any]) -> None:
        url = obj.get("url")
        if url:
            obj["hash"] = hashlib.blake2s(
                str(url).encode("utf-8"), digest_size=16
            ).hexdigest()
        self._send(obj)

    def _send(self, obj: dict[str, Any]) -> None:
        raise NotImplementedError

    def flush(self, timeout: Optional[float] = None) -> None:
        pass

    def close(self) -> None:
        pass
