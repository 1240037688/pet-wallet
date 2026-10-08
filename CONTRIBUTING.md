# Contributing to Pet Wallet

Thank you for your interest in contributing to Pet Wallet!

## Development Setup

1. **Prerequisites**:
   - Python 3.12+
   - Node.js 20+
   - Hermes Agent Desktop 0.21.0+

2. **Installation**:
   ```bash
   git clone https://github.com/<your-username>/pet-wallet.git
   cd pet-wallet
   python -m venv .venv
   source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt
   npm install
   ```

3. **Running Tests**:
   ```bash
   # Python tests
   pytest plugin-src/pet-wallet/dashboard/tests -v

   # Desktop JS tests
   npm test
   ```

4. **Building Desktop Artifact**:
   ```bash
   node tools/build-desktop.mjs
   ```

5. **Security Scanning**:
   ```bash
   python tools/check-security.py
   node tools/check-security.mjs
   ```

## Pull Request Guidelines

- Ensure all existing unit tests pass.
- Write tests for new providers or features.
- Never commit credentials, private API keys, or machine-specific paths.
- Keep commits focused and provide clear descriptions.
