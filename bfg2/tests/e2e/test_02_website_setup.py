"""
E2E Test 02: Website Setup
"""

import pytest
from bfg.web.models import Site, Page
from bfg.web.services import SiteService

@pytest.mark.e2e
@pytest.mark.django_db
class TestWebsiteSetup:
    
    def test_site_creation(self, authenticated_client, workspace):
        """Test site creation via API"""
        payload = {
            "name": "Main Site",
            "domain": "www.test.com",
            "site_title": "My Shop",
            "default_language": "en"
        }
        
        response = authenticated_client.post('/api/v1/web/sites/', payload)
        
        assert response.status_code == 201
        assert response.data['domain'] == "www.test.com"
        assert response.data['workspace'] == workspace.id
        
    def test_page_creation(self, authenticated_client, workspace):
        """Test page creation via API"""
        # 1. Create site first
        site_payload = {"name": "Site", "domain": "site.com", "site_title": "Site"}
        site_res = authenticated_client.post('/api/v1/web/sites/', site_payload)
        site_id = site_res.data['id']
        
        # 2. Create page
        payload = {
            "title": "Home Page",
            "slug": "home",
            "content": "<h1>Welcome</h1>",
            "status": "published",
            "language": "en"
        }
        
        response = authenticated_client.post('/api/v1/web/pages/', payload)
        
        assert response.status_code == 201
        assert response.data['slug'] == "home"
        assert response.data['content'] == "<h1>Welcome</h1>"
