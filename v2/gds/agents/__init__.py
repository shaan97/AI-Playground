"""Agents: vertices whose transition kernel is a mind (e.g. an LLM)."""

from __future__ import annotations

from .llm import LLMKernel

__all__ = ["LLMKernel"]
