from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message, User

from bot.config import Settings, load_settings
from bot.constants import (
    CHAMPIONSHIPS,
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
from bot.database import Database, Profile, now_iso
from bot.keyboards import (
    contact_keyboard,
    create_profile_keyboard,
    delete_confirm_keyboard,
    edit_fields_keyboard,
    feed_filters_keyboard,
    feed_reaction_keyboard,
    main_menu,
    multi_select_keyboard,
    my_profile_keyboard,
    name_keyboard,
    optional_text_keyboard,
    profile_confirm_keyboard,
    single_text_keyboard,
    status_keyboard,
)
from bot.states import BrowseState, ProfileForm


router = Router()


def user_username(user: User) -> str | None:
    if user.username:
        return f"@{user.username}"
    return None


def build_default_draft(user: User, existing: Profile | None = None) -> dict[str, Any]:
    username = user_username(user)
    if existing is not None:
        return {
            "name": existing.name,
            "championships": list(existing.championships),
            "roles": list(existing.roles),
            "status": existing.status,
            "looking_for_roles": list(existing.looking_for_roles),
            "city": existing.city,
            "username": username or existing.username,
            "contact": existing.contact,
            "about": existing.about,
            "photo_file_id": existing.photo_file_id,
            "created_at": existing.created_at,
        }

    return {
        "name": user.full_name,
        "championships": [],
        "roles": [],
        "status": STATUS_LOOKING,
        "looking_for_roles": [],
        "city": "",
        "username": username,
        "contact": username or "",
        "about": None,
        "photo_file_id": None,
        "created_at": now_iso(),
    }


def format_tags(values: list[str]) -> str:
    return ", ".join(values)


def format_profile_card(profile: Profile | dict[str, Any], reveal_contact: bool = False) -> str:
    if isinstance(profile, Profile):
        data = {
            "name": profile.name,
            "championships": profile.championships,
            "roles": profile.roles,
            "status": profile.status,
            "looking_for_roles": profile.looking_for_roles,
            "city": profile.city,
            "contact": profile.contact,
            "about": profile.about,
        }
    else:
        data = profile

    lines = [
        f"Имя: {data['name']}",
        f"Чемпионаты: {format_tags(data['championships'])}",
        f"Сильные стороны: {format_tags(data['roles'])}",
        f"Статус: {STATUS_LABELS[data['status']]}",
    ]

    if data["status"] == STATUS_HAS_TEAM and data.get("looking_for_roles"):
        lines.append(f"Кого ищут в команду: {format_tags(data['looking_for_roles'])}")

    lines.append(f"Город / регион: {data['city']}")

    about = data.get("about")
    if about:
        lines.append(f"О себе: {about}")

    if reveal_contact:
        lines.append(f"Контакт: {data['contact']}")

    return "\n".join(lines)


def format_filters(filters: dict[str, list[str]]) -> str:
    championships = format_tags(filters.get("championships", [])) if filters.get("championships") else "любые"
    roles = format_tags(filters.get("roles", [])) if filters.get("roles") else "любые"
    looking = (
        format_tags(filters.get("looking_for_roles", []))
        if filters.get("looking_for_roles")
        else "любые"
    )
    return (
        "Фильтры ленты:\n"
        f"• Чемпионаты: {championships}\n"
        f"• Сильные стороны: {roles}\n"
        f"• Кого ищут: {looking}\n\n"
        "Настрой фильтры и нажми «Показать анкеты»."
    )


async def send_profile_message(
    message: Message,
    profile: Profile | dict[str, Any],
    reply_markup=None,
    reveal_contact: bool = False,
) -> None:
    card_text = format_profile_card(profile, reveal_contact=reveal_contact)
    photo_file_id = profile.photo_file_id if isinstance(profile, Profile) else profile.get("photo_file_id")

    if photo_file_id:
        if len(card_text) <= 1000:
            await message.answer_photo(photo=photo_file_id, caption=card_text, reply_markup=reply_markup)
            return
        await message.answer_photo(photo=photo_file_id, caption="Фото участника")

    await message.answer(card_text, reply_markup=reply_markup)


async def ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.name)
    draft = (await state.get_data())["draft"]
    await message.answer(
        "Шаг 1/8. Как тебя зовут?\n"
        f"Сейчас в черновике: {draft['name']}\n"
        "Можешь отправить своё имя текстом или оставить имя из Telegram.",
        reply_markup=name_keyboard(),
    )


