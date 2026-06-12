from typing import Any, Optional

from quorascrapper.filter.core import url_hash


class BaseSender:
    def send(self, obj: dict[str, Any]) -> None:
        url = obj.get("url")
        if url:
            obj["hash"] = url_hash(str(url))
        self._send(obj)

    def _send(self, obj: dict[str, Any]) -> None:
        raise NotImplementedError

    def flush(self, timeout: Optional[float] = None) -> None:
        pass

    def close(self) -> None:
        pass
