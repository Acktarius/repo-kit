#!/usr/bin/env bash
MODULE_NAME="contre-attaque"
MODULE_DESC="Recent CVE/advisory applicability review with persistent state and agent handoff"
MODULE_DEPENDS=("base" "security")
MODULE_CONFLICTS=()
MODULE_PRESERVE=(".repo-kit/contre-attaque/.gitignore")
