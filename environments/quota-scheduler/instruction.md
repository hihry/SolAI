# Ticket: Deficit Round Robin Quantum Scheduler

Implement `FairScheduler.schedule_round` in `/app/src/scheduler.py` and hook up the `step` subcommand in `/app/src/cli.py`.

## Requirements
- Advance active tenants in Deficit Round Robin order using each tenant's configured `quantum`.
- Enforce per-tenant `QuotaLedger` remaining compute units and global `worker_slots` ceilings.
- Preserve all existing `TenantQueue` and `QuotaLedger` invariants.
