from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cxboards.app import create_app
from cxboards.config import Config
from cxboards.store import Store

W = {"X-CXBoards": "1"}
AGENT = {"X-CXBoards": "1", "X-CXBoards-Actor": "agent"}


def fake_unfurl(url: str) -> dict[str, str]:
    return {"title": f"Preview of {url}", "site": "example", "image": "https://example.com/i.png"}


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(home=tmp_path / "home", port=4870)


@pytest.fixture
def store(config: Config) -> Store:
    return Store(config)


@pytest.fixture
def client(config: Config):
    app = create_app(config, unfurl=fake_unfurl, export_delay=0.05)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def bounce(tmp_path: Path) -> Path:
    """A real (tiny) wav standing in for a bounce on the ChrisX drive."""
    path = tmp_path / "MuZik" / "Oct2026" / "endofworld_2.wav"
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    return path


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201a5f2"
    "d3a10000000049454e44ae426082"
)
