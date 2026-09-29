"""
VALLEN CIHUY — FastAPI router for PRD Studio & Autonomous Bridge.
Credit: VALLEN NEXT (vallennextproject)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .generator import generate_blueprint, generate_discovery_questions, CihuyBlueprint
from vallen_cli.core.workspace import get_workspace

router = APIRouter(prefix="/api/cihuy", tags=["cihuy"])


class QuestionRequest(BaseModel):
    idea: str
    target_stack: Optional[str] = "Next.js 14 + Tailwind + Supabase PostgreSQL"
    app_type: Optional[str] = "Web & Responsive App"
    model: Optional[str] = None


class GenerateRequest(BaseModel):
    idea: str
    target_stack: Optional[str] = "Next.js + Tailwind + Supabase"
    app_type: Optional[str] = "Web Application"
    complexity: Optional[str] = "MVP (Fast)"
    answers: Optional[Dict[str, str]] = None
    model: Optional[str] = None


class ExportRequest(BaseModel):
    title: str
    prd_markdown: str
    schema_sql: Optional[str] = ""
    api_spec_markdown: Optional[str] = ""
    tasks_markdown: Optional[str] = ""
    target_dir: Optional[str] = None


PRESET_TEMPLATES = [
    {
        "id": "pos-kasir",
        "title": "Aplikasi Kasir POS & Antrean Laundry",
        "app_type": "Web & Responsive App",
        "target_stack": "Next.js 14, Tailwind CSS, Supabase PostgreSQL",
        "complexity": "MVP (Cepat & Fokus)",
        "idea": "Aplikasi Point of Sale (POS) modern untuk usaha laundry kiloan dan satuan. Fitur: input nota order masuk, kalkulasi otomatis berat/harga, pelacak status cuci-kering-setrika-siap ambil, cetak struk via bluetooth thermal printer, serta dashboard laporan omset harian kasir.",
    },
    {
        "id": "micro-saas",
        "title": "AI Content Repurposer Micro-SaaS",
        "app_type": "SaaS Platform",
        "target_stack": "FastAPI, React Vite, PostgreSQL, Stripe/Midtrans",
        "complexity": "Medium (Production Ready)",
        "idea": "Platform SaaS yang mengubah satu video YouTube atau audio podcast menjadi 10 thread Twitter/X, artikel LinkedIn, dan rangkuman blog post otomatis menggunakan AI. Dilengkapi sistem kredit token, autentikasi Google, dan integrasi payment gateway langganan bulanan.",
    },
    {
        "id": "inventory-erp",
        "title": "Sistem Manajemen Gudang & Stok Barang",
        "app_type": "Internal Dashboard",
        "target_stack": "Django / FastAPI, Vue 3, SQLite/PostgreSQL",
        "complexity": "Medium (Production Ready)",
        "idea": "Sistem inventaris internal untuk toko retail multi-cabang. Fitur: scan barcode SKU barang, mutasi transfer antar cabang, notifikasi stok menipis (low stock alert), rekap kartu stok, dan export laporan bulanan ke Excel/PDF.",
    },
    {
        "id": "cli-devkit",
        "title": "Developer Automation CLI Tool",
        "app_type": "CLI Utility",
        "target_stack": "Python Click/Rich atau Rust",
        "complexity": "MVP (Cepat & Fokus)",
        "idea": "Terminal CLI tool untuk automasi setup boilerplate repository baru: auto konfigurasi Git pre-commit hooks, linter formatting, Dockerfile multi-stage, dan GitHub Actions CI/CD pipeline hanya dengan 1 perintah interaktif.",
    }
]


@router.get("/templates")
def list_templates() -> List[Dict[str, Any]]:
    """Return pre-configured software blueprint templates."""
    return PRESET_TEMPLATES


@router.post("/questions")
async def get_discovery_questions(req: QuestionRequest) -> Dict[str, Any]:
    """Formulate 3-4 interactive discovery questions powered by code-architect skill."""
    if not req.idea or not req.idea.strip():
        raise HTTPException(status_code=400, detail="Ide aplikasi tidak boleh kosong.")

    try:
        questions = await generate_discovery_questions(
            idea=req.idea,
            target_stack=req.target_stack or "Modern Fullstack",
            app_type=req.app_type or "Web App",
            model=req.model,
        )
        return {
            "status": "ok",
            "skill": "code-architect",
            "questions": questions,
            "credit": "VALLEN NEXT (vallennextproject)",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal merumuskan pertanyaan: {e}")


@router.post("/generate")
async def generate_cihuy_blueprint(req: GenerateRequest) -> Dict[str, Any]:
    """Generate complete PRD, architecture, and task blueprint from idea and user answers."""
    if not req.idea or not req.idea.strip():
        raise HTTPException(status_code=400, detail="Ide aplikasi tidak boleh kosong.")

    try:
        blueprint = await generate_blueprint(
            idea=req.idea,
            target_stack=req.target_stack or "Modern Fullstack",
            app_type=req.app_type or "Web App",
            complexity=req.complexity or "MVP",
            answers=req.answers,
            model=req.model,
        )
        return {
            "status": "ok",
            "blueprint": blueprint.to_dict(),
            "credit": "VALLEN NEXT (vallennextproject)",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal generate blueprint: {e}")


@router.post("/export")
def export_blueprint_to_workspace(req: ExportRequest) -> Dict[str, Any]:
    """Export generated blueprint files (PRD.md, SCHEMA.sql, TASKS.md) directly into workspace."""
    ws = get_workspace()
    dest_path = req.target_dir or ws.active_project_path or os.getcwd()
    dest = Path(dest_path).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    written_files = []

    # 1. PRD.md
    prd_file = dest / "PRD.md"
    prd_file.write_text(req.prd_markdown, encoding="utf-8")
    written_files.append("PRD.md")

    # 2. SCHEMA.sql (if provided)
    if req.schema_sql and req.schema_sql.strip():
        schema_file = dest / "SCHEMA.sql"
        schema_file.write_text(req.schema_sql, encoding="utf-8")
        written_files.append("SCHEMA.sql")

    # 3. TASKS.md (if provided)
    if req.tasks_markdown and req.tasks_markdown.strip():
        tasks_file = dest / "TASKS.md"
        tasks_file.write_text(req.tasks_markdown, encoding="utf-8")
        written_files.append("TASKS.md")

    # 4. API_SPEC.md (if provided)
    if req.api_spec_markdown and req.api_spec_markdown.strip():
        api_file = dest / "API_SPEC.md"
        api_file.write_text(req.api_spec_markdown, encoding="utf-8")
        written_files.append("API_SPEC.md")

    return {
        "status": "ok",
        "workspace": str(dest),
        "files": written_files,
        "credit": "VALLEN NEXT (vallennextproject)",
        "message": f"✓ Berhasil mengekspor {len(written_files)} file blueprint ke {dest.name}/",
    }
