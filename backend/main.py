"""Local ASGI entry point: uvicorn main:app --reload (from backend/).
Lambda imports the shared factory directly, without constructing this local app.
"""
from app.application import create_app

app = create_app()
