# Invoice Processing System

A comprehensive system for monitoring email inboxes for invoices, validating them against purchase orders, and generating approval reports.

## Overview

This system automates the invoice processing workflow by:

1. Monitoring email inboxes for incoming invoices
2. Extracting invoice details using OCR and text analysis
3. Validating invoices against purchase orders in the database
4. Generating summary reports highlighting discrepancies
5. Sending reports to approvers for review

## Components

The system consists of three main components:

### 1. Email Monitor (`email_monitor.py`)

- Connects to an email server via IMAP
- Monitors for new emails with invoice attachments
- Downloads and processes PDF and image attachments
- Extracts invoice details using OCR and regex patterns
- Integrates with the database manager for validation
- Sends summary reports to approvers

### 2. Database Manager (`database_manager.py`)

- Manages SQLite database for purchase orders and invoices
- Provides methods for adding, retrieving, and validating data
- Validates invoices against purchase orders
- Generates summary reports with discrepancy highlighting
- Tracks approval status of invoices

### 3. Test Script (`test_invoice_system.py`)

- Demonstrates how to use the system
- Provides examples of database operations
- Shows how to validate invoices
- Illustrates report generation

## Setup

### Prerequisites

- Python 3.6+
- Required Python packages:
  - imaplib, email, PyPDF2, pytesseract, PIL, pandas, sqlite3

### Installation

1. Clone this repository
2. Install required packages:
   ```
   pip install python-dotenv PyPDF2 pytesseract pillow pandas
   ```
3. Install Tesseract OCR (required for image text extraction):
   - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki
   - macOS: `brew install tesseract`
   - Linux: `apt-get install tesseract-ocr`

4. Create a credentials environment file at `venv/credentials.env` with:
   ```
   EMAIL_ADDRESS=your_email@example.com
   EMAIL_PASSWORD=your_email_password
   IMAP_SERVER=imap.example.com
   IMAP_PORT=993
   SMTP_SERVER=smtp.example.com
   SMTP_PORT=587
   APPROVER_EMAIL=approver@example.com
   GENERATE_INITIAL_REPORT=false
   ```

## Usage

### Adding Purchase Orders

Before processing invoices, add purchase orders to the database:

```python
from database_manager import DatabaseManager

db = DatabaseManager()
po_data = {
    'po_number': 'PO12345',
    'vendor_name': 'ABC Supplies',
    'issue_date': '2025-03-20',
    'total_amount': 1800.00,
    'items': [
        {'item_name': 'Office Supplies', 'quantity': 10, 'unit_price': 180.00}
    ],
    'status': 'approved'
}
po_id = db.add_purchase_order(po_data)
```

### Starting the Email Monitor

To start monitoring for invoices:

```python
from email_monitor import InvoiceMonitor

# Initialize with environment variables
monitor = InvoiceMonitor()

# Start monitoring
monitor.monitor_mailbox()
```

### Running the Test Script

To test the system without connecting to an email server:

```
python test_invoice_system.py
```

## Workflow

1. Purchase orders are entered into the system
2. The email monitor continuously checks for new emails
3. When an invoice is detected, it's downloaded and processed
4. The system extracts invoice details and validates against purchase orders
5. Discrepancies are highlighted in the validation report
6. Summary reports are sent to approvers periodically
7. Approvers can review and approve/reject invoices

## Customization

- Adjust the invoice detection keywords in `is_potential_invoice()`
- Modify the regex patterns in `extract_invoice_details_from_text()`
- Change the reporting frequency by adjusting the check in `monitor_mailbox()`

## Troubleshooting

- Check the log file (`invoice_monitor.log`) for detailed error messages
- Ensure the email account has proper permissions
- Verify that Tesseract OCR is properly installed for image processing
- Make sure the database file (`invoices.db`) is writable

