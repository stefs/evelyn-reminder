#  Evelyn Reminder
#  Copyright © 2022  Stefan Schindler
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

import asyncio
import logging
import sys
import time
from argparse import ArgumentParser
from configparser import ConfigParser

import discord

from evelyn_reminder.client.bot import Bot, Embed

logging.basicConfig(format='[%(asctime)s|%(levelname)s|%(name)s] %(message)s', level=logging.INFO, stream=sys.stdout)
CLIENT = discord.Client(intents=discord.Intents(guilds=True, emojis=True, guild_messages=True))
BOT: Bot


def main() -> None:
    global BOT
    # read config
    parser = ArgumentParser(add_help=False)
    parser.add_argument('config', help='configuration file')
    args = parser.parse_args()
    config = ConfigParser()
    config.read(args.config)
    # setup application
    BOT = Bot(
        netloc=config.get('DEFAULT', 'evelyn_netloc'),
        base_path=config.get('DEFAULT', 'evelyn_base_path'),
        api_key=config.get('DEFAULT', 'evelyn_api_key'))
    # run application
    CLIENT.loop.create_task(my_background_task())
    CLIENT.run(config.get('DEFAULT', 'discord_token'))


async def my_background_task() -> None:
    await CLIENT.wait_until_ready()
    while not CLIENT.is_closed():
        start = time.time()
        check = BOT.check()
        pinged = None
        while True:
            try:
                ping = check.send(pinged)
            except StopIteration:
                break
            pinged = False
            try:
                channel = CLIENT.get_channel(ping.channel)
                assert channel is not None, f'Invalid channel: {ping.channel!r}'
                embed = _make_embed(ping.embed)
                await channel.send(ping.message, tts=ping.tts_message, embed=embed)
                if ping.tts_custom is not None:
                    message_object = await channel.send(ping.tts_custom, tts=True)
                    await message_object.delete()
            except Exception as e:
                logging.error(f'{type(e).__name__}: {e}')
                continue
            pinged = True
        duration = time.time() - start
        logging.info(f'Check session: {duration * 1000:.0f} ms')
        await asyncio.sleep(30)


@CLIENT.event
async def on_ready() -> None:
    logging.info(f'{CLIENT.user} is connected to the following guilds:\n' +
                 '\n'.join(f'> "{guild.name}" (ID: {guild.id})' for guild in CLIENT.guilds))


@CLIENT.event
async def on_message(
        message: discord.Message
) -> None:
    # process command
    start = time.time()
    response = BOT.command(
        text=message.content,
        guild=message.guild.id,
        member=message.author.id,
        channel=message.channel.id)
    if response is None:
        return
    duration = time.time() - start
    logging.info(f'Command session: {duration * 1000:.0f} ms')
    # make response
    start = time.time()
    text = response.text
    if response.member is not None:
        text = f'<@{response.member}> {text}'
    if response.emote is not None:
        text = f'{text} {CLIENT.get_emoji(response.emote)}'
    embed = None
    if response.embed is not None:
        embed = _make_embed(response.embed)
    await message.channel.send(text, embed=embed)
    duration = time.time() - start
    logging.info(f'Command response: {duration * 1000:.0f} ms')


def _make_embed(
        embed: Embed
) -> discord.Embed:
    color_rgb = (int(embed.color_hex[index:index + 2], base=16) for index in range(1, 7, 2))
    discord_embed = discord.Embed(
        title=embed.title,
        type='rich',
        description=embed.description,
        color=discord.Color.from_rgb(*color_rgb))
    return discord_embed
