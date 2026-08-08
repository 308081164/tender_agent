import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "")
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


IS_DESKTOP = _env_bool("TENDER_DESKTOP") or _is_frozen()
DESKTOP_DEFAULT_PORT = 18766
DESKTOP_PG_PORT = 55432
DESKTOP_MINIO_PORT = 59000


def _resolve_install_dir() -> Path:
    if os.environ.get("TENDER_INSTALL_DIR"):
        return Path(os.environ["TENDER_INSTALL_DIR"]).resolve()
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    project_root = BACKEND_ROOT.parent
    if (project_root / "frontend").exists():
        return project_root.resolve()
    return BACKEND_ROOT.resolve()


def _resolve_data_dir() -> Path:
    if os.environ.get("TENDER_DATA_DIR"):
        return Path(os.environ["TENDER_DATA_DIR"]).resolve()
    if IS_DESKTOP:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return (base / "TenderAgent" / "data").resolve()
    return (BACKEND_ROOT.parent / "data").resolve()


INSTALL_DIR = _resolve_install_dir()
DATA_DIR = _resolve_data_dir()

if IS_DESKTOP:
    ROOT = INSTALL_DIR
else:
    ROOT = BACKEND_ROOT.parent if (BACKEND_ROOT.parent / "frontend").exists() else BACKEND_ROOT

ENV_FILE = ROOT / ".env" if (ROOT / ".env").exists() else BACKEND_ROOT / ".env"
if IS_DESKTOP and not ENV_FILE.exists():
    ENV_FILE = DATA_DIR / ".env"

_settings_config = (
    SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")
    if ENV_FILE.exists()
    else SettingsConfigDict(extra="ignore")
)


def _desktop_defaults() -> dict:
    customer = INSTALL_DIR / "customer_data" / "heyuanzhineng_20260729"
    return {
        "database_url": (
            f"postgresql://tender:tender123@127.0.0.1:{DESKTOP_PG_PORT}/tender_agent"
        ),
        "minio_endpoint": f"127.0.0.1:{DESKTOP_MINIO_PORT}",
        "sample_data_dir": str(INSTALL_DIR / "sample_data"),
        "customer_data_dir": str(customer) if customer.exists() else "",
        "aspose_license_path": str(INSTALL_DIR / "aspose" / "Aspose.License.txt"),
        "cors_origins": (
            f"http://127.0.0.1:{DESKTOP_DEFAULT_PORT},"
            f"http://localhost:{DESKTOP_DEFAULT_PORT}"
        ),
    }


class Settings(BaseSettings):
    model_config = _settings_config

    app_name: str = "标书智能体系统"
    database_url: str = "postgresql://tender:tender123@db:5432/tender_agent"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "tender-agent"
    minio_secure: bool = False
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    sample_data_dir: str = "/app/sample_data"
    customer_data_dir: str = ""
    cors_origins: str = "*"
    aspose_license_path: str = "/aspose/Aspose.License.txt"
    prefer_customer_pack: bool = True

    @model_validator(mode="before")
    @classmethod
    def apply_desktop_defaults(cls, data):
        if not isinstance(data, dict):
            return data
        if IS_DESKTOP:
            for key, value in _desktop_defaults().items():
                data.setdefault(key, value)
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
