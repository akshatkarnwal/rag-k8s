# app/tasks.py
from app.worker import celery


@celery.task(name="app.tasks.add")
def add(x: int, y: int) -> int:
    """Trivial smoke-test task — proves the worker is alive and executing."""
    return x + y