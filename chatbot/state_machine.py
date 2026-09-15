from chatbot.session import State
from chatbot.handlers import start, job_seeker, employer, scam , help



def handle_message(session, message=None, action_id=None):
    state = session.state

    # 🔹 Global Main Menu Reset
    if action_id == "main_menu":
        session.state = State.MAIN_MENU
        return start.main_menu()

    # 🔹 START → MAIN MENU
    if state == State.START:
        session.state = State.MAIN_MENU
        return start.main_menu()

    # 🔹 MAIN MENU
    if state == State.MAIN_MENU:

        if action_id == "job_seeker":
            session.state = State.JOB_SEEKER_MENU
            return job_seeker.job_seeker_menu()

        if action_id == "employer":
            session.state = State.EMPLOYER_MENU
            return employer.employer_menu()

        if action_id == "scam":
            session.state = State.SCAM_REPORT
            return scam.scam_info()
        
        if action_id == "facing_difficulty":
            session.state = State.FACING_DIFFICULTY
            return help.facing_difficulty()

    # 🔹 JOB SEEKER MENU
    if state == State.JOB_SEEKER_MENU:

        if action_id == "submit_resume":
            session.state = State.WAITING_FOR_EMAIL
            return job_seeker.ask_email()

    # 🔹 WAITING FOR EMAIL
    if state == State.WAITING_FOR_EMAIL:

        if not message:
            return {
                "reply": "Please enter a valid email address.",
                "buttons": [],
                "input_enabled": True,
            }

        session.metadata["email"] = message
        session.state = State.END
        return job_seeker.confirm_submission(message)

    # 🔹 EMPLOYER MENU
    if state == State.EMPLOYER_MENU:

        if action_id == "post_job":
            session.state = State.WAITING_FOR_JOB_TITLE
            return employer.ask_job_title()

        if action_id == "search_candidates":
            session.state = State.SEARCH_CANDIDATES
            return employer.ask_skill_keyword()

    # 🔹 WAITING FOR JOB TITLE
    if state == State.WAITING_FOR_JOB_TITLE:

        if not message:
            return {
                "reply": "Please enter a job title.",
                "buttons": [],
                "input_enabled": True,
            }

        session.metadata["job_title"] = message
        session.state = State.EMPLOYER_MENU
        return employer.confirm_job_post(message)

    # 🔹 SEARCH CANDIDATES
    if state == State.SEARCH_CANDIDATES:

        if not message:
            return {
                "reply": "Please enter a skill keyword.",
                "buttons": [],
                "input_enabled": True,
            }

        session.metadata["skill"] = message
        session.state = State.EMPLOYER_MENU
        return employer.show_search_results(message)
    
    if state == State.FACING_DIFFICULTY:

        if action_id == "main_menu":
            session.state = State.MAIN_MENU
            return start.main_menu()

        if action_id == "all_good":
            session.state = State.END
            return {
                "reply": "Glad everything is sorted! Let me know if you need anything else.",
                "buttons": [
                    {"id": "main_menu", "label": "Main Menu"}
                ],
                "input_enabled": False,
            }

    # 🔹 SAFE FALLBACK
    return {
        "reply": "Please select a valid option from the menu.",
        "buttons": [
            {"id": "main_menu", "label": "Back to Main Menu"}
        ],
        "input_enabled": False,
    }
