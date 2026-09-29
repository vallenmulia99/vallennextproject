---
name: code-architect
description: Architectural design patterns and feature planning. Analyzes codebase conventions, module boundaries, data flows, and creates implementation blueprints before coding.
---

# Code Architect & Design Blueprint

Before writing code for any multi-step feature or complex refactor, perform architectural analysis:

## 1. Codebase Pattern & Dependency Analysis
- Scan the existing codebase using `glob` and `grep` to understand conventions, patterns, and folder hierarchy.
- Identify module boundaries, abstraction layers, and established libraries already in use.
- Never introduce new external dependencies if the existing stack already provides suitable tools.

## 2. Architecture Decision & Interface Design
- Make decisive choices commit to a clean, decoupled design.
- Define data models and types first (Pydantic / TypeScript types / Dataclasses).
- Design component contracts, parameters, return types, and clear error boundaries.

## 3. Phased Implementation Sequence
- Phase 1: Core data structures and interfaces.
- Phase 2: Core business logic and service methods.
- Phase 3: API endpoints or UI integration.
- Phase 4: Automated verification and regression testing.
