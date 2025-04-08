#!/usr/bin/env python3
"""
Test script for the Invoice Processing System

This script demonstrates how to use the enhanced invoice processing system.
It includes examples of:
1. Adding purchase orders to the database
2. Processing invoices
3. Validating invoices against purchase orders
4. Real-time approver validation
5. Generating and sending summary reports
"""

import os
import sys
import time
from datetime import datetime, timedelta
from database_manager import DatabaseManager
from email_monitor import InvoiceMonitor

def test_database_operations():
    """Test database operations for purchase orders and invoices"""
    print("Testing database operations...")
    
    # Initialize the database manager
    db_manager = DatabaseManager()
    
    # Add sample purchase orders - using a dictionary to prevent duplicates
    purchase_orders = {
        'PO12345': {
            'po_number': 'PO12345',
            'vendor_name': 'ABC Supplies',
            'issue_date': '2025-03-20',
            'total_amount': 1800.00,
            'status': 'active'
        },
        'PO67890': {
            'po_number': 'PO67890',
            'vendor_name': 'XYZ Corporation',
            'issue_date': '2025-03-22',
            'total_amount': 2500.00,
            'status': 'active'
        }
    }
    
    # Add purchase orders to database
    for po_number, po_data in purchase_orders.items():
        success = db_manager.add_purchase_order(po_data)
        if success:
            print(f"Added purchase order {po_number}")
        else:
            print(f"Purchase order {po_number} already exists")
    
    # Add sample invoices - using a dictionary to prevent duplicates
    invoices = {
        'INV-001': {
            'invoice_number': 'INV-001',
            'purchase_order': 'PO12345',
            'vendor_name': 'ABC Supplies',
            'invoice_date': '2025-03-25',
            'total_amount': 1800.00,
            'file_path': './invoices/sample_invoice_1.pdf',
            'status': 'pending'
        },
        'INV-002': {
            'invoice_number': 'INV-002',
            'purchase_order': 'PO67890',
            'vendor_name': 'XYZ Corporation',
            'invoice_date': '2025-03-26',
            'total_amount': 2600.00,  # Intentional mismatch with PO
            'file_path': './invoices/sample_invoice_2.pdf',
            'status': 'pending'
        }
    }
    
    # Add invoices to database
    for invoice_number, invoice_data in invoices.items():
        inv_id = db_manager.add_invoice(invoice_data)
        if inv_id:
            print(f"Added invoice {invoice_number} with ID: {inv_id}")
        else:
            print(f"Invoice {invoice_number} already exists")
    
    # Validate invoices against purchase orders
    for invoice_number in invoices.keys():
        validation_result = db_manager.validate_invoice(invoice_number)
        print(f"Validation result for {invoice_number}: {validation_result['status']}")
    
    # Generate summary report
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    report = db_manager.generate_summary_report(
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d')
    )
    
    print("\nSummary Report:")
    print(report)
    
    # Get pending approvals
    pending_approvals = db_manager.get_pending_approvals()
    print("\nPending Approvals:")
    for approval in pending_approvals:
        print(f"- Invoice #{approval['invoice_number']} from {approval['vendor_name']} for PO #{approval['po_number']}")

def test_email_monitoring(test_mode=True):
    """Test email monitoring functionality"""
    print("\nTesting email monitoring...")
    
    # In test mode, we don't actually connect to an email server
    if test_mode:
        print("Running in test mode - simulating email processing")
        
        # Initialize the database manager
        db_manager = DatabaseManager()
        
        # Simulate processing an invoice from email
        invoice_details = {
            'invoice_number': 'INV-003',
            'purchase_order': 'PO12345',
            'vendor_name': 'ABC Supplies',
            'invoice_date': '2025-03-27',
            'total_amount': 1800.00,
            'file_path': './invoices/sample_invoice_3.pdf',
            'status': 'pending'
        }
        
        inv_id = db_manager.add_invoice(invoice_details)
        if inv_id:
            print(f"Simulated processing of invoice {invoice_details['invoice_number']} with ID: {inv_id}")
            
            # Validate the invoice
            validation_result = db_manager.validate_invoice(invoice_details['invoice_number'])
            print(f"Validation result: {validation_result['status']}")
            
            # Generate and "send" a summary report
            print("\nGenerating summary report...")
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            report = db_manager.generate_summary_report(
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d')
            )
            
            print("Summary report generated")
            print("In a real scenario, this would be emailed to the approver")
        else:
            print(f"Invoice {invoice_details['invoice_number']} already exists")
    else:
        print("To run actual email monitoring, configure environment variables and uncomment the code in this function")

