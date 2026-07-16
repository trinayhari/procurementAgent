"""Durable background jobs: persistence, restart recovery, exception queue."""
from app.db import SessionLocal
from app.repositories import jobs as jobs_repo
from tests.conftest import make_confirmed_bom, run_supplier_search


def test_search_job_is_persisted(project):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    run_supplier_search(client, headers, pid, bom_id)
    r = client.get("/api/jobs", headers=headers)
    jobs = r.json()
    assert any(j["kind"] == "supplier_search" and j["status"] == "done" for j in jobs)
    job = next(j for j in jobs if j["kind"] == "supplier_search")
    assert job["detail"]["mocked"] is True
    assert job["detail"]["radiusMi"] == 75


def test_orphaned_running_jobs_fail_on_boot(project):
    client, headers, pid = project
    # Simulate a job left 'running' by a crash…
    with SessionLocal() as db:
        job = jobs_repo.start(db, "quote_ingest", pid, {"projectId": pid})
    # …then a "restart": the startup recovery hook.
    from app.repositories.jobs import fail_orphaned_running

    with SessionLocal() as db:
        failed = fail_orphaned_running(db)
    assert job["id"] in failed
    r = client.get("/api/jobs?status=error", headers=headers)
    entry = next(j for j in r.json() if j["id"] == job["id"])
    assert "restart" in entry["error"].lower()


def test_exception_queue_retry(project):
    client, headers, pid = project
    with SessionLocal() as db:
        job = jobs_repo.start(db, "quote_ingest", pid, {"projectId": pid})
        jobs_repo.fail(db, job["id"], "boom")

    # Failed jobs are visible in the queue.
    r = client.get("/api/jobs?status=error", headers=headers)
    assert any(j["id"] == job["id"] for j in r.json())

    # Retry re-runs it (mock ingest with no RFQs completes as done).
    r = client.post(f"/api/jobs/{job['id']}/retry", headers=headers)
    assert r.status_code == 200
    r = client.get("/api/jobs", headers=headers)
    entry = next(j for j in r.json() if j["id"] == job["id"])
    assert entry["status"] == "done"
    assert entry["attempts"] == 2

    # Only failed jobs can be retried.
    r = client.post(f"/api/jobs/{job['id']}/retry", headers=headers)
    assert r.status_code == 409


def test_ingest_status_survives_process_state(project):
    """Ingest status comes from the DB, not process memory: a fresh lookup
    (as another worker would do) sees the same terminal state."""
    client, headers, pid = project
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    with SessionLocal() as db:  # separate session ≈ another worker
        job = jobs_repo.latest(db, "quote_ingest", pid)
    assert job is not None and job["status"] == "done"
