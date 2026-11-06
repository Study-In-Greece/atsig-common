"""
Response schemas the services share, for the routes that answer with a small body
(a delete, a signed URL). Each one has exactly the fields the routes returned as plain
dicts before, so the JSON is the same; the schema only documents it in OpenAPI.
"""

from pydantic import BaseModel


class IdRead(BaseModel):
    """The id of the resource that was deleted (an integer primary key)."""

    id: int


class FileUrlRead(BaseModel):
    """A signed URL of a stored file."""

    url: str
