---
name: systematic-debugging
description: Rigorous root-cause analysis and systematic debugging protocol. Use when troubleshooting bugs, runtime crashes, test failures, or unexpected behavior.
---

# Systematic Debugging Protocol

When diagnosing bugs or test failures, never guess, make random edits, or apply surface-level band-aids. Always follow this 5-phase protocol:

## Phase 1: Symptom Identification & Reproduction
1. Read the complete error traceback, exit code, and exact failure line.
2. Identify the immediate point of failure and observe variable states.
3. If possible, reproduce the failure with a minimal reproducible command or test.

## Phase 2: Root-Cause Tracing (Trace Backwards)
1. Do not merely fix the symptom where the crash happened.
2. Trace the data flow backwards: Where did the bad argument, unexpected NoneType, or corrupted state originate?
3. Check upstream callers, configuration values, and assumptions.
4. Verify why the problem occurred in the first place (e.g. edge cases, unhandled falsy values, concurrency, missing parameter).

## Phase 3: Formulate a Concrete Hypothesis
1. Formulate an explicit hypothesis: "The bug happens because X receives Y under condition Z".
2. Confirm the hypothesis by reading the relevant source code.

## Phase 4: Surgical & Minimal Remediation
1. Fix the problem at the root cause rather than patching symptoms.
2. Minimize blast radius: change only the necessary lines and preserve existing function signatures, types, and conventions.
3. Ensure backwards compatibility and handle edge cases (empty strings, None values, missing keys).

## Phase 5: Verification & Regression Check
1. Test the fix immediately using syntax checks, unit tests, or direct execution.
2. Verify that adjacent code or tests were not broken.
