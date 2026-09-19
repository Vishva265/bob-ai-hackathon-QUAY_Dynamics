from fastapi import APIRouter
from app.api.copilot import ReadDB
from app.services.data_lab import LabInput, validate_upload, simulate_upload

router = APIRouter(prefix='/data-lab', tags=['data lab'])


@router.post('/validate')
def validate(payload: LabInput, db: ReadDB):
    return validate_upload(db, payload)


@router.post('/simulate')
def simulate(payload: LabInput, db: ReadDB):
    return simulate_upload(db, payload)
