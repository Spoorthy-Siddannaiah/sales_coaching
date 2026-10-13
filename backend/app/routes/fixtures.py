from fastapi import APIRouter, Request

from app.services.fixture_import import import_fixture
from app.workflow_models import FixtureRequest

router = APIRouter()


@router.post("/imports/fixture")
def fixture(body: FixtureRequest, request: Request):
    return import_fixture(request.app.state.settings.database_path, body.fixture)
