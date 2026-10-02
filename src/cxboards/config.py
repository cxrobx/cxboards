"""Where CXBoards keeps its data and which port it serves on.

Everything lives under one home directory (``CXBOARDS_HOME``, default
``~/Library/Application Support/CXBoards``): the SQLite database, uploaded
images, and the static snapshots Onyx reads. CXBoards never writes anywhere
else; audio cards only *read* the files they point at.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 4870
DEFAULT_HOME = Path.home() / "Library" / "Application Support" / "CXBoards"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class Config:
    home: Path
    port: int

    @property
    def db_path(self) -> Path:
        return self.home / "cxboards.db"

    @property
    def uploads_dir(self) -> Path:
        return self.home / "uploads"

    @property
    def export_dir(self) -> Path:
        return self.home / "export"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def ensure_dirs(self) -> None:
        for path in (self.home, self.uploads_dir, self.export_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    home = Path(os.environ.get("CXBOARDS_HOME", str(DEFAULT_HOME))).expanduser()
    port = int(os.environ.get("CXBOARDS_PORT", str(DEFAULT_PORT)))
    return Config(home=home, port=port)
