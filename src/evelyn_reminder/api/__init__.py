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
from argparse import ArgumentParser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple, List, Dict

import flask
import flask.views
import pytz
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.ext.declarative
import sqlalchemy.orm
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Interval, SmallInteger, String, Time
from sqlalchemy import Column, ForeignKeyConstraint

Base = sqlalchemy.ext.declarative.declarative_base()
Session = sqlalchemy.orm.sessionmaker()


class TtsType(Enum):
    NO_TTS = 1
    TTS_PING_AND_NUMBER = 2
    TTS_NAME_ONLY = 3
    TTS_CUSTOM_TEXT = 4


class Reminder(Base):
    __tablename__ = 'reminder'

    guild = Column(BigInteger, primary_key=True)
    member = Column(BigInteger, primary_key=True)
    key = Column(Integer, primary_key=True)

    channel = Column(BigInteger, nullable=False)
    timezone = Column(String(50), nullable=False)
    cycles_per_day = Column(Integer, nullable=False, default=3)
    correction_amount = Column(Interval, nullable=False, default=datetime.timedelta(hours=1))
    ping_interval = Column(Interval, nullable=False, default=datetime.timedelta(minutes=30))
    bed_time_utc = Column(Time, nullable=False, default=datetime.time(hour=22))
    show_alternating = Column(String(100), nullable=True, default=None)
    ping_message = Column(String(100), nullable=False, default='Reminder text')
    tts_value = Column(SmallInteger, nullable=False, default=TtsType.NO_TTS.value)
    tts_custom = Column(String(100), nullable=True, default=None)
    response_message = Column(String(100), nullable=False, default='Nice')
    response_emotes = Column(String(56), nullable=True, default=None)
    color_hex = Column(String(7), nullable=False, default='#eb349e')
    last_ping_utc = Column(DateTime, nullable=False, default=datetime.datetime.min)
    mute_until_utc = Column(DateTime, nullable=False, default=datetime.datetime.min)
    alternating_flag = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)

    histories = sqlalchemy.orm.relationship('History', back_populates='reminder')

    def __str__(self):
        return f'[guild={self.guild}|member={self.member}|key={self.key}]'

    @property
    def tzinfo(self) -> pytz.tzinfo:
        return pytz.timezone(self.timezone)

    @property
    def period(self) -> datetime.timedelta:
        return datetime.timedelta(days=1) / self.cycles_per_day

    @property
    def bed_time(self) -> datetime.time:
        return self.bed_time_utc.replace(tzinfo=datetime.timezone.utc)

    @property
    def tts_type(self) -> TtsType:
        return TtsType(self.tts_value)

    @property
    def last_ping(self) -> datetime.datetime:
        return self.last_ping_utc.replace(tzinfo=datetime.timezone.utc)

    @property
    def mute_until(self) -> datetime.datetime:
        return self.mute_until_utc.replace(tzinfo=datetime.timezone.utc)

    def get_emote(
            self,
            cycle: int
    ) -> int:
        response_emotes = self.response_emotes.split(',')
        return int(response_emotes[cycle % len(response_emotes)])


class History(Base):
    __tablename__ = 'history'

    id = Column(Integer, primary_key=True)

    reminder_guild = Column(BigInteger, nullable=False)
    reminder_member = Column(BigInteger, nullable=False)
    reminder_key = Column(Integer, nullable=False)
    timestamp_utc = Column(DateTime, nullable=False)
    center_utc = Column(DateTime, nullable=False)

    reminder = sqlalchemy.orm.relationship('Reminder', back_populates='histories')

    __table_args__ = (ForeignKeyConstraint((reminder_guild, reminder_member, reminder_key),
                                           (Reminder.guild, Reminder.member, Reminder.key)),
                      {})

    @property
    def timestamp(self) -> datetime.datetime:
        return self.timestamp_utc.replace(tzinfo=datetime.timezone.utc)

    @property
    def center(self) -> datetime.datetime:
        return self.center_utc.replace(tzinfo=datetime.timezone.utc)

    def jsonify(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'reminder_guild': self.reminder_guild,
            'reminder_member': self.reminder_member,
            'reminder_key': self.reminder_key,
            'timestamp_utc': str(self.timestamp_utc),
            'center_utc': self.center_utc}


