"""
E2E Test 02: Website Setup
"""

import uuid
import pytest

@pytest.mark.e2e
class TestWebsiteSetup:
    
    def test_site_creation(self, authenticated_client, workspace):
        """Test site creation via API"""
        suffix = uuid.uuid4().hex[:6]
        payload = {
            "name": "Main Site",
            "domain": f"www.test.com-{suffix}",
            "site_title": "My Shop",
            "default_language": "en"
        }
        
        response = authenticated_client.post('/api/v1/web/sites/', payload)
        
        assert response.status_code == 201
        assert response.data['domain'] == payload["domain"]
        assert response.data['workspace'] == workspace.id
        
    def test_page_creation(self, authenticated_client, workspace):
        """Test page creation via API"""
        suffix = uuid.uuid4().hex[:6]
        # 1. Create site first
        site_payload = {"name": "Site", "domain": f"site.com-{suffix}", "site_title": "Site"}
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
