"""Tests for requirement_yogi.py."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_base_path = Path(__file__).parent.parent
sys.path.insert(0, str(_base_path / 'atlassian-skills'))
sys.path.insert(0, str(_base_path / 'atlassian-skills' / 'scripts'))

from scripts.requirement_yogi import (
    requirement_yogi_get_requirement,
    requirement_yogi_list_requirements,
    requirement_yogi_create_requirement,
    requirement_yogi_update_requirement,
    requirement_yogi_delete_requirement,
    requirement_yogi_bulk_update_requirements,
    _simplify_requirement,
    _strip_html,
    RY_BASE_PATH,
    MAX_REQUIREMENTS_LIMIT,
)
from scripts._common import AtlassianCredentials


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_requirement_data():
    """Sample Requirements Yogi requirement payload (THCU/IAM_001)."""
    return {
        'key': 'IAM_001',
        'spaceKey': 'THCU',
        'status': 'ACTIVE',
        'storageData': {
            'type': 'storage',
            'data': '<p>The system <strong>shall</strong> authenticate users.</p>',
        },
        'properties': [
            {'key': 'Category', 'value': 'Functional'},
            {'key': 'Priority', 'value': 'High'},
        ],
        'references': [
            {'key': 'IAM_002', 'spaceKey': 'THCU', 'direction': 'TO'},
        ],
        'issues': [
            {'issueKey': 'PROJ-123', 'summary': 'Implement auth', 'status': 'In Progress'},
        ],
        'pageId': 467382,
        'pageTitle': 'Identity & Access Management',
        'genericUrl': 'https://confluence.example.com/x/abc',
    }


@pytest.fixture
def sample_list_response(sample_requirement_data):
    return {
        'results': [sample_requirement_data],
        'count': 1,
        'limit': 50,
        'offset': 0,
        'explanation': "Requirements in space 'THCU'",
    }


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_strip_html_basic(self):
        assert _strip_html('<p>Hello <b>world</b></p>') == 'Hello world'

    def test_strip_html_entities(self):
        assert _strip_html('<p>A &amp; B &lt;C&gt;</p>') == 'A & B <C>'

    def test_strip_html_empty(self):
        assert _strip_html('') == ''

    def test_simplify_requirement_full(self, sample_requirement_data):
        simplified = _simplify_requirement(sample_requirement_data)
        assert simplified['key'] == 'IAM_001'
        assert simplified['space_key'] == 'THCU'
        assert simplified['status'] == 'ACTIVE'
        assert 'authenticate users' in simplified['content']
        assert simplified['content_html'].startswith('<p>')
        assert simplified['properties'] == {'Category': 'Functional', 'Priority': 'High'}
        assert simplified['references'][0]['key'] == 'IAM_002'
        assert simplified['references'][0]['direction'] == 'TO'
        assert simplified['jira_links'][0]['issue_key'] == 'PROJ-123'
        assert simplified['page_id'] == 467382
        assert simplified['url'] == 'https://confluence.example.com/x/abc'

    def test_simplify_requirement_empty(self):
        assert _simplify_requirement({}) == {}

    def test_simplify_requirement_minimal(self):
        simplified = _simplify_requirement({'key': 'X_001', 'spaceKey': 'X'})
        assert simplified == {'key': 'X_001', 'space_key': 'X', 'status': 'ACTIVE'}


# ---------------------------------------------------------------------------
# requirement_yogi_get_requirement
# ---------------------------------------------------------------------------

class TestGetRequirement:
    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_get_requirement_success(self, mock_get_client, sample_requirement_data):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = sample_requirement_data

        result = requirement_yogi_get_requirement('THCU', 'IAM_001')
        data = json.loads(result)

        assert data['key'] == 'IAM_001'
        assert data['space_key'] == 'THCU'
        assert data['properties']['Category'] == 'Functional'
        mock_client.get.assert_called_once_with(
            f'{RY_BASE_PATH}/requirement2/THCU/IAM_001'
        )

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_get_requirement_missing_space(self, mock_get_client):
        result = requirement_yogi_get_requirement('', 'IAM_001')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'
        mock_get_client.assert_not_called()

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_get_requirement_missing_key(self, mock_get_client):
        result = requirement_yogi_get_requirement('THCU', '')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_get_requirement_not_found(self, mock_get_client):
        # NOTE: import _common via the same path the script uses so the
        # NotFoundError class identity matches what the decorator catches.
        import _common as _ry_common
        NotFoundError = _ry_common.NotFoundError
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.side_effect = NotFoundError('Resource not found: IAM_999')

        result = requirement_yogi_get_requirement('THCU', 'IAM_999')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'NotFoundError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_get_requirement_spaces_filter_blocks(self, mock_get_client):
        creds = AtlassianCredentials(
            confluence_url='https://confluence.example.com',
            confluence_pat_token='tok',
            requirement_yogi_spaces_filter='THCU,DEV',
        )
        result = requirement_yogi_get_requirement(
            'OTHER', 'IAM_001', credentials=creds
        )
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'
        mock_get_client.assert_not_called()

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_get_requirement_spaces_filter_allows(
        self, mock_get_client, sample_requirement_data
    ):
        creds = AtlassianCredentials(
            confluence_url='https://confluence.example.com',
            confluence_pat_token='tok',
            requirement_yogi_spaces_filter='THCU,DEV',
        )
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = sample_requirement_data

        result = requirement_yogi_get_requirement(
            'THCU', 'IAM_001', credentials=creds
        )
        data = json.loads(result)
        assert data['key'] == 'IAM_001'


# ---------------------------------------------------------------------------
# requirement_yogi_list_requirements
# ---------------------------------------------------------------------------

class TestListRequirements:
    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_list_requirements_success(self, mock_get_client, sample_list_response):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = sample_list_response

        result = requirement_yogi_list_requirements('THCU')
        data = json.loads(result)

        assert data['count'] == 1
        assert data['limit'] == 50
        assert data['results'][0]['key'] == 'IAM_001'
        assert data['explanation']
        mock_client.get.assert_called_once_with(
            f'{RY_BASE_PATH}/requirement2/THCU', params={'limit': 50}
        )

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_list_requirements_with_query_and_limit(
        self, mock_get_client, sample_list_response
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = sample_list_response

        result = requirement_yogi_list_requirements(
            'THCU', query="key ~ 'IAM_%'", limit=10
        )
        data = json.loads(result)
        assert 'results' in data
        mock_client.get.assert_called_once_with(
            f'{RY_BASE_PATH}/requirement2/THCU',
            params={'limit': 10, 'q': "key ~ 'IAM_%'"},
        )

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_list_requirements_missing_space(self, mock_get_client):
        result = requirement_yogi_list_requirements('')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_list_requirements_invalid_limit(self, mock_get_client):
        result = requirement_yogi_list_requirements('THCU', limit=0)
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

        result = requirement_yogi_list_requirements(
            'THCU', limit=MAX_REQUIREMENTS_LIMIT + 1
        )
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_list_requirements_handles_list_response(
        self, mock_get_client, sample_requirement_data
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = [sample_requirement_data]

        result = requirement_yogi_list_requirements('THCU')
        data = json.loads(result)
        assert data['count'] == 1
        assert data['results'][0]['key'] == 'IAM_001'


# ---------------------------------------------------------------------------
# requirement_yogi_create_requirement
# ---------------------------------------------------------------------------

class TestCreateRequirement:
    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_create_requirement_success(self, mock_get_client, sample_requirement_data):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.post.return_value = sample_requirement_data

        result = requirement_yogi_create_requirement(
            'THCU', 'IAM_001',
            title='Auth requirement',
            content_html='<p>The system shall authenticate.</p>',
            properties={'Category': 'Functional', 'Priority': 'High'},
        )
        data = json.loads(result)
        assert data['key'] == 'IAM_001'

        call = mock_client.post.call_args
        assert call.args[0] == f'{RY_BASE_PATH}/requirement2/THCU/IAM_001'
        payload = call.kwargs['json']
        assert payload['key'] == 'IAM_001'
        assert payload['spaceKey'] == 'THCU'
        assert payload['title'] == 'Auth requirement'
        assert payload['storageData']['data'] == '<p>The system shall authenticate.</p>'
        assert {'key': 'Category', 'value': 'Functional'} in payload['properties']

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_create_requirement_defaults_content_from_title(
        self, mock_get_client, sample_requirement_data
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.post.return_value = sample_requirement_data

        requirement_yogi_create_requirement('THCU', 'IAM_001', title='Auth')
        payload = mock_client.post.call_args.kwargs['json']
        assert payload['storageData']['data'] == '<p>Auth</p>'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_create_requirement_missing_space(self, mock_get_client):
        result = requirement_yogi_create_requirement('', 'IAM_001', title='X')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_create_requirement_missing_key(self, mock_get_client):
        result = requirement_yogi_create_requirement('THCU', '', title='X')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_create_requirement_requires_some_content(self, mock_get_client):
        result = requirement_yogi_create_requirement('THCU', 'IAM_001')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'


# ---------------------------------------------------------------------------
# requirement_yogi_update_requirement
# ---------------------------------------------------------------------------

class TestUpdateRequirement:
    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_update_requirement_success(self, mock_get_client, sample_requirement_data):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.put.return_value = sample_requirement_data

        result = requirement_yogi_update_requirement(
            'THCU', 'IAM_001',
            title='Updated title',
            properties={'Priority': 'Critical'},
        )
        data = json.loads(result)
        assert data['key'] == 'IAM_001'

        call = mock_client.put.call_args
        assert call.args[0] == f'{RY_BASE_PATH}/requirement2/THCU/IAM_001'
        payload = call.kwargs['json']
        assert payload['title'] == 'Updated title'
        assert 'storageData' not in payload  # not provided
        assert {'key': 'Priority', 'value': 'Critical'} in payload['properties']

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_update_requirement_no_fields(self, mock_get_client):
        result = requirement_yogi_update_requirement('THCU', 'IAM_001')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_update_requirement_missing_key(self, mock_get_client):
        result = requirement_yogi_update_requirement('THCU', '', title='X')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'


# ---------------------------------------------------------------------------
# requirement_yogi_delete_requirement
# ---------------------------------------------------------------------------

class TestDeleteRequirement:
    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_delete_requirement_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.delete.return_value = True

        result = requirement_yogi_delete_requirement('THCU', 'IAM_001')
        data = json.loads(result)
        assert data['success'] is True
        assert 'IAM_001' in data['message']
        mock_client.delete.assert_called_once_with(
            f'{RY_BASE_PATH}/requirement2/THCU/IAM_001'
        )

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_delete_requirement_missing_space(self, mock_get_client):
        result = requirement_yogi_delete_requirement('', 'IAM_001')
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'


# ---------------------------------------------------------------------------
# requirement_yogi_bulk_update_requirements
# ---------------------------------------------------------------------------

class TestBulkUpdateRequirements:
    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_bulk_update_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.put.return_value = {'updated': 2, 'failed': 0}

        result = requirement_yogi_bulk_update_requirements(
            'THCU',
            [
                {'key': 'IAM_001', 'title': 'Updated 1'},
                {
                    'key': 'IAM_002',
                    'content_html': '<p>Body 2</p>',
                    'properties': {'Priority': 'Low'},
                },
            ],
        )
        data = json.loads(result)
        assert data['updated'] == 2

        call = mock_client.put.call_args
        assert call.args[0] == f'{RY_BASE_PATH}/requirement2/THCU'
        payload = call.kwargs['json']
        assert len(payload['requirements']) == 2
        assert payload['requirements'][0]['title'] == 'Updated 1'
        assert payload['requirements'][1]['storageData']['data'] == '<p>Body 2</p>'
        assert {'key': 'Priority', 'value': 'Low'} in payload['requirements'][1]['properties']

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_bulk_update_empty_list(self, mock_get_client):
        result = requirement_yogi_bulk_update_requirements('THCU', [])
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'

    @patch('scripts.requirement_yogi.get_requirement_yogi_client')
    def test_bulk_update_item_missing_key(self, mock_get_client):
        result = requirement_yogi_bulk_update_requirements(
            'THCU', [{'title': 'No key'}]
        )
        data = json.loads(result)
        assert data['success'] is False
        assert data['error_type'] == 'ValidationError'


# ---------------------------------------------------------------------------
# Credentials availability
# ---------------------------------------------------------------------------

class TestRequirementYogiAvailability:
    def test_available_with_confluence_pat(self):
        creds = AtlassianCredentials(
            confluence_url='https://confluence.example.com',
            confluence_pat_token='tok',
        )
        assert creds.is_requirement_yogi_available() is True
        assert 'requirement_yogi' in creds.get_available_services()

    def test_unavailable_without_url(self):
        creds = AtlassianCredentials()
        assert creds.is_requirement_yogi_available() is False
        unavailable = creds.get_unavailable_services()
        assert 'requirement_yogi' in unavailable
        assert 'confluence_url' in unavailable['requirement_yogi']

    def test_unavailable_without_auth(self):
        creds = AtlassianCredentials(
            confluence_url='https://confluence.example.com',
        )
        assert creds.is_requirement_yogi_available() is False
        unavailable = creds.get_unavailable_services()
        assert 'requirement_yogi' in unavailable
        assert 'authentication' in unavailable['requirement_yogi'].lower()
