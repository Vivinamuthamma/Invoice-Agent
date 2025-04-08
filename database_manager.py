import sqlite3
import os
import logging
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Debug print statement commented out
# print(os.path.exists('invoices.db'))  # Should return True if the file exists

class DatabaseManager:
    def __init__(self, db_path='invoices.db'):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.setup_database()

        # Email configuration
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', 587))
        self.email_address = os.getenv('EMAIL_ADDRESS')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.approver_email = os.getenv('APPROVER_EMAIL')

    def setup_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create purchase_orders table with UNIQUE constraint on po_number
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT UNIQUE,
                vendor_name TEXT,
                issue_date TEXT,
                total_amount REAL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # Create invoices table with UNIQUE constraint
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE,
                po_number TEXT,
                vendor_name TEXT,
                invoice_date TEXT,
                total_amount REAL,
                file_path TEXT,
                status TEXT DEFAULT 'pending',
                validation_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (po_number) REFERENCES purchase_orders (po_number)
            )
            ''')
            
            # Create validation_reports table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS validation_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER,
                report_content TEXT,
                discrepancies TEXT,
                approval_status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
            ''')
            
            conn.commit()
            self.logger.info("Database schema setup complete")
            
            # Remove duplicate invoices
            cursor.execute('''
            DELETE FROM invoices
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM invoices
                GROUP BY invoice_number
            );
            ''')
            
            # Remove duplicate purchase orders
            cursor.execute('''
            DELETE FROM purchase_orders
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM purchase_orders
                GROUP BY po_number
            );
            ''')
            
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error setting up database: {e}")
        finally:
            if conn:
                conn.close()

    def add_purchase_order(self, po_data):
        """
        Add a new purchase order to the database.
        
        Args:
            po_data (dict): Dictionary containing purchase order details
                - po_number: Purchase order number
                - vendor_name: Name of the vendor
                - issue_date: Date the PO was issued
                - total_amount: Total amount of the PO
                - status: Status of the PO (default: 'active')
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO purchase_orders (po_number, vendor_name, issue_date, total_amount, status)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                po_data.get('po_number'),
                po_data.get('vendor_name'),
                po_data.get('issue_date'),
                po_data.get('total_amount'),
                po_data.get('status', 'active')
            ))
            
            conn.commit()
            self.logger.info(f"Added purchase order: {po_data.get('po_number')}")
            return True
        except sqlite3.IntegrityError:
            self.logger.warning(f"Purchase order {po_data.get('po_number')} already exists")
            return False
        except Exception as e:
            self.logger.error(f"Error adding purchase order: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def add_invoice(self, invoice_data):
        """
        Add a new invoice to the database.
        
        Args:
            invoice_data (dict): Dictionary containing invoice details
                - invoice_number: Invoice number
                - po_number: Associated purchase order number
                - vendor_name: Name of the vendor
                - invoice_date: Date of the invoice
                - total_amount: Total amount of the invoice
                - file_path: Path to the invoice file
        
        Returns:
            int: ID of the added invoice, or None if failed
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO invoices (invoice_number, po_number, vendor_name, invoice_date, total_amount, file_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                invoice_data.get('invoice_number'),
                invoice_data.get('purchase_order'),
                invoice_data.get('vendor_name'),
                invoice_data.get('invoice_date'),
                invoice_data.get('total_amount'),
                invoice_data.get('file_path'),
                'pending'
            ))
            
            invoice_id = cursor.lastrowid
            conn.commit()
            self.logger.info(f"Added invoice: {invoice_data.get('invoice_number')}")
            return invoice_id
        except sqlite3.IntegrityError:
            self.logger.warning(f"Duplicate invoice detected: {invoice_data.get('invoice_number')}")
            return None
        except Exception as e:
            self.logger.error(f"Error adding invoice: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def validate_purchase_order(self, po_number):
        """
        Check if a purchase order exists in the database.
        
        Args:
            po_number (str): Purchase order number to validate
        
        Returns:
            bool: True if the purchase order exists, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT id FROM purchase_orders WHERE po_number = ? AND status = 'active'
            ''', (po_number,))
            
            result = cursor.fetchone()
            return result is not None
        except Exception as e:
            self.logger.error(f"Error validating purchase order: {e}")
            return False
        finally:
            if conn:
                conn.close()


    def _format_discrepancies(self, discrepancies):
        """
        Format discrepancies for the validation report.
        
        Args:
            discrepancies (list): List of discrepancy dictionaries
        
        Returns:
            str: Formatted discrepancies text
        """
        if not discrepancies:
            return "None found"
        
        formatted = []
        for d in discrepancies:
            if d["field"] == "total_amount":
                formatted.append(f"- {d['field'].replace('_', ' ').title()}: PO: ${d['po_value']} vs Invoice: ${d['invoice_value']} (Difference: ${d['difference']})")
            else:
                formatted.append(f"- {d['field'].replace('_', ' ').title()}: PO: {d['po_value']} vs Invoice: {d['invoice_value']}")
        
        return "\n".join(formatted)

    def send_validation_report(self, validation_result, invoice_file_path=None):
        """
        Send a validation report to the approver.
        
        Args:
            validation_result (dict): Validation result dictionary
            invoice_file_path (str): Path to the invoice file
        
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if not self.email_address or not self.email_password or not self.approver_email:
            self.logger.warning("Email configuration incomplete. Cannot send validation report.")
            return False
        
        try:
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = self.approver_email
            msg['Subject'] = f"Invoice Validation Report - {validation_result.get('status').upper()}"
            
            # Email body
            body = validation_result.get('report_content', 'No report content available')
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach invoice file if available
            if invoice_file_path and os.path.exists(invoice_file_path):
                with open(invoice_file_path, 'rb') as file:
                    attachment = MIMEApplication(file.read(), Name=os.path.basename(invoice_file_path))
                    attachment['Content-Disposition'] = f'attachment; filename="{os.path.basename(invoice_file_path)}"'
                    msg.attach(attachment)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)
                server.send_message(msg)
            
            self.logger.info(f"Validation report sent to {self.approver_email}")
            return True
        except Exception as e:
            self.logger.error(f"Error sending validation report: {e}")
            return False

    def update_approval_status(self, report_id, approval_status, comments=None):
        """
        Update the approval status of a validation report.
        
        Args:
            report_id (int): ID of the validation report
            approval_status (str): New approval status ('approved', 'rejected')
            comments (str): Optional comments from the approver
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Update validation report
            cursor.execute('''
            UPDATE validation_reports 
            SET approval_status = ?, 
                report_content = report_content || ? 
            WHERE id = ?
            ''', (
                approval_status,
                f"\n\nApprover Comments: {comments}" if comments else "\n\nApproved without comments",
                report_id
            ))
            
            # Get invoice ID from the report
            cursor.execute('SELECT invoice_id FROM validation_reports WHERE id = ?', (report_id,))
            invoice_id = cursor.fetchone()[0]
            
            # Update invoice status based on approval
            if approval_status == 'approved':
                cursor.execute('UPDATE invoices SET status = ? WHERE id = ?', ('approved', invoice_id))
            else:
                cursor.execute('UPDATE invoices SET status = ? WHERE id = ?', ('rejected', invoice_id))
            
            conn.commit()
            self.logger.info(f"Updated approval status for report {report_id} to {approval_status}")
            return True
        except Exception as e:
            self.logger.error(f"Error updating approval status: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def generate_summary_report(self, start_date=None, end_date=None):
        """
        Generate a summary report of invoices and their validation status.
        
        Args:
            start_date (str): Optional start date for filtering (YYYY-MM-DD)
            end_date (str): Optional end date for filtering (YYYY-MM-DD)
        
        Returns:
            pandas.DataFrame: Summary report as a DataFrame
        """
        try:
            conn = sqlite3.connect(self.db_path)
            
            query = '''
            SELECT 
                i.invoice_number,
                i.po_number,
                i.vendor_name,
                i.invoice_date,
                i.total_amount,
                i.status,
                i.validation_result,
                vr.approval_status
            FROM 
                invoices i
            LEFT JOIN 
                validation_reports vr ON i.id = vr.invoice_id
            '''
            
            params = []
            if start_date or end_date:
                query += " WHERE "
                conditions = []
                
                if start_date:
                    conditions.append("i.created_at >= ?")
                    params.append(start_date)
                
                if end_date:
                    conditions.append("i.created_at <= ?")
                    params.append(end_date)
                
                query += " AND ".join(conditions)
            
            query += " ORDER BY i.created_at DESC"
            
            df = pd.read_sql_query(query, conn, params=params)
            self.logger.info("Generated summary report")
            return df
        except Exception as e:
            self.logger.error(f"Error generating summary report: {e}")
            return pd.DataFrame()
        finally:
            if conn:
                conn.close()

    def export_summary_report(self, output_path, start_date=None, end_date=None):
        """
        Export a summary report to CSV.
        
        Args:
            output_path (str): Path to save the CSV file
            start_date (str): Optional start date for filtering (YYYY-MM-DD)
            end_date (str): Optional end date for filtering (YYYY-MM-DD)
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            df = self.generate_summary_report(start_date, end_date)
            if df.empty:
                self.logger.warning("No data to export")
                return False
            
            df.to_csv(output_path, index=False)
            self.logger.info(f"Exported summary report to {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error exporting summary report: {e}")
            return False

    def get_invoice_details(self, invoice_id):
        """
        Get detailed information about an invoice.
        
        Args:
            invoice_id (int): ID of the invoice
        
        Returns:
            dict: Invoice details
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT 
                i.id, i.invoice_number, i.po_number, i.vendor_name, 
                i.invoice_date, i.total_amount, i.file_path, i.status, 
                i.validation_result, i.created_at,
                vr.id as report_id, vr.report_content, vr.approval_status
            FROM 
                invoices i
            LEFT JOIN 
                validation_reports vr ON i.id = vr.invoice_id
            WHERE 
                i.id = ?
            ''', (invoice_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            column_names = [description[0] for description in cursor.description]
            invoice_details = dict(zip(column_names, row))
            
            return invoice_details
        except Exception as e:
            self.logger.error(f"Error getting invoice details: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_pending_approvals(self):
        """
        Get a list of validation reports that require approval.
        
        Returns:
            list: List of reports requiring approval
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT 
                vr.id as report_id,
                i.invoice_number,
                i.po_number,
                i.vendor_name,
                i.total_amount,
                i.file_path,
                vr.created_at
            FROM 
                validation_reports vr
            JOIN 
                invoices i ON vr.invoice_id = i.id
            WHERE 
                vr.approval_status = 'requires_approval'
            ORDER BY 
                vr.created_at DESC
            ''')
            
            column_names = [description[0] for description in cursor.description]
            pending_approvals = []
            
            for row in cursor.fetchall():
                pending_approvals.append(dict(zip(column_names, row)))
            
            return pending_approvals
        except Exception as e:
            self.logger.error(f"Error getting pending approvals: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def _get_connection(self):
        """
        Get a database connection.
        
        Returns:
            sqlite3.Connection: A database connection
        """
        return sqlite3.connect(self.db_path)
    
    def get_invoice_id_by_number(self, invoice_number):
        """
        Get the ID of an invoice by its invoice number.
        
        Args:
            invoice_number (str): The invoice number to look up
        
        Returns:
            int: The invoice ID, or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT id FROM invoices WHERE invoice_number = ?
            ''', (invoice_number,))
            
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            self.logger.error(f"Error getting invoice ID by number: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def validate_invoice(self, invoice_identifier):
        """
        Validate an invoice against its associated purchase order.
        
        Args:
            invoice_identifier: Either an invoice ID (int) or invoice number (str)
        
        Returns:
            dict: Validation results with discrepancies
        """
        # Convert invoice number to ID if needed
        invoice_id = invoice_identifier
        if isinstance(invoice_identifier, str):
            invoice_id = self.get_invoice_id_by_number(invoice_identifier)
            if not invoice_id:
                self.logger.error(f"Invoice with number {invoice_identifier} not found")
                return {"status": "error", "message": f"Invoice with number {invoice_identifier} not found"}
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get invoice details
            cursor.execute('''
            SELECT invoice_number, po_number, vendor_name, total_amount, file_path
            FROM invoices WHERE id = ?
            ''', (invoice_id,))
            
            invoice = cursor.fetchone()
            if not invoice:
                self.logger.error(f"Invoice with ID {invoice_id} not found")
                return None
            
            invoice_number, po_number, invoice_vendor, invoice_amount, file_path = invoice
            
            # Get purchase order details
            cursor.execute('''
            SELECT vendor_name, total_amount
            FROM purchase_orders WHERE po_number = ?
            ''', (po_number,))
            
            po = cursor.fetchone()
            if not po:
                # Update invoice status to indicate PO not found
                cursor.execute('''
                UPDATE invoices SET status = 'error', validation_result = 'Purchase order not found'
                WHERE id = ?
                ''', (invoice_id,))
                conn.commit()
                
                self.logger.warning(f"Purchase order {po_number} not found for invoice {invoice_number}")
                return {"status": "error", "message": "Purchase order not found"}
            
            po_vendor, po_amount = po
            
            # Check for discrepancies
            discrepancies = []
            
            if po_vendor and invoice_vendor and po_vendor.lower() != invoice_vendor.lower():
                discrepancies.append({
                    "field": "vendor_name",
                    "po_value": po_vendor,
                    "invoice_value": invoice_vendor
                })
            
            if po_amount and invoice_amount and abs(float(po_amount) - float(invoice_amount)) > 0.01:
                discrepancies.append({
                    "field": "total_amount",
                    "po_value": po_amount,
                    "invoice_value": invoice_amount,
                    "difference": abs(float(po_amount) - float(invoice_amount))
                })
            
            # Determine validation status
            if discrepancies:
                status = "discrepancies_found"
                validation_result = "Discrepancies found between invoice and purchase order"
            else:
                status = "validated"
                validation_result = "Invoice matches purchase order"
            
            # Update invoice status
            cursor.execute('''
            UPDATE invoices SET status = ?, validation_result = ?
            WHERE id = ?
            ''', (status, validation_result, invoice_id))
            
            # Create validation report
            report_content = f"""
            Invoice Validation Report
            -------------------------
            Invoice Number: {invoice_number}
            Purchase Order: {po_number}
            Validation Status: {status}
            
            Details:
            - Invoice Vendor: {invoice_vendor}
            - PO Vendor: {po_vendor}
            - Invoice Amount: ${invoice_amount}
            - PO Amount: ${po_amount}
            
            Discrepancies:
            {self._format_discrepancies(discrepancies) if discrepancies else "None found"}
            """
            
            cursor.execute('''
            INSERT INTO validation_reports (invoice_id, report_content, discrepancies, approval_status)
            VALUES (?, ?, ?, ?)
            ''', (
                invoice_id,
                report_content,
                str(discrepancies) if discrepancies else None,
                "requires_approval" if discrepancies else "auto_approved"
            ))
            
            report_id = cursor.lastrowid
            conn.commit()
            
            validation_result = {
                "status": status,
                "invoice_id": invoice_id,
                "report_id": report_id,
                "discrepancies": discrepancies,
                "report_content": report_content
            }
            
            # Send report to approver if discrepancies found
            if discrepancies and self.approver_email:
                self.send_validation_report(validation_result, file_path)
            
            return validation_result
        except Exception as e:
            self.logger.error(f"Error validating invoice: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

def view_database(db_path='./invoices.db', table=None, limit=None, where=None):
    """
    View the contents of the database tables with formatted output.
    
    Args:
        db_path (str): Path to the database file
        table (str): Optional specific table to view (purchase_orders, invoices, validation_reports)
        limit (int): Optional limit on the number of rows to display
        where (str): Optional WHERE clause for filtering results
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # This enables column access by name
        cursor = conn.cursor()
        
        # Get list of tables if no specific table is requested
        if table is None:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
        else:
            tables = [table]
        
        for table_name in tables:
            print(f"\n{'=' * 80}")
            print(f"TABLE: {table_name.upper()}")
            print(f"{'=' * 80}")
            
            # Get column names
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [column[1] for column in cursor.fetchall()]
            
            # Build query with optional WHERE clause and LIMIT
            query = f"SELECT * FROM {table_name}"
            params = []
            
            if where:
                query += f" WHERE {where}"
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                print("No records found.")
                continue
            
            # Calculate column widths for formatting
            col_widths = {}
            for col in columns:
                col_widths[col] = max(len(col), max([len(str(row[col])) for row in rows if row[col] is not None] or [0]) + 2)
            
            # Print header
            header = " | ".join(col.ljust(col_widths[col]) for col in columns)
            print(header)
            print("-" * len(header))
            
            # Print rows
            for row in rows:
                row_str = " | ".join(str(row[col]).ljust(col_widths[col]) for col in columns)
                print(row_str)
            
            print(f"\nTotal records: {len(rows)}")
    
    except Exception as e:
        print(f"Error viewing database: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    view_database()