---
name: rust-standards
description: Apply Rust style, Cargo, rustfmt, and clippy conventions for this repo.
---

# Rust standards

Use this skill when editing Rust sources, `Cargo.toml`, or build/test scripts.

## Tooling

- Format with **rustfmt** (`rustfmt.toml`).
- Prefer `cargo clippy` with warnings treated seriously.
- Prefer `cargo test` for verification.

## Style

- Idiomatic ownership and borrowing; avoid unnecessary `.clone()`.
- Prefer `Result`/`Option` over panics in library code.
- Keep modules small and cohesive; use `mod` layout consistent with the crate.

## Cargo

- After init, create or adjust the crate with `cargo init` / `cargo new` as needed.
- Pin dependency policy to match the team's Cargo practices; do not commit registry tokens.
