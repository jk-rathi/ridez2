"""Production WSGI entry point. Worker startup is owned by Gunicorn hooks."""
from app import create_app

app = create_app()
