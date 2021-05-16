#  Evelyn Reminder
#  Copyright © 2021  Stefan Schindler
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License in version 3
#  as published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Optional, Generator, Any, Mapping

from evelyn_reminder.client import EvelynClient, NotFoundError


class CommandType(Enum):
    HELP = 1
    LIST = 2
    LIST_ALL = 3
    INFO = 4
    TAKEN = 5
    DELETE = 6
    BED_TIME = 7
    MUTE = 8
    UNMUTE = 9


@dataclass
class Command(object):
    PATTERNS = {
        CommandType.HELP:
            re.compile(r'help'),
        CommandType.LIST:
            re.compile(r'\?( <@!?(?P<member>\d{18})>)?'),
        CommandType.LIST_ALL:
            re.compile(r'all\?'),
        CommandType.INFO:
            re.compile(r'(?P<key>[1-9])\?( <@!?(?P<member>\d{18})>)?'),
        CommandType.TAKEN:
            re.compile(r'(?P<key>[1-9])( (?P<duration>(\d+[mhdwMy])+))?( <@!?(?P<member>\d{18})>)?'),
        CommandType.DELETE:
            re.compile(r'(?P<key>[1-9]) del( <@!?(?P<member>\d{18})>)?'),
        CommandType.BED_TIME:
            re.compile(r'(?P<key>[1-9]) (?P<hour>\d{1,2}):(?P<minute>\d{2})( <@!?(?P<member>\d{18})>)?'),
        CommandType.MUTE:
            re.compile(r'(?P<key>[1-9]) mute (?P<duration>(\d+[mhdwMy])+)( <@!?(?P<member>\d{18})>)?'),
        CommandType.UNMUTE:
            re.compile(r'(?P<key>[1-9]) unmute( <@!?(?P<member>\d{18})>)?')}
    PATTERN_DURATION = re.compile(r'(?P<value>\d+)(?P<time>[mhdwMy])')
    DAYS_PER_YEAR = 365.2425
    TIMES = {
        'm': datetime.timedelta(minutes=1),
        'h': datetime.timedelta(hours=1),
        'd': datetime.timedelta(days=1),
        'w': datetime.timedelta(weeks=1),
        'M': datetime.timedelta(days=DAYS_PER_YEAR / 12),
        'y': datetime.timedelta(days=DAYS_PER_YEAR)}

    type: CommandType
    key: Optional[int]
    member: Optional[int]
    time: Optional[datetime.time]
    duration: Optional[datetime.timedelta]

    @classmethod
    def from_text(
            cls,
            text: str
    ) -> Command:
        for command_type, pattern in cls.PATTERNS.items():
            match = pattern.fullmatch(text)
            if not match:
                continue
            match = match.groupdict()
            # key
            try:
                key = int(match['key'])
            except KeyError:
                key = None
            # member
            try:
                member = int(match['member'])
            except (KeyError, TypeError):
                member = None
            # time
            try:
                time = datetime.time(hour=int(match['hour']), minute=int(match['minute']))
            except KeyError:
                time = None
            # duration
            try:
                duration = sum((int(match_['value']) * cls.TIMES[match_['time']]
                                for match_ in cls.PATTERN_DURATION.finditer(match['duration'])),
                               start=datetime.timedelta())
            except (KeyError, TypeError):
                duration = None
            # done
            return cls(
                type=command_type,
                key=key,
                member=member,
                time=time,
                duration=duration)
        raise InvalidCommandError


@dataclass
class Response(object):
    text: str
    member: Optional[int] = None
    emote: Optional[int] = None
    embed: Optional[Embed] = None


@dataclass
class Embed(object):
    title: str
    description: str
    color_hex: str = '#808080'

    @classmethod
    def from_ping(
            cls,
            ping: Mapping[str, Any],
            include_message: bool = False
    ) -> Embed:
        title = ping['when']
        if include_message:
            message = ping['message']
            title = f'{message}\n{title}'
        last = ping['last']
        gaps = ping['gaps']
        schedule = ping['schedule']
        description = (f'**Last:** {last}\n'
                       f'**Gaps:** {gaps}\n'
                       f'**Schedule:** {schedule}')
        muted = ping['muted']
        if muted is not None:
            description = f'{description}\n{muted}'
        return cls(
            title=title,
            description=description,
            color_hex=ping['reminder']['color_hex'])


@dataclass
class Ping(object):
    channel: int
    message: str
    embed: Embed
    tts_message: bool
    tts_custom: Optional[str]


