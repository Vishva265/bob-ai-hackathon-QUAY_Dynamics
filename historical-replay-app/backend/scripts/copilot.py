"""Query trusted operational evidence with no database writes or LLM prerequisite."""
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy.engine import make_url
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.database import make_engine
from app.api.copilot import readonly_session
from app.copilot.schemas import CopilotInput
from app.services.copilot import CopilotService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question',required=True)
    parser.add_argument('--database-url')
    for name in ('run-id','port-id','terminal-id','call-id','compare-run-id'):parser.add_argument('--'+name)
    parser.add_argument('--shift-index',type=int,default=0)
    parser.add_argument('--arrival-delay-hours',type=float)
    args=parser.parse_args();settings=get_settings();url=args.database_url or settings.database_url
    parsed=make_url(url)
    if parsed.get_backend_name()=='sqlite' and (not parsed.database or not Path(parsed.database).is_file()):
        parser.error('SQLite source does not exist; seed the dashboard first. This command never creates a database.')
    engine=make_engine(url);guard=readonly_session(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine))))
    try:
        payload=CopilotInput.model_validate({k:v for k,v in vars(args).items() if k!='database_url'})
        result=CopilotService(next(guard)).query(payload)
        print(json.dumps(result.model_dump(mode='json'),indent=2,ensure_ascii=True))
    finally:
        guard.close();engine.dispose()


if __name__=='__main__':main()
