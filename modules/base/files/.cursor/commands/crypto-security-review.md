# crypto-security-review

Perform a security-focused review of the provided code, diff, or selected files.

Read `.cursor/skills/crypto-security-review/SKILL.md` and follow it.

## Instructions

Review in this exact order:

1. Entry points and trust boundaries.
2. Authentication, authorization, and secrets handling.
3. Input validation, parsing, serialization, deserialization, and injection risks.
4. Cryptographic correctness and misuse.
5. Integrity, replay, race conditions, state transitions, and error handling.
6. Dependency, configuration, and environment assumptions.

Assume the main risk is misuse, unsafe composition, or broken assumptions rather than failure of standard primitives.

Flag especially:

- custom cryptography or protocol deviations.
- nonce or IV reuse risk.
- weak or unverifiable randomness.
- broken key derivation or key separation.
- missing authentication before decryption where relevant.
- missing signature verification, wrong object being signed, or partial verification.
- ambiguous serialization or canonicalization issues.
- replay, downgrade, or cross-context message reuse.
- secret leakage through logs, errors, debug paths, persistence, or client exposure.
- timing-sensitive equality checks or side-channel sensitive branches.
- unsafe fallback behavior after verification or decryption failure.

## Required output format

Output Markdown only. Sort findings by risk: Critical → High → Medium → Low
(higher confidence first within the same severity).

For each finding, use exactly this structure:

```markdown
### [Severity] Short title

- **Severity:** Critical | High | Medium | Low
- **Confidence:** High | Medium | Low
- **Location:** file + function + line or nearest code block
- **Issue:** one-sentence description
- **Why it matters:** concrete exploit path or failure mode
- **Evidence:** exact observed code behavior
- **Suggested solution:** smallest safe remediation
- **Residual risk:** what still needs manual verification
```

Then output these sections only:

## Confirmed findings

(findings sorted by risk, each in the Markdown format above)

## Crypto-specific concerns

## Things requiring human validation

## Minimal remediation plan

(ordered checklist of suggested solutions, highest risk first)

If no confirmed vulnerability is found, say exactly:

No confirmed vulnerability found in the reviewed scope.

Then still provide:

- likely weak spots
- assumptions that must be validated manually
- tests or abuse cases to run next
