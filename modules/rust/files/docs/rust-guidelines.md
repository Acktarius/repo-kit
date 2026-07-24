# Rust guidelines

## Defaults

- Format: `rustfmt.toml`
- Workflow: `cargo fmt`, `cargo clippy`, `cargo test`

## After init

This module does not ship a full `Cargo.toml` crate (to avoid fighting an existing project name). Create one if needed:

```bash
cargo init .
```

## Cursor

- Command: `rust-setup`
- Skill: `rust-standards`