class Dose(object):
    def __init__(
            self,
            reminder: Reminder,
            timestamp: datetime.datetime,
            center: datetime.datetime
    ) -> None:
        assert timestamp.tzinfo == datetime.timezone.utc
        assert center.tzinfo == datetime.timezone.utc
        self.reminder = reminder
        self.timestamp = timestamp
        self.center = center
        self.late = self.timestamp - self.center
        self.cycle, self.closest_center = self._get_cycle(reminder=reminder, timestamp=self.center)

    def __repr__(self) -> str:
        return (
            f'{type(self).__name__}('
            f'reminder={self.reminder}, '
            f'timestamp={self.timestamp}, '
            f'center={self.center}, '
            f'late={self.late}, '
            f'cycle={self.cycle})')

    def get_target(
            self,
            now: datetime.datetime
    ) -> Dose:
        # next center
        center = self.closest_center
        next_center = center + self.reminder.period
        # next time
        desired_next_time = self.timestamp + self.reminder.period
        correction = center - self.timestamp
        correction = max(min(correction, self.reminder.correction_amount), -self.reminder.correction_amount)
        next_time = desired_next_time + correction
        assert desired_next_time.tzinfo == datetime.timezone.utc
        assert now.tzinfo == datetime.timezone.utc
        minimum_time = min(desired_next_time, now)
        next_time = max(next_time, minimum_time)
        # done
        return Dose(reminder=self.reminder, timestamp=next_time, center=next_center)

    def get_taken(
            self,
            now: datetime.datetime
    ) -> Dose:
        # target next center
        center = self.closest_center
        next_center = center + self.reminder.period
        # prevent saving intervals that are way into the past or future
        if next_center > now:
            # prevent saving more than one center into the future
            while True:
                smaller_center = next_center - self.reminder.period
                if smaller_center > now + self.reminder.correction_amount:
                    next_center = smaller_center
                else:
                    break
        else:
            # prevent saving more than one center into the past
            while True:
                bigger_center = next_center + self.reminder.period
                if bigger_center < now - self.reminder.correction_amount:
                    next_center = bigger_center
                else:
                    break
        # prevent saving multiple centers in the future
        return Dose(reminder=self.reminder, timestamp=now, center=next_center)

    @staticmethod
    def _get_cycle(
            reminder: Reminder,
            timestamp: datetime.datetime
    ) -> Tuple[int, datetime.datetime]:
        closest_center = datetime.datetime.combine(timestamp.date(), reminder.bed_time)
        cycle = reminder.cycles_per_day - 1
        while True:
            if abs(timestamp - closest_center) <= reminder.period / 2:
                return cycle, closest_center
            if timestamp > closest_center:
                closest_center += reminder.period
                cycle = (cycle + 1) % reminder.cycles_per_day
            else:
                closest_center -= reminder.period
                cycle = (cycle + reminder.cycles_per_day - 1) % reminder.cycles_per_day


@dataclass
class ReminderResponse(object):
    guild: int
    member: int
    key: int
    channel: int
    timezone: str
    cycles_per_day: int
    correction_amount: str
    ping_interval: str
    bed_time: str
    show_alternating: str
    ping_message: str
    tts_value: int
    tts_custom: str
    response_message: str
    response_emotes: str
    color_hex: str
    last_ping: str
    mute_until: str
    alternating_flag: bool

    @classmethod
    def from_reminder(
            cls,
            reminder: Reminder
    ) -> ReminderResponse:
        return cls(
            guild=reminder.guild,
            member=reminder.member,
            key=reminder.key,
            channel=reminder.channel,
            timezone=reminder.timezone,
            cycles_per_day=reminder.cycles_per_day,
            correction_amount=str(reminder.correction_amount),
            ping_interval=str(reminder.ping_interval),
            bed_time=reminder.bed_time.isoformat(),
            show_alternating=reminder.show_alternating,
            ping_message=reminder.ping_message,
            tts_value=reminder.tts_value,
            tts_custom=reminder.tts_custom,
            response_message=reminder.response_message,
            response_emotes=reminder.response_emotes,
            color_hex=reminder.color_hex,
            last_ping=reminder.last_ping.isoformat(),
            mute_until=reminder.mute_until.isoformat(),
            alternating_flag=reminder.alternating_flag)


