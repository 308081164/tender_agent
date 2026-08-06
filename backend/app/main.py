from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from app.config import get_settings
from app.database_migrate import ensure_schema
from app.routers import api, admin
from app.seed.load_sample import run_seed
from app.seed.import_customer_pack import run_import, pack_root
from app.services.aspose_runtime import ensure_license

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_license(settings.aspose_license_path)
    ensure_schema()
    try:
        root = pack_root()
        if settings.prefer_customer_pack and (root / "engineered_templates").exists():
            run_import(force=False)
        else:
            run_seed()
    except Exception as e:
        print(f"[startup] seed/import warning: {e}")
        try:
            run_seed()
        except Exception as e2:
            print(f"[startup] sample seed warning: {e2}")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/")
def root():
    return {"message": "标书智能体系统 API", "docs": "/docs"}
