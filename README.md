# FinControl — Personal Finance Control Centre

A private, self-hosted Flask + SQLite finance ledger. It supports manual transaction entry, multiple bank accounts, paired own-account transfers, rental properties, manual investment holdings, CSV import/export, basic reporting and database backup.

## Important scope and limitations

This is a usable **local-first starter application**, not a certified accounting product or bank-connected application. It does not connect to banks, brokers, AMCs, stock exchanges or market-data vendors. Investment prices and values are entered manually. It currently uses a single-user local login model; do not expose it directly to the public internet.

The first release intentionally prioritizes a transparent cash ledger. It does not yet implement XIRR, tax calculations, receipt upload, PDF/Excel report generation, recurring-entry scheduler, multi-user roles, advanced reconciliation workflow, or automated market data. Recurring transactions are represented in the schema for the next development stage, but the pending-entry generator is not yet exposed in this release.

## Requirements

- Python 3.10+
- Windows, macOS or Linux

## Installation

### Windows
1. Extract the ZIP.
2. Open the extracted folder.
3. Double-click `run.bat` or run it from Command Prompt.
4. Open `http://127.0.0.1:5000`.
5. Create your first account.

### macOS / Linux
```bash
chmod +x run.sh
./run.sh
```
Then open `http://127.0.0.1:5000`.

Manual alternative:
```bash
python -m venv .venv
# activate the environment
pip install -r requirements.txt
python app.py
```

The SQLite database `finance.db` is created automatically on first launch.

## First-time setup

1. Create your login using a unique username and a password of at least 12 characters.
2. Add each bank account under **Accounts**. Enter the actual balance as of a clearly chosen opening date. This release treats the opening balance as the starting ledger value; keep a note of the date.
3. Add properties under **Properties**.
4. Record income and expenses under **Transactions**.
5. Use **Transfer** for movements between your own accounts. Do not enter an own-account transfer as income or expense.
6. Add holdings under **Investments** and update current values when you review your statements.

## CSV import format

Required headers:
```csv
date,type,amount,description,category
2026-11-01,income,85000,Monthly salary,Salary
2026-11-02,expense,1450,Groceries,Household
```
Only `income` and `expense` are accepted. Imports are assigned to the first configured bank account and use a fingerprint for basic duplicate detection. Review every imported row and correct account assignments as needed. Bank statement exports vary; normalize them before import.

## Financial calculations

- Bank balance = opening balance + posted income + posted transfer-in + posted investment-sale cash − posted expenses − posted transfer-out − posted investment-purchase cash.
- Net cash savings = income − operating expenses. Transfers and investment allocations are excluded.
- Savings percentage = net cash savings / income × 100; displayed as zero when income is zero.
- Investment gain/loss = manually entered current value − invested amount. This is a simple absolute difference, not XIRR or a tax-adjusted return.
- Net worth is not yet calculated because liabilities and non-investment assets are not fully modelled.

Pending transactions do not affect balances or reports.

## Backup and recovery

- Sign in and open `/backup` to download a SQLite backup.
- Keep backups encrypted and in a separate secure location.
- To restore, stop the application, preserve the current `finance.db`, then replace it with the backup file.
- Start the application and verify account balances and transaction history.
- Test restore on a copy before relying on a backup.

## Security

- Passwords are stored as salted Werkzeug password hashes, never plaintext.
- Session cookies are HttpOnly and SameSite=Lax. Secure-cookie mode can be enabled behind HTTPS using `COOKIE_SECURE=1`.
- POST forms use session CSRF tokens.
- A 30-minute session lifetime is configured.
- Do not store bank passwords, PINs, CVVs, OTPs or full account numbers.
- Keep the application bound to `127.0.0.1` for local use.
- Before private-server deployment: set a strong random `SECRET_KEY`, enable HTTPS and `COOKIE_SECURE=1`, use a production WSGI server, firewall the host, encrypt disk/backups, patch dependencies, and arrange tested off-site backups. Do not use Flask's development server in production.

## Architecture

- `app.py`: routes, validation, calculations, schema initialization and ledger operations.
- `templates/`: responsive pages.
- `static/style.css`: interface styling.
- `finance.db`: local SQLite database, created at runtime.
- `tests/`: starter validation tests.

## Known gaps / next increments

1. Add immutable ledger events and robust reversal entries instead of hard deletion.
2. Add atomic paired-transfer editing/deletion and account reconciliation workflow.
3. Add full transaction edit validation and audit history viewer.
4. Add pending recurring-entry generation and confirmation.
5. Add investment transaction lots, realized gain/loss, dividends, XIRR and portfolio snapshots.
6. Add liabilities, assets and net-worth statement.
7. Add robust bank CSV column mapping, preview, account selection and duplicate review.
8. Add receipt attachments with strict file validation and encrypted storage.
9. Add Excel/PDF exports, quarterly/yearly reports and charts.
10. Add production deployment with PostgreSQL, migrations, rate limiting, MFA and automated encrypted backups.

## Disclaimer

This software is for personal record keeping and educational use. Verify all records against official bank and investment statements. It is not investment, tax, legal or regulated financial advice.
