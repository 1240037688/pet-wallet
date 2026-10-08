# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Security Architecture & Principles

1. **Local-First & Loopback Only**:
   All sensitive endpoints, accounting databases, and credentials are kept strictly local to your machine. The internal FastAPI endpoints strictly verify loopback requests (`127.0.0.1` / `::1`).
2. **Credential Sanitization**:
   API keys and tokens are never returned in cleartext to the UI, never stored in client-side state, and automatically redacted from application logs.
3. **No External Code Execution**:
   Desktop UI plugins run within the standard Hermes Desktop sandbox without dynamic external asset injection or unpinned CDN loading.

## Reporting a Vulnerability

If you discover a security vulnerability within Pet Wallet, please report it privately:
- Do not open a public issue.
- Please draft a report with reproduction steps and submit through GitHub Security Advisories or contact the maintainer directly.