async def ask_championships(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.championships)
    draft = (await state.get_data())["draft"]
    await message.answer(
        "Шаг 2/8. Выбери чемпионаты, которые тебе интересны.\n"
        "Можно отметить несколько вариантов.",
        reply_markup=multi_select_keyboard("championships", draft["championships"]),
    )


async def ask_roles(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.roles)
    draft = (await state.get_data())["draft"]
    await message.answer(
        "Шаг 3/8. В чём ты силён(сильна)?\n"
        "Можно отметить несколько ролей.",
        reply_markup=multi_select_keyboard("roles", draft["roles"]),
    )


async def ask_status(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.status)
    await message.answer(
        "Шаг 4/8. Какой у тебя статус сейчас?",
        reply_markup=status_keyboard(),
    )


async def ask_looking_for_roles(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.looking_for_roles)
    draft = (await state.get_data())["draft"]
    await message.answer(
        "Шаг 5/8. Кого вам не хватает в команде?\n"
        "Можно отметить несколько ролей.",
        reply_markup=multi_select_keyboard("looking_for_roles", draft["looking_for_roles"]),
    )


async def ask_city(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.city)
    await message.answer(
        "Шаг 6/8. Напиши город или регион коротко.",
        reply_markup=single_text_keyboard(TEXT_CANCEL),
    )


async def ask_contact(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.contact)
    draft = (await state.get_data())["draft"]
    has_username = bool(draft.get("username"))
    current_contact = draft.get("contact") or "не указан"
    text = (
        "Шаг 7/8. Как с тобой связаться после мэтча?\n"
        "До взаимного мэтча контакт никому не показывается.\n"
    )
    if has_username:
        text += f"Можно оставить текущий контакт: {current_contact}"
    else:
        text += "У тебя нет @username, поэтому напиши удобный контакт вручную."
    await message.answer(text, reply_markup=contact_keyboard(has_username))


async def ask_about(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.about)
    await message.answer(
        "Шаг 8/8. Расскажи коротко о себе. Это поле можно пропустить.",
        reply_markup=optional_text_keyboard(),
    )


async def ask_photo(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.photo)
    draft = (await state.get_data())["draft"]
    await message.answer(
        "Финальный штрих: можно отправить одну фотографию для анкеты.\n"
        "Если не хочешь добавлять фото, нажми «Пропустить».",
        reply_markup=optional_text_keyboard(include_clear_photo=bool(draft.get("photo_file_id"))),
    )


async def show_profile_preview(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.confirm)
    data = await state.get_data()
    draft = data["draft"]
    create_mode = data.get("mode") == "create"
    await message.answer("Вот как будет выглядеть твоя анкета:")
    await send_profile_message(
        message,
        draft,
        reply_markup=profile_confirm_keyboard(create_mode=create_mode),
        reveal_contact=True,
    )


async def start_create_flow(message: Message, user: User, state: FSMContext, db: Database) -> None:
    existing = db.get_profile(user.id)
    await state.clear()
    await state.update_data(
        mode="create",
        draft=build_default_draft(user, existing),
    )
    await ask_name(message, state)


async def start_edit_flow(message: Message, user: User, state: FSMContext, db: Database, field: str) -> None:
    existing = db.get_profile(user.id)
    if existing is None:
        await message.answer("Анкеты пока нет. Сначала создай её.", reply_markup=create_profile_keyboard())
        return

    draft = build_default_draft(user, existing)
    await state.clear()
    await state.update_data(mode="edit", edit_field=field, draft=draft)

    if field == "name":
        await ask_name(message, state)
    elif field == "championships":
        await ask_championships(message, state)
    elif field == "roles":
        await ask_roles(message, state)
    elif field == "status":
        await ask_status(message, state)
    elif field == "looking_for_roles":
        await ask_looking_for_roles(message, state)
    elif field == "city":
        await ask_city(message, state)
    elif field == "contact":
        await ask_contact(message, state)
    elif field == "about":
        await ask_about(message, state)
    elif field == "photo_file_id":
        await ask_photo(message, state)


