"""
VALLEN CIHUY — AI PRD & System Architecture Generator.
Powered by the 'code-architect' skill and VALLEN NEXT engine.
Credit: VALLEN NEXT (vallennextproject)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from vallen_cli.providers.registry import get_registry
from vallen_cli.core.config import get_config
from vallen_cli.providers.base import Message


@dataclass
class CihuyBlueprint:
    title: str
    tagline: str
    summary: str
    target_stack: str
    prd_markdown: str
    schema_sql: str
    api_spec_markdown: str
    tasks_markdown: str
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_architect_guidance() -> str:
    """Fetch instructions from installed code-architect skill if available."""
    try:
        from vallen_cli.core.skills import get_skills
        skills = get_skills()
        if "code-architect" in skills:
            s = skills["code-architect"]
            text = getattr(s, "content", "") or getattr(s, "instructions", "")
            if text:
                return f"\n\n[Skill Guidance: code-architect]\n{text[:1500]}"
    except Exception:
        pass
    return ""


QUESTION_SYSTEM_PROMPT = """You are ⚡ VALLEN CIHUY, the elite AI Product Architect powered by the 'code-architect' skill.
Analyze the user's software idea and generate 3 to 4 critical, high-impact architectural discovery questions.
These questions must help nail down:
1. Target User / Access Roles (e.g. Single-user vs Multi-tenant, Mobile vs Desktop)
2. Database / Auth Architecture (e.g. Supabase, Local SQLite, Custom REST)
3. Killer Feature & Integrations (e.g. Payment gateway, thermal printer, AI background worker)
4. Release Scope / MVP Boundary

STRICT FORMAT INSTRUCTIONS:
Return ONLY a valid, parseable JSON object matching this schema:
{
  "questions": [
    {
      "id": "q1",
      "header": "Short Header (e.g. Target User)",
      "question": "Clear single-sentence prompt in Indonesian?",
      "options": [
        { "key": "A", "label": "Option Title (Rekomendasi)", "desc": "One short sentence explaining tradeoff or benefit." },
        { "key": "B", "label": "Option Title", "desc": "One short sentence explaining tradeoff or benefit." },
        { "key": "C", "label": "Option Title", "desc": "One short sentence explaining tradeoff or benefit." }
      ]
    }
  ]
}

Ensure the first option (A) is always the recommended best-practice choice and ends with '(Rekomendasi)'.
Do NOT include markdown formatting or commentary. Output raw JSON only."""


async def generate_discovery_questions(
    idea: str,
    target_stack: str = "Modern Fullstack",
    app_type: str = "Web App",
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Formulate 3-4 interactive A/B/C discovery questions for the user's idea."""
    cfg = get_config()
    registry = get_registry()
    provider = registry.active()

    if not provider:
        raise RuntimeError("No active LLM provider configured.")

    guidance = _get_architect_guidance()
    user_prompt = f"""Analyze this project idea and generate 3-4 discovery questions with A/B/C choices:

PROJECT IDEA:
{idea}

APPLICATION TYPE:
{app_type}

TARGET STACK:
{target_stack}
{guidance}

Generate the architectural questions now:"""

    messages = [
        Message(role="system", content=QUESTION_SYSTEM_PROMPT),
        Message(role="user", content=user_prompt),
    ]

    effective_model = model or provider.model or cfg.active_model
    res = await provider.complete(
        messages=messages,
        model=effective_model,
        temperature=0.2,
        max_tokens=2048,
    )

    content = res.content.strip()
    if content.startswith("```"):
        first_line_end = content.find("\n")
        if first_line_end != -1:
            content = content[first_line_end + 1:]
        if content.endswith("```"):
            content = content[:-3].rstrip()

    try:
        data = json.loads(content)
        questions = data.get("questions", [])
        if questions:
            return questions
    except Exception:
        pass

    # Fallback questions if LLM response couldn't be parsed
    return [
        {
            "id": "q1",
            "header": "Target Pengguna",
            "question": f"Siapa target pengguna utama untuk {idea[:40]}...?",
            "options": [
              { "key": "A", "label": "Pengguna Langsung / Internal (Rekomendasi)", "desc": "Sistem fokus untuk operasional cepat dengan akses admin & staf." },
              { "key": "B", "label": "Multi-Tenant / Publik", "desc": "Setiap pengguna atau cabang memiliki akun dan database terpisah." },
              { "key": "C", "label": "Self-Service Mobile", "desc": "Pengguna mengakses lewat smartphone masing-masing secara mandiri." }
            ]
        },
        {
            "id": "q2",
            "header": "Database & Auth",
            "question": "Bagaimana preferensi arsitektur data dan sistem autentikasi?",
            "options": [
              { "key": "A", "label": "Supabase + PostgreSQL (Rekomendasi)", "desc": "Relasional kuat, autentikasi instan, dan mendukung realtime subscription." },
              { "key": "B", "label": "Local SQLite / DuckDB", "desc": "Ringan, private, offline-first tanpa perlu koneksi internet eksternal." },
              { "key": "C", "label": "FastAPI / Node REST API", "desc": "Cocok untuk arsitektur microservice atau server mandiri kustom." }
            ]
        },
        {
            "id": "q3",
            "header": "Scope Rilis (MVP)",
            "question": "Berapa target ruang lingkup fitur untuk rilis pertama?",
            "options": [
              { "key": "A", "label": "Fokus Fitur Inti / MVP Cepat (Rekomendasi)", "desc": "Prioritaskan alur kerja utama selesai 100% sebelum fitur sekunder." },
              { "key": "B", "label": "Production Ready Lengkap", "desc": "Dilengkapi reporting omset, export Excel/PDF, dan dashboard visual." },
              { "key": "C", "label": "Automasi Penuh & Notifikasi", "desc": "Dilengkapi bot webhook (Telegram/WhatsApp) dan background workers." }
            ]
        }
    ]


