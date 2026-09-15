import base64
import hashlib
import json

from sqlalchemy import select

from app.errors import DomainError


class Repository:
    def __init__(self, session):
        self.session = session

    def get(self, model, identifier):
        row = self.session.get(model, identifier)
        if row is None:
            raise DomainError('NOT_FOUND', f'{model.__name__} {identifier} was not found', 404)
        return row

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row

    def all(self, model, *conditions):
        return list(self.session.scalars(select(model).where(*conditions).order_by(model.id)))

    def page(self, model, conditions, limit, cursor, context):
        fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()
        query = select(model).where(*conditions)
        if cursor:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if value['context'] != fingerprint or not isinstance(value['after'], str):
                    raise ValueError()
                query = query.where(model.id > value['after'])
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise DomainError('INVALID_CURSOR', 'Cursor is invalid or belongs to different filters')
        rows = list(self.session.scalars(query.order_by(model.id).limit(limit+1)))
        next_cursor = None
        if len(rows) > limit:
            next_cursor = base64.urlsafe_b64encode(json.dumps({'after': rows[limit-1].id, 'context': fingerprint}).encode()).decode()
        return dict(items=rows[:limit], next_cursor=next_cursor)


def page_values(items, limit, cursor, context):
    fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()
    items = sorted(items, key=lambda i: i['id'])
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if value['context'] != fingerprint or not isinstance(value['after'], str):
                raise ValueError()
            items = [i for i in items if i['id'] > value['after']]
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise DomainError('INVALID_CURSOR', 'Cursor is invalid or belongs to different filters')
    next_cursor = None
    if len(items) > limit:
        next_cursor = base64.urlsafe_b64encode(json.dumps({'after': items[limit-1]['id'], 'context': fingerprint}).encode()).decode()
    return dict(items=items[:limit], next_cursor=next_cursor)
