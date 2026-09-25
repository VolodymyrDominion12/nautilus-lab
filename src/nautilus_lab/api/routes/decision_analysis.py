from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from nautilus_lab.api.context import Lab
# For now, we mock the LLM client integration since it's a "future capability"
# or if llm_client exists, we would use it here.

router = APIRouter()

class AnalyzeDecisionsRequest(BaseModel):
    records: list[dict[str, Any]]
    question: str = "Analyze these decisions and provide insights."

@router.post("/api/decisions/analyze")
async def analyze_decisions(ctx: Lab, req: AnalyzeDecisionsRequest) -> dict[str, Any]:
    """
    Offline analysis of decision logs using LLM.
    This simulates an LLM call which would analyze the decision records.
    """
    if not req.records:
        raise HTTPException(status_code=400, detail="No records provided for analysis.")
    
    # Mock LLM analysis response
    mock_analysis = (
        f"Analyzed {len(req.records)} decision records.\n\n"
        f"Question: {req.question}\n\n"
        "Insights:\n"
        "- The robot primarily followed the market trend.\n"
        "- Risk management filters blocked 15% of signals.\n"
        "- The selected regime allowed for profitable entries.\n"
    )
    
    return {
        "status": "ok",
        "analysis": mock_analysis
    }
