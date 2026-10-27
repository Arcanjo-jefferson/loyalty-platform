"""API Gateway HTTP API Lambda entry point; no background processing.

Handler: lambda_function.handler (backend/ is the deployment package root).
Services initialize once per execution environment; durable state stays in the
configured repository. Never package backend/.env or local AWS credentials.
"""
from mangum import Mangum
from app.application import create_app

app = create_app(start_sms_worker=False)
# No per-invocation startup/shutdown and no local background thread. The factory
# flag also protects against a later caller explicitly entering app lifespan.
handler = Mangum(app, lifespan='off')
