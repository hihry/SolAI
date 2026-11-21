# AGENTS.md

Agent harness for the Solumn RLE Cyber-Boundary repository (`environments/`, `results/`, `README.md`, `QUALITY_BAR.md`, and `solumn_cyber_harm_submission.zip`).

## Startup Workflow

Before writing code:

1. **Confirm working directory** with `pwd` (`/home/hihry/Projects/solumnAI`)
2. **Read this file** and project docs (`README.md`, `QUALITY_BAR.md`)
3. **Run `./init.sh`** to verify syntax, baseline unit tests, and archive integrity
4. **Read `feature_list.json` and `progress.md`** to inspect current feature status
5. **Review recent commits** with `git status -sb`

If baseline verification fails, fix it before starting new work.

## Working Rules

- **One feature at a time**: Pick a single unfinished item from `feature_list.json`
- **Stay in scope**: Keep each environment within 4–8 source files and 300–700 lines; keep `.env` credentials and harness files (`AGENTS.md`, `feature_list.json`, `progress.md`, `session-handoff.md`, `init.sh`) out of `solumn_cyber_harm_submission.zip`
- **Verification required**: Run `./init.sh` before marking any feature complete
- **Update artifacts**: Record verification evidence in `feature_list.json` and `progress.md`
- **Leave clean state**: Remove `__pycache__` artifacts and keep the repo immediately restartable

## Definition of Done

A feature is done only when ALL of the following hold:

- [ ] Target behavior is implemented within repository bounds
- [ ] Static compile check, unit tests, and archive checks pass via `./init.sh`
- [ ] Verification Evidence is recorded in `feature_list.json` and `progress.md`
- [ ] Repository remains clean and restartable for the next session

## End of Session

Before ending a session:

1. Re-run `./init.sh` and rebuild `solumn_cyber_harm_submission.zip` if submission files changed (`zip -rq solumn_cyber_harm_submission.zip environments results QUALITY_BAR.md README.md -x '*__pycache__*' '*.pyc'`)
2. Update `progress.md`, `feature_list.json`, and `session-handoff.md`
3. Record any unresolved blockers or open scope decisions

## Verification Commands

```bash
./init.sh
```

Individual checks run by `./init.sh`:
- `python3 -B -m compileall -q environments`
- `for d in environments/*/environment/app; do (cd "$d" && python3 -B -m unittest discover -s tests_unit -p 'test_*.py'); done`
- `unzip -t solumn_cyber_harm_submission.zip >/dev/null`
