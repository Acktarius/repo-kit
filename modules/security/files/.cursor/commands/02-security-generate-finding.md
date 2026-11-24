# Security generate finding

Convert one validated security issue into a proposed finding.

1. Read the issue evidence.
2. Check `security/findings-reviewed.json` and `security/accepted-risks.md`.
3. Classify it as `new`, `duplicate`, `accepted-risk`, or `rejected`.
4. For a new finding, generate an object matching
   `security/findings.schema.json`.
5. When the evidence establishes them, add optional `weaknessClasses` and
   `entrySink`. Omit the class when the mapping is uncertain and say why.
   Do not invent a class. Do not put report-local `S-*` or `F-*` ids in
   the finding object.

Be conservative. Do not invent file paths, exploit paths, or impact. Do not
modify any files or automatically record the proposal. Optional metadata
does not lower the supported-finding threshold.
