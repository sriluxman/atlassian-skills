"""Requirements Yogi tools (read-only).

Requirements Yogi is a Confluence plugin for requirement management. It exposes
a REST API at ``/rest/reqs/1/...`` on the Confluence host, secured with the
same Confluence authentication (PAT for Data Center, username + API token for
Cloud). This module exposes only the read operations.

Tools:
    - requirement_yogi_get_requirement: Get a single requirement
    - requirement_yogi_list_requirements: List/search requirements in a space
"""

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from typing import Any, Dict, Optional

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

RY_BASE_PATH = '/rest/reqs/1'
DEFAULT_REQUIREMENTS_LIMIT = 50
MAX_REQUIREMENTS_LIMIT = 200


# =============================================================================
# Helpers
# =============================================================================

def _apply_spaces_filter(space_key: str, credentials: Optional[AtlassianCredentials]) -> None:
    raw = get_requirement_yogi_spaces_filter(credentials)
    if not raw:
        return
    allowed = [s.strip() for s in raw.split(',') if s.strip()]
    if space_key not in allowed:
        raise ValidationError(
            f"Space '{space_key}' is not in the allowed Requirements Yogi spaces filter: {allowed}"
        )


def _strip_html(html: str) -> str:
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


def _handle_errors(func):
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
        except Exception as e:  # pragma: no cover
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
