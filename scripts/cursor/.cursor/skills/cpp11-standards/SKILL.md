---
name: cpp11-standards
description: Apply C++11 style, CMake, and clang-format conventions for this repo.
---

# C++11 standards

Use this skill when editing C++ sources, headers, or build files in this repo.

## Language

- Target **C++11** (`-std=c++11`). Do not use C++14/17/20 features unless the project upgrades.
- Prefer RAII, `unique_ptr`/`shared_ptr` where ownership is needed, and range-friendly algorithms available in C++11.
- Avoid raw owning `new`/`delete` in application code.

## Style

- Follow `.clang-format`.
- Keep headers self-contained; prefer include guards or `#pragma once` consistently with existing files.
- Prefer clear names over abbreviations.

## Build

- Use the top-level `CMakeLists.txt` patterns (warnings enabled, C++11 standard set).
- Keep platform-specific flags isolated and documented.
