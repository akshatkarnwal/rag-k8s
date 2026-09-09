"""
Load test for rag-k8s.

Usage (web UI, recommended for a first run so you can watch it live
alongside Grafana):

    uv run locust -f locustfile.py --host http://localhost:8000

Then open http://localhost:8089, set number of users + spawn rate, and
start. Watch rag_query_latency_seconds / rag_query_total on your Grafana
dashboard while it runs.

Headless run (for capturing a fixed run's numbers into a file, e.g. for
the README or resume):

    uv run locust -f locustfile.py --host http://localhost:8000 \
        --headless -u 50 -r 5 -t 3m \
        --csv=results/run1

That produces results/run1_stats.csv, results/run1_stats_history.csv,
and results/run1_failures.csv you can pull numbers or a chart from.

--- ASSUMPTIONS TO VERIFY AGAINST YOUR ACTUAL CODE BEFORE RUNNING ---

1. Login endpoint: assumed to be `POST /token`, OAuth2PasswordRequestForm
   style (form-encoded `username` + `password`, NOT JSON), returning
   {"access_token": "...", "token_type": "bearer"}. This is the FastAPI
   `OAuth2PasswordBearer` convention. If your /token endpoint takes JSON
   instead, change `client.post("/token", data=...)` to
   `client.post("/token", json=...)` below.

2. Demo credentials: read from DEMO_USERNAME / DEMO_PASSWORD env vars,
   defaulting to "demo" / "demo". Set these to match whatever single demo
   user you created when you added JWT auth, e.g.:

       export DEMO_USERNAME=demo
       export DEMO_PASSWORD=your-actual-demo-password

3. Query endpoint: assumed to be `POST /query` with a JSON body shaped
   {"query": "<question text>"} and an `Authorization: Bearer <token>`
   header. Adjust QUERY_PAYLOAD_KEY below if your Pydantic request model
   uses a different field name (e.g. "question" or "text").

4. /health and /metrics are assumed to still be unauthenticated, per your
   existing setup — the HealthCheckUser below hits /health with no token.
"""

import os
import random
import threading

from locust import HttpUser, task, between, events

DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo")

# Hard cap on total successful /query calls for this run. Each call burns
# real Gemini quota (free tier: 20 generate_content calls/day as of this
# writing), so this stops the run automatically once the cap is hit,
# regardless of user count, ramp speed, or wait_time — safer than trying
# to hand-compute timing to land under quota.
MAX_QUERY_REQUESTS = int(os.environ.get("MAX_QUERY_REQUESTS", "15"))
_query_count_lock = threading.Lock()
_query_count = 0

# The field name your /query request body expects. app/main.py defines
# QueryRequest with a `question` field (request.question is used inside
# the endpoint), not `query`.
QUERY_PAYLOAD_KEY = "question"

# A small pool of realistic questions to vary load across different
# queries rather than hammering pgvector/Gemini with the exact same
# cached-friendly request every time.
SAMPLE_QUESTIONS = [
    "How do I fix high CPU on DNIF?",
    "What is the escalation path for a P1 incident?",
    "How do I restart the ingestion service?",
    "What are the steps to rotate API keys?",
    "How do I check replica health in the cluster?",
    "What's the runbook for a failed deployment?",
]


class RagQueryUser(HttpUser):
    """
    Simulates a real client of the RAG API: logs in once, then repeatedly
    issues queries at a random human-ish pace.
    """

    wait_time = between(1, 3)
    weight = 9  # spawn far more of these than HealthCheckUser (see below)

    def on_start(self):
        """Runs once per simulated user when it spawns. Logs in and
        stashes the bearer token for use on every subsequent request.

        Uses catch_response=True so we can inspect/mark the response
        ourselves — required any time you call response.failure() or
        response.success() manually instead of relying on Locust's
        automatic status-code-based pass/fail.
        """
        self.token = None
        with self.client.post(
            "/token",
            data={"username": DEMO_USERNAME, "password": DEMO_PASSWORD},
            name="/token",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                # Fail loudly rather than silently sending unauthenticated
                # requests for the rest of the run — an auth misconfiguration
                # should show up immediately, not as a wall of /query 401s.
                response.failure(
                    f"Login failed with {response.status_code}: {response.text}"
                )
            else:
                self.token = response.json().get("access_token")

    @task
    def query(self):
        global _query_count
        if not self.token:
            return  # login failed in on_start; skip to avoid spamming 401s

        with _query_count_lock:
            if _query_count >= MAX_QUERY_REQUESTS:
                # Cap reached — stop this user's traffic and tell the
                # whole runner to shut down so the run ends cleanly with
                # a real summary instead of grinding on into 429s.
                if self.environment.runner is not None:
                    self.environment.runner.quit()
                return
            _query_count += 1

        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {QUERY_PAYLOAD_KEY: random.choice(SAMPLE_QUESTIONS)}
        self.client.post("/query", json=payload, headers=headers, name="/query")


class HealthCheckUser(HttpUser):
    """
    A light-weight baseline user hitting the unauthenticated /health
    endpoint. Useful for confirming the load balancer / pod readiness
    stays responsive even while RagQueryUser is under heavy load —
    if /health starts timing out, that's a sign the bottleneck is at
    the infra layer, not just slow LLM calls.
    """

    wait_time = between(2, 5)
    weight = 1  # spawn far fewer of these than RagQueryUser (9:1 ratio)

    @task
    def health(self):
        self.client.get("/health", name="/health")


@events.quitting.add_listener
def _summary(environment, **kwargs):
    """Print a one-line pass/fail summary at the end of a headless run,
    useful for CI or quick terminal checks without opening the CSVs."""
    stats = environment.stats.total
    print(
        f"\nSummary: {stats.num_requests} requests, "
        f"{stats.num_failures} failures, "
        f"p95={stats.get_response_time_percentile(0.95)}ms, "
        f"p99={stats.get_response_time_percentile(0.99)}ms, "
        f"avg={stats.avg_response_time:.0f}ms"
    )