async def route_after_field(message: Message, state: FSMContext, completed_field: str) -> None:
    data = await state.get_data()
    draft = data["draft"]
    mode = data.get("mode")
    edit_field = data.get("edit_field")

    if mode == "edit" and edit_field and edit_field != completed_field:
        await show_profile_preview(message, state)
        return

    if mode == "edit":
        if completed_field == "status" and draft["status"] == STATUS_HAS_TEAM:
            await ask_looking_for_roles(message, state)
            return
        await show_profile_preview(message, state)
        return

    if completed_field == "name":
        await ask_championships(message, state)
    elif completed_field == "championships":
        await ask_roles(message, state)
    elif completed_field == "roles":
        await ask_status(message, state)
    elif completed_field == "status":
        if draft["status"] == STATUS_HAS_TEAM:
            await ask_looking_for_roles(message, state)
        else:
            draft["looking_for_roles"] = []
            await state.update_data(draft=draft)
            await ask_city(message, state)
    elif completed_field == "looking_for_roles":
        await ask_city(message, state)
    elif completed_field == "city":
        await ask_contact(message, state)
    elif completed_field == "contact":
        await ask_about(message, state)
    elif completed_field == "about":
        await ask_photo(message, state)
    elif completed_field == "photo_file_id":
        await show_profile_preview(message, state)


def build_profile_from_draft(user_id: int, draft: dict[str, Any]) -> Profile:
    return Profile(
        user_id=user_id,
        name=draft["name"],
        championships=list(draft["championships"]),
        roles=list(draft["roles"]),
        status=draft["status"],
        looking_for_roles=list(draft.get("looking_for_roles", [])),
        city=draft["city"],
        username=draft.get("username"),
        contact=draft["contact"],
        about=draft.get("about"),
        photo_file_id=draft.get("photo_file_id"),
        created_at=draft["created_at"],
        updated_at=now_iso(),
    )


async def show_my_profile(message: Message, db: Database, user_id: int) -> None:
    profile = db.get_profile(user_id)
    if profile is None:
        await message.answer(
            "У тебя пока нет анкеты. Создай её, чтобы попасть в ленту.",
            reply_markup=create_profile_keyboard(),
        )
        return

    await send_profile_message(
        message,
        profile,
        reply_markup=my_profile_keyboard(),
        reveal_contact=True,
    )


async def show_feed_filters(message: Message, user_id: int, state: FSMContext, db: Database) -> None:
    profile = db.get_profile(user_id)
    if profile is None:
        await message.answer(
            "Сначала создай свою анкету, а потом можно смотреть других.",
            reply_markup=create_profile_keyboard(),
        )
        return

    await state.clear()
    filters = {"championships": [], "roles": [], "looking_for_roles": []}
    await state.set_state(BrowseState.filters)
    await state.update_data(feed_filters=filters)
    await message.answer(format_filters(filters), reply_markup=feed_filters_keyboard(filters))


