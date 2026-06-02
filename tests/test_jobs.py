"""Tests for jobs.py — Background Job Tracking."""

from wartz_workflow import jobs


class TestCreateJob:
    def test_creates_job(self):
        job = jobs.create_job("AAT-1", "0.6", "wartzresearcher")
        assert job.jira_key == "AAT-1"
        assert job.phase_id == "0.6"
        assert job.agent == "wartzresearcher"
        assert job.status == "pending"
        assert len(job.job_id) == 8

    def test_job_persisted(self):
        job = jobs.create_job("AAT-1", "7.5", "wartzreviewer")
        loaded = jobs.load_job(job.job_id)
        assert loaded is not None
        assert loaded.phase_id == "7.5"


class TestUpdateJobStatus:
    def test_running(self):
        job = jobs.create_job("AAT-1", "1", "wartzcoder")
        jobs.update_job_status(job.job_id, "running")
        loaded = jobs.load_job(job.job_id)
        assert loaded.status == "running"
        assert loaded.started_at is not None

    def test_complete(self):
        job = jobs.create_job("AAT-1", "2", "wartzcoder")
        jobs.update_job_status(job.job_id, "complete", "All done")
        loaded = jobs.load_job(job.job_id)
        assert loaded.status == "complete"
        assert loaded.completed_at is not None
        assert loaded.result == "All done"


class TestListJobs:
    def test_filter_by_jira(self):
        # Create some jobs
        j1 = jobs.create_job("AAT-2", "0.6", "wartzresearcher")
        j2 = jobs.create_job("AAT-2", "7.5", "wartzreviewer")
        j3 = jobs.create_job("AAT-3", "0.6", "wartzresearcher")

        aat2 = jobs.list_jobs(jira_key="AAT-2")
        assert len(aat2) >= 2
        assert all(j.jira_key == "AAT-2" for j in aat2)

    def test_filter_by_phase(self):
        j1 = jobs.create_job("AAT-4", "7.6", "wartzreviewer")
        aat4_76 = jobs.list_jobs(jira_key="AAT-4", phase_id="7.6")
        assert len(aat4_76) >= 1
        assert aat4_76[0].phase_id == "7.6"


class TestIsPhaseDelegated:
    def test_true_when_pending(self):
        jobs.create_job("AAT-5", "0.6", "wartzresearcher")
        assert jobs.is_phase_delegated("AAT-5", "0.6")

    def test_false_when_not_created(self):
        assert not jobs.is_phase_delegated("AAT-NO-JOBS", "0.6")


class TestRenderJobsTable:
    def test_empty(self):
        text = jobs.render_jobs_table("AAT-NO-JOBS")
        assert "Нет background jobs" in text

    def test_with_jobs(self):
        jobs.create_job("AAT-6", "0.6", "wartzresearcher")
        text = jobs.render_jobs_table("AAT-6")
        assert "Job" in text
        assert "Phase" in text
        assert "0.6" in text
