"""
BFG Inbox Module Serializers

Serializers for inbox module models
"""

from rest_framework import serializers
from bfg.inbox.models import Message, MessageRecipient, MessageTemplate, SMSMessage


class MessageSerializer(serializers.ModelSerializer):
    """Message serializer"""
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    recipient_count = serializers.IntegerField(source='recipients.count', read_only=True)
    
    class Meta:
        model = Message
        fields = [
            'id', 'subject', 'message', 'message_type',
            'sender', 'sender_name', 'action_url', 'action_label',
            'send_email', 'send_sms', 'send_push',
            'expires_at', 'recipient_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class MessageRecipientSerializer(serializers.ModelSerializer):
    """Message recipient serializer"""
    message_subject = serializers.CharField(source='message.subject', read_only=True)
    message_content = serializers.CharField(source='message.message', read_only=True)
    message_type = serializers.CharField(source='message.message_type', read_only=True)
    action_url = serializers.CharField(source='message.action_url', read_only=True)
    action_label = serializers.CharField(source='message.action_label', read_only=True)
    sender = serializers.SerializerMethodField()
    sender_name = serializers.CharField(source='message.sender.get_full_name', read_only=True)
    created_at = serializers.DateTimeField(source='message.created_at', read_only=True)
    
    class Meta:
        model = MessageRecipient
        fields = [
            'id', 'message', 'message_subject', 'message_content',
            'message_type', 'action_url', 'action_label',
            'sender', 'sender_name', 'created_at',
            'is_read', 'is_archived', 'delivered_at', 'read_at'
        ]
        read_only_fields = ['id', 'delivered_at', 'read_at']
    
    def get_sender(self, obj):
        """Get sender information if available"""
        if obj.message and obj.message.sender:
            return {
                'id': obj.message.sender.id,
                'email': obj.message.sender.email,
                'first_name': getattr(obj.message.sender, 'first_name', None),
                'last_name': getattr(obj.message.sender, 'last_name', None)
            }
        return None


class MessageTemplateSerializer(serializers.ModelSerializer):
    """Message template serializer"""
    
    class Meta:
        model = MessageTemplate
        fields = [
            'id', 'workspace', 'name', 'code', 'event', 'language',
            'email_enabled', 'email_subject', 'email_body',
            'app_message_enabled', 'app_message_title', 'app_message_body',
            'sms_enabled', 'sms_body',
            'push_enabled', 'push_title', 'push_body',
            'available_variables', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'workspace', 'created_at', 'updated_at']
    
    def validate(self, attrs):
        """Validate uniqueness including workspace from request context"""
        request = self.context.get('request')
        if request and hasattr(request, 'workspace'):
            workspace = request.workspace
            code = attrs.get('code')
            language = attrs.get('language')
            
            # Check for existing template
            existing = MessageTemplate.objects.filter(
                workspace=workspace,
                code=code,
                language=language
            )
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise serializers.ValidationError({
                    'code': 'A template with this code and language already exists for this workspace.'
                })
        
        return attrs
    


class SMSMessageSerializer(serializers.ModelSerializer):
    """SMS message serializer"""
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    
    class Meta:
        model = SMSMessage
        fields = [
            'id', 'customer', 'customer_name', 'phone_number',
            'message', 'status', 'provider', 'provider_id',
            'created_at', 'sent_at', 'delivered_at'
        ]
        read_only_fields = ['id', 'status', 'provider', 'provider_id', 'created_at', 'sent_at', 'delivered_at']
