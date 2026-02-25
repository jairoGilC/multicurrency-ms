"""FastAPI application for the Multi-Currency Refund Engine."""

from fastapi import FastAPI

from src.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Currency Refund Engine",
        description="Falcon Travel's Multi-Currency Refund Processing API",
        version="1.0.0",
    )
    app.include_router(router)
    return app


app = create_app()
