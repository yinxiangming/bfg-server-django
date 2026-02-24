"""
BFG Web Module Services

Media management service
"""

import os
from typing import Any
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet
from bfg.core.services import BaseService
from bfg.web.exceptions import MediaUploadFailed
from bfg.web.models import Media


class MediaService(BaseService):
    """
    Media management service
    
    Handles file uploads, storage, and media library management
    """
    
    @transaction.atomic
    def upload_media(self, file: UploadedFile, **kwargs: Any) -> Media:
        """
        Upload and process media file
        
        Args:
            file: Django UploadedFile instance
            **kwargs: Additional media metadata
            
        Returns:
            Media: Created media instance
            
        Raises:
            MediaUploadFailed: If upload fails
        """
        try:
            # Determine file type
            mime_type = file.content_type
            if mime_type.startswith('image/'):
                file_type = 'image'
            elif mime_type.startswith('video/'):
                file_type = 'video'
            elif mime_type.startswith('application/pdf') or mime_type.startswith('application/msword'):
                file_type = 'document'
            else:
                file_type = 'other'
            
            # Get file dimensions for images
            width = None
            height = None
            if file_type == 'image':
                try:
                    from PIL import Image
                    image = Image.open(file)
                    width, height = image.size
                except Exception:
                    pass  # If PIL fails, continue without dimensions
            
            # Create media record
            media = Media.objects.create(
                workspace=self.workspace,
                file=file,
                file_name=file.name,
                file_type=file_type,
                mime_type=mime_type,
                file_size=file.size,
                title=kwargs.get('title', file.name),
                alt_text=kwargs.get('alt_text', ''),
                caption=kwargs.get('caption', ''),
                width=width,
                height=height,
                uploaded_by=self.user,
            )
            
            return media
            
        except Exception as e:
            raise MediaUploadFailed(f"Failed to upload media: {str(e)}")
    
    def delete_media(self, media: Media) -> None:
        """
        Delete media file and record
        
        Args:
            media: Media instance
        """
        self.validate_workspace_access(media)
        
        # Delete physical file
        if media.file:
            try:
                default_storage.delete(media.file.name)
            except Exception:
                pass  # File might already be deleted
        
        # Delete record
        media.delete()
    
    def get_media_by_type(self, file_type: str) -> QuerySet[Media]:
        """
        Get media files filtered by type
        
        Args:
            file_type: File type ('image', 'video', 'document')
            
        Returns:
            QuerySet: Media files of specified type
        """
        return Media.objects.filter(
            workspace=self.workspace,
            file_type=file_type
        ).select_related('uploaded_by').order_by('-uploaded_at')
    
    def update_media(self, media: Media, **kwargs: Any) -> Media:
        """
        Update media metadata
        
        Args:
            media: Media instance
            **kwargs: Fields to update
            
        Returns:
            Media: Updated media instance
        """
        self.validate_workspace_access(media)
        
        allowed_fields = ['title', 'alt_text', 'caption']
        
        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(media, key):
                setattr(media, key, value)
        
        media.save()
        return media
