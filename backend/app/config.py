from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
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

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
