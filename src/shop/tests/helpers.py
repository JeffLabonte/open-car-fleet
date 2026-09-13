"""Shared test fixtures and fakes for the shop test modules."""


class FakeHankoResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR'
PDF_SIGNATURE = b'%PDF-1.4'
MP4_SIGNATURE = b'\x00\x00\x00\x20ftypisom'
