"""
HPA load test for rag-k8s: sustained bcrypt (/token) load, ZERO Gemini calls.

/query is quota-limited and I/O-bound (the work happens at Google), so it can't
push the pod's CPU. /token runs bcrypt on every call, which is CPU-bound, so
hammering it drives CPU toward the pod limit and lets you watch the HPA scale.

Usage (needs DEMO_USERNAME / DEMO_PASSWORD exported in the same terminal):

    uv run locust -f locustfile_hpa.py \
        --host "$(minikube service rag-k8s-service --url)" \
        --headless -u 8 -r 2 -t 4m --csv=results/run3_hpa

Watch in other terminals:
    kubectl get hpa rag-k8s-hpa -w
    kubectl get pods -w
"""

import os

from locust import HttpUser, task, between

DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo")


class LoginStormUser(HttpUser):
    # Short waits keep several bcrypt verifications in flight at all times.
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # new TCP connection per request so kube-proxy can spread load across pods
        self.client.headers["Connection"] = "close"

    @task
    def login(self):
        self.client.post(
            "/token",
            data={"username": DEMO_USERNAME, "password": DEMO_PASSWORD},
            name="/token",
        )
