"""Requirements Yogi tools.

Requirements Yogi is a Confluence plugin for requirement management. It exposes
a REST API at ``/rest/reqs/1/...`` on the Confluence host, secured with the
same Confluence authentication (PAT for Data Center, username + API token for
Cloud). These tools wrap the public ``RequirementResource2`` CRUD API.

Tools:
    - requirement_yogi_get_requirement: Get a single requirement
    - requirement_yogi_list_requirements: List/search requirements in a space
    - requirement_yogi_create_requirement: Create a requirement
    - requirement_yogi_update_requirement: Update an existing requirement
    - requirement_yogi_delete_requirement: Delete a requirement
    - requirement_yogi_bulk_update_requirements: Bulk update requirements
"""

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from typing import Any, Dict, List, Optional

from _common import (
    AtlassianCredentials,
    get_requirement_yogi_client,
    get_requirement_yogi_spaces_filter,
    format_json_response,
    format_error_response,
    ConfigurationError,
    AuthenticationError,
    ValidationError,
    NotFoundError,
    APIError,
    NetworkError,
)


# =============================================================================
# Constants
# =============================================================================

# Requirements Yogi REST API base path (mounted on the Confluence host)
RY_BASE_PATH = '/rest/reqs/1'

# Pagination limits (mirror the upstream MCP server defaults)
DEFAULT_REQUIREMENTS_LIMIT = 50
MAX_REQUIREMENTS_LIMIT = 200


# =============================================================================
# Helpers
# =============================================================================

def _apply_spaces_filter(space_key: str, credentials: Optional[AtlassianCredentials]) -> None:
    """Raise ValidationError if ``space_key`` is not in the allowed filter.

    The filter is read from the credentials' ``requirement_yogi_spaces_filter``
    field or the ``REQUIREMENT_YOGI_SPACES_FILTER`` env var (comma-separated).
    No filter means all spaces are allowed.
    """
    raw = get_requirement_yogi_spaces_filter(credentials)
    if not raw:
        return
    allowed = [s.strip() for s in raw.split(',') if s.strip()]
    if space_key not in allowed:
        raise ValidationError(
            f"Space '{space_key}' is not in the allowed Requirements Yogi spaces filter: {allowed}"
        )


def _strip_html(html: str) -> str:
    """Best-effort plain-text extraction from HTML (no external deps)."""
    if not html:
        return ''
    text = re.sub(r'<[^>]+>', ' ', html)
    text = (
        text.replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'")
            .replace('&nbsp;', ' ')
    )
    return re.sub(r'\s+', ' ', text).strip()


def _simplify_property(prop: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'key': prop.get('key', ''),
        'value': prop.get('value', ''),
    }


def _simplify_reference(ref: Dict[str, Any]) -> Dict[str, Any]:
    result = {'key': ref.get('key', '')}
    if ref.get('spaceKey'):
        result['space_key'] = ref['spaceKey']
    if ref.get('direction'):
        result['direction'] = ref['direction']
    if ref.get('url'):
        result['url'] = ref['url']
    return result


def _simplify_jira_link(link: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        'issue_key': link.get('issueKey', link.get('key', '')),
    }
    if link.get('issueId') is not None:
        result['issue_id'] = link['issueId']
    if link.get('summary'):
        result['summary'] = link['summary']
    if link.get('status'):
        result['status'] = link['status']
    if link.get('url'):
        result['url'] = link['url']
    return result


