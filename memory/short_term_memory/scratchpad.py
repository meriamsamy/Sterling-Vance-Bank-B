class Scratchpad:
    """
    Stores the agent's internal working state.
    It is NOT part of the conversation history.
    """

    def __init__(self):
        self.goal = ""
        self.plan = []
        self.current_step = ""
        self.notes = []

    def set_goal(self, goal: str):
        self.goal = goal

    def add_plan_step(self, step: str):
        self.plan.append(step)

    def set_current_step(self, step: str):
        self.current_step = step

    def add_note(self, note: str):
        self.notes.append(note)

    def clear(self):
        self.goal = ""
        self.plan = []
        self.current_step = ""
        self.notes = []

    def get_state(self):
        return {
            "goal": self.goal,
            "plan": self.plan,
            "current_step": self.current_step,
            "notes": self.notes,
        }