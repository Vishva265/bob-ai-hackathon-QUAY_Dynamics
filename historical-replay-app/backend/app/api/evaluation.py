from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.services.evaluation import EvaluationPublication, latest, directory
from app.errors import DomainError

router=APIRouter(tags=['hackathon evaluation'])


@router.get('/evaluation/latest',response_model=EvaluationPublication)
def evaluation():
    return latest()


@router.get('/evaluation/report',response_class=FileResponse)
def report():
    path=directory()/'hackathon-evaluation.md'
    if not path.is_file():raise DomainError('EVALUATION_NOT_READY','Generate the evaluation report first',404)
    return FileResponse(path,media_type='text/markdown',filename='hackathon-evaluation.md')
