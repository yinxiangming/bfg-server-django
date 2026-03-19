"""
E2E Test 05: Media Upload (API-only; same contract for all backends).
"""

import pytest
from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile


@pytest.mark.e2e
@pytest.mark.django_db
class TestMediaUpload:

    def test_image_upload(self, authenticated_client, workspace):
        """Test image upload via API. Skips if endpoint not implemented (404)."""
        # Create a dummy image file
        image_content = b"fake_image_content"
        image = SimpleUploadedFile(
            "test_image.jpg",
            image_content,
            content_type="image/jpeg"
        )
        
        payload = {
            "file": image,
            "file_name": "test_image.jpg",
            "file_type": "image",
            "mime_type": "image/jpeg",
            "file_size": len(image_content)
        }
        
        response = authenticated_client.post(
            '/api/v1/web/media/',
            payload,
            format='multipart'
        )
        assert response.status_code == 201, (
            f"Media upload failed: {response.status_code} {response.data}"
        )
        assert response.data['file_name'] == "test_image.jpg"
        assert response.data['file_type'] == "image"
    
    def test_product_media_upload(self, authenticated_client, workspace):
        """Test product media upload via API"""
        import uuid
        suffix = uuid.uuid4().hex[:6]
        # Create category and product first
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            'name': f'Electronics {suffix}', 'slug': f'electronics-{suffix}', 'language': 'en'
        })
        assert cat_res.status_code == 201
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            'name': f'Camera {suffix}', 'slug': f'camera-{suffix}', 'price': '599.00', 'language': 'en'
        })
        assert prod_res.status_code == 201
        product_id = prod_res.data['id']
        
        # Create a test image
        image = Image.new('RGB', (100, 100), color='red')
        image_file = BytesIO()
        image.save(image_file, 'JPEG')
        image_file.seek(0)
        
        uploaded_file = SimpleUploadedFile(
            name='test_camera.jpg',
            content=image_file.read(),
            content_type='image/jpeg'
        )
        
        # Upload product media
        media_res = authenticated_client.post(
            '/api/v1/shop/product-media/',
            {
                'product': product_id,
                'media_type': 'image',
                'file': uploaded_file,
                'alt_text': 'Camera main image',
                'position': 1
            },
            format='multipart'
        )
        assert media_res.status_code == 201, (
            f"Product media upload failed: {media_res.status_code} {media_res.data}"
        )
        assert media_res.data['media_type'] == 'image'
        assert media_res.data['alt_text'] == 'Camera main image'
        assert 'file' in media_res.data
