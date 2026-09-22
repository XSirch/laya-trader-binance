from io import BytesIO
from pathlib import Path
import zipfile

from laya_trader.data import binance_public


class FakeResponse:
    def __init__(self, status_code: int, *, content: bytes = b"", text: str = ""):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.ok = 200 <= status_code < 300

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, archive_bytes: bytes):
        self.archive_bytes = archive_bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str, timeout: int):
        if url.endswith(".CHECKSUM"):
            return FakeResponse(404)
        return FakeResponse(200, content=self.archive_bytes)


def valid_zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-15m-2025-01.csv", "1,2,3\n")
    return buffer.getvalue()


def test_corrupt_cached_archive_is_revalidated_and_replaced(tmp_path: Path, monkeypatch):
    archive_bytes = valid_zip_bytes()
    monkeypatch.setattr(
        binance_public.requests,
        "Session",
        lambda: FakeSession(archive_bytes),
    )

    target = (
        tmp_path
        / "binance"
        / "futures"
        / "um"
        / "monthly"
        / "klines"
        / "BTCUSDT"
        / "15m"
        / "BTCUSDT-15m-2025-01.zip"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not-a-zip")

    symbol, month, status = binance_public.download_one(
        "um",
        "BTCUSDT",
        "15m",
        "2025-01",
        tmp_path,
    )

    assert (symbol, month, status) == ("BTCUSDT", "2025-01", "downloaded")
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
