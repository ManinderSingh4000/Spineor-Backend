import uuid
from enum import Enum


class State(str, Enum):
    START = "START"
    MAIN_MENU = "MAIN_MENU"

    JOB_SEEKER_MENU = "JOB_SEEKER_MENU"
    WAITING_FOR_EMAIL = "WAITING_FOR_EMAIL"

    EMPLOYER_MENU = "EMPLOYER_MENU"
    POST_JOB = "POST_JOB"
    WAITING_FOR_JOB_TITLE = "WAITING_FOR_JOB_TITLE"
    SEARCH_CANDIDATES = "SEARCH_CANDIDATES"

    SCAM_REPORT = "SCAM_REPORT"
    
    FACING_DIFFICULTY = "FACING_DIFFICULTY"


    END = "END"


class Session:
    def __init__(self):
        self.state = State.START
        self.metadata = {}


# In-memory store
sessions = {}


def get_or_create_session(session_id: str | None):
    if not session_id or session_id not in sessions:
        session_id = str(uuid.uuid4())
        sessions[session_id] = Session()

    return session_id, sessions[session_id]
