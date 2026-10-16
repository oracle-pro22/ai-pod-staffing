"""Bounded copy polishing. The model can choose wording, never staffing facts."""
import json
import logging
from typing import Literal

from app.contracts import Contract

log = logging.getLogger(__name__)


class ExplanationCopy(Contract):
    version: Literal[1] = 1
    opening: Literal['team_first', 'work_first'] = 'team_first'
    effort: Literal['total_first', 'people_first'] = 'total_first'
    source: Literal['llm', 'fallback'] = 'fallback'


def enabled(settings):
    return bool(getattr(settings, 'staffing_explanation_enabled', True) and all(
        getattr(settings, key, '') for key in ('oci_genai_endpoint', 'oci_genai_compartment_id',
                                             'oci_genai_model_id', 'oci_genai_provider')))


def polish_copy(settings):
    """One short, tool-free OCI call; no names, employee evidence or numbers sent.

    Approved phrase IDs intentionally replace free-form prose: arbitrary rewritten
    text cannot be reliably checked for invented qualifications or availability.
    The UI fills these sentence patterns with the authoritative saved team facts.
    """
    fallback = ExplanationCopy()
    if not enabled(settings):
        return fallback
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agents.oci_model import build_model
        # This optional presentation call has its own small timeout/token bound,
        # not the agent's tool budget. No retries and no tools are supplied.
        bounded = settings.model_copy(update={
            'oci_timeout_seconds': getattr(settings, 'staffing_explanation_timeout_seconds', 6),
            'oci_max_output_tokens': 128,
        })
        response = build_model(bounded).invoke([
            SystemMessage(content='You polish the wording of a short staffing explanation. '
                'Choose only the approved sentence patterns below. Do not return prose, facts, names, '
                'numbers, claims of expertise, reasoning or tool calls. Return exactly one JSON object '
                'with keys opening and effort. '
                'opening: team_first means "[Lead] will lead the work, supported by [Members]"; '
                'work_first means "The work will be led by [Lead], with support from [Members]". '
                'effort: total_first puts total planned hours before team size; '
                'people_first puts team size before total planned hours. '
                'Allowed values: opening=team_first|work_first, effort=total_first|people_first.'),
            HumanMessage(content='Choose the clearest, concise wording for a Captain reviewing a proposed POD.'),
        ], config={'callbacks': []})
        content = response.content
        if isinstance(content, list):
            content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
        if not isinstance(content, str) or len(content) > 1000 or getattr(response, 'tool_calls', None):
            return fallback
        value = json.loads(content)
        if not isinstance(value, dict) or set(value) != {'opening', 'effort'}:
            return fallback
        return ExplanationCopy(**value, source='llm')
    except Exception as error:
        # Never log prompts, provider replies, credentials or employee details.
        log.warning('POD explanation uses fallback: type=%s', type(error).__name__)
        return fallback


def saved_copy(value):
    try:
        return ExplanationCopy.model_validate(value)
    except (ValueError, TypeError):
        return ExplanationCopy()
