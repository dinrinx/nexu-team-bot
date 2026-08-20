from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.constants import (
    CHAMPIONSHIPS,
    EDITABLE_FIELDS,
    MENU_BROWSE,
    MENU_CREATE,
    MENU_MATCHES,
    MENU_MY,
    ROLES,
    STATUS_HAS_TEAM,
    STATUS_LABELS,
    STATUS_LOOKING,
    TEXT_CANCEL,
    TEXT_CLEAR_PHOTO,
    TEXT_SKIP,
    TEXT_USE_DEFAULT_NAME,
    TEXT_USE_USERNAME,
)


def main_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=MENU_CREATE),
        KeyboardButton(text=MENU_BROWSE),
    )
    builder.row(
        KeyboardButton(text=MENU_MY),
        KeyboardButton(text=MENU_MATCHES),
    )
    return builder.as_markup(resize_keyboard=True)


def single_text_keyboard(*buttons: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for button in buttons:
        builder.row(KeyboardButton(text=button))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def optional_text_keyboard(include_clear_photo: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=TEXT_SKIP), KeyboardButton(text=TEXT_CANCEL))
    if include_clear_photo:
        builder.row(KeyboardButton(text=TEXT_CLEAR_PHOTO))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def name_keyboard() -> ReplyKeyboardMarkup:
    return single_text_keyboard(TEXT_USE_DEFAULT_NAME, TEXT_CANCEL)


def contact_keyboard(has_username: bool) -> ReplyKeyboardMarkup:
    if has_username:
        return single_text_keyboard(TEXT_USE_USERNAME, TEXT_CANCEL)
    return single_text_keyboard(TEXT_CANCEL)


def status_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=STATUS_LABELS[STATUS_LOOKING], callback_data=f"status:{STATUS_LOOKING}")
    builder.button(text=STATUS_LABELS[STATUS_HAS_TEAM], callback_data=f"status:{STATUS_HAS_TEAM}")
    builder.adjust(1)
    return builder.as_markup()


def multi_select_keyboard(field: str, selected: list[str]) -> InlineKeyboardMarkup:
    options = CHAMPIONSHIPS if field == "championships" else ROLES
    builder = InlineKeyboardBuilder()
    for index, option in enumerate(options):
        mark = "✅" if option in selected else "☑️"
        builder.button(text=f"{mark} {option}", callback_data=f"pick:{field}:{index}")
    builder.adjust(1)
    builder.button(text="Готово", callback_data=f"done:{field}")
    return builder.as_markup()


def profile_confirm_keyboard(create_mode: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить анкету", callback_data="confirm:save")
    if create_mode:
        builder.button(text="Начать заново", callback_data="confirm:restart")
    builder.button(text="Отменить", callback_data="confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def create_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать анкету", callback_data="profile:create")
    return builder.as_markup()


def my_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Редактировать", callback_data="my:edit")
    builder.button(text="Удалить анкету", callback_data="my:delete")
    builder.adjust(1)
    return builder.as_markup()


def edit_fields_keyboard(include_looking_for_roles: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fields = [
        "name",
        "championships",
        "roles",
        "status",
        "city",
        "contact",
        "about",
        "photo_file_id",
    ]
    if include_looking_for_roles:
        fields.insert(4, "looking_for_roles")

    for field in fields:
        builder.button(text=EDITABLE_FIELDS[field], callback_data=f"edit:{field}")

    builder.adjust(2)
    builder.button(text="Назад", callback_data="edit:back")
    return builder.as_markup()


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data="delete:yes")
    builder.button(text="Нет, оставить", callback_data="delete:no")
    builder.adjust(1)
    return builder.as_markup()


def feed_filters_keyboard(filters: dict[str, list[str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for index, option in enumerate(CHAMPIONSHIPS):
        mark = "✅" if option in filters.get("championships", []) else "☑️"
        builder.button(text=f"{mark} {option}", callback_data=f"filter:championships:{index}")

    for index, option in enumerate(ROLES):
        mark = "✅" if option in filters.get("roles", []) else "☑️"
        builder.button(text=f"{mark} {option}", callback_data=f"filter:roles:{index}")

    for index, option in enumerate(ROLES):
        mark = "✅" if option in filters.get("looking_for_roles", []) else "☑️"
        builder.button(text=f"{mark} Ищут: {option}", callback_data=f"filter:looking_for_roles:{index}")

    builder.adjust(1)
    builder.button(text="Сбросить фильтры", callback_data="filter:reset")
    builder.button(text="Показать анкеты", callback_data="filter:show")
    builder.adjust(1)
    return builder.as_markup()


def feed_reaction_keyboard(profile_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Откликнуться", callback_data=f"react:like:{profile_id}")
    builder.button(text="➡️ Пропустить", callback_data=f"react:pass:{profile_id}")
    builder.adjust(2)
    return builder.as_markup()
