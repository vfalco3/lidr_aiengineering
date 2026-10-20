from fastapi import FastAPI; from app.config import settings; from app.routers import estimations; app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG); app.include_router(estimations.router)
