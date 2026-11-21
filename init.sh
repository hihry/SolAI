#!/bin/bash
set -e
export PYTHONDONTWRITEBYTECODE=1
_PYCACHE_TMP="$(mktemp -d)"
export PYTHONPYCACHEPREFIX="$_PYCACHE_TMP"
trap 'rm -rf "$_PYCACHE_TMP"' EXIT

echo "=== Harness Initialization ==="

echo "=== Static Python Syntax Check ==="
python3 -B -m compileall -q environments

echo "=== Environment Baseline Unit Tests ==="
for d in environments/*/environment/app; do
  echo "  -> testing $d"
  (cd "$d" && python3 -B -m unittest discover -s tests_unit -p 'test_*.py' -q)
done

echo "=== Submission Archive Integrity & Exclusion Check ==="
unzip -t solumn_cyber_harm_submission.zip >/dev/null
if unzip -l solumn_cyber_harm_submission.zip | grep -Eq '(AGENTS\.md|feature_list\.json|progress\.md|session-handoff\.md|init\.sh|\.env)'; then
  echo "ERROR: Harness or .env file found inside solumn_cyber_harm_submission.zip" >&2
  exit 1
fi

echo "=== Verification Complete ==="
echo ""
echo "Next steps:"
echo "1. Read feature_list.json to see current feature state"
echo "2. Pick ONE unfinished feature to work on"
echo "3. Implement only that feature"
echo "4. Re-run ./init.sh before claiming done"
