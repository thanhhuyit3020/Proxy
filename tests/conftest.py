"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio

import pytest

from proxy_manager.db import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


class FakeStreamWriter:
    """Test double cho asyncio.StreamWriter: ghi vao buffer, khong mo socket that."""

    def __init__(self):
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def make_reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


@pytest.fixture
def fake_writer():
    return FakeStreamWriter()


@pytest.fixture
def reader_factory():
    return make_reader
