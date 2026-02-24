"""
Media-related ViewSets
"""
from rest_framework import viewsets, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import models
import os
import shutil
import logging

from django.contrib.contenttypes.models import ContentType
from bfg.core.permissions import IsWorkspaceStaff
from bfg.common.models import Media, MediaLink
from bfg.shop.models import Product, ProductVariant
from bfg.common.serializers import MediaSerializer, MediaLinkSerializer
from django.conf import settings


class MediaPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


class MediaViewSet(viewsets.ModelViewSet):
    """Independent Media management ViewSet (Media Library)"""
    serializer_class = MediaSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    pagination_class = MediaPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_serializer_context(self):
        """Add request to serializer context for building absolute URLs"""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    def get_queryset(self):
        """Get media for current workspace"""
        queryset = Media.objects.filter(
            workspace=self.request.workspace
        ).order_by('-created_at')
        
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(file__icontains=search) |
                models.Q(alt_text__icontains=search)
            )
        
        folder = self.request.query_params.get('folder') or self.request.query_params.get('dir')
        if folder:
            folder = folder.strip('/')
            workspace_id = self.request.workspace.id
            folder_path = f'media/{workspace_id}/{folder}/'
            queryset = queryset.filter(file__startswith=folder_path)
        
        return queryset
    
    def perform_create(self, serializer):
        """Set workspace and folder before saving"""
        instance = serializer.save(workspace=self.request.workspace)
        folder = self.request.data.get('folder', '').strip()
        if folder:
            instance._upload_folder = folder
            instance.save()
    
    @action(detail=False, methods=['get'])
    def folders(self, request):
        """List all folders for the current workspace"""
        workspace_id = request.workspace.id
        media_root = os.path.join(settings.MEDIA_ROOT, 'media', str(workspace_id))
        
        folders = []
        if os.path.exists(media_root):
            for item in os.listdir(media_root):
                item_path = os.path.join(media_root, item)
                if os.path.isdir(item_path):
                    folders.append(item)
        
        return Response({'folders': sorted(folders)})
    
    @action(detail=False, methods=['post'])
    def create_folder(self, request):
        """Create a new folder physically"""
        folder = request.data.get('folder', '').strip()
        if not folder:
            return Response({'detail': 'folder is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        workspace_id = request.workspace.id
        folder_path = os.path.join(settings.MEDIA_ROOT, 'media', str(workspace_id), folder)
        
        try:
            os.makedirs(folder_path, exist_ok=True)
            return Response({'message': f'Folder {folder} created successfully'}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['delete'])
    def delete_folder(self, request):
        """Delete a folder and all its contents"""
        folder = request.query_params.get('folder', '').strip()
        if not folder:
            return Response({'detail': 'folder is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        workspace_id = request.workspace.id
        folder_path = os.path.join(settings.MEDIA_ROOT, 'media', str(workspace_id), folder)
        
        if not os.path.exists(folder_path):
            return Response({'detail': 'Folder not found'}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            folder_path_pattern = f'media/{workspace_id}/{folder}/'
            Media.objects.filter(file__startswith=folder_path_pattern).delete()
            shutil.rmtree(folder_path)
            return Response({'message': f'Folder {folder} deleted successfully'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['delete'])
    def delete_file(self, request, pk=None):
        """Delete the actual file from storage and the database record"""
        instance = self.get_object()
        
        if instance.file:
            try:
                instance.file.delete(save=False)
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.error(f"Error deleting file {instance.file}: {e}")
        
        instance.delete()
        return Response({'message': 'File and record deleted successfully'}, status=status.HTTP_200_OK)


class ProductMediaPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


class ProductMediaViewSet(viewsets.ModelViewSet):
    """Product media management ViewSet - uses generic MediaLink"""
    serializer_class = MediaLinkSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    pagination_class = ProductMediaPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_serializer_context(self):
        """Add request to serializer context for building absolute URLs"""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    def get_queryset(self):
        """Get product media for current workspace"""
        product_content_type = ContentType.objects.get_for_model(Product)
        queryset = MediaLink.objects.filter(
            content_type=product_content_type,
            media__workspace=self.request.workspace
        ).select_related('media', 'content_type').prefetch_related('content_object').order_by('-id')
        
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(object_id=product_id)
        
        # Note: variant support removed as MediaLink is generic
        # Variant-specific media can be stored as separate MediaLinks if needed

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(media__file__icontains=search) |
                models.Q(media__alt_text__icontains=search)
            )

        folder = self.request.query_params.get('folder') or self.request.query_params.get('dir')
        if folder:
            folder = folder.strip('/')
            workspace_id = self.request.workspace.id
            folder_path = f'media/{workspace_id}/{folder}/'
            queryset = queryset.filter(media__file__startswith=folder_path)
        
        return queryset
    
    def destroy(self, request, *args, **kwargs):
        """Delete product media reference only (do not delete the actual Media object)."""
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['post'])
    def copy_to_product(self, request, pk=None):
        """Copy media to another product."""
        instance = self.get_object()
        target_product_id = request.data.get('product_id')
        
        if not target_product_id:
            return Response(
                {'detail': 'product_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            target_product = Product.objects.get(
                id=target_product_id,
                workspace=self.request.workspace
            )
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Target product not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        product_content_type = ContentType.objects.get_for_model(Product)
        existing = MediaLink.objects.filter(
            content_type=product_content_type,
            object_id=target_product_id,
            media=instance.media
        ).first()
        
        if existing:
            response_serializer = self.get_serializer(existing)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        
        new_media_link = MediaLink.objects.create(
            media=instance.media,
            content_object=target_product,
            position=instance.position,
            description=instance.description
        )
        
        response_serializer = self.get_serializer(new_media_link)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
    
    def create(self, request, *args, **kwargs):
        """Create product media reference."""
        product_id = request.data.get('product')
        if not product_id:
            return Response(
                {'detail': 'product is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            product = Product.objects.get(id=product_id, workspace=request.workspace)
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        media_id = request.data.get('media_id')
        if media_id:
            try:
                media = Media.objects.get(id=media_id, workspace=request.workspace)
            except Media.DoesNotExist:
                return Response({'detail': 'Media not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            folder = request.data.get('folder', 'products').strip()
            media_data = {
                'workspace': request.workspace,
                'file': request.data.get('file'),
                'external_url': request.data.get('external_url', ''),
                'media_type': request.data.get('media_type', 'image'),
                'alt_text': request.data.get('alt_text', ''),
            }
            media = Media(**media_data)
            if folder:
                media._upload_folder = folder
            media.save()
        
        # Use update_or_create to avoid duplicate entry errors
        # If a MediaLink already exists for this media and product, update it
        media_link, created = MediaLink.objects.update_or_create(
            media=media,
            content_type=ContentType.objects.get_for_model(product),
            object_id=product.id,
            defaults={
                'position': request.data.get('position', 100),
                'description': request.data.get('description', '')
            }
        )
        
        response_serializer = self.get_serializer(media_link)
        headers = self.get_success_headers(response_serializer.data)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    @action(detail=False, methods=['get'])
    def folders(self, request):
        """List all folders for the current workspace."""
        workspace = request.workspace
        workspace_id = workspace.id
        base_path = os.path.join(settings.MEDIA_ROOT, 'media', str(workspace_id))
        
        folders_list = []
        if os.path.exists(base_path) and os.path.isdir(base_path):
            for item in os.listdir(base_path):
                item_path = os.path.join(base_path, item)
                if os.path.isdir(item_path):
                    folders_list.append(item)
        
        folders_list = sorted(folders_list)
        return Response({
            'folders': folders_list,
            'count': len(folders_list)
        })
    
    @action(detail=False, methods=['post'], parser_classes=[JSONParser])
    def create_folder(self, request):
        """Create a new folder physically."""
        folder = request.data.get('folder', '').strip()
        
        if not folder:
            return Response(
                {'detail': 'Folder name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if folder.startswith('/') or folder.endswith('/'):
            return Response(
                {'detail': 'Folder name should not start or end with slash'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if '/' in folder or '\\' in folder:
            return Response(
                {'detail': 'Folder name should not contain path separators'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        workspace_id = request.workspace.id
        base_path = os.path.join(settings.MEDIA_ROOT, 'media', str(workspace_id))
        folder_path = os.path.join(base_path, folder)
        
        try:
            os.makedirs(folder_path, exist_ok=True)
            return Response({
                'folder': folder,
                'message': f'Folder "{folder}" created successfully'
            })
        except OSError as e:
            return Response(
                {'detail': f'Failed to create folder: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['delete'])
    def delete_folder(self, request):
        """Delete a folder and all media files in it."""
        folder = request.query_params.get('folder', '').strip()
        
        if not folder:
            return Response(
                {'detail': 'Folder name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        workspace_id = request.workspace.id
        folder_path_prefix = f'media/{workspace_id}/{folder}/'
        product_content_type = ContentType.objects.get_for_model(Product)
        media_links = MediaLink.objects.filter(
            content_type=product_content_type,
            media__workspace=request.workspace,
            media__file__startswith=folder_path_prefix
        )
        
        count = media_links.count()
        
        for media_link in media_links:
            if media_link.media.file:
                try:
                    media_link.media.file.delete(save=False)
                except Exception:
                    pass
            media_link.media.delete()  # Delete Media object (this will cascade delete MediaLink)
        
        base_path = os.path.join(settings.MEDIA_ROOT, 'media', str(workspace_id))
        folder_path = os.path.join(base_path, folder)
        
        try:
            if os.path.exists(folder_path) and os.path.isdir(folder_path):
                shutil.rmtree(folder_path)
        except OSError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting folder {folder_path}: {e}")
        
        if count == 0:
            message = f'Deleted empty folder "{folder}"'
        else:
            message = f'Deleted folder "{folder}" and {count} media file(s)'
        
        return Response({
            'folder': folder,
            'deleted_count': count,
            'message': message
        })

