import html
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime
from functools import wraps
from itertools import zip_longest
from pprint import pprint
from secrets import LIST_OF_ADMINS, TOKEN
from threading import Thread
from collections import Counter
from operator import itemgetter

import filetype
from rich import print
from telegram import (ChatAction, InlineKeyboardButton, InlineKeyboardMarkup,
                      ParseMode)
from telegram.ext import (BaseFilter, CallbackQueryHandler, CommandHandler,
                          Filters, MessageHandler, PicklePersistence, Updater)
from telegram.utils.helpers import mention_html

logging.basicConfig(format='%(asctime)s - %(levelname)s\n%(message)s', level=logging.INFO)

persistence = PicklePersistence(filename='data.persist', on_flush=False)
updater = Updater(token=TOKEN, persistence=persistence, use_context=True)
dispatcher = updater.dispatcher


class FilterFromCW(BaseFilter):
    def filter(self, message):
        try:
            return message.forward_from.id in [408101137]
        except:
            return False


from_chatwars = FilterFromCW()


def error(update, context):
    # add all the dev user_ids in this list. You can also add ids of channels or groups.
    devs = LIST_OF_ADMINS
    # we want to notify the user of this problem. This will always work, but not notify users if the update is an
    # callback or inline query, or a poll update. In case you want this, keep in mind that sending the message
    # could fail
    if not update:
        return
    if update.effective_message:
        text = "Hey. I'm sorry to inform you that an error happened while I tried to handle your update. My developer has been notified."
        update.effective_message.reply_text(text)
    # This traceback is created with accessing the traceback object from the sys.exc_info, which is returned as the
    # third value of the returned tuple. Then we use the traceback.format_tb to get the traceback as a string, which
    # for a weird reason separates the line breaks in a list, but keeps the linebreaks itself. So just joining an
    # empty string works fine.
    trace = "".join(traceback.format_tb(sys.exc_info()[2]))
    # lets try to get as much information from the telegram update as possible
    payload = ""
    # normally, we always have an user. If not, its either a channel or a poll update.
    if update.effective_user:
        payload += f' with the user {mention_html(update.effective_user.id, update.effective_user.first_name)}'
    # there are more situations when you don't get a chat
    if update.effective_chat:
        payload += f' within the chat <i>{html.escape(str(update.effective_chat.title))}</i>'
        if update.effective_chat.username:
            payload += f' (@{update.effective_chat.username})'
    # but only one where you have an empty payload by now: A poll (buuuh)
    if update.poll:
        payload += f' with the poll id {update.poll.id}.'
    # lets put this in a "well" formatted text
    text = f"Hey.\n The error <code>{html.escape(str(context.error))}</code> happened{payload}. The full traceback:\n\n<code>{html.escape(trace)}</code>"
    # and send it to the dev(s)
    for dev_id in devs:
        context.bot.send_message(dev_id, update.effective_message.text, parse_mode=ParseMode.HTML)
        context.bot.send_message(dev_id, text, parse_mode=ParseMode.HTML)
    # we raise the error again, so the logger module catches it. If you don't use the logger module, use it.
    raise


def send_typing_action(func):
    '''decorator that sends typing action while processing func command.'''
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)
        return func(update, context, *args, **kwargs)
    return wrapped


def log(func):
    '''decorator that logs who said what to the bot'''
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        id = update.effective_user.id
        name = update.effective_user.username
        logging.info(f'{name} ({id}) said:\n{update.effective_message.text}')
        return func(update, context, *args, **kwargs)
    return wrapped


def restricted(func):
    '''decorator that restricts use to only the admins listed in secrets.py'''
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        name = update.effective_user.username
        if user_id not in LIST_OF_ADMINS:
            logging.info(f'Unauthorized access: {name} ({user_id}) tried to use {func.__name__}()')
            return
        return func(update, context, *args, **kwargs)
    return wrapped


@send_typing_action
@log
def start(update, context):
    '''intro function'''
    text = 'New bot. Who dis?\n'\
           '\n'\
           'Send me something with your name and guild tag on it.'

    context.bot.send_message(chat_id=update.effective_message.chat_id, text=text, parse_mode=ParseMode.HTML)


@restricted
@log
def restart(update, context):
    def stop_and_restart():
        """Gracefully stop the Updater and replace the current process with a new one"""
        persistence.flush()
        updater.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    logging.info('Bot is restarting...')
    context.bot.send_message(chat_id=update.effective_message.chat_id, text='Bot is restarting...')
    Thread(target=stop_and_restart).start()
    logging.info("...and we're back")
    context.bot.send_message(chat_id=update.effective_message.chat_id, text="...and we're back")


#@send_typing_action
@log
def forwarded(update, context):
    '''main function that deals with forwarded messages'''
    # print(update.to_dict())

    user_id = update.effective_message.from_user.id
    text = update.effective_message.text
    exact_time = update.effective_message.forward_date
    time = game_time(exact_time)
    # this regex is out here because there isn't any other good way to detect the messages that carry this info
    guild_match = re.search(r'(?P<castle>[(🐺🐉🌑🦌🥔🦅🦈)])\[(?P<guild>[A-Z\d]{2,3})\](?P<name>\w+)', text)
    if guild_match and update.effective_message.chat.type == 'private':
        user = '{castle}[{guild}]{name}'.format(**guild(guild_match))
        context.user_data['name'] = user
        update.message.reply_text(f'Hello, {user}')
    elif 'То remember the route you associated it with simple combination:' in text:
        store_route(update, context)
    elif (('You received:' in text
           or 'Being a naturally born pathfinder, you found a secret passage and saved some energy +1🔋' in text
           or text in context.bot_data.get('flavors', {}))
          and (update.effective_message.chat.type == 'private')):
        ask_location(update, context)
    elif update.effective_message.chat.type == 'private':
        context.user_data['text_info'] = 'unknown'
        response = f"{time}\n{exact_time}\n{context.user_data['text_info']}"
        update.message.reply_text(response, quote=True)
    else:
        pass


