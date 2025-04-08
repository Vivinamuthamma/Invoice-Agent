import imaplib
import email
import os
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import time
import json
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
from PyPDF2 import PdfReader
from dotenv import load_dotenv  # Import dotenv to load environment variables
from database_manager import DatabaseManager
import pytesseract
from PIL import Image

# Load environment variables from .env file
load_dotenv(os.path.join("venv\credentials.env"))

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# This helps maintain a history of operations

class InvoiceMonitor:
    def __init__(self, email_address, email_password, 
                 imap_server='imap.gmail.com', 
                 imap_port=993,
                 smtp_server='smtp.gmail.com',
                 smtp_port=587,
                 invoice_download_path='./invoices',
                 log_path='./invoice_monitor.log',
                 approver_email=None):
        
        self.email_address = email_address
        self.email_password = email_password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.invoice_download_path = invoice_download_path
        self.approver_email = approver_email or os.getenv('APPROVER_EMAIL')
        
        # Initialize the database manager with email configuration
        self.db_manager = DatabaseManager()
        
        # Setup logging with rotation and console output
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)  # Set the logging level to DEBUG

        # File handler for logging to a file with rotation
        file_handler = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
        file_handler.setFormatter(file_formatter)

        # Console handler for logging to the terminal
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_formatter)

        # Add both handlers to the logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Create directories
        os.makedirs(invoice_download_path, exist_ok=True)
        
        # Initialize processed emails set
        self.processed_emails = set()  # Track processed emails
        
        # Load previously processed emails if available
        self.load_processed_emails()
        
        # Schedule periodic summary reports
        self.last_summary_report = datetime.now()

    def load_processed_emails(self):

        #Load previously processed email IDs from a file to avoid reprocessing.
        
        try:
            processed_emails_file = os.path.join(os.path.dirname(self.invoice_download_path), 'processed_emails.json')
            if os.path.exists(processed_emails_file):
                with open(processed_emails_file, 'r') as f:
                    self.processed_emails = set(json.load(f))
                self.logger.info(f"Loaded {len(self.processed_emails)} previously processed emails")
        except Exception as e:
            self.logger.error(f"Error loading processed emails: {e}")

    def save_processed_emails(self):
       
        #Save processed email IDs to a file for persistence.
    
        try:
            processed_emails_file = os.path.join(os.path.dirname(self.invoice_download_path), 'processed_emails.json')
            with open(processed_emails_file, 'w') as f:
                json.dump(list(self.processed_emails), f)
            self.logger.info(f"Saved {len(self.processed_emails)} processed emails")
        except Exception as e:
            self.logger.error(f"Error saving processed emails: {e}")

    def connect_to_mailbox(self, retries=3, delay=60):
        """
        Establish secure connection to email server with retries.
        
        Args:
            retries (int): Number of retry attempts.
            delay (int): Delay (in seconds) between retries.
        
        Returns:
            IMAP4_SSL: The IMAP connection object, or None if all attempts fail.
        """
        for attempt in range(1, retries + 1):  # Start attempt count from 1
            try:
                self.logger.info(f"Connecting to IMAP server: {self.imap_server}:{self.imap_port} (Attempt {attempt}/{retries})")
                mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
                mail.login(self.email_address, self.email_password)
                self.logger.info("Successfully connected to mailbox")
                return mail
            except Exception as e:
                self.logger.error(f"Mailbox connection failed (Attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    self.logger.info(f"Retrying connection in {delay} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error("All connection attempts failed. Exiting.")
                    return None

    def is_potential_invoice(self, text):
        """
        Detect if email content suggests an invoice with improved accuracy.
        
        Args:
            text (str): Text content to analyze
            
        Returns:
            bool: True if the text likely contains invoice information
        """
        invoice_keywords = [
            'invoice', 'bill', 'receipt', 'statement', 
            'total amount', 'due date', 'tax invoice',
            'payment due', 'charges', 'order number', 
            'balance due', 'purchase order', 'VAT', 'GST',
            'invoice number', 'invoice date', 'billing date',
            'payment terms', 'subtotal', 'total due', 'amount due',
            'invoice total', 'account number', 'customer id'
        ]
        
        text_lower = text.lower()
        keyword_matches = sum(1 for keyword in invoice_keywords if keyword in text_lower)
        
        # More sophisticated detection logic
        if keyword_matches >= 3:
            return True
        elif keyword_matches >= 2 and any(k in text_lower for k in ['invoice number', 'purchase order', 'total amount']):
            return True
        elif re.search(r'invoice\s*#\s*\w+', text_lower) and re.search(r'total\s*[:$]?\s*\d+', text_lower):
            return True
        
        return False

    def extract_email_body(self, email_message):
        """
        Extract text body from email
        
        Args:
            email_message: Email message object
            
        Returns:
            str: Extracted text from the email body
        """
        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain' or content_type == 'text/html':
                    try:
                        body += part.get_payload(decode=True).decode()
                    except Exception as e:
                        self.logger.error(f"Failed to decode email body: {e}")
        else:
            try:
                body = email_message.get_payload(decode=True).decode()
            except Exception as e:
                self.logger.error(f"Failed to decode email body: {e}")
        return body

    def process_attachments(self, email_message, email_subject=None, email_sender=None):
        """
        Process email attachments for invoices and validate purchase orders.
        
        Args:
            email_message: Email message object
            email_subject (str): Subject of the email
            email_sender (str): Sender of the email
            
        Returns:
            list: List of processed invoice IDs
        """
        processed_invoices = []
        for part in email_message.walk():
            filename = part.get_filename()
            if filename:
                self.logger.info(f"Found attachment: {filename}")
                if filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
                    filepath = self.download_attachment(email_message, filename)
                    if filepath:
                        text = self.extract_text_from_file(filepath)
                        self.logger.debug(f"Extracted text from {filename}: {text}")
                        if self.is_potential_invoice(text):
                            self.logger.info(f"Invoice detected in attachment: {filename}")
                            # Extract invoice details with enhanced extraction
                            invoice_details = self.extract_invoice_details_from_text(text, filepath, email_subject, email_sender)
                            purchase_order = invoice_details.get('purchase_order')
                            if purchase_order:
                                if self.db_manager.validate_purchase_order(purchase_order):
                                    self.logger.info(f"Purchase order {purchase_order} is valid.")
                                else:
                                    self.logger.warning(f"Purchase order {purchase_order} is not found in the database.")
                            
                            # Add invoice to database and get the invoice ID
                            invoice_id = self.db_manager.add_invoice(invoice_details)
                            if invoice_id:
                                processed_invoices.append(invoice_id)
                                self.logger.info(f"Added invoice to database with ID: {invoice_id}")
                                
                                # Log the invoice to CSV file
                                self.log_invoice_to_csv(invoice_details)
                        else:
                            self.logger.info(f"Attachment {filename} is not an invoice.")
        
        return processed_invoices

    def download_attachment(self, msg, filename):
        """
        Download email attachment
        
        Args:
            msg: Email message object
            filename (str): Name of the attachment to download
            
        Returns:
            str: Path to the downloaded file, or None if download failed
        """
        try:
            for part in msg.walk():
                if part.get_filename() == filename:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    save_path = os.path.join(self.invoice_download_path, f"{timestamp}_{filename}")
                    with open(save_path, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                    self.logger.info(f"Downloaded attachment: {save_path}")
                    return save_path
        except Exception as e:
            self.logger.error(f"Attachment download failed: {e}")
        return None

    def extract_text_from_file(self, filepath):
        
        if filepath.endswith('.pdf'):
            # Extract text from PDF
            reader = PdfReader(filepath)
            text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
            
            # If no text is found, use OCR on each page image
            if not text.strip():
                self.logger.info(f"No text found in PDF {filepath}. Using OCR.")
                text = self.extract_text_from_pdf_with_ocr(filepath)
            return text

        elif filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
            # Extract text from image using OCR
            return self.extract_text_from_image(filepath)

        return ''

    def extract_text_from_image(self, image_path):
        
        try:
            text = pytesseract.image_to_string(Image.open(image_path))
            self.logger.debug(f"OCR extracted text: {text}")
            return text
        except Exception as e:
            self.logger.error(f"Failed to extract text from image {image_path}: {e}")
            return ''

    def extract_text_from_pdf_with_ocr(self, pdf_path):
       
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(pdf_path)
            text = ""
            for page in pages:
                text += pytesseract.image_to_string(page)
            self.logger.info(f"Extracted text from PDF {pdf_path} using OCR")
            return text
        except Exception as e:
            self.logger.error(f"Failed to extract text from PDF {pdf_path} using OCR: {e}")
            return ''

    def extract_invoice_details_from_text(self, text, filepath=None, email_subject=None, email_sender=None):
        """
        Extract invoice details from text using regex patterns.
        
        Args:
            text (str): The text content of the invoice.
            filepath (str): Path to the invoice file
            email_subject (str): Subject of the email containing the invoice
            email_sender (str): Sender of the email containing the invoice
        
        Returns:
            dict: A dictionary containing invoice details.
        """
        invoice_details = {
            'invoice_number': None,
            'purchase_order': None,
            'total_amount': None,
            'invoice_date': None,
            'file_path': filepath,
            'vendor_name': None,
            'due_date': None,
            'tax_amount': None,
            'subtotal': None,
            'currency': 'USD',  # Default currency
            'status': 'pending',
            'extracted_from': 'email_attachment'
        }

        # Extract invoice number
        invoice_match = re.search(r'invoice\s*#\s*(\w+)', text, re.IGNORECASE)
        if invoice_match:
            invoice_details['invoice_number'] = invoice_match.group(1)
        else:
            # Try alternative patterns
            alt_invoice_match = re.search(r'invoice\s*(?:no|number|num)[.:\s]*(\w+[-\w]*)', text, re.IGNORECASE)
            if alt_invoice_match:
                invoice_details['invoice_number'] = alt_invoice_match.group(1)

        # Extract purchase order number
        po_match = re.search(r'purchase\s*order\s*#\s*(\w+)', text, re.IGNORECASE)
        if po_match:
            invoice_details['purchase_order'] = po_match.group(1)
        else:
            # Try alternative patterns
            alt_po_match = re.search(r'(?:po|p\.o\.|purchase\s*order)[.:\s#]*(\w+[-\w]*)', text, re.IGNORECASE)
            if alt_po_match:
                invoice_details['purchase_order'] = alt_po_match.group(1)

        # Extract total amount
        amount_match = re.search(r'total\s*amount\s*[:$]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', text, re.IGNORECASE)
        if amount_match:
            invoice_details['total_amount'] = float(amount_match.group(1).replace(',', ''))
        else:
            # Try alternative patterns
            alt_amount_match = re.search(r'(?:total|amount\s*due|balance\s*due|grand\s*total)[.:\s]*[$€£]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', text, re.IGNORECASE)
            if alt_amount_match:
                invoice_details['total_amount'] = float(alt_amount_match.group(1).replace(',', ''))

        # Extract invoice date
        date_match = re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', text)
        if date_match:
            invoice_details['invoice_date'] = date_match.group(0)
        else:
            # Try alternative date formats
            alt_date_match = re.search(r'(?:invoice|bill|statement)\s*date[.:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})', text, re.IGNORECASE)
            if alt_date_match:
                invoice_details['invoice_date'] = alt_date_match.group(1)
        
        # Extract vendor name
        vendor_match = re.search(r'(?:vendor|supplier|from|bill\s*from|sold\s*by)[.:\s]*([A-Za-z0-9\s.,&]+?)(?:\n|Inc\.|\bLLC\b|\bLtd\b|\bCorp\.?\b)', text, re.IGNORECASE)
        if vendor_match:
            invoice_details['vendor_name'] = vendor_match.group(1).strip()
        elif email_sender:
            # Try to extract vendor from email sender
            sender_match = re.search(r'([^<@]+)@', email_sender)
            if sender_match:
                invoice_details['vendor_name'] = sender_match.group(1).replace('.', ' ').title()
        
        # Extract due date
        due_date_match = re.search(r'(?:due|payment\s*due|due\s*date)[.:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})', text, re.IGNORECASE)
        if due_date_match:
            invoice_details['due_date'] = due_date_match.group(1)
        
        # Extract tax amount
        tax_match = re.search(r'(?:tax|vat|gst)[.:\s]*[$€£]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', text, re.IGNORECASE)
        if tax_match:
            invoice_details['tax_amount'] = float(tax_match.group(1).replace(',', ''))
        
        # Extract subtotal
        subtotal_match = re.search(r'(?:subtotal|sub\s*total)[.:\s]*[$€£]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', text, re.IGNORECASE)
        if subtotal_match:
            invoice_details['subtotal'] = float(subtotal_match.group(1).replace(',', ''))
        
        # Extract currency
        currency_match = re.search(r'(?:currency|in)[.:\s]*(USD|EUR|GBP|JPY|CAD|AUD|CHF)', text, re.IGNORECASE)
        if currency_match:
            invoice_details['currency'] = currency_match.group(1).upper()
        elif re.search(r'[$]', text):
            invoice_details['currency'] = 'USD'
        elif re.search(r'[€]', text):
            invoice_details['currency'] = 'EUR'
        elif re.search(r'[£]', text):
            invoice_details['currency'] = 'GBP'

        return invoice_details

    def log_invoice_to_csv(self, invoice_details):
       
        try:
            import csv
            csv_file = './invoice_log.csv'
            file_exists = os.path.isfile(csv_file)
            
            with open(csv_file, 'a', newline='') as f:
                fieldnames = ['filepath', 'filename', 'detected_at', 'invoice_number', 'total_amount', 'date']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow({
                    'filepath': invoice_details.get('file_path', ''),
                    'filename': os.path.basename(invoice_details.get('file_path', '')),
                    'detected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'invoice_number': invoice_details.get('invoice_number', 'N/A'),
                    'total_amount': invoice_details.get('total_amount', 'N/A'),
                    'date': invoice_details.get('invoice_date', 'N/A')
                })
            
            self.logger.info(f"Invoice logged to CSV: {invoice_details.get('file_path')}")
        except Exception as e:
            self.logger.error(f"Invoice CSV logging failed: {e}")

    def monitor_mailbox(self, check_interval=60):
        
        while True:
            mail = self.connect_to_mailbox()
            if not mail:
                self.logger.error("Unable to connect to mailbox. Retrying in 60 seconds...")
                time.sleep(60)
                continue

            try:
                # Select the Inbox folder
                status, _ = mail.select("INBOX")
                if status != 'OK':
                    self.logger.error("Failed to select Inbox folder.")
                    mail.logout()
                    time.sleep(check_interval)
                    continue

                # Search for unread emails
                status, messages = mail.search(None, 'UNSEEN')
                if status != 'OK':
                    self.logger.error("Failed to search for unread emails.")
                    mail.logout()
                    time.sleep(check_interval)
                    continue

                if not messages[0]:
                    self.logger.info("No new emails found.")
                    
                    # Check if it's time to generate a summary report
                    if (datetime.now() - self.last_summary_report).total_seconds() > 86400:  # 24 hours
                        self.generate_and_send_summary_report()
                        self.last_summary_report = datetime.now()
                    
                    mail.logout()
                    time.sleep(check_interval)
                    continue

                # Process each unread email
                for num in messages[0].split():
                    status, msg_data = mail.fetch(num, '(RFC822)')
                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)

                    # Process the email
                    self.process_email(email_message)

                mail.logout()
                
                # Save processed emails list after each batch
                self.save_processed_emails()

            except Exception as e:
                self.logger.error(f"Error while monitoring mailbox: {e}")

            self.logger.info("Waiting for the next check interval...")
            time.sleep(check_interval)

    def process_email(self, email_message):
        """
        Process an email to extract and log invoice details.
        """
        message_id = email_message.get("Message-ID", "")
        if message_id in self.processed_emails:
            self.logger.info(f"Email with Message ID {message_id} already processed. Skipping.")
            return []
        
        self.processed_emails.add(message_id)
        
        # Decode email subject and sender
        email_subject = decode_email_header(email_message.get('subject', ''))
        email_sender = decode_email_header(email_message.get('from', ''))
        
        self.logger.debug(f"Email subject: {email_subject}")
        self.logger.debug(f"Email sender: {email_sender}")
        
        processed_invoices = []
        
        # Extract email body
        body_text = self.extract_email_body(email_message)
        if self.is_potential_invoice(body_text):
            self.logger.info(f"Potential invoice email detected: {email_subject}")
            processed_invoices = self.process_attachments(email_message, email_subject, email_sender)
        else:
            self.logger.info(f"No invoice detected in email: {email_subject}")
            
        return processed_invoices

    def generate_and_send_summary_report(self, days=1):
     
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Generate report using database manager
            report_df = self.db_manager.generate_summary_report(
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d')
            )
            
            if report_df.empty:
                self.logger.info("No invoice data for summary report")
                return False
            
            # Export to CSV
            report_path = os.path.join(os.path.dirname(self.invoice_download_path), 'invoice_summary_report.csv')
            report_df.to_csv(report_path, index=False)
            
            # Get pending approvals
            pending_approvals = self.db_manager.get_pending_approvals()
            
            # Create email content
            subject = f"Invoice Processing Summary Report - {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            
            body = f"""
            Invoice Processing Summary Report
            ================================
            Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}
            
            Summary:
            - Total Invoices Processed: {len(report_df)}
            - Invoices Requiring Approval: {len(pending_approvals)}
            - Validated Invoices: {len(report_df[report_df['status'] == 'validated'])}
            - Approved Invoices: {len(report_df[report_df['status'] == 'approved'])}
            - Rejected Invoices: {len(report_df[report_df['status'] == 'rejected'])}
            - Pending Invoices: {len(report_df[report_df['status'] == 'pending'])}
            
            Pending Approvals:
            {self._format_pending_approvals(pending_approvals)}
            
            Please review the attached CSV file for detailed information.
            """
            
            # Send email with attachment
            if self.approver_email:
                self.send_email(
                    recipient=self.approver_email,
                    subject=subject,
                    body=body,
                    attachments=[report_path]
                )
                self.logger.info(f"Summary report sent to {self.approver_email}")
                return True
            else:
                self.logger.warning("No approver email configured. Cannot send summary report.")
                return False
                
        except Exception as e:
            self.logger.error(f"Error generating and sending summary report: {e}")
            return False
    
    def _format_pending_approvals(self, pending_approvals):
        
        if not pending_approvals:
            return "None"
        
        formatted = []
        for approval in pending_approvals:
            formatted.append(f"- Invoice #{approval['invoice_number']} from {approval['vendor_name']} for PO #{approval['po_number']} (Amount: ${approval['total_amount']})")
        
        return "\n".join(formatted)
    
    def send_email(self, recipient, subject, body, attachments=None):
       
        if not self.email_address or not self.email_password:
            self.logger.warning("Email configuration incomplete. Cannot send email.")
            return False
        
        try:
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = recipient
            msg['Subject'] = subject
            
            # Email body
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach files if provided
            if attachments:
                for attachment_path in attachments:
                    if os.path.exists(attachment_path):
                        with open(attachment_path, 'rb') as file:
                            attachment = MIMEApplication(file.read(), Name=os.path.basename(attachment_path))
                            attachment['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
                            msg.attach(attachment)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)
                server.send_message(msg)
            
            self.logger.info(f"Email sent to {recipient}")
            return True
        except Exception as e:
            self.logger.error(f"Error sending email: {e}")
            return False

def decode_email_header(header):
   
    decoded_parts = decode_header(header)
    decoded_header = ""
    for part, encoding in decoded_parts:
        try:
            if isinstance(part, bytes):
                decoded_header += part.decode(encoding or "utf-8", errors="ignore")
            else:
                decoded_header += part
        except Exception as e:
            print(f"Error decoding header part: {e}. Falling back to UTF-8.")
            decoded_header += part.decode("utf-8", errors="ignore") if isinstance(part, bytes) else part
    return decoded_header

def main():
    # Load credentials from environment variables
    email_address = os.getenv('EMAIL_ADDRESS')
    email_password = os.getenv('EMAIL_PASSWORD')
    imap_server = os.getenv('IMAP_SERVER', 'imap.gmail.com')
    imap_port = int(os.getenv('IMAP_PORT', 993))
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    approver_email = os.getenv('APPROVER_EMAIL')

    # Initialize Invoice Monitor
    monitor = InvoiceMonitor(
        email_address=email_address,
        email_password=email_password,
        imap_server=imap_server,
        imap_port=imap_port,
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        approver_email=approver_email
    )
  
   # Generate an initial summary report if needed
    if os.getenv('GENERATE_INITIAL_REPORT', 'false').lower() == 'true':
        monitor.generate_and_send_summary_report(days=7)  # Last 7 days

    # Start monitoring mailbox
    try:
        monitor.monitor_mailbox()
    except KeyboardInterrupt:
        monitor.logger.info("Monitoring stopped by user")
        monitor.save_processed_emails()

if __name__ == '__main__':
    main()