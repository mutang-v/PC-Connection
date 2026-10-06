from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    host: str = os.environ.get("COMPANION_HOST", "0.0.0.0")
    port: int = int(os.environ.get("COMPANION_PORT", "8000"))
    web_dir: str = os.environ.get("COMPANION_WEB_DIR", "web")

settings = Settings()
