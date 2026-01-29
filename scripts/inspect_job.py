from app.config import get_settings
from app.storage.postgres_jobs_repo import PostgresJobsRepository

settings = get_settings()

if not settings.pg_dsn:
  print("Error: DYLEN_PG_DSN not set in environment.")
  exit(1)

repo = PostgresJobsRepository(dsn=settings.pg_dsn, connect_timeout=settings.pg_connect_timeout, table_name=settings.pg_jobs_table)

job_id = "66976cb7-d9e9-4042-8b27-e7c8076201e0"
job = repo.get_job(job_id)

if not job:
  print(f"Job {job_id} not found.")
else:
  print(f"Job Status: {job.status}")
  print(f"Job Phase: {job.phase}")
  print("Logs:")
  for log in job.logs:
    print(f" - {log}")
