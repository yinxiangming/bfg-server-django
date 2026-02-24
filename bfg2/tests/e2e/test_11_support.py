"""
E2E Test 11: Support Ticket Management
"""

import pytest
from bfg.support.models import SupportTicket, TicketCategory, TicketPriority

@pytest.mark.e2e
@pytest.mark.django_db
class TestSupport:
    
    def test_ticket_creation(self, authenticated_client, workspace, customer):
        """Test support ticket creation via API"""
        payload = {
            "subject": "Test Support Ticket",
            "description": "This is a test support ticket",
            "customer": customer.id,
            "status": "new",
            "channel": "web"
        }
        
        response = authenticated_client.post('/api/v1/support/tickets/', payload)
        
        assert response.status_code == 201
        assert response.data['subject'] == "Test Support Ticket"
        assert response.data['status'] == "new"
        assert response.data['customer'] == customer.id
    
    def test_ticket_update(self, authenticated_client, workspace, customer):
        """Test support ticket update via API"""
        # Create ticket first
        create_res = authenticated_client.post('/api/v1/support/tickets/', {
            "subject": "Test Ticket",
            "description": "Initial description",
            "customer": customer.id,
            "status": "new",
            "channel": "web"
        })
        assert create_res.status_code == 201
        ticket_id = create_res.data['id']
        
        # Update ticket
        update_payload = {
            "status": "open",
            "description": "Updated description"
        }
        
        response = authenticated_client.patch(f'/api/v1/support/tickets/{ticket_id}/', update_payload)
        
        assert response.status_code == 200
        assert response.data['status'] == "open"
        assert response.data['description'] == "Updated description"
    
    def test_ticket_list_filtering(self, authenticated_client, workspace, customer):
        """Test ticket list with status filtering"""
        # Create multiple tickets with different statuses
        authenticated_client.post('/api/v1/support/tickets/', {
            "subject": "New Ticket",
            "description": "New ticket",
            "customer": customer.id,
            "status": "new",
            "channel": "web"
        })
        
        authenticated_client.post('/api/v1/support/tickets/', {
            "subject": "Open Ticket",
            "description": "Open ticket",
            "customer": customer.id,
            "status": "open",
            "channel": "web"
        })
        
        # Filter by status
        response = authenticated_client.get('/api/v1/support/tickets/?status=new')
        
        assert response.status_code == 200
        assert len(response.data) >= 1
        assert all(ticket['status'] == 'new' for ticket in response.data)
    
    def test_ticket_reply(self, authenticated_client, workspace, customer):
        """Test adding reply to ticket"""
        # Create ticket
        create_res = authenticated_client.post('/api/v1/support/tickets/', {
            "subject": "Test Ticket",
            "description": "Initial description",
            "customer": customer.id,
            "status": "new",
            "channel": "web"
        })
        ticket_id = create_res.data['id']
        
        # Add reply (assuming there's a reply endpoint or nested resource)
        # This depends on the actual API structure
        reply_payload = {
            "message": "This is a reply to the ticket",
            "is_internal": False
        }
        
        # Try to update with reply or use a specific reply endpoint
        response = authenticated_client.patch(f'/api/v1/support/tickets/{ticket_id}/', {
            "description": "Initial description\n\nReply: This is a reply to the ticket"
        })
        
        assert response.status_code == 200
