"""Tests for confluence_spaces.py."""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
_base_path = Path(__file__).parent.parent
sys.path.insert(0, str(_base_path / 'atlassian-skills'))
sys.path.insert(0, str(_base_path / 'atlassian-skills' / 'scripts'))

from scripts.confluence_spaces import (
    confluence_get_spaces,
    confluence_get_space,
    confluence_get_space_content,
)
import _common
NotFoundError = _common.NotFoundError


class TestConfluenceGetSpaces:
    """Tests for confluence_get_spaces function."""

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_spaces_success(self, mock_get_client, sample_space_data):
        """Test successful retrieval of all spaces."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = {'results': [sample_space_data]}

        result = confluence_get_spaces()
        data = json.loads(result)

        assert data['total'] == 1
        assert len(data['spaces']) == 1
        assert data['spaces'][0]['key'] == 'TEST'
        assert data['spaces'][0]['name'] == 'Test Space'
        assert data['spaces'][0]['type'] == 'global'
        mock_client.get.assert_called_once()

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_spaces_with_type_filter(self, mock_get_client, sample_space_data):
        """Test retrieval with space type filter."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = {'results': [sample_space_data]}

        result = confluence_get_spaces(space_type='global')
        data = json.loads(result)

        assert data['total'] == 1
        # Verify type parameter was passed
        call_args = mock_client.get.call_args
        assert call_args[1]['params']['type'] == 'global'

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_spaces_with_limit(self, mock_get_client, sample_space_data):
        """Test retrieval with custom limit."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = {'results': [sample_space_data]}

        result = confluence_get_spaces(limit=50)
        data = json.loads(result)

        assert data['total'] == 1
        call_args = mock_client.get.call_args
        assert call_args[1]['params']['limit'] == 50

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_spaces_empty_results(self, mock_get_client):
        """Test retrieval when no spaces available."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = {'results': []}

        result = confluence_get_spaces()
        data = json.loads(result)

        assert data['total'] == 0
        assert data['spaces'] == []

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_spaces_multiple_spaces(self, mock_get_client, sample_space_data):
        """Test retrieval of multiple spaces."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        space1 = sample_space_data.copy()
        space2 = {
            'id': '12346',
            'key': 'KB',
            'name': 'Knowledge Base',
            'type': 'collaboration',
            'description': {'plain': {'value': 'KB space'}},
            'status': 'current',
            '_links': {'webui': '/wiki/spaces/KB'}
        }
        mock_client.get.return_value = {'results': [space1, space2]}

        result = confluence_get_spaces()
        data = json.loads(result)

        assert data['total'] == 2
        assert len(data['spaces']) == 2
        keys = [s['key'] for s in data['spaces']]
        assert 'TEST' in keys
        assert 'KB' in keys

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_spaces_missing_description(self, mock_get_client):
        """Test handling of space without description."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        space_data = {
            'id': '12345',
            'key': 'TEST',
            'name': 'Test Space',
            'type': 'global',
            'status': 'current',
            '_links': {'webui': '/wiki/spaces/TEST'}
        }
        mock_client.get.return_value = {'results': [space_data]}

        result = confluence_get_spaces()
        data = json.loads(result)

        assert data['spaces'][0]['description'] == ''


class TestConfluenceGetSpace:
    """Tests for confluence_get_space function."""

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_space_success(self, mock_get_client, sample_space_data):
        """Test successful retrieval of a specific space."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = sample_space_data

        result = confluence_get_space('TEST')
        data = json.loads(result)

        assert data['key'] == 'TEST'
        assert data['name'] == 'Test Space'
        assert data['type'] == 'global'
        assert data['status'] == 'current'
        mock_client.get.assert_called_once()

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_space_with_permissions(self, mock_get_client, sample_space_data):
        """Test retrieval of space with permissions info."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        space_with_perms = sample_space_data.copy()
        space_with_perms['permissions'] = [
            {'operation': {'operationKey': 'read'}, 'subjects': {}},
            {'operation': {'operationKey': 'update'}, 'subjects': {}}
        ]
        mock_client.get.return_value = space_with_perms

        result = confluence_get_space('TEST')
        data = json.loads(result)

        assert data['permissions_count'] == 2

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_space_missing_key(self, mock_get_client):
        """Test error when space_key is missing."""
        mock_get_client.return_value = MagicMock()
        result = confluence_get_space('')
        data = json.loads(result)

        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_space_not_found(self, mock_get_client):
        """Test error when space is not found."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.side_effect = NotFoundError('Space not found')

        result = confluence_get_space('NONEXISTENT')
        data = json.loads(result)

        assert data['success'] is False
        assert data['error_type'] == 'NotFoundError'


class TestConfluenceGetSpaceContent:
    """Tests for confluence_get_space_content function."""

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_content_pages_success(self, mock_get_client):
        """Test successful retrieval of pages from space."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        content_data = {
            'results': [
                {
                    'id': '10001',
                    'title': 'Page One',
                    'type': 'page',
                    'version': {'number': 1, 'when': '2024-01-01T00:00:00.000Z'},
                    '_links': {'webui': '/wiki/spaces/TEST/pages/10001'}
                },
                {
                    'id': '10002',
                    'title': 'Page Two',
                    'type': 'page',
                    'version': {'number': 2, 'when': '2024-01-02T00:00:00.000Z'},
                    '_links': {'webui': '/wiki/spaces/TEST/pages/10002'}
                }
            ]
        }
        mock_client.get.return_value = content_data

        result = confluence_get_space_content('TEST')
        data = json.loads(result)

        assert data['space_key'] == 'TEST'
        assert data['content_type'] == 'page'
        assert data['total'] == 2
        assert len(data['contents']) == 2
        assert data['contents'][0]['title'] == 'Page One'
        assert data['contents'][1]['version'] == 2

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_content_blogposts(self, mock_get_client):
        """Test retrieval of blog posts from space."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        content_data = {
            'results': [
                {
                    'id': '20001',
                    'title': 'Blog Post One',
                    'type': 'blogpost',
                    'version': {'number': 1, 'when': '2024-01-01T00:00:00.000Z'},
                    '_links': {'webui': '/wiki/spaces/TEST/blog/20001'}
                }
            ]
        }
        mock_client.get.return_value = content_data

        result = confluence_get_space_content('TEST', content_type='blogpost')
        data = json.loads(result)

        assert data['content_type'] == 'blogpost'
        assert data['total'] == 1
        assert data['contents'][0]['type'] == 'blogpost'

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_content_with_limit(self, mock_get_client):
        """Test retrieval with custom limit."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = {'results': []}

        result = confluence_get_space_content('TEST', limit=25)
        data = json.loads(result)

        call_args = mock_client.get.call_args
        assert call_args[1]['params']['limit'] == 25

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_content_missing_space_key(self, mock_get_client):
        """Test error when space_key is missing."""
        mock_get_client.return_value = MagicMock()
        result = confluence_get_space_content('')
        data = json.loads(result)

        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_content_empty_results(self, mock_get_client):
        """Test retrieval when space has no content."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = {'results': []}

        result = confluence_get_space_content('TEST')
        data = json.loads(result)

        assert data['total'] == 0
        assert data['contents'] == []

    @patch('scripts.confluence_spaces.get_confluence_client')
    def test_get_content_not_found(self, mock_get_client):
        """Test error when space is not found."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.side_effect = NotFoundError('Space not found')

        result = confluence_get_space_content('NONEXISTENT')
        data = json.loads(result)

        assert data['success'] is False
        assert data['error_type'] == 'NotFoundError'