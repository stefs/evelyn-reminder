## Usage
### Discord bot

Each reminder gets assigned a number between 1 and 9, so each user can have up to 9 reminders. To execute a command that
is related to a specific reminder, it needs to start with the respective number.

Each reminder is linked to the channel it was created in. This means that reminder pings will appear in the same
channel. Commands that are not related to a specific reminder will work in every channel, so it is recommended to
restrict the bot to relevant channels using the Discord channel permission "Read Messages".

\*) append `@user` to execute for someone else  
\*\*) use one or more of: `m`in, `h`our, `d`ay, `w`eek, `M`onth, `y`ear  
\*\*\*) see this [list of tz database time zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List), column
"TZ database name"

Setup a reminder:

Command               | Description
--------------------- | ---
`help`                | Show this help
`new`                 | Create new reminder \*
`1 msg Do the thing!` | Set the ping message \*
`1 num 3`             | Set number of reminders per day \*
`1 tz Europe/Berlin`  | Set the timezone \* \*\*\*
`1 13:37`             | Set time of last reminder of the day \*
`?`                   | List your registered reminders \*
`all?`                | List registered reminders from all users

Daily usage:

Command     | Description
----------- | ---
`1?`        | Show status of reminder 1 \*
`1`         | Record reminder 1 done \*
`1 42m`     | Record reminder 1 done 42 minutes ago \*\* \*
`1 del`     | Delete last record of reminder 1 \*
`1 mute 3d` | Mute reminder 1 for 3 days \*\* \*
`1 unmute`  | Unmute reminder 1 \*

Advanced options:

Command                   | Description
------------------------- | ---
`1 channel <id>`          | Linked channel by [ID](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID-)
`1 correction 1h`         | Duration to correct per period
`1 ping 30m`              | Ping interval when ignored
`1 alternate left,right`  | Extra alternating message, empty to disable
`1 tts_value 3`           | ...
`1 tts_custom 3`          | ...
`1 response Well done!`   | Response when reminder done 
`1 emotes <id>,<id>,<id>` | Emojis by ID added to response (amount from `num`)
`1 color_hex f188d6`      | Hex color value
`1 remove`                | Remove the reminder and all history
