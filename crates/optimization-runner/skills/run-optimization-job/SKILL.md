---
name: run-optimization-job
description: "Stage input files, validate, submit, reconnect to, and cancel durable optimization jobs over MCP."
---

1. Call describe_node and describe_worker for capacity, profiles, payload
   schemas and examples. On a node with eight free slots, an eligible profile
   can use eight single-threaded outer retries or one outer task with eight
   evaluation threads. The latter needs a worker that supports inner
   parallelism for the selected profile.
2. Use put_input for model files. Put the returned file name and SHA-256 in
   the job inputs and pass the returned input_dir. Build the job envelope
   and call validate_job.
3. Submit with a stable request_key. Persist the task reference if the client
   supports Tasks, or save the job_id. When recovering from a lost reply,
   reuse the exact request and key to identify the same job.
4. After reconnecting, poll the saved task or call get_job. Use tasks/cancel
   or cancel_job for a cooperative stop. Then read committed work with
   get_result.

Read [the job API](references/job-api.md), [the MCP tools](references/mcp.md)
and [CPU budgeting](references/cpu-budget.md) as needed.
