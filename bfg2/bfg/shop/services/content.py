"""Compose content from original sources on every render; never mutate products."""
import re
from html import unescape

from bfg.shop.models import ProductCategory, ProductContentPolicy


def plain_text(value):
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', value or '', flags=re.I | re.S)
    value = re.sub(r'<br\s*/?>|</(?:p|div|li|h[1-6]|tr)>', '\n', value, flags=re.I)
    return unescape(re.sub(r'<[^>]+>', '', value)).replace('\r\n', '\n').replace('\r', '\n').strip()


class ProductContentComposer:
    def compose(self, product, *, body=None, category_id=None, language=None, include_category=True, include_workspace=True):
        language = language or product.language or 'en'
        if body is None and product.language and language != product.language:
            raise ValueError('Provide channel content in the selected language; product language differs.')
        categories = list(ProductCategory.all_objects.filter(products=product, workspace_id=product.workspace_id))
        if include_category and category_id is None:
            if len(categories) > 1:
                raise ValueError('Select a content category explicitly for this multi-category product.')
            category_id = categories[0].pk if categories else None
        if category_id is not None and category_id not in [c.pk for c in categories]:
            raise ValueError('Content category must be assigned to this product.')
        policies = list(ProductContentPolicy.all_objects.filter(workspace_id=product.workspace_id, slot='footer'))
        by_scope = {(p.category_id, p.language): p for p in policies}
        configured_scopes = {p.category_id for p in policies}
        segments = [{'kind': 'body', 'text': plain_text(product.description if body is None else body)}]
        sources = []

        def resolve(scope):
            policy = by_scope.get((scope, language))
            if policy is None and scope in configured_scopes:
                raise ValueError(f'Missing {language} public content for {"workspace" if scope is None else "category " + str(scope)}; add it or explicitly disable this segment.')
            sources.append({'scope': scope, 'id': policy.pk if policy else None, 'revision': policy.revision if policy else None})
            return policy

        if include_category and category_id:
            visited = set()
            current_id = category_id
            while current_id:
                if current_id in visited:
                    raise ValueError('Content category hierarchy contains a cycle.')
                visited.add(current_id)
                try:
                    category = ProductCategory.all_objects.get(pk=current_id, workspace_id=product.workspace_id)
                except ProductCategory.DoesNotExist as exc:
                    raise ValueError('Content category hierarchy crosses workspace boundaries.') from exc
                sources.append({'category': category.pk, 'parent': category.parent_id})
                policy = resolve(current_id)
                if policy:
                    if current_id != category_id and not policy.include_descendants:
                        current_id = category.parent_id
                        continue
                    if not policy.enabled or policy.mode == 'off':
                        break
                    if policy.mode == 'own':
                        segments.append({'kind': 'category', 'text': plain_text(policy.text), 'id': policy.pk, 'revision': policy.revision, 'category': category.pk})
                        break
                current_id = category.parent_id
        if include_workspace:
            policy = resolve(None)
            if policy and policy.enabled and policy.mode == 'own':
                segments.append({'kind': 'workspace', 'text': plain_text(policy.text), 'id': policy.pk, 'revision': policy.revision})
        return {'language': language, 'category': category_id, 'segments': segments, 'sources': sources,
                'text': '\n\n'.join(s['text'] for s in segments if s['text'])}
