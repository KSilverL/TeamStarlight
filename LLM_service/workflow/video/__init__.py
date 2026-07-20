"""
Post-approval video rendering: asset resolution (assets.py) and the local Remotion
render subprocess + job orchestration (render.py, jobs.py).

Deliberately NOT inside workflow/executors/ — this package is not a MAF graph node.
A render takes 45+ seconds (asset fetches, headless Chromium); the workflow's sole
output node (media_producer) must stay fast, so rendering is triggered as a separate,
explicitly-POSTed job (see api.py's video_jobs_router) tracked in its own Postgres
table, not awaited as part of advancing the workflow graph.
"""