@dataclass
class HistoryResponse(object):
    message: str
    emote: int

    @classmethod
    def from_reminder(
            cls,
            reminder: Reminder,
            dose_taken: Dose
    ) -> HistoryResponse:
        return cls(
            message=reminder.response_message,
            emote=reminder.get_emote(dose_taken.cycle))


@dataclass
class PingResponse(object):
    reminder: ReminderResponse
    message: str
    tts_message: bool
    tts_custom: Optional[str]
    when: str
    last: str
    gaps: str
    schedule: str
    muted: Optional[str]
    flag_due: bool
    flag_muted: bool
    flag_ping: bool

    @classmethod
    def from_reminder(
            cls,
            reminder: Reminder,
            dose_tail: List[Tuple[Dose, datetime.timedelta]],
            dose_last: Dose,
            now: datetime.datetime
    ) -> PingResponse:
        dose_target = dose_last.get_target(now)
        # when
        when = cls._pretty_dose(dose=dose_target, now=now)
        when = when[0].upper() + when[1:]
        # message, tts_message, tts_custom
        message = reminder.ping_message
        if reminder.show_alternating:
            alternating = reminder.show_alternating.split(',')[int(reminder.alternating_flag)]
            message = f'{message}\u2002({alternating})'
        if reminder.tts_type is TtsType.NO_TTS:
            tts_message = False
            tts_custom = None
        elif reminder.tts_type is TtsType.TTS_PING_AND_NUMBER:
            tts_message = True
            tts_custom = None
        elif reminder.tts_type is TtsType.TTS_NAME_ONLY:
            tts_message = False
            tts_custom = message
        elif reminder.tts_type is TtsType.TTS_CUSTOM_TEXT:
            tts_message = False
            tts_custom = reminder.tts_custom if reminder.tts_custom else message
        else:
            raise RuntimeError(f'Unknown tts type: {reminder.tts_type}')
        message = f'[{reminder.key}] {message}'
        # last
        last = cls._pretty_dose(dose=dose_last, now=now, late_flag=True)
        # gaps
        gaps = ', '.join(cls._natural_delta(period) for dose, period in reversed(dose_tail))
        # schedule
        local_now = now.astimezone(reminder.tzinfo)
        bed_time_secs = reminder.bed_time.hour * 3600 + reminder.bed_time.minute * 60 + reminder.bed_time.second
        bed_time_secs += local_now.utcoffset().total_seconds()
        bed_time_secs %= 86400
        period_secs = 86400 / reminder.cycles_per_day
        schedule = []
        for cycle in reversed(range(reminder.cycles_per_day)):
            time_secs = bed_time_secs - cycle * period_secs
            if time_secs < 0:
                time_secs += 86400
            hour = int(time_secs // 3600)
            time_secs -= hour * 3600
            minute = int(time_secs // 60)
            second = int(time_secs - minute * 60)
            schedule.append(datetime.time(hour=hour, minute=minute, second=second))
        schedule = ', '.join(cls._fix_time_str(f'{time_obj:%H:%M}') for time_obj in schedule)
        schedule = f'{schedule}\u2002({local_now:%Z})'
        # next ping
        if now < reminder.mute_until:
            muted = f'Muted for another {cls._natural_delta(now - reminder.mute_until, hours_only=False)}.'
        else:
            muted = None
        # debug
        # dose_taken = dose_last.get_taken(now)
        # for index, (dose, period) in enumerate(dose_tail):
        #     description.append(f'Last {index - reminder.TAIL} | {dose} | {period}')
        # description.append(f'Next target | {dose_target} | {dose_target.timestamp - dose_last.timestamp}')
        # description.append(f'Next taken | {dose_taken} | {dose_taken.timestamp - dose_last.timestamp}')
        # flags
        flag_due = now >= dose_target.timestamp
        flag_muted = now < reminder.mute_until
        flag_ping = flag_due and not flag_muted and now >= reminder.last_ping + reminder.ping_interval
        # done
        return PingResponse(
            reminder=ReminderResponse.from_reminder(reminder),
            message=message,
            tts_message=tts_message,
            tts_custom=tts_custom,
            when=when,
            last=last,
            gaps=gaps,
            schedule=schedule,
            muted=muted,
            flag_due=flag_due,
            flag_muted=flag_muted,
            flag_ping=flag_ping)

    @classmethod
    def _pretty_dose(
            cls,
            dose: Dose,
            now: datetime.datetime,
            late_flag: bool = False
    ) -> str:
        extra = []
        # late
        if late_flag and abs(dose.late) > dose.reminder.correction_amount:
            natural = cls._natural_delta(dose.late)
            direction = 'late' if dose.late > datetime.timedelta() else 'early'
            extra.append(f'{natural} {direction}')
        # cycle
        if dose.reminder.cycles_per_day != 1 and abs(dose.late) > dose.reminder.period / 2:
            extra.append(f'{dose.cycle + 1}/{dose.reminder.cycles_per_day}')
        # extra
        if extra:
            extra = ', '.join(extra)
            extra = f'\u2002({extra})'
        else:
            extra = ''
        # done
        local_dose_timestamp = dose.timestamp.astimezone(dose.reminder.tzinfo)
        time_str = cls._fix_time_str(f'{local_dose_timestamp:%H:%M}')
        return f'{cls._natural_delta(now - dose.timestamp, relative=True)} at {time_str}{extra}'

    @classmethod
    def _natural_delta(
            cls,
            delta: datetime.timedelta,
            relative: bool = False,
            hours_only: bool = True
    ) -> str:
        # calculate numbers
        seconds = delta.total_seconds()
        past = seconds >= 0
        minutes = abs(seconds) / 60
        hours = minutes / 60
        days = hours / 24
        weeks = days / 7
        years = days / 365.2425
        months = years * 12
        # special relative case
        if relative and minutes < 1:
            return 'now'
        # make relative text
        if relative:
            if past:
                relative_text = ' ago'
            else:
                relative_text = ' from now'
        else:
            relative_text = ''
        # return hours
        minutes = round(minutes)
        if minutes < 60:
            unit = 'minute' if minutes == 1 else 'minutes'
            return f'{minutes} {unit}{relative_text}'
        # return hours
        hours = round(hours)
        if hours < 24 or hours_only:
            unit = 'hour' if hours == 1 else 'hours'
            return f'{hours} {unit}{relative_text}'
        # return days
        days = round(days)
        if days < 7:
            unit = 'day' if days == 1 else 'days'
            return f'{days} {unit}{relative_text}'
        # return weeks
        weeks = round(weeks)
        if months < 1:
            unit = 'week' if weeks == 1 else 'weeks'
            return f'{weeks} {unit}{relative_text}'
        # return months
        months = round(months)
        if months < 12:
            unit = 'month' if months == 1 else 'months'
            return f'{months} {unit}{relative_text}'
        # return years
        years = round(years)
        unit = 'year' if years == 1 else 'years'
        return f'{years} {unit}{relative_text}'

    @staticmethod
    def _fix_time_str(
            time_str: str
    ) -> str:
        if time_str.startswith('00'):
            return time_str[1:]
        return time_str.lstrip('0')


class Mixin(object):
    @staticmethod
    def _parse_args(
            guild_optional: bool = False,
            member_optional: bool = False,
            key_optional: bool = False
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        # api_key
        api_key = flask.request.args.get('api_key')
        if api_key != flask.current_app.config['API_KEY']:
            flask.abort(401)
        # guild
        guild = flask.request.args.get('guild')
        if guild is None and not guild_optional:
            flask.abort(400, 'Argument "guild" missing!')
        # member
        member = flask.request.args.get('member')
        if member is None and not member_optional:
            flask.abort(400, 'Argument "member" missing!')
        # key
        key = flask.request.args.get('key')
        if key is None and not key_optional:
            flask.abort(400, 'Argument "key" missing!')
        # check values
        try:
            if guild is not None:
                guild = int(guild)
            if member is not None:
                member = int(member)
            if key is not None:
                key = int(key)
        except ValueError:
            flask.abort(400, 'Invalid value for "guild", "member", or "key" argument!')
        # done
        return guild, member, key

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    @staticmethod
    def _reminder_query(
            session: Session,
            guild: Optional[int],
            member: Optional[int],
            key: Optional[int]
    ) -> Iterator[Reminder]:
        query = session.query(Reminder).filter_by(active=True)
        if guild is not None:
            query = query.filter_by(guild=guild)
        if member is not None:
            query = query.filter_by(member=member)
        if key is not None:
            query = query.filter_by(key=key)
        query = query.order_by(Reminder.member, Reminder.key)
        return iter(query)

    @classmethod
    def _get_reminder(
            cls,
            session: Session,
            guild: int,
            member: int,
            key: int
    ) -> Reminder:
        reminder = session.query(Reminder).get((guild, member, key))
        if reminder is None:
            raise NotFoundError
        return reminder

    @staticmethod
    def _get_history_tail(
            session: Session,
            reminder: Reminder
    ) -> List[History]:
        # noinspection PyUnresolvedReferences
        return list(
            session.query(History)
            .filter_by(reminder=reminder)
            .order_by(History.timestamp_utc.desc())
            .limit(4))

    @classmethod
    def _dose_tail(
            cls,
            session: Session,
            reminder: Reminder
    ) -> List[Tuple[Dose, datetime.timedelta]]:
        tail = cls._get_history_tail(session, reminder)
        tail = [Dose(reminder=reminder, timestamp=history.timestamp, center=history.center)
                for history in reversed(tail)]
        periods = [tail[index + 1].timestamp - tail[index].timestamp for index in range(len(tail) - 1)]
        return list(zip(tail[1:], periods))

    @classmethod
    def _dose_last(
            cls,
            session: Session,
            reminder: Reminder,
            now: datetime.datetime
    ) -> Dose:
        history_tail = cls._get_history_tail(session, reminder)
        if history_tail:
            history = history_tail[0]
            return Dose(
                reminder=reminder,
                timestamp=history.timestamp,
                center=history.center)
        else:
            # assume properly taken on last opportunity
            # FIXME: Instead of creating fake dose on demand, save one fake does to the database when creating a
            #        reminder. Otherwise it will never start pinging, because the fake dose is always adjusting.
            timestamp = datetime.datetime.combine(now.date(), reminder.bed_time)
            while timestamp < now:
                timestamp += reminder.period
            while timestamp >= now:
                timestamp -= reminder.period
            return Dose(
                reminder=reminder,
                timestamp=timestamp,
                center=timestamp)


class ReminderResource(flask.views.MethodView, Mixin):
    def get(self) -> flask.Response:
        guild, member, key = self._parse_args(member_optional=True, key_optional=True)
        # session
        reminders = []
        with session_scope() as session:
            for reminder in self._reminder_query(session, guild, member, key):
                reminders.append(ReminderResponse.from_reminder(reminder))
        # done
        return flask.jsonify(reminders)

    def put(self) -> Tuple[str, int]:
        guild, member, key = self._parse_args()
        data = flask.request.json
        if data is None:
            data = {}
        # updates
        updates = {}
        for attr, value in data.items():
            try:
                if attr == 'channel':
                    value = int(value)
                elif attr == 'timezone':
                    value = pytz.timezone(str(value)).zone
                elif attr == 'cycles_per_day':
                    value = max(int(value), 1)
                elif attr == 'correction_amount':
                    value = datetime.timedelta(seconds=max(float(value), 0))
                elif attr == 'ping_interval':
                    value = datetime.timedelta(seconds=max(float(value), 0))
                elif attr == 'bed_time_utc':
                    value = parse_time_utc(str(value))
                elif attr == 'show_alternating':
                    value = str(value) if value is not None else None
                elif attr == 'ping_message':
                    value = str(value)
                elif attr == 'tts_value':
                    value = TtsType(int(value)).value
                elif attr == 'tts_custom':
                    value = str(value) if value is not None else None
                elif attr == 'response_message':
                    value = str(value)
                elif attr == 'response_emotes':
                    value = str(value) if value is not None else None
                elif attr == 'color_hex':
                    value = str(value)
                elif attr == 'last_ping_utc':
                    value = parse_time_iso(str(value)).replace(tzinfo=None)
                elif attr == 'mute_until_utc':
                    value = parse_time_iso(str(value)).replace(tzinfo=None)
                elif attr == 'alternating_flag':
                    value = bool(value)
                else:
                    flask.abort(400, f'Unknown reminder attribute: "{attr}"')
            except ValueError as e:
                flask.abort(400, str(e))
            updates[attr] = value
        # session
        with session_scope() as session:
            # get reminder
            try:
                reminder = self._get_reminder(session, guild, member, key)
            except NotFoundError:
                for key in ['channel', 'timezone']:
                    if key not in updates:
                        flask.abort(400, f'Required reminder attribute "{key}" is missing!')
                reminder = Reminder(
                    guild=guild,
                    member=member,
                    key=key)
                session.add(reminder)
            # update reminder attributes
            bed_time_key = 'bed_time_utc'
            for key, value in updates.items():
                if key == bed_time_key:
                    continue
                setattr(reminder, key, value)
            # bed time
            if bed_time_key in updates:
                time_user = updates[bed_time_key]
                timezone_user = reminder.tzinfo
                now = self._now()
                matching_date = now.astimezone(timezone_user).date()
                time_user = datetime.datetime.combine(matching_date, time_user)
                time_utc = timezone_user.localize(time_user).astimezone(datetime.timezone.utc)
                time_utc = time_utc.time().replace(tzinfo=None)
                reminder.bed_time_utc = time_utc
            session.commit()
        # done
        return '', 204

    def delete(self) -> Tuple[str, int]:
        guild, member, key = self._parse_args()
        # session
        with session_scope() as session:
            try:
                reminder = self._get_reminder(session, guild, member, key)
            except NotFoundError:
                flask.abort(404)
            session.delete(reminder)
            session.commit()
        # done
        return '', 204


class HistoryResource(flask.views.MethodView, Mixin):
    def post(self) -> flask.Response:
        guild, member, key = self._parse_args()
        # time_utc
        now = self._now()
        time_utc = flask.request.args.get('time_utc')
        if time_utc is None:
            time_ = now
        else:
            try:
                time_ = parse_time_iso(time_utc)
            except ValueError as e:
                flask.abort(400, str(e))
            # noinspection PyUnboundLocalVariable
            if time_ > now:
                flask.abort(400, 'Time cannot be in the future!')
        # session
        with session_scope() as session:
            try:
                reminder = self._get_reminder(session, guild, member, key)
            except NotFoundError:
                flask.abort(404)
            dose_last = self._dose_last(session, reminder, time_)
            if time_ < dose_last.timestamp:
                flask.abort(400, 'Time cannot be before previously recorded time!')
            dose_taken = dose_last.get_taken(time_)
            history = History(reminder=reminder, timestamp_utc=dose_taken.timestamp, center_utc=dose_taken.center)
            if reminder.show_alternating:
                reminder.alternating_flag = not reminder.alternating_flag
            session.add(history)
            session.commit()
            history_response = HistoryResponse.from_reminder(reminder, dose_taken)
        # done
        return flask.jsonify(history_response)

    def delete(self) -> Tuple[str, int]:
        guild, member, key = self._parse_args()
        # session
        with session_scope() as session:
            try:
                reminder = self._get_reminder(session, guild, member, key)
            except NotFoundError:
                flask.abort(404)
            history_tail = self._get_history_tail(session, reminder)
            if history_tail:
                history = history_tail[0]
                if reminder.show_alternating:
                    reminder.alternating_flag = not reminder.alternating_flag
                session.delete(history)
                session.commit()
        # done
        return '', 204


class PingResource(flask.views.MethodView, Mixin):
    def get(self) -> flask.Response:
        guild, member, key = self._parse_args(guild_optional=True, member_optional=True, key_optional=True)
        # pinged
        try:
            filter_due = parse_bool_arg(flask.request.args.get('filter_due'), default=True)
            filter_muted = parse_bool_arg(flask.request.args.get('filter_muted'), default=True)
            filter_ping_due = parse_bool_arg(flask.request.args.get('filter_ping_due'), default=True)
        except ValueError as e:
            flask.abort(400, str(e))
        # session
        now = self._now()
        pings = []
        with session_scope() as session:
            for reminder in self._reminder_query(session, guild, member, key):
                ping_response = PingResponse.from_reminder(
                    reminder=reminder,
                    dose_tail=self._dose_tail(session, reminder),
                    dose_last=self._dose_last(session, reminder, now),
                    now=now)
                # noinspection PyUnboundLocalVariable
                if not ping_response.flag_due and filter_due:
                    continue
                # noinspection PyUnboundLocalVariable
                if ping_response.flag_muted and filter_muted:
                    continue
                # noinspection PyUnboundLocalVariable
                if not ping_response.flag_ping and filter_ping_due:
                    continue
                pings.append(ping_response)
        # done
        return flask.jsonify(pings)

    def post(self) -> Tuple[str, int]:
        guild, member, key = self._parse_args()
        # session
        now = self._now()
        with session_scope() as session:
            try:
                reminder = self._get_reminder(session, guild, member, key)
            except NotFoundError:
                flask.abort(404)
            reminder.last_ping_utc = now.replace(tzinfo=None)
            session.commit()
        # done
        return '', 204


class NotFoundError(Exception):
    pass


@contextmanager
def session_scope():
    session = Session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def parse_time_iso(
        time_iso: str
) -> datetime.datetime:
    if time_iso.endswith('Z'):
        # https://discuss.python.org/t/parse-z-timezone-suffix-in-datetime/2220
        time_iso = time_iso[:-1] + '+00:00'
    time_ = datetime.datetime.fromisoformat(time_iso)
    if time_.tzinfo is None:
        raise ValueError('Time zone information is missing!')
    return time_.astimezone(datetime.timezone.utc)


def parse_time_utc(
        time_iso: str
) -> datetime.time:
    time_ = datetime.time.fromisoformat(time_iso)
    if time_.tzinfo is not None:
        raise ValueError('Time zone information is not supported!')
    return time_


def parse_bool_arg(
        value: Optional[str],
        default: bool
) -> bool:
    if value is None:
        return default
    if value == 'true':
        return True
    if value == 'false':
        return False
    raise ValueError('Invalid boolean value.')


def setup_database() -> None:
    host = flask.current_app.config['DB_HOST']
    name = flask.current_app.config['DB_NAME']
    username = flask.current_app.config['DB_USERNAME']
    password = flask.current_app.config['DB_PASSWORD']
    create_all = False
    uri1 = f'mysql+mysqldb://{username}:{password}@{host}/{name}'
    engine = sqlalchemy.create_engine(uri1, isolation_level='READ COMMITTED')
    Session.configure(bind=engine)
    if create_all:
        Base.metadata.create_all(engine)


logging.basicConfig(format='[%(asctime)s|%(levelname)s|%(name)s] %(message)s', level=logging.INFO)

parser = ArgumentParser(add_help=False)
parser.add_argument('config', help='configuration file')
args = parser.parse_args()

application = flask.Flask(__name__)
application.config.from_pyfile(args.config)
application.add_url_rule('/reminder', view_func=ReminderResource.as_view('reminder_resource'))
application.add_url_rule('/history', view_func=HistoryResource.as_view('taken_resource'))
application.add_url_rule('/ping', view_func=PingResource.as_view('ping_resource'))
application.before_first_request(setup_database)