def guild(guild_match):
    return guild_match.groupdict()


def store_route(update, context):
    routes = context.bot_data.get('routes', {})
    decode = alliance(update.effective_message.text)
    times_seen = routes.get(decode['code'], {}).get('times_seen', set())
    exact_time = update.effective_message.forward_date
    times_seen.add(str(exact_time))
    if str(exact_time) < max(times_seen):
        decode = routes.get(decode['code'], {})
    decode['times_seen'] = times_seen
    decode['count'] = len(times_seen)
    routes[decode['code']] = decode
    context.bot_data['routes'] = routes
    response = '{name}\nTimes seen: {count}'.format(**decode)
    update.message.reply_text(response, quote=True)


def game_time(datetime):
    game_time_lookup = [
                   'morning', 'day', 'day', 'evening', 'evening', 'night', 'night',
        'morning', 'morning', 'day', 'day', 'evening', 'evening', 'night', 'night',
        'morning', 'morning', 'day', 'day', 'evening', 'evening', 'night', 'night',
        'morning'
    ]
    return game_time_lookup[datetime.hour]


def alliance(text):
    pattern = r'You found hidden \w+ (?P<name>.+)\n(?P<occupied>You noticed that objective is captured by alliance\.\n)?(?P<defended>You noticed a .+ of defender near it\.\n)?То remember the route you associated it with simple combination: (?P<code>\w+)'
    alliance_match = re.search(pattern, text)
    return alliance_match.groupdict()


def ask_location(update, context):
    keyboard = [
        [
            InlineKeyboardButton('🌲', callback_data='🌲'),
            InlineKeyboardButton('🍄', callback_data='🍄'),
            InlineKeyboardButton('🏔', callback_data='🏔')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    data = quest(update.effective_message.text)
    stats = context.user_data.get('flavors', {}).get(data['flavor_text'], '')
    if stats:
        stats = stats[0]

    update.message.reply_text(f'Where was this?\n{stats}', reply_markup=reply_markup, quote=True)


def button(update, context):
    query = update.callback_query
    query.answer()

    exact_time = query.message.reply_to_message.forward_date
    data = quest(query.message.reply_to_message.text)

    flavors = context.user_data.get('flavors', {})
    count, times = flavors.get(data['flavor_text'], (Counter(), set()))
    if str(exact_time) not in times:
        times.add(str(exact_time))
        count.update(query.data)
        flavors[data['flavor_text']] = count, times
        context.user_data['flavors'] = flavors

    new_text = f"{game_time(query.message.reply_to_message.forward_date)} {query.data}\n{data}\n{count}"
    query.edit_message_text(text=new_text)


def quest(text):
    pathfinder_text = 'Being a naturally born pathfinder, you found a secret passage and saved some energy +1🔋'
    results = {}
    results['pathfinder'] = pathfinder_text in text
    results['flavor_text'] = text.replace(pathfinder_text, '').partition('You received:')[0].strip()

    pattern = r'Earned: (?P<item>.+)\((?P<count>\d+)\)'
    quest_matches = re.finditer(pattern, text)
    results['loot'] = [match.groupdict() for match in quest_matches]
    return results


@restricted
@send_typing_action
@log
def get_flavors(update, context):
    response = json.dumps(context.user_data.get('flavors'), indent=3, sort_keys=True, default=str)
    for response_slice in zip_longest(*[iter(response)] * 4096, fillvalue=''):
        update.message.reply_text(''.join(response_slice))


@send_typing_action
@log
def raw_routes(update, context):
    response = json.dumps(context.bot_data.get('routes'), indent=3, sort_keys=True, default=str)
    for response_slice in zip_longest(*[iter(response)] * 4096, fillvalue=''):
        update.message.reply_text(''.join(response_slice))


@send_typing_action
@log
def routes(update, context):
    output = []
    for loc in sorted(context.bot_data.get('routes').values(), key=itemgetter('name')):
        location = f"<code>{loc['code']}</code> {loc['name']} Seen: {loc['count']} {'🈵' if loc['occupied'] else ''}{'🛡️' if loc['defended'] else ''}"
        output.append(location)
    print(output)
    update.message.reply_text('\n'.join(output), parse_mode=ParseMode.HTML)


@restricted
@send_typing_action
@log
def get_bot_data(update, context):
    response = json.dumps(context.bot_data, indent=3, sort_keys=True, default=str)
    for response_slice in zip_longest(*[iter(response)] * 4096, fillvalue=''):
        update.message.reply_text(''.join(response_slice))


dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(MessageHandler(Filters.forwarded & Filters.text & from_chatwars, forwarded))
dispatcher.add_handler(CommandHandler('r', restart))
dispatcher.add_handler(CommandHandler('raw_routes', raw_routes))
dispatcher.add_handler(CommandHandler('routes', routes))
dispatcher.add_handler(CommandHandler('flavors', get_flavors))
dispatcher.add_handler(CommandHandler('alldata', get_bot_data))
dispatcher.add_handler(CallbackQueryHandler(button))
dispatcher.add_error_handler(error)

logging.info('bot started')
updater.start_polling()
updater.idle()
