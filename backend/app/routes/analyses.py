from fastapi import APIRouter, HTTPException, Request

from app.repositories.analyses import get_analysis
from app.workflow_models import AnalysisRequest

router = APIRouter()


@router.post("/conversations/{conversation_id}/analyses", status_code=202)
async def start_analysis(conversation_id: str, body: AnalysisRequest, request: Request):
    return request.app.state.analysis_runner.submit(conversation_id, body)


@router.get("/analyses/{analysis_id}")
def retrieve_analysis(analysis_id: str, request: Request):
    record = get_analysis(request.app.state.settings.database_path, analysis_id)
    if record is None:
        raise HTTPException(404, detail="Analysis not found.")
    return record
