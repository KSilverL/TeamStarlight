# Trend Scout routine — container image for the Azure Container Apps scheduled Job.
# One run = one daily scan (the job's cron trigger starts a replica, run_scan.py exits,
# the replica is torn down). All config comes from the job's env vars + secrets —
# no .env is baked in (see .dockerignore).
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# prompt.md is only needed for --print-instructions (the agent's instructions live on
# the portal agent version), but it keeps the image self-documenting.
COPY run_scan.py prompt.md ./

CMD ["python", "run_scan.py"]
