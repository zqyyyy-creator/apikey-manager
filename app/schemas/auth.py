from pydantic import BaseModel


class AuthContext(BaseModel):
    client_id: str
    user_id: str
    team_id: str