def test_approver_validation():
    """Test real-time approver validation functionality"""
    print("\nTesting real-time approver validation...")
    
    # Initialize the database manager
    db_manager = DatabaseManager()
    
    # Get pending approvals
    pending_approvals = db_manager.get_pending_approvals()
    
    if not pending_approvals:
        print("No pending approvals found. Creating a test invoice with discrepancies...")
        
        # Create a test purchase order
        po_data = {
            'po_number': 'PO-TEST-APPROVAL',
            'vendor_name': 'Test Vendor',
            'issue_date': datetime.now().strftime('%Y-%m-%d'),
            'total_amount': 1000.00,
            'status': 'active'
        }
        
        db_manager.add_purchase_order(po_data)
        
        # Create a test invoice with discrepancies
        invoice_data = {
            'invoice_number': 'INV-TEST-APPROVAL',
            'purchase_order': 'PO-TEST-APPROVAL',
            'vendor_name': 'Different Vendor Name',  # Intentional mismatch
            'invoice_date': datetime.now().strftime('%Y-%m-%d'),
            'total_amount': 1200.00,  # Intentional mismatch
            'file_path': './invoices/test_approval.pdf',
            'status': 'pending'
        }
        
        inv_id = db_manager.add_invoice(invoice_data)
        if inv_id:
            print(f"Created test invoice with ID: {inv_id}")
            
            # Validate the invoice to generate a validation report
            validation_result = db_manager.validate_invoice('INV-TEST-APPROVAL')
            print(f"Validation result: {validation_result['status']}")
            
            # Get the updated pending approvals
            pending_approvals = db_manager.get_pending_approvals()
        else:
            print("Failed to create test invoice")
    
    # Process pending approvals
    for approval in pending_approvals:
        print(f"\nProcessing approval for invoice #{approval['invoice_number']}:")
        print(f"- Vendor: {approval['vendor_name']}")
        print(f"- PO: {approval['po_number']}")
        print(f"- Amount: ${approval['total_amount']}")
        
        # Simulate approver decision (approve or reject)
        # In a real system, this would come from user input or an API call
        decision = 'approved'  # or 'rejected'
        comments = "Approved after verifying with the vendor"
        
        # Update approval status
        report_id = approval['report_id']
        success = db_manager.update_approval_status(report_id, decision, comments)
        
        if success:
            print(f"Invoice {approval['invoice_number']} has been {decision}")
        else:
            print(f"Failed to update approval status for invoice {approval['invoice_number']}")

def test_summary_report():
    """Test generating and sending summary reports to approvers"""
    print("\nTesting summary report generation and sending...")
    
    # Initialize the database manager
    db_manager = DatabaseManager()
    
    # Generate a summary report for the last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    # Generate the report
    report = db_manager.generate_summary_report(
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d')
    )
    
    if not report.empty:
        print("\nSummary Report:")
        print(report)
        
        # Export the report to CSV
        output_path = './invoice_summary_report.csv'
        success = db_manager.export_summary_report(output_path, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        if success:
            print(f"Summary report exported to {output_path}")
            
            # In a real system, this would send the report to the approver via email
            print("In a real scenario, this report would be emailed to the approver")
        else:
            print("Failed to export summary report")
    else:
        print("No data available for summary report")

def main():
    """Main function to run the tests"""
    print("=== Invoice Processing System Test ===\n")
    
    # Test database operations
    test_database_operations()
    
    # Test email monitoring (in test mode)
    test_email_monitoring()
    
    # Test real-time approver validation
    test_approver_validation()
    
    # Test summary report generation and sending
    test_summary_report()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()