async def show_next_profile(message: Message, user_id: int, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    filters = data.get("feed_filters", {"championships": [], "roles": [], "looking_for_roles": []})
    candidates = db.get_feed_candidates(user_id, filters)
    if not candidates:
        await message.answer("Анкет пока нет или ты уже просмотрел(а) всё. Загляни позже.")
        return

    await send_profile_message(
        message,
        candidates[0],
        reply_markup=feed_reaction_keyboard(candidates[0].user_id),
    )


async def safe_remove_inline_keyboard(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        return


async def send_match_notifications(bot: Bot, first_profile: Profile, second_profile: Profile) -> None:
    first_text = (
        f"🎉 У тебя мэтч с {second_profile.name}!\n"
        f"Вот контакт: {second_profile.contact}"
    )
    second_text = (
        f"🎉 У тебя мэтч с {first_profile.name}!\n"
        f"Вот контакт: {first_profile.contact}"
    )

    for chat_id, text in (
        (first_profile.user_id, first_text),
        (second_profile.user_id, second_text),
    ):
        try:
            await bot.send_message(chat_id, text, reply_markup=main_menu())
        except TelegramForbiddenError:
            logging.warning("Could not notify user %s about match", chat_id)


def format_matches(matches: list[tuple[Profile, str]]) -> str:
    if not matches:
        return "Мэтчей пока нет. Возвращайся в ленту и ищи команду."

    lines = ["Твои мэтчи:"]
    for profile, created_at in matches:
        created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        lines.append(f"• {profile.name} — {profile.contact} ({created})")
    return "\n".join(lines)


def format_stats(stats: dict[str, Any]) -> str:
    championship_lines = [
        f"• {championship}: {count}"
        for championship, count in sorted(stats["by_championship"].items())
    ]
    if not championship_lines:
        championship_lines = ["• Пока нет данных"]

    return (
        "Статистика бота:\n"
        f"• Всего анкет: {stats['profiles_count']}\n"
        f"• Ищу команду: {stats['by_status'].get(STATUS_LOOKING, 0)}\n"
        f"• Есть команда: {stats['by_status'].get(STATUS_HAS_TEAM, 0)}\n"
        f"• Лайков: {stats['likes_count']}\n"
        f"• Взаимных мэтчей: {stats['matches_count']}\n\n"
        "Разбивка по чемпионатам:\n"
        + "\n".join(championship_lines)
    )


def toggle_option(options: list[str], value: str) -> list[str]:
    updated = list(options)
    if value in updated:
        updated.remove(value)
    else:
        updated.append(value)
    return updated


@router.message(CommandStart())
async def start_handler(message: Message, db: Database) -> None:
    profile = db.get_profile(message.from_user.id)
    if profile is None:
        text = (
            "Привет! Я помогу участникам NEXU найти команду для кейс-чемпионатов.\n\n"
            "Сначала создай анкету, потом сможешь смотреть других участников и получать мэтчи."
        )
        await message.answer(text, reply_markup=main_menu())
        await message.answer("Готов(а) начать?", reply_markup=create_profile_keyboard())
        return

    await message.answer(
        "Привет! Твоя анкета уже есть в базе. Можно смотреть ленту, редактировать профиль и проверять мэтчи.",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
@router.message(F.text == TEXT_CANCEL)
async def cancel_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущее действие отменено.", reply_markup=main_menu())


@router.message(Command("my"))
@router.message(F.text == MENU_MY)
async def my_handler(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await show_my_profile(message, db, message.from_user.id)


@router.message(Command("matches"))
@router.message(F.text == MENU_MATCHES)
async def matches_handler(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await message.answer(format_matches(db.get_matches_for_user(message.from_user.id)), reply_markup=main_menu())


@router.message(F.text == MENU_CREATE)
async def menu_create_handler(message: Message, state: FSMContext, db: Database) -> None:
    await start_create_flow(message, message.from_user, state, db)


@router.message(F.text == MENU_BROWSE)
async def menu_browse_handler(message: Message, state: FSMContext, db: Database) -> None:
    await show_feed_filters(message, message.from_user.id, state, db)


@router.callback_query(F.data == "profile:create")
async def profile_create_callback(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    await start_create_flow(callback.message, callback.from_user, state, db)


@router.message(ProfileForm.name, F.text)
async def profile_name_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]

    if message.text == TEXT_USE_DEFAULT_NAME:
        draft["name"] = message.from_user.full_name if message.from_user else draft["name"]
    else:
        draft["name"] = message.text.strip()

    if not draft["name"]:
        await message.answer("Имя не должно быть пустым.")
        return

    await state.update_data(draft=draft)
    await route_after_field(message, state, "name")


@router.callback_query(ProfileForm.championships, F.data.startswith("pick:championships:"))
@router.callback_query(ProfileForm.roles, F.data.startswith("pick:roles:"))
@router.callback_query(ProfileForm.looking_for_roles, F.data.startswith("pick:looking_for_roles:"))
async def pick_multi_value(callback: CallbackQuery, state: FSMContext) -> None:
    _, field, raw_index = callback.data.split(":")
    index = int(raw_index)
    options = CHAMPIONSHIPS if field == "championships" else ROLES
    value = options[index]

    data = await state.get_data()
    draft = data["draft"]
    draft[field] = toggle_option(draft.get(field, []), value)
    await state.update_data(draft=draft)

    await callback.message.edit_reply_markup(reply_markup=multi_select_keyboard(field, draft[field]))
    await callback.answer()


@router.callback_query(ProfileForm.championships, F.data == "done:championships")
@router.callback_query(ProfileForm.roles, F.data == "done:roles")
@router.callback_query(ProfileForm.looking_for_roles, F.data == "done:looking_for_roles")
async def done_multi_value(callback: CallbackQuery, state: FSMContext) -> None:
    _, field = callback.data.split(":")
    data = await state.get_data()
    draft = data["draft"]
    selected = draft.get(field, [])
    if not selected:
        await callback.answer("Нужно выбрать хотя бы один вариант.", show_alert=True)
        return

    await callback.answer()
    await route_after_field(callback.message, state, field)


@router.callback_query(ProfileForm.status, F.data.startswith("status:"))
async def status_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _, status = callback.data.split(":")
    data = await state.get_data()
    draft = data["draft"]
    draft["status"] = status
    if status == STATUS_LOOKING:
        draft["looking_for_roles"] = []
    await state.update_data(draft=draft)
    await callback.answer()
    await route_after_field(callback.message, state, "status")


@router.message(ProfileForm.city, F.text)
async def city_handler(message: Message, state: FSMContext) -> None:
    city = message.text.strip()
    if not city:
        await message.answer("Город или регион не должен быть пустым.")
        return

    data = await state.get_data()
    draft = data["draft"]
    draft["city"] = city
    await state.update_data(draft=draft)
    await route_after_field(message, state, "city")


@router.message(ProfileForm.contact, F.text)
async def contact_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]
    username = user_username(message.from_user)
    draft["username"] = username

    if message.text == TEXT_USE_USERNAME:
        if not username:
            await message.answer("Сейчас у тебя нет @username, напиши контакт текстом.")
            return
        draft["contact"] = username
    else:
        draft["contact"] = message.text.strip()

    if not draft["contact"]:
        await message.answer("Контакт не должен быть пустым.")
        return

    await state.update_data(draft=draft)
    await route_after_field(message, state, "contact")


@router.message(ProfileForm.about, F.text)
async def about_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]
    draft["about"] = None if message.text == TEXT_SKIP else message.text.strip()
    if draft["about"] == "":
        draft["about"] = None
    await state.update_data(draft=draft)
    await route_after_field(message, state, "about")


@router.message(ProfileForm.photo, F.photo)
async def photo_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]
    draft["photo_file_id"] = message.photo[-1].file_id
    await state.update_data(draft=draft)
    await route_after_field(message, state, "photo_file_id")


@router.message(ProfileForm.photo, F.text)
async def photo_text_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]

    if message.text == TEXT_SKIP:
        await route_after_field(message, state, "photo_file_id")
        return

    if message.text == TEXT_CLEAR_PHOTO:
        draft["photo_file_id"] = None
        await state.update_data(draft=draft)
        await route_after_field(message, state, "photo_file_id")
        return

    await message.answer("Отправь одну фотографию или нажми «Пропустить».")


@router.callback_query(ProfileForm.confirm, F.data == "confirm:save")
async def confirm_save_handler(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    draft = data["draft"]
    profile = build_profile_from_draft(callback.from_user.id, draft)
    db.upsert_profile(profile)
    await state.clear()
    await callback.answer("Анкета сохранена.")
    await callback.message.answer("Анкета сохранена. Теперь можно смотреть ленту.", reply_markup=main_menu())


@router.callback_query(ProfileForm.confirm, F.data == "confirm:restart")
async def confirm_restart_handler(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    await start_create_flow(callback.message, callback.from_user, state, db)


@router.callback_query(ProfileForm.confirm, F.data == "confirm:cancel")
async def confirm_cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Сохранение отменено.")
    await callback.message.answer("Черновик анкеты не сохранён.", reply_markup=main_menu())


@router.callback_query(F.data == "my:edit")
async def my_edit_handler(callback: CallbackQuery, db: Database) -> None:
    profile = db.get_profile(callback.from_user.id)
    if profile is None:
        await callback.answer("Анкеты пока нет.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(
        "Что хочешь отредактировать?",
        reply_markup=edit_fields_keyboard(include_looking_for_roles=profile.status == STATUS_HAS_TEAM),
    )


@router.callback_query(F.data.startswith("edit:"))
async def edit_field_handler(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, field = callback.data.split(":")
    if field == "back":
        await callback.answer()
        await show_my_profile(callback.message, db, callback.from_user.id)
        return

    await callback.answer()
    await start_edit_flow(callback.message, callback.from_user, state, db, field)


@router.callback_query(F.data == "my:delete")
async def my_delete_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Удалить анкету? Все лайки и мэтчи тоже будут удалены.",
        reply_markup=delete_confirm_keyboard(),
    )


@router.callback_query(F.data == "delete:yes")
async def confirm_delete_handler(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    db.delete_profile(callback.from_user.id)
    await state.clear()
    await callback.answer("Анкета удалена.")
    await callback.message.answer("Анкета удалена. Если захочешь вернуться, создай новую.", reply_markup=main_menu())


@router.callback_query(F.data == "delete:no")
async def cancel_delete_handler(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    await show_my_profile(callback.message, db, callback.from_user.id)


@router.callback_query(F.data.startswith("filter:"))
async def feed_filters_handler(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if callback.data == "filter:show":
        await callback.answer()
        await show_next_profile(callback.message, callback.from_user.id, state, db)
        return

    data = await state.get_data()
    filters = data.get("feed_filters", {"championships": [], "roles": [], "looking_for_roles": []})

    if callback.data == "filter:reset":
        filters = {"championships": [], "roles": [], "looking_for_roles": []}
    else:
        _, field, raw_index = callback.data.split(":")
        index = int(raw_index)
        option = CHAMPIONSHIPS[index] if field == "championships" else ROLES[index]
        filters[field] = toggle_option(filters.get(field, []), option)

    await state.update_data(feed_filters=filters)
    await callback.message.edit_text(format_filters(filters), reply_markup=feed_filters_keyboard(filters))
    await callback.answer()


@router.callback_query(F.data.startswith("react:"))
async def reaction_handler(callback: CallbackQuery, db: Database, state: FSMContext, bot: Bot) -> None:
    _, reaction, raw_target_id = callback.data.split(":")
    target_id = int(raw_target_id)

    if target_id == callback.from_user.id:
        await callback.answer("Свою анкету нельзя оценивать.", show_alert=True)
        return

    saved = db.save_reaction(callback.from_user.id, target_id, reaction)
    if not saved:
        await callback.answer("Ты уже реагировал(а) на эту анкету.")
        return

    await safe_remove_inline_keyboard(callback)
    await callback.answer("Реакция сохранена.")

    if reaction == "like" and db.is_mutual_like(callback.from_user.id, target_id):
        if db.create_match(callback.from_user.id, target_id):
            first_profile = db.get_profile(callback.from_user.id)
            second_profile = db.get_profile(target_id)
            if first_profile and second_profile:
                await send_match_notifications(bot, first_profile, second_profile)

    await show_next_profile(callback.message, callback.from_user.id, state, db)


@router.message(Command("stats"))
async def stats_handler(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user.id != settings.admin_id:
        await message.answer("Эта команда доступна только администратору.")
        return
    await message.answer(format_stats(db.get_stats()), reply_markup=main_menu())


@router.message(Command("broadcast_team"))
async def broadcast_handler(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if message.from_user.id != settings.admin_id:
        await message.answer("Эта команда доступна только администратору.")
        return

    sent = 0
    failed = 0
    text = message.text.removeprefix("/broadcast_team").strip() if message.text else ""

    if not text and not message.reply_to_message:
        await message.answer(
            "Использование: /broadcast_team текст\n"
            "Или ответь этой командой на сообщение, которое нужно разослать."
        )
        return

    for user_id in db.get_profile_ids():
        try:
            if message.reply_to_message:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.reply_to_message.message_id,
                )
            else:
                await bot.send_message(user_id, text)
            sent += 1
        except TelegramForbiddenError:
            failed += 1

    await message.answer(f"Рассылка завершена. Отправлено: {sent}, не доставлено: {failed}.")


@router.message()
async def fallback_handler(message: Message) -> None:
    await message.answer(
        "Я понял не всё. Используй кнопки меню или команды /start, /my, /matches, /cancel.",
        reply_markup=main_menu(),
    )


async def setup_commands(bot: Bot, settings: Settings) -> None:
    commands = [
        BotCommand(command="start", description="Открыть главное меню"),
        BotCommand(command="my", description="Моя анкета"),
        BotCommand(command="matches", description="Мои мэтчи"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
    ]
    if settings.admin_id:
        commands.extend(
            [
                BotCommand(command="stats", description="Статистика"),
                BotCommand(command="broadcast_team", description="Рассылка участникам"),
            ]
        )
    await bot.set_my_commands(commands)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    db = Database(settings.database_path)
    db.init_schema()

    bot = Bot(settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await setup_commands(bot, settings)
    await dp.start_polling(bot, db=db, settings=settings)
    db.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
