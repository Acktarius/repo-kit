# Threat model

Complete this file for the target repository before treating a security review
as comprehensive.

## System purpose

Describe what the system does and where it is deployed.

## Sensitive assets

- Credentials, tokens, keys, and secrets
- Personal, financial, or operational data
- Privileged processes and administrative controls

## Entry points

- Public and internal network interfaces
- Files, messages, jobs, webhooks, and user input
- Build, deployment, and dependency update paths

## Trust boundaries

- Untrusted clients → application
- Application → data stores and privileged services
- Repository and CI → build artifacts and deployment
- Application → third-party services

## Primary security concerns

List repository-specific risks supported by the architecture. Do not use this
section as a generic finding list.

## Assumptions and unknowns

Record deployment assumptions and facts that still require validation.
