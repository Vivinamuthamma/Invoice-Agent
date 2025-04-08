#!/usr/bin/env python3
"""
Approver Interface for the Invoice Processing System

This script provides a simple command-line interface for approvers to:
1. View pending approvals
2. Approve or reject invoices
3. View and export summary reports
4. Send summary reports to stakeholders

Usage:
    python approver_interface.py

Commands:
    list        - List pending approvals
    view <id>   - View details of a specific invoice
    approve <id> [comments] - Approve an invoice with optional comments
    reject <id> [comments]  - Reject an invoice with optional comments
    report      - Generate and view a summary report
    export      - Export the summary report to CSV
    send        - Send the summary report to stakeholders
    help        - Show this help message
    exit        - Exit the program
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from database_manager import DatabaseManager
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv

# Load environment variables from credentials.env file
env_path = os.path.join('venv', 'credentials.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"Loaded environment variables from {env_path}")
else:
    print(f"Warning: {env_path} not found. Email functionality may not work properly.")

class ApproverInterface:
    def __init__(self):
        """Initialize the approver interface"""
        self.db_manager = DatabaseManager()
        self.commands = {
            'list': self.list_pending_approvals,
            'view': self.view_invoice_details,
            'approve': self.approve_invoice,
            'reject': self.reject_invoice,
            'report': self.generate_report,
            'export': self.export_report,
            'send': self.send_report,
            'help': self.show_help,
            'exit': self.exit_program
        }
        
        # Store the last generated report
        self.last_report = None
        self.report_start_date = None
        self.report_end_date = None
    
    def run(self):
        """Run the approver interface"""
        print("=== Invoice Approver Interface ===")
        print("Type 'help' for a list of commands")
        
        while True:
            try:
                command = input("\nEnter command: ").strip()
                
                if not command:
                    continue
                
                parts = command.split()
                cmd = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                
                if cmd in self.commands:
                    self.commands[cmd](*args)
                else:
                    print(f"Unknown command: {cmd}")
                    print("Type 'help' for a list of commands")
            
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
    
    def list_pending_approvals(self):
        """List all pending approvals"""
        pending_approvals = self.db_manager.get_pending_approvals()
        
        if not pending_approvals:
            print("No pending approvals found.")
            return
        
        print("\nPending Approvals:")
        print(f"{'ID':<5} {'Invoice':<15} {'PO Number':<15} {'Vendor':<20} {'Amount':<10}")
        print("-" * 70)
        
        for approval in pending_approvals:
            print(f"{approval['report_id']:<5} {approval['invoice_number']:<15} {approval['po_number']:<15} {approval['vendor_name']:<20} ${approval['total_amount']:<10}")
    
    def view_invoice_details(self, report_id=None):
        """View details of a specific invoice"""
        if not report_id:
            print("Please provide a report ID")
            return
        
        try:
            report_id = int(report_id)
        except ValueError:
            print("Report ID must be a number")
            return
        
        # Get the validation report
        conn = self.db_manager._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT 
            vr.id, vr.report_content, vr.approval_status,
            i.invoice_number, i.po_number, i.vendor_name, i.total_amount, i.file_path
        FROM 
            validation_reports vr
        JOIN 
            invoices i ON vr.invoice_id = i.id
        WHERE 
            vr.id = ?
        ''', (report_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            print(f"Report with ID {report_id} not found")
            return
        
        report_id, report_content, approval_status, invoice_number, po_number, vendor_name, total_amount, file_path = row
        
        print("\nInvoice Details:")
        print(f"Report ID: {report_id}")
        print(f"Invoice Number: {invoice_number}")
        print(f"PO Number: {po_number}")
        print(f"Vendor: {vendor_name}")
        print(f"Amount: ${total_amount}")
        print(f"Status: {approval_status}")
        print(f"File: {file_path}")
        print("\nValidation Report:")
        print(report_content)
    
    def approve_invoice(self, report_id=None, *comments):
        """Approve an invoice"""
        if not report_id:
            print("Please provide a report ID")
            return
        
        try:
            report_id = int(report_id)
        except ValueError:
            print("Report ID must be a number")
            return
        
        comments_text = " ".join(comments) if comments else "Approved without comments"
        
        success = self.db_manager.update_approval_status(report_id, 'approved', comments_text)
        
        if success:
            print(f"Invoice with report ID {report_id} has been approved")
        else:
            print(f"Failed to approve invoice with report ID {report_id}")
    
    def reject_invoice(self, report_id=None, *comments):
        """Reject an invoice"""
        if not report_id:
            print("Please provide a report ID")
            return
        
        try:
            report_id = int(report_id)
        except ValueError:
            print("Report ID must be a number")
            return
        
        comments_text = " ".join(comments) if comments else "Rejected without comments"
        
        success = self.db_manager.update_approval_status(report_id, 'rejected', comments_text)
        
        if success:
            print(f"Invoice with report ID {report_id} has been rejected")
        else:
            print(f"Failed to reject invoice with report ID {report_id}")
    
    def generate_report(self, days=30):
        """Generate a summary report"""
        try:
            days = int(days)
        except ValueError:
            print("Days must be a number")
            return
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        self.report_start_date = start_date.strftime('%Y-%m-%d')
        self.report_end_date = end_date.strftime('%Y-%m-%d')
        
        print(f"\nGenerating summary report for {self.report_start_date} to {self.report_end_date}...")
        
        self.last_report = self.db_manager.generate_summary_report(
            start_date=self.report_start_date,
            end_date=self.report_end_date
        )
        
        if self.last_report.empty:
            print("No data available for the specified date range")
            return
        
        print("\nSummary Report:")
        print(self.last_report)
        
        # Print statistics
        total_invoices = len(self.last_report)
        validated = len(self.last_report[self.last_report['status'] == 'validated'])
        approved = len(self.last_report[self.last_report['status'] == 'approved'])
        rejected = len(self.last_report[self.last_report['status'] == 'rejected'])
        pending = len(self.last_report[self.last_report['status'] == 'pending'])
        
        print("\nStatistics:")
        print(f"Total Invoices: {total_invoices}")
        print(f"Validated: {validated} ({validated/total_invoices*100:.1f}%)")
        print(f"Approved: {approved} ({approved/total_invoices*100:.1f}%)")
        print(f"Rejected: {rejected} ({rejected/total_invoices*100:.1f}%)")
        print(f"Pending: {pending} ({pending/total_invoices*100:.1f}%)")
    
    def export_report(self, output_path=None):
        """Export the summary report to CSV"""
        if self.last_report is None:
            print("No report generated yet. Use 'report' command first.")
            return
        
        if not output_path:
            output_path = f"invoice_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        success = self.db_manager.export_summary_report(
            output_path=output_path,
            start_date=self.report_start_date,
            end_date=self.report_end_date
        )
        
        if success:
            print(f"Summary report exported to {output_path}")
        else:
            print("Failed to export summary report")
    
    def send_report(self):
        """Send the summary report to stakeholders"""
        if self.last_report is None:
            print("No report generated yet. Use 'report' command first.")
            return

        # Get approver email from environment variables directly
        approver_email = os.getenv("APPROVER_EMAIL")
        if not approver_email:
            print("No approver email configured in environment variables.")
            print("Please check your credentials.env file and ensure APPROVER_EMAIL is set.")
            return

        # Generate a temporary CSV file for the report
        report_file = f"invoice_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.last_report.to_csv(report_file, index=False)

        # Email configuration - get directly from environment variables
        sender_email = os.getenv("EMAIL_ADDRESS")
        sender_password = os.getenv("EMAIL_PASSWORD")
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        
        # Print configuration for debugging (without password)
        print(f"Using email configuration:")
        print(f"  From: {sender_email}")
        print(f"  To: {approver_email}")
        print(f"  SMTP Server: {smtp_server}:{smtp_port}")

        # Create the email
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = approver_email
        msg["Subject"] = "Invoice Summary Report"

        # Email body
        body = f"""
        Dear Approver,

        Please find attached the summary report for invoices from {self.report_start_date} to {self.report_end_date}.

        Best regards,
        Invoice Processing System
        """
        msg.attach(MIMEText(body, "plain"))

        # Attach the CSV file
        with open(report_file, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={report_file}",
            )
            msg.attach(part)

        # Send the email
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
            print(f"Summary report sent to {approver_email}")
        except Exception as e:
            print(f"Failed to send summary report: {e}")
        finally:
            # Clean up the temporary file
            if os.path.exists(report_file):
                os.remove(report_file)
    
    def set_approver_email(self, email):
        """
        Set the approver's email address.
        
        Args:
            email (str): The approver's email address.
        
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            if not email or "@" not in email:
                self.logger.error("Invalid email address provided.")
                return False
            
            self.approver_email = email
            self.logger.info(f"Approver email updated to: {email}")
            return True
        except Exception as e:
            self.logger.error(f"Error setting approver email: {e}")
            return False
    
    def update_approver_email(self):
        """Update the approver's email address"""
        db_manager = DatabaseManager()
        success = db_manager.set_approver_email("new_approver_email@example.com")
        if success:
            print("Approver email updated successfully.")
        else:
            print("Failed to update approver email.")
    
    def show_help(self):
        """Show help message"""
        print("\nAvailable commands:")
        print("  list                    - List pending approvals")
        print("  view <id>               - View details of a specific invoice")
        print("  approve <id> [comments] - Approve an invoice with optional comments")
        print("  reject <id> [comments]  - Reject an invoice with optional comments")
        print("  report [days]           - Generate and view a summary report (default: last 30 days)")
        print("  export [path]           - Export the summary report to CSV")
        print("  send                    - Send the summary report to stakeholders")
        print("  help                    - Show this help message")
        print("  exit                    - Exit the program")
    
    def exit_program(self):
        """Exit the program"""
        print("Exiting...")
        sys.exit(0)

def main():
    """Main function"""
    interface = ApproverInterface()
    interface.run()

if __name__ == "__main__":
    main()