from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import IS_DESKTOP, ROOT, get_settings
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


STATIC_DIR = ROOT / "frontend" / "dist"
ASSETS_DIR = STATIC_DIR / "assets"
_STATIC_FILE_SUFFIXES = {
    ".png",
    ".ico",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".json",
    ".txt",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".css",
    ".js",
}


def _mount_frontend_spa() -> None:
    if not STATIC_DIR.exists() or not (STATIC_DIR / "index.html").exists():
        return
    if ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        candidate = (STATIC_DIR / full_path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return {"detail": "Not Found"}
        if candidate.is_file() and candidate.suffix.lower() in _STATIC_FILE_SUFFIXES:
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"detail": "frontend not built"}


if IS_DESKTOP or (STATIC_DIR / "index.html").exists():
    _mount_frontend_spa()
else:

    @app.get("/")
    def root():
        return {"message": "标书智能体系统 API", "docs": "/docs"}
