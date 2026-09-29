---
name: security-guidance
description: Security guidelines and vulnerability prevention (preventing command injection, XSS, unsafe deserialization, SQL injection, and secret leaks).
---

# Security Guidance & Guardrails

When generating, modifying, or reviewing code, always follow these critical security rules:

## 1. Injection Prevention
- **Command Injection**: Never pass unsanitized user input into `os.system()`, `subprocess.Popen(..., shell=True)`, or bash strings. Always use `subprocess.run(["cmd", arg1, arg2], shell=False)` with argument lists.
- **SQL Injection**: Never format or concatenate SQL strings (`f"SELECT * FROM users WHERE id = '{user_id}'"`). Always use parameterized queries (`cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))`) or an ORM.
- **XSS (Cross-Site Scripting)**: In frontend HTML/JS, never use `.innerHTML = userInput` or React `dangerouslySetInnerHTML` with untrusted data. Use `.textContent` or framework escaping.

## 2. Safe Deserialization
- **Python Pickle**: Avoid `pickle.load()` on untrusted data. Use `json`, `pydantic`, or `msgspec`.
- **YAML**: Always use `yaml.safe_load(content)` instead of `yaml.load()`.
- **PyTorch**: Pass `weights_only=True` when calling `torch.load()`.

## 3. Secret & Credential Safety
- Never hardcode API keys, tokens, or passwords into source files.
- Always read credentials from environment variables (`os.environ.get("...")`) or `.env` files.
- Never commit `.env` or credentials files into git repositories.

## 4. Input Validation & Boundaries
- Validate all incoming API request data against explicit schemas (Pydantic models in Python, Zod schemas in TypeScript).
- Never trust client-supplied file paths without validating that the resolved path stays within the intended directory boundary.
