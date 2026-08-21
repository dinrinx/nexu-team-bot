from aiogram.fsm.state import State, StatesGroup


class ProfileForm(StatesGroup):
    name = State()
    age = State()
    study_info = State()
    championships = State()
    roles = State()
    status = State()
    looking_for_roles = State()
    city = State()
    contact = State()
    about = State()
    photo = State()
    confirm = State()
