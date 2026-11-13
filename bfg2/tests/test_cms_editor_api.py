"""Editor persistence and the separate tenant-safe public CMS catalogue."""
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, User, Workspace
from bfg.web.models import Category, Page, Post
from bfg.web.services.block_service import BlockService
from bfg.web.services.page_service import get_page_rendered_cache_key


@pytest.fixture
def editor(db):
    workspace = Workspace.objects.create(name='Editorial', slug='editorial')
    user = User.objects.create_user(username='editorial-admin', password='test-only')
    role = StaffRole.objects.create(workspace=workspace, code='admin', name='Admin')
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client, workspace, user


def test_page_editor_persists_every_field_and_blocks(editor):
    client, workspace, _ = editor
    payload = {'title': 'About', 'slug': 'about', 'content': '', 'language': 'en',
               'excerpt': 'Introduction', 'meta_title': 'About our team',
               'meta_description': 'Our description', 'meta_keywords': 'team',
               'template': 'default', 'status': 'draft',
               'blocks': [{'id': 'text', 'type': 'text_block_v1', 'data': {'content': {'en': '<p>Team</p>'}}}]}
    response = client.post('/api/v1/web/pages/', payload, format='json')
    assert response.status_code == 201, response.data
    url = f"/api/v1/web/pages/{response.data['id']}/"
    for field in ['excerpt', 'meta_title', 'meta_description', 'meta_keywords', 'template', 'blocks']:
        assert client.get(url).data[field] == payload[field]
    edited = client.patch(url, {'meta_title': 'Edited SEO', 'excerpt': 'Edited excerpt', 'blocks': []}, format='json')
    assert edited.status_code == 200
    detail = client.get(url).data
    assert (detail['meta_title'], detail['excerpt'], detail['blocks']) == ('Edited SEO', 'Edited excerpt', [])
    assert Page.objects.get(pk=detail['id']).workspace_id == workspace.id
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_tag_editor_crud_assigns_workspace(editor):
    client, workspace, _ = editor
    response = client.post('/api/v1/web/tags/', {'name': 'Mobility', 'slug': 'mobility', 'language': 'en'}, format='json')
    assert response.status_code == 201, response.data
    url = f"/api/v1/web/tags/{response.data['id']}/"
    assert client.patch(url, {'name': 'Support'}, format='json').data['name'] == 'Support'
    from bfg.web.models import Tag
    assert Tag.objects.get(pk=response.data['id']).workspace_id == workspace.id
    assert client.delete(url).status_code == 204


def make_post(workspace, slug, **kwargs):
    category, _ = Category.objects.get_or_create(workspace=workspace, slug='projects', defaults={'name': 'Projects'})
    return Post.objects.create(workspace=workspace, category=category, title=slug, slug=slug,
                                   content='<p>Published body</p>', language='en',
                                   author=User.objects.get(username='editorial-admin'), **kwargs)


def test_public_catalogue_excludes_other_tenants_drafts_scheduled_and_inactive_categories(editor):
    _, workspace, _ = editor
    live = make_post(workspace, 'live', status='published', published_at=timezone.now()-timedelta(days=1))
    make_post(workspace, 'draft', status='draft')
    make_post(workspace, 'scheduled', status='published', published_at=timezone.now()+timedelta(days=1))
    translated = make_post(workspace, 'untranslated', status='published', published_at=timezone.now())
    translated.language = 'zh-hans'
    translated.save()
    other = Workspace.objects.create(name='Other', slug='other-editorial')
    make_post(other, 'private-to-other-site', status='published', published_at=timezone.now())
    public = APIClient()
    response = public.get('/api/v1/web/posts/published/?category_slug=projects&lang=en', HTTP_X_WORKSPACE_ID=str(workspace.id))
    assert response.status_code == 200, response.data
    rows = response.data['results'] if isinstance(response.data, dict) else response.data
    assert [row['slug'] for row in rows] == ['live']
    assert rows[0]['category_slug'] == 'projects'
    assert not {'author', 'author_name', 'status', 'view_count'} & rows[0].keys()
    assert public.get('/api/v1/web/posts/', HTTP_X_WORKSPACE_ID=str(workspace.id)).status_code in (401, 403)
    live.category.is_active = False
    live.category.save()
    remaining = public.get('/api/v1/web/posts/published/', HTTP_X_WORKSPACE_ID=str(workspace.id)).data
    assert (remaining['count'] if isinstance(remaining, dict) else len(remaining)) == 0


