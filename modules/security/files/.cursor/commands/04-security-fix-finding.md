# Security fix finding

Implement a minimal fix for one approved security finding.

1. Locate the requested ID in `security/findings-reviewed.json`.
2. Confirm it is open unless the user explicitly says otherwise.
3. Explain the affected files, patch strategy, and likely side effects.
4. Apply only the changes required to address that root cause.
5. Run focused validation and summarize the evidence.

Do not fix unrelated issues, add dependencies without approval, or update the
findings store automatically.
