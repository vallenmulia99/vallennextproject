---
name: code-simplifier
description: Code elegance, simplicity, and maintainability rules. Reduces unnecessary complexity and over-engineering while strictly preserving functionality.
---

# Code Simplifier & Clean Code Protocol

After writing or modifying code, refine and simplify it according to these standards:

## 1. Preserve Exact Functionality
- Never alter business logic, outputs, or expected behaviors. Only refine *how* it is written.

## 2. Eliminate Over-Engineering
- Eliminate unnecessary nested abstractions, superfluous wrapper classes, and premature optimizations.
- Reduce nesting depth: prefer guard clauses and early returns over deeply nested `if/else` ladders.
- Replace convoluted ternary operators or dense one-liners with readable, explicit code.
- Avoid duplicate logic: apply DRY (Don't Repeat Yourself) pragmatically without creating rigid coupling.

## 3. Clear Naming & Readability
- Use self-documenting function and variable names that describe purpose and units (e.g. `timeout_seconds`, `is_connected`).
- Remove redundant comments that merely restate what the code clearly expresses.
- Keep functions small, single-purpose, and easy to unit test.
