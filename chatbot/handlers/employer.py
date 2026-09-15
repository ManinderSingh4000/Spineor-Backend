def employer_menu():
    return {
        "reply": "Welcome Employer. What would you like to do?",
        "buttons": [
            {"id": "post_job", "label": "Post a Job"},
            {"id": "search_candidates", "label": "Search Candidates"},
            {"id": "main_menu", "label": "Main Menu"}
        ],
        "input_enabled": False,
    }

def ask_job_title():
    return {
        "reply": "Please enter the job title for the new post.",
        "buttons": [{"id": "main_menu", "label": "Main Menu"}],
        "input_enabled": True,
    }

def confirm_job_post(job_title: str):
    return {
        "reply": f"The job '{job_title}' has been drafted successfully.",
        "buttons": [{"id": "main_menu", "label": "Main Menu"}],
        "input_enabled": False,
    }

def ask_skill_keyword():
    return {
        "reply": "Please enter a skill keyword to search for candidates.",
        "buttons": [{"id": "main_menu", "label": "Main Menu"}],
        "input_enabled": True,
    }

def show_search_results(skill: str):
    return {
        "reply": f"Here are the top candidates for '{skill}'.",
        "buttons": [{"id": "main_menu", "label": "Main Menu"}],
        "input_enabled": False,
    }
