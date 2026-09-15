from sqlalchemy import select
from app import models as m
from app.repositories.operations import Repository


class RecommendationRepository(Repository):
    def assignments(self, run_id):
        return self.all(m.BerthAssignment, m.BerthAssignment.run_id == run_id)

    def decisions(self, run_id):
        return self.all(m.RecommendationDecision, m.RecommendationDecision.run_id == run_id)

    def latest_runs(self):
        return list(self.session.scalars(select(m.RecommendationRun).order_by(m.RecommendationRun.created_at.desc())))