BLUEPRINT_SYSTEM_PROMPT = """You are ⚡ VALLEN CIHUY, the elite AI Software Architect powered by the 'code-architect' skill from VALLEN NEXT (vallennext).
Your mission is to transform user ideas and their selected architectural choices into production-ready software blueprints that autonomous coding agents (VALLEN IDE & VALLEN CLI) can immediately execute without ambiguity.

Format your response as a valid, strictly parseable JSON object matching this schema:
{
  "title": "Short Catchy App Name",
  "tagline": "One punchy sentence describing the app",
  "summary": "2-3 paragraphs describing the core problem, target audience, and solution",
  "target_stack": "Recommended modern tech stack (Frontend, Backend, Database, Auth)",
  "prd_markdown": "# PRD: [App Name] ... (Detailed Markdown containing: 1. Objective, 2. User Personas & Stories, 3. Functional Requirements P0/P1/P2, 4. Non-Functional Requirements, 5. User Flows)",
  "schema_sql": "-- Production SQL Schema with tables, foreign keys, indexes, and sample seed data",
  "api_spec_markdown": "# API Specification ... (Endpoints table with Method, Path, Auth, Request Body, Response Example)",
  "tasks_markdown": "# Autonomous Implementation Tasks\\n\\n- [ ] Task 01: ...\\n- [ ] Task 02: ..."
}

STRICT INSTRUCTIONS:
1. Always output ONLY the JSON object. Do not prefix with conversational words or trailing commentary.
2. In all generated markdown files, append the footer credit:
   `> *Generated with ⚡ VALLEN CIHUY — Autonomous Engineering Studio by VALLEN NEXT (vallennext)*`
3. Strictly adhere to the user's architectural choices (A/B/C answers).
4. Make the tasks concrete, sequential, and bite-sized so an AI coding agent can pick them up step-by-step.
"""


async def generate_blueprint(
    idea: str,
    target_stack: str = "Modern Fullstack",
    app_type: str = "Web App",
    complexity: str = "MVP",
    answers: Optional[Dict[str, str]] = None,
    model: Optional[str] = None,
) -> CihuyBlueprint:
    """Generate a comprehensive PRD and technical blueprint from idea and interactive answers."""
    cfg = get_config()
    registry = get_registry()
    provider = registry.active()

    if not provider:
        raise RuntimeError("No active LLM provider configured.")

    guidance = _get_architect_guidance()

    answers_formatted = ""
    if answers:
        answers_formatted = "\n\nUSER ARCHITECTURAL DECISIONS (From Discovery Interview):\n"
        for q_id, ans in answers.items():
            answers_formatted += f"- {q_id}: {ans}\n"

    user_prompt = f"""Generate a complete software blueprint and PRD for this project:

IDEA / CONCEPT:
{idea}

APPLICATION TYPE:
{app_type}

TARGET TECH STACK PREFERENCE:
{target_stack}

COMPLEXITY LEVEL:
{complexity}
{answers_formatted}
{guidance}

Ensure the PRD is deeply technical, specific, incorporates all selected decisions, and is directly actionable for VALLEN NEXT coding agents."""

    messages = [
        Message(role="system", content=BLUEPRINT_SYSTEM_PROMPT),
        Message(role="user", content=user_prompt),
    ]

    effective_model = model or provider.model or cfg.active_model
    res = await provider.complete(
        messages=messages,
        model=effective_model,
        temperature=0.3,
        max_tokens=8192,
    )

    content = res.content.strip()

    if content.startswith("```"):
        first_line_end = content.find("\n")
        if first_line_end != -1:
            content = content[first_line_end + 1:]
        if content.endswith("```"):
            content = content[:-3].rstrip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            data = {
                "title": "VALLEN CIHUY Project",
                "tagline": "Crafted with VALLEN NEXT",
                "summary": idea,
                "target_stack": target_stack,
                "prd_markdown": content,
                "schema_sql": "-- Schema generated from prompt\n",
                "api_spec_markdown": "# API Spec\n",
                "tasks_markdown": "# Tasks\n- [ ] Task 01: Setup workspace\n",
            }

    credit_footer = "\n\n> *Generated with ⚡ VALLEN CIHUY — Autonomous Engineering Studio by VALLEN NEXT (vallennext)*\n"

    prd = data.get("prd_markdown", "")
    if credit_footer.strip() not in prd:
        prd += credit_footer

    tasks = data.get("tasks_markdown", "")
    if credit_footer.strip() not in tasks:
        tasks += credit_footer

    return CihuyBlueprint(
        title=data.get("title") or "VALLEN CIHUY Project",
        tagline=data.get("tagline") or "Autonomous Blueprint",
        summary=data.get("summary") or idea,
        target_stack=data.get("target_stack") or target_stack,
        prd_markdown=prd,
        schema_sql=data.get("schema_sql", ""),
        api_spec_markdown=data.get("api_spec_markdown", ""),
        tasks_markdown=tasks,
        raw_response=content,
    )
