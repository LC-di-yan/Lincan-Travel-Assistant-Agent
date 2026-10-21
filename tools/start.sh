#!/bin/bash
cd /opt/aligo
source venv/bin/activate
exec python -m uvicorn server.app:app --host 0.0.0.0 --port 3003
