from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, serializers, viewsets
from bfg.core.permissions import StaffReadAdminWrite
from bfg.shop.models import ProductCategory, ProductContentPolicy


class ProductContentPolicySerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=ProductCategory.all_objects.none(), allow_null=True, required=False)

    class Meta:
        model = ProductContentPolicy
        fields = ['id', 'category', 'scope_key', 'language', 'slot', 'mode', 'include_descendants', 'text', 'enabled', 'revision', 'updated_at']
        read_only_fields = ['scope_key', 'revision', 'updated_at']
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request:
            self.fields['category'].queryset = ProductCategory.all_objects.filter(workspace=request.workspace)


class ProductContentPolicyViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ProductContentPolicySerializer
    permission_classes = [StaffReadAdminWrite]
    pagination_class = None

    def get_queryset(self):
        return ProductContentPolicy.all_objects.filter(workspace=self.request.workspace)

    def perform_create(self, serializer):
        self._save(serializer, workspace=self.request.workspace)

    def perform_update(self, serializer):
        self._save(serializer)

    @staticmethod
    def _save(serializer, **kwargs):
        try:
            serializer.save(**kwargs)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
