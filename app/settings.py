"""
AgentOS Settings
================

Shared runtime objects for the AgentOS.
"""

from os import getenv

from agno.models.openai import OpenAIResponses


def default_model() -> OpenAIResponses:
    """Fresh model instance per agent — avoids memory leaks."""
    return OpenAIResponses(id="gpt-5.5")


def runtime_env() -> str:
    """``RUNTIME_ENV`` with the production default."""
    return getenv("RUNTIME_ENV", "prd")


def is_prd() -> bool:
    """True unless explicitly running dev — auth and owner checks rely on this."""
    return runtime_env() == "prd"