class Bot(object):
    def __init__(
            self,
            netloc: str,
            base_path: str,
            api_key: str
    ) -> None:
        self.client = EvelynClient(netloc=netloc, base_path=base_path, api_key=api_key, log_url=True)

    def command(
            self,
            text: str,
            guild: int,
            member: int,
            channel: int
    ) -> Optional[Response]:
        # parse message
        # noinspection PyBroadException
        try:
            command = Command.from_text(text)
        except Exception:
            return None
        if command.member is not None:
            member_command = command.member
            member_ping = command.member
        else:
            member_command = member
            member_ping = None
        # main work
        try:
            # get reminder
            if command.key is not None:
                try:
                    # TODO: remove this api call
                    reminder = self.client.get_reminder(guild=guild, member=member_command, key=command.key)
                except NotFoundError:
                    return Response(member=member_ping, text=f'You don\'t have a reminder {command.key}!')
                reminder_channel = reminder['channel']
                reminder_ping_message = reminder['ping_message']
                if reminder_channel != channel:
                    return Response(text=f'Please use the channel <#{reminder_channel}> '
                                         f'for the reminder "{reminder_ping_message}"!')
            else:
                reminder = None
            # process command
            if command.type is CommandType.HELP:
                return Response(
                    text='Here is how to use this bot.',
                    embed=Embed(
                        title='Command help',
                        description=multiline(r"""
                            `help` - Show this help
                            `?` - List your registered reminders \*
                            `all?` - List registered reminders from all users
                            `1?` - Show status of reminder 1 \*
                            `1` - Record reminder 1 done \*
                            `1 42m` - Record reminder 1 done 42 minutes ago \*\* \*
                            `1 del` - Delete last record of reminder 1 \*
                            `1 13:37` - Set time of last reminder of the day \*
                            `1 mute 3d` - Mute reminder 1 for 3 days \*\* \*
                            `1 unmute` - Unmute reminder 1 \*
                            \*) append `@user` to execute for someone else
                            \*\*) use one or more of: `m`in, `h`our, `d`ay, `w`eek, `M`onth, `y`ear
                            
                            Made with love
                            This bot is free software, licensed under GPL
                            https://github.com/stefs/evelyn-reminder
                            """)))
            if command.type in [CommandType.LIST, CommandType.LIST_ALL]:
                text, description = self._list_reminders(
                    guild=guild, member=member_command if command.type is CommandType.LIST else None)
                return Response(member=member_ping, text=text, embed=Embed(title='Reminders', description=description))
            # process commands with reminder info box
            now = datetime.datetime.now(datetime.timezone.utc)
            if command.type is CommandType.INFO:
                response = Response(member=member_ping, text='Here is the status of your reminder.')
            elif command.type is CommandType.TAKEN:
                if command.duration is None:
                    data = self.client.post_history(guild=guild, member=member_command, key=command.key)
                else:
                    data = self.client.post_history(guild=guild, member=member_command, key=command.key,
                                                    time_utc=now - command.duration)
                response = Response(member=member_ping, text=data['message'], emote=data['emote'])
            elif command.type is CommandType.DELETE:
                self.client.delete_history(guild=guild, member=member_command, key=command.key)
                response = Response(member=member_ping, text='The last record of your reminder was deleted.')
            elif command.type is CommandType.BED_TIME:
                self.client.put_reminder(guild=guild, member=member_command, key=command.key, bed_time_utc=command.time)
                response = Response(member=member_ping, text='The bed time of your reminder was adjusted.')
            elif command.type is CommandType.MUTE:
                self.client.put_reminder(guild=guild, member=member_command, key=command.key,
                                         mute_until_utc=now + command.duration)
                response = Response(member=member_ping, text='Your reminder was muted.')
            elif command.type is CommandType.UNMUTE:
                self.client.put_reminder(guild=guild, member=member_command, key=command.key, mute_until_utc=now)
                response = Response(member=member_ping, text='Your reminder was unmuted.')
            else:
                return None
            ping = self.client.get_ping(guild=guild, member=member_command, key=command.key,
                                        filter_due=False, filter_muted=False, filter_ping_due=False)
            response.embed = Embed.from_ping(ping, include_message=True)
            return response
        except Exception as e:
            logging.critical(f'{type(e).__name__}: {e}')

    def _list_reminders(
            self,
            guild: int,
            member: Optional[int]
    ) -> Tuple[str, Optional[str]]:
        # prepare query
        reminders = self.client.get_reminder(guild=guild, member=member)
        # collect entries
        description = []
        for reminder in reminders:
            key = reminder['key']
            message = reminder['ping_message']
            entry = f'[{key}] {message}'
            if member is None:
                member_ = reminder['member']
                entry = f'<@{member_}> - {entry}'
            description.append(entry)
        # done
        count = len(description)
        if member is None:
            text = f'There are {count} registered reminders.'
        else:
            text = f'You have {count} registered reminders.'
        description = '\n'.join(description) if description else None
        return text, description

    def check(self) -> Generator[Ping, bool, None]:
        try:
            for ping in self.client.get_ping():
                member = ping['reminder']['member']
                message = ping['message']
                pinged = yield Ping(
                    channel=ping['reminder']['channel'],
                    message=f'<@{member}> {message}',
                    embed=Embed.from_ping(ping),
                    tts_message=ping['tts_message'],
                    tts_custom=ping['tts_custom'])
                if pinged:
                    self.client.post_ping(
                        guild=ping['reminder']['guild'],
                        member=ping['reminder']['member'],
                        key=ping['reminder']['key'])
        except Exception as e:
            logging.critical(f'{type(e).__name__}: {e}')


class InvalidCommandError(Exception):
    pass


def multiline(
        text: str
) -> str:
    text = [line.strip() for line in text.split('\n')]
    while text and not text[0]:
        del text[0]
    while text and not text[-1]:
        del text[-1]
    return '\n'.join(text)
