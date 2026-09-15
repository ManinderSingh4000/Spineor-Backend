def job_seeker_menu():
    return {
        "reply": "Are you looking to submit your resume?",
        "buttons": [
            {"id": "submit_resume", "label": "Submit Resume"},
            {"id": "main_menu", "label": "Main Menu"}
        ],
        "input_enabled": False,
    }


def ask_email():
    return {
        "reply": "Please enter your email address to proceed.",
        "buttons": [{"id": "main_menu", "label": "Main Menu"}],
        "input_enabled": True,
    }

def confirm_submission(email: str):
    return {
        "reply": f"Thank you! We will process your application for {email}.",
        "buttons": [{"id": "main_menu", "label": "Main Menu"}],
        "input_enabled": False,
    }