def _simplify_requirement(req: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Requirements Yogi requirement payload.

    Returns a stable, JSON-friendly shape:
        {
            "key", "space_key", "status",
            "content", "content_html",
            "properties": {key: value, ...},
            "references": [...],
            "jira_links": [...],
            "page_id", "page_title", "url"
        }
    """
    if not req:
        return {}

    storage = req.get('storageData') or {}
    html = storage.get('data', '') if isinstance(storage, dict) else ''

    properties_list = req.get('properties', []) or []
    properties_map: Dict[str, str] = {}
    for p in properties_list:
        if isinstance(p, dict):
            properties_map[p.get('key', '')] = p.get('value', '')

    simplified: Dict[str, Any] = {
        'key': req.get('key', ''),
        'space_key': req.get('spaceKey', ''),
        'status': req.get('status', 'ACTIVE'),
    }

    if html:
        simplified['content'] = _strip_html(html)
        simplified['content_html'] = html

    if properties_map:
        simplified['properties'] = properties_map

    references = req.get('references', []) or []
    if references:
        simplified['references'] = [_simplify_reference(r) for r in references if isinstance(r, dict)]

    jira_links = req.get('issues') or req.get('jiraLinks') or []
    if jira_links:
        simplified['jira_links'] = [_simplify_jira_link(j) for j in jira_links if isinstance(j, dict)]

    if req.get('pageId') is not None:
        simplified['page_id'] = req['pageId']
    if req.get('pageTitle'):
        simplified['page_title'] = req['pageTitle']
    if req.get('genericUrl'):
        simplified['url'] = req['genericUrl']

    return simplified


def _properties_to_payload(properties: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Convert a {key: value} dict into the API's [{key, value}, ...] form."""
    if not properties:
        return []
    return [{'key': str(k), 'value': '' if v is None else str(v)} for k, v in properties.items()]


def _handle_errors(func):
    """Decorator that converts known exceptions into JSON error responses."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ConfigurationError as e:
            return format_error_response('ConfigurationError', str(e))
        except AuthenticationError as e:
            return format_error_response('AuthenticationError', str(e))
        except ValidationError as e:
            return format_error_response('ValidationError', str(e))
        except NotFoundError as e:
            return format_error_response('NotFoundError', str(e))
        except (APIError, NetworkError) as e:
            return format_error_response(type(e).__name__, str(e))
        except Exception as e:  # pragma: no cover - safety net
            return format_error_response('UnexpectedError', f'Unexpected error: {str(e)}')
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# =============================================================================
# Read operations
# =============================================================================

@_handle_errors
def requirement_yogi_get_requirement(
    space_key: str,
    requirement_key: str,
    credentials: Optional[AtlassianCredentials] = None,
) -> str:
    """Get a single Requirements Yogi requirement by space and key.

    API: ``GET /rest/reqs/1/requirement2/{spaceKey}/{key}``

    Args:
        space_key: Confluence space key (e.g. ``THCU``).
        requirement_key: Requirement key within the space (e.g. ``IAM_001``).
        credentials: Optional AtlassianCredentials. If omitted, Confluence
            environment variables are used.

    Returns:
        JSON string with the flattened requirement or an error object.
    """
    if not space_key:
        raise ValidationError('space_key is required')
    if not requirement_key:
        raise ValidationError('requirement_key is required')

    _apply_spaces_filter(space_key, credentials)
    client = get_requirement_yogi_client(credentials)

    path = f'{RY_BASE_PATH}/requirement2/{space_key}/{requirement_key}'
    data = client.get(path)
    if not isinstance(data, dict):
        raise APIError(f'Unexpected response for requirement {space_key}/{requirement_key}')

    return format_json_response(_simplify_requirement(data))


@_handle_errors
def requirement_yogi_list_requirements(
    space_key: str,
    query: Optional[str] = None,
    limit: int = DEFAULT_REQUIREMENTS_LIMIT,
    credentials: Optional[AtlassianCredentials] = None,
) -> str:
    """List or search requirements in a Confluence space.

    API: ``GET /rest/reqs/1/requirement2/{spaceKey}?q=...&limit=...``

    Args:
        space_key: Confluence space key.
        query: Optional Requirements Yogi search query (see the Requirements
            Yogi search syntax). Examples:
              * ``key ~ 'IAM_%'``
              * ``@Category = 'Functional' AND @Priority = 'High'``
              * ``jira = 'PROJ-123'``
        limit: Maximum number of requirements to return (1-200, default 50).
        credentials: Optional AtlassianCredentials.

    Returns:
        JSON string with ``{results, count, limit, offset, explanation?}``
        or an error object.
    """
    if not space_key:
        raise ValidationError('space_key is required')
    if not isinstance(limit, int) or limit < 1 or limit > MAX_REQUIREMENTS_LIMIT:
        raise ValidationError(
            f'limit must be an integer between 1 and {MAX_REQUIREMENTS_LIMIT}'
        )

    _apply_spaces_filter(space_key, credentials)
    client = get_requirement_yogi_client(credentials)

    path = f'{RY_BASE_PATH}/requirement2/{space_key}'
    params: Dict[str, Any] = {'limit': limit}
    if query:
        params['q'] = query

    data = client.get(path, params=params)

    # Normal shape: dict with 'results' list. Tolerate raw lists.
    if isinstance(data, list):
        results_raw = data
        meta: Dict[str, Any] = {}
    elif isinstance(data, dict):
        results_raw = data.get('results', []) or []
        meta = data
    else:
        results_raw = []
        meta = {}

    results = [_simplify_requirement(r) for r in results_raw if isinstance(r, dict)]
    response: Dict[str, Any] = {
        'results': results,
        'count': meta.get('count', len(results)),
        'limit': meta.get('limit', limit),
        'offset': meta.get('offset', 0),
    }
    if meta.get('explanation'):
        response['explanation'] = meta['explanation']

    return format_json_response(response)


# =============================================================================
# Write operations
# =============================================================================

@_handle_errors
def requirement_yogi_create_requirement(
    space_key: str,
    requirement_key: str,
    title: Optional[str] = None,
    content_html: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    credentials: Optional[AtlassianCredentials] = None,
) -> str:
    """Create a new Requirements Yogi requirement.

    API: ``POST /rest/reqs/1/requirement2/{spaceKey}/{key}``

    Args:
        space_key: Confluence space key.
        requirement_key: Unique requirement key to create (e.g. ``IAM_042``).
        title: Optional short title; stored as the requirement's title.
        content_html: Optional HTML body stored in ``storageData.data``.
            When omitted, ``title`` is used as a minimal body.
        properties: Optional ``{name: value}`` map of custom properties.
        credentials: Optional AtlassianCredentials.

    At least one of ``title``, ``content_html`` or ``properties`` must be
    provided so the requirement has some content.

    Returns:
        JSON string with the created requirement, or an error object.
    """
    if not space_key:
        raise ValidationError('space_key is required')
    if not requirement_key:
        raise ValidationError('requirement_key is required')
    if not (title or content_html or properties):
        raise ValidationError(
            'Provide at least one of: title, content_html, or properties'
        )

    _apply_spaces_filter(space_key, credentials)
    client = get_requirement_yogi_client(credentials)

    body_html = content_html or (f'<p>{title}</p>' if title else '')
    payload: Dict[str, Any] = {
        'key': requirement_key,
        'spaceKey': space_key,
        'storageData': {
            'type': 'storage',
            'data': body_html,
        },
    }
    if title:
        payload['title'] = title
    if properties:
        payload['properties'] = _properties_to_payload(properties)

    path = f'{RY_BASE_PATH}/requirement2/{space_key}/{requirement_key}'
    data = client.post(path, json=payload)
    return format_json_response(_simplify_requirement(data if isinstance(data, dict) else {}))


@_handle_errors
def requirement_yogi_update_requirement(
    space_key: str,
    requirement_key: str,
    title: Optional[str] = None,
    content_html: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    credentials: Optional[AtlassianCredentials] = None,
) -> str:
    """Update an existing Requirements Yogi requirement.

    API: ``PUT /rest/reqs/1/requirement2/{spaceKey}/{key}``

    Only the fields supplied are sent; omit a field to leave it unchanged.

    Args:
        space_key: Confluence space key.
        requirement_key: Requirement key to update.
        title: New title (optional).
        content_html: New HTML body for ``storageData.data`` (optional).
        properties: ``{name: value}`` map of properties to set (optional).
            Pass an empty dict to clear properties.
        credentials: Optional AtlassianCredentials.

    Returns:
        JSON string with the updated requirement, or an error object.
    """
    if not space_key:
        raise ValidationError('space_key is required')
    if not requirement_key:
        raise ValidationError('requirement_key is required')
    if title is None and content_html is None and properties is None:
        raise ValidationError(
            'Provide at least one of: title, content_html, or properties to update'
        )

    _apply_spaces_filter(space_key, credentials)
    client = get_requirement_yogi_client(credentials)

    payload: Dict[str, Any] = {
        'key': requirement_key,
        'spaceKey': space_key,
    }
    if title is not None:
        payload['title'] = title
    if content_html is not None:
        payload['storageData'] = {'type': 'storage', 'data': content_html}
    if properties is not None:
        payload['properties'] = _properties_to_payload(properties)

    path = f'{RY_BASE_PATH}/requirement2/{space_key}/{requirement_key}'
    data = client.put(path, json=payload)
    return format_json_response(_simplify_requirement(data if isinstance(data, dict) else {}))


@_handle_errors
def requirement_yogi_delete_requirement(
    space_key: str,
    requirement_key: str,
    credentials: Optional[AtlassianCredentials] = None,
) -> str:
    """Delete a Requirements Yogi requirement.

    API: ``DELETE /rest/reqs/1/requirement2/{spaceKey}/{key}``

    Args:
        space_key: Confluence space key.
        requirement_key: Requirement key to delete.
        credentials: Optional AtlassianCredentials.

    Returns:
        JSON string with ``{"success": True, "message": ...}`` or an error
        object.
    """
    if not space_key:
        raise ValidationError('space_key is required')
    if not requirement_key:
        raise ValidationError('requirement_key is required')

    _apply_spaces_filter(space_key, credentials)
    client = get_requirement_yogi_client(credentials)

    path = f'{RY_BASE_PATH}/requirement2/{space_key}/{requirement_key}'
    client.delete(path)
    return format_json_response({
        'success': True,
        'message': f'Requirement {space_key}/{requirement_key} deleted successfully',
    })


@_handle_errors
def requirement_yogi_bulk_update_requirements(
    space_key: str,
    requirements: List[Dict[str, Any]],
    credentials: Optional[AtlassianCredentials] = None,
) -> str:
    """Bulk update multiple Requirements Yogi requirements in a space.

    API: ``PUT /rest/reqs/1/requirement2/{spaceKey}``

    Args:
        space_key: Confluence space key.
        requirements: A list of requirement payloads. Each item should at
            least contain ``key``; supported convenience keys per item are
            ``title``, ``content_html`` and ``properties`` (a ``{name: value}``
            map). Raw API field names (``storageData``, ``properties`` as a
            list) are also forwarded as-is.
        credentials: Optional AtlassianCredentials.

    Returns:
        JSON string with the raw bulk-update result, or an error object.
    """
    if not space_key:
        raise ValidationError('space_key is required')
    if not requirements or not isinstance(requirements, list):
        raise ValidationError('requirements must be a non-empty list')

    _apply_spaces_filter(space_key, credentials)
    client = get_requirement_yogi_client(credentials)

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(requirements):
        if not isinstance(item, dict) or not item.get('key'):
            raise ValidationError(
                f"requirements[{idx}] must be a dict with a 'key' field"
            )
        payload: Dict[str, Any] = {'key': item['key'], 'spaceKey': space_key}
        if 'title' in item:
            payload['title'] = item['title']
        if 'content_html' in item:
            payload['storageData'] = {'type': 'storage', 'data': item['content_html']}
        elif 'storageData' in item:
            payload['storageData'] = item['storageData']
        if 'properties' in item:
            props = item['properties']
            if isinstance(props, dict):
                payload['properties'] = _properties_to_payload(props)
            elif isinstance(props, list):
                payload['properties'] = props
        normalized.append(payload)

    path = f'{RY_BASE_PATH}/requirement2/{space_key}'
    data = client.put(path, json={'requirements': normalized})
    return format_json_response(data if isinstance(data, (dict, list)) else {'result': data})