def test_blocks_respect_language_publication_manual_order_and_empty_selection(editor):
    _, workspace, _ = editor
    first = make_post(workspace, 'first', status='published', published_at=timezone.now()-timedelta(days=2))
    second = make_post(workspace, 'second', status='published', published_at=timezone.now()-timedelta(days=1))
    future = make_post(workspace, 'future', status='published', published_at=timezone.now()+timedelta(days=1))
    service = BlockService(workspace=workspace)
    block = {'type': 'post_list_v1', 'data': {'source': 'manual', 'postIds': [second.id, future.id, first.id]}}
    assert [row['slug'] for row in service.resolve_block_data(block, language='en')['resolvedData']] == ['second', 'first']
    assert service.resolve_block_data({'type': 'post_list_v1', 'data': {'source': 'manual', 'postIds': []}})['resolvedData'] == []


def test_committed_post_change_invalidates_referencing_home(editor, django_capture_on_commit_callbacks):
    _, workspace, _ = editor
    key = get_page_rendered_cache_key(workspace.id, 'home', 'en')
    cache.set(key, {'stale': True})
    with django_capture_on_commit_callbacks(execute=True):
        make_post(workspace, 'edited', status='published', published_at=timezone.now())
    assert cache.get(key) is None


def test_general_company_fields_reach_public_config_and_can_be_cleared(editor):
    client, workspace, _ = editor
    settings = client.get('/api/v1/settings/').data[0]
    url = f"/api/v1/settings/{settings['id']}/"
    custom = {'general': {'site_name': 'Edited company', 'contact_email': 'edited@example.test',
                          'contact_phone': '09 123 4567', 'contact_address': 'First line\nSecond line',
                          'footer_copyright': 'Edited copyright'},
              'web': {'seo_default_title': 'Edited default title', 'seo_default_description': 'Edited description'}}
    response = client.patch(url, {'custom_settings': custom}, format='json')
    assert response.status_code == 200, response.data
    public = APIClient()
    config = public.get('/api/v1/settings/storefront/', HTTP_X_WORKSPACE_ID=str(workspace.id)).data
    for key in ['site_name', 'contact_email', 'contact_phone', 'contact_address', 'footer_copyright']:
        assert config[key] == custom['general'][key]
    assert config['seo_default_title'] == 'Edited default title'
    custom['general']['contact_email'] = ''
    cleared = client.patch(url, {'custom_settings': custom}, format='json')
    assert cleared.status_code == 200, cleared.data
    assert public.get('/api/v1/settings/storefront/', HTTP_X_WORKSPACE_ID=str(workspace.id)).data['contact_email'] == ''


def test_navigation_changes_invalidate_public_config(editor, django_capture_on_commit_callbacks):
    from bfg.web.models import Menu, MenuItem
    _, workspace, _ = editor
    public = APIClient()
    headers = {'HTTP_X_WORKSPACE_ID': str(workspace.id)}
    public.get('/api/v1/settings/storefront/', **headers)
    with django_capture_on_commit_callbacks(execute=True):
        menu = Menu.objects.create(workspace=workspace, name='Header', slug='header', location='header', language='en')
        item = MenuItem.objects.create(menu=menu, title='New link', url='/new')
    assert public.get('/api/v1/settings/storefront/', **headers).data['header_menus'][0]['title'] == 'New link'
    with django_capture_on_commit_callbacks(execute=True):
        item.title = 'Edited link'
        item.save()
    assert public.get('/api/v1/settings/storefront/', **headers).data['header_menus'][0]['title'] == 'Edited link'
    with django_capture_on_commit_callbacks(execute=True):
        item.delete()
    assert public.get('/api/v1/settings/storefront/', **headers).data['header_menus'] == []


def test_editing_a_linked_menu_url_replaces_old_page_and_rejects_unknown_items(editor):
    from bfg.web.models import Menu, MenuItem
    client, workspace, user = editor
    page = Page.objects.create(workspace=workspace, created_by=user, title='About', slug='about')
    menu = Menu.objects.create(workspace=workspace, name='Header', slug='header', location='header')
    item = MenuItem.objects.create(menu=menu, title='About', url='/about', page=page)
    url = f'/api/v1/web/menus/{menu.id}/'
    response = client.patch(url, {'items': [{'id': item.id, 'title': 'Contact', 'url': '/contact'}]}, format='json')
    assert response.status_code == 200, response.data
    item.refresh_from_db()
    assert item.url == '/contact' and item.page_id is None
    invalid = client.patch(url, {'name': 'Should roll back', 'items': [{'id': item.id+999, 'title': 'Unknown', 'url': '/wrong'}]}, format='json')
    assert invalid.status_code == 400
    menu.refresh_from_db()
    assert menu.name == 'Header' and menu.items.count() == 1
