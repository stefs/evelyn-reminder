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

import json
import logging
from datetime import datetime, timezone, timedelta, time
from typing import Optional, Any, Mapping
from urllib.error import HTTPError
from urllib.parse import ParseResult, urlunparse, urlencode
from urllib.request import Request, urlopen

NotSpecified = object()


class EvelynClient(object):
    def __init__(
            self,
            netloc: str,
            base_path: str,
            api_key: str,
            log_url: bool = False
    ) -> None:
        super().__init__()
        self.netloc = netloc
        self.base_path = base_path
        self.api_key = api_key
        self.log_url = log_url

    def _urlopen(
            self,
            method: str,
            path: str,
            data: Optional[Mapping[str, Any]] = None,
            **kwargs
    ) -> Any:
        args = {'api_key': self.api_key}
        for key, value in kwargs.items():
            if value is not None:
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                elif isinstance(value, datetime):
                    value = value.astimezone(timezone.utc).isoformat()
                args[key] = str(value)
        # noinspection PyArgumentList
        url = urlunparse(ParseResult(
            scheme='https',
            netloc=self.netloc,
            path=f'{self.base_path}/{path}',
            params='',
            query=urlencode(args),
            fragment=''))
        log = f'{method} {url}'
        if data is not None:
            data = json.dumps(dict(data), indent=4)
            log += f'\n{data}'
        if self.log_url:
            logging.info(log)
        if data is not None:
            data = data.encode('utf-8')
        request = Request(url=url, method=method, data=data)
        if data is not None:
            request.add_header('content-type', 'application/json')
        try:
            with urlopen(request) as response:
                data = response.read()
        except HTTPError as e:
            raise HttpError(e) from e
        data = data.decode()
        if not data:
            return None
        return json.loads(data)

    def get_reminder(
            self,
            guild: int,
            member: Optional[int] = None,
            key: Optional[int] = None
    ) -> Any:
        reminders = self._urlopen('GET', 'reminder', guild=guild, member=member, key=key)
        if member is not None and key is not None:
            if reminders:
                return reminders[0]
            raise NotFoundError('Reminder not found')
        return reminders

    def put_reminder(
            self,
            guild: int,
            member: int,
            key: int,
            channel: int = NotSpecified,
            timezone_: str = NotSpecified,
            cycles_per_day: int = NotSpecified,
            correction_amount: timedelta = NotSpecified,
            ping_interval: timedelta = NotSpecified,
            bed_time_utc: time = NotSpecified,
            show_alternating: Optional[str] = NotSpecified,
            ping_message: str = NotSpecified,
            tts_value: int = NotSpecified,
            tts_custom: Optional[str] = NotSpecified,
            response_message: str = NotSpecified,
            response_emotes: Optional[str] = NotSpecified,
            color_hex: str = NotSpecified,
            last_ping_utc: datetime = NotSpecified,
            mute_until_utc: datetime = NotSpecified,
            alternating_flag: bool = NotSpecified
    ) -> Any:
        data = {}
        if channel is not NotSpecified:
            data['channel'] = channel
        if timezone_ is not NotSpecified:
            data['timezone'] = timezone_
        if cycles_per_day is not NotSpecified:
            data['cycles_per_day'] = cycles_per_day
        if correction_amount is not NotSpecified:
            data['correction_amount'] = correction_amount.total_seconds()
        if ping_interval is not NotSpecified:
            data['ping_interval'] = ping_interval.total_seconds()
        if bed_time_utc is not NotSpecified:
            data['bed_time_utc'] = bed_time_utc.isoformat()
        if show_alternating is not NotSpecified:
            data['show_alternating'] = show_alternating
        if ping_message is not NotSpecified:
            data['ping_message'] = ping_message
        if tts_value is not NotSpecified:
            data['tts_value'] = tts_value
        if tts_custom is not NotSpecified:
            data['tts_custom'] = tts_custom
        if response_message is not NotSpecified:
            data['response_message'] = response_message
        if response_emotes is not NotSpecified:
            data['response_emotes'] = response_emotes
        if color_hex is not NotSpecified:
            data['color_hex'] = color_hex
        if last_ping_utc is not NotSpecified:
            data['last_ping_utc'] = last_ping_utc.isoformat()
        if mute_until_utc is not NotSpecified:
            data['mute_until_utc'] = mute_until_utc.isoformat()
        if alternating_flag is not NotSpecified:
            data['alternating_flag'] = alternating_flag
        return self._urlopen('PUT', 'reminder', guild=guild, member=member, key=key, data=data)

    def delete_reminder(
            self,
            guild: int,
            member: int,
            key: int
    ) -> Any:
        return self._urlopen('DELETE', 'reminder', guild=guild, member=member, key=key)

    def post_history(
            self,
            guild: int,
            member: int,
            key: int,
            time_utc: Optional[datetime] = None
    ) -> Any:
        return self._urlopen('POST', 'history', guild=guild, member=member, key=key, time_utc=time_utc)

    def delete_history(
            self,
            guild: int,
            member: int,
            key: int
    ) -> Any:
        return self._urlopen('DELETE', 'history', guild=guild, member=member, key=key)

    def get_ping(
            self,
            guild: Optional[int] = None,
            member: Optional[int] = None,
            key: Optional[int] = None,
            filter_due: bool = True,
            filter_muted: bool = True,
            filter_ping_due: bool = True
    ) -> Any:
        pings = self._urlopen('GET', 'ping', guild=guild, member=member, key=key,
                              filter_due=False if not filter_due else None,
                              filter_muted=False if not filter_muted else None,
                              filter_ping_due=False if not filter_ping_due else None)
        if guild is not None and member is not None and key is not None:
            if pings:
                return pings[0]
            raise NotFoundError('Ping not found')
        return pings

    def post_ping(
            self,
            guild: int,
            member: int,
            key: int
    ) -> Any:
        return self._urlopen('POST', 'ping', guild=guild, member=member, key=key)


class HttpError(Exception):
    def __init__(
            self,
            e: HTTPError
    ) -> None:
        super().__init__(e.read().decode())


class NotFoundError(Exception):
    pass
