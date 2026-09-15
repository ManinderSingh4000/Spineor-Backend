
def main_menu():
    return {
        "reply": "Welcome to the Job Portal Chatbot. How can I assist you today?",
        "buttons": [
            {"id": "job_seeker", "label": "I am a Job Seeker"},
            {"id": "employer", "label": "I am an Employer"},
            {"id": "scam", "label": "Report a Scam"},
            {"id": "facing_difficulty", "label": "I need help"}
        ],
        "input_enabled": False,
    }
