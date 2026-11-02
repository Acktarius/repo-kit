#!/usr/bin/env bash
MODULE_NAME="security"
MODULE_DESC="Repo-aware security planning, review, findings, triage, remediation, and CI"
MODULE_DEPENDS=("base")
MODULE_CONFLICTS=()
MODULE_PRESERVE=(
  "security/findings-reviewed.json"
  "security/accepted-risks.md"
  "security/threat-model.md"
)
