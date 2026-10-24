# Everyday utilities

Commands without special setup, unless noted. Output is sent to the channel where the command was typed.

## Weather and conversions

| Command | Description |
|---|---|
| `weather [place]` (alias `w`) | The weather as an image. The place is remembered per user, so `weather` alone reuses the last one. Needs `WEGO_EXE` (a `wego` binary, rendered with `WEATHER_FONT`) or `WEATHER_URL` (default `http://wttr.in/`). |
| `convert <number> <from> to <to>` | Unit and currency conversion: `convert 100 USD to EUR`, `convert 5'10" to cm`. Units come from `convert.json`, currencies from cryptocompare.com. |

## Games

| Command | Description |
|---|---|
| `roll [NdS+B ...]` | Rolls dice, for example `roll 2d6+3`, `roll d20`. Defaults to `1d6`. Several specs can be given. |
| `roll magic8` | Magic 8-Ball. |
| `roll statline [drop1]` | Six lines of 4d6 keeping the highest three (role-playing ability scores). `drop1` re-rolls ones. |
| `cointoss` | Heads or tails. |

## Kudos

Needs `KUDOS_DATABASE_URL`.

| Command | Description |
|---|---|
| `kudos @user [reason]` | Records kudos from you to one or more mentioned users, and often adds a random gift emoji. You cannot give kudos to yourself. |
| `kudos view [days] [channel] [-g] [-t\|-x\|-v\|-i]` | Leaderboard of the last `days` (default 14) for this channel, a given channel, or `*` for all. `-g` shows givers instead of receivers. Output as text (`-t`), Excel (`-x`), a retro arcade video (`-v`) or an image (`-i`). |

## Information

| Command | Description |
|---|---|
| `stocks <name>` (aliases `stock`, `stonk`) | Stock information (yfinance). |
| `crypto <symbol...>` | Current price in EUR and USD (cryptocompare.com). |
| `covid <country>` (aliases `covid19`, `covid_19`) | Latest COVID-19 statistics from `data/owid-covid-data.json`. The country can be a two or three letter code or a name. |
| `urban_dictionary <terms...>` (alias `ud`) | First Urban Dictionary definition. |
| `youtube_info <url>` | YouTube oEmbed metadata of a video, as a file. |
| `joke [-x]` | A dad joke (uses `ALT_PROXY` if set). |
| `fortune` | A fortune cookie (needs `/usr/games/fortune`). |

## Text tools

| Command | Description |
|---|---|
| `binary <bits...>` (alias `b`) | Decodes 8-bit binary groups to text. |
| `unicode <text>` | Code point, character and name of each character, as a file. |

## Server

| Command | Description |
|---|---|
| `version` | `git describe` of the deployed code. |
| `uptime` | Server and bot process uptime. |
| `disk_space` | Free disk space with a progress bar. |
| `disk_space_ex` | Free disk space through `duf` (must be installed). |
| `path` | The `PATH` of the bot process, one entry per line. |
| `planets [-f format]` | Sample table, for testing the table formats. |
