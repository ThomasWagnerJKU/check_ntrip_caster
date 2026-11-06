# check_ntrip_caster

A Nagios/Icinga plugin that checks whether an NTRIP caster serves current GNSS
correction data. Python 3 with the standard library only.

| Mode | Answers | Default thresholds |
|---|---|---|
| `sourcetable` | Does the caster answer with a complete sourcetable, is its clock right, and is a given mountpoint listed? | `-w 10 -c 60` (seconds of clock offset) |
| `stream` | Does a mountpoint stream valid RTCM3 data, and how old is its newest observation epoch? | `-w 3 -c 10` (seconds of data age) |

## Usage

```sh
check_ntrip_caster sourcetable -H caster.example.com -p 2101 -m JKU0
check_ntrip_caster stream      -H caster.example.com -p 2101 -m JKU0 -u monitor -f /etc/icinga2/ntrip.secret
```

```
NTRIP SOURCETABLE OK - RTKLIB demo5 b34L lists 1 stream(s) (JKU0), caster clock +0.4s off | time=0.806s;;;0 streams=1;;;0 clock_offset=0.4s;10;60
NTRIP STREAM OK - JKU0: newest epoch 0.08s old (GPS), 23 RTCM3 frames in 5.9s, messages 1005 1074 1077 1230 | age=0.083s;3;10 frames=23;;;0 bytes=1637B;;;0 crc_errors=0;;;0 first_frame=0.902s;;;0
```

Common options: `-H` host name (required), `-p` port (default 2101), `-t`
timeout in seconds for connecting and between two reads (default 10), `-w` and
`-c` thresholds.

### sourcetable

Requests the sourcetable without credentials and checks that it is complete
(ends with `ENDSOURCETABLE`). With `-m`, the mountpoint has to be listed, or
the check is CRITICAL. The thresholds apply to the difference between the
caster's `Date` header and the local clock; a missing `Date` header is a
WARNING. Both the HTTP date format and the `YYYY/MM/DD HH:MM:SS UTC` format of
RTKLIB are understood.

### stream

Logs in to the mountpoint given with `-m` and reads the stream for `-d`
seconds (default 5). It validates the RTCM3 framing and checksums and decodes
the observation epoch of the observation messages: legacy GPS (1001-1004) and
GLONASS (1009-1012) messages and the MSM messages of GPS, GLONASS, Galileo,
SBAS, QZSS, BeiDou and NavIC. The age of the newest epoch is compared with the
local clock, and the thresholds apply to its absolute value, so a stream
running ahead of the local clock alerts as well. GPS time is taken as UTC plus
18 leap seconds; `--leap-seconds` changes that when a leap second is added.

The check is CRITICAL when the caster does not serve the mountpoint (casters
answer an unknown mountpoint with their sourcetable), when no RTCM3 data
arrives, or when the data is older than `-c`. Frames with a wrong checksum and
a caster that closes the stream early are WARNINGs. A stream without any
observation message, for example only station coordinates, is UNKNOWN, as its
age cannot be told.

### Content of the stream

The stream mode also looks at what the data says. It always reports, and puts
into the performance data:

- the satellites per constellation of the newest complete epoch, from the MSM
  messages (all MSM1-7) and the legacy messages 1001-1004 and 1009-1012
  (`satellites_gps`, `satellites_glonass`, ...)
- the mean C/N0 of all signals in the MSM4 to MSM7 messages (`cnr`, in dBHz).
  A falling C/N0 is the typical sign of an aging antenna or cable.

These options turn them into alerts:

| Option | Alert |
|---|---|
| `--require-messages 1005,1077,1087,1230` | CRITICAL when one of these message types does not arrive within the read time |
| `--position LAT,LON,HEIGHT` | CRITICAL when the antenna reference point in 1005/1006 is more than `--position-tolerance` metres (default 0.05) away from this WGS84 position; WARNING when no 1005/1006 arrives |
| `--satellites-warning GPS=8,GLONASS=4`, `--satellites-critical GPS=5,GLONASS=2` | below this many satellites of a constellation; a constellation that sends nothing counts 0 |
| `--cnr-warning 35`, `--cnr-critical 30` | mean C/N0 below this; WARNING when the stream has no MSM4 to MSM7 message |

Stations send 1005/1006 only every few seconds, often every 10 s: read long
enough with `-d` (for example `-d 12`) when you require it or check the
position. The position is compared in earth-centred coordinates, so the
height is the ellipsoidal height, as RTCM carries it.

```
NTRIP STREAM CRITICAL - station position 0.732m away from 48.3359715,14.3226885,324.978 (tolerance 0.05m); only 2 GLONASS satellite(s); mean C/N0 32.9dBHz, JKU0: newest epoch 0.02s old (GPS), 73 RTCM3 frames in 12.0s, messages 1005 1074 1077 1084 1087 1230, position 0.732m off, satellites GLONASS 2 GPS 10, C/N0 32.9dBHz | age=0.019s;3;10 frames=73;;;0 bytes=5055B;;;0 crc_errors=0;;;0 first_frame=0.007s;;;0 position_error=0.732m;;0.05;0 satellites_glonass=2;4;2;0 satellites_gps=10;8;5;0 cnr=32.9dBHz;35;30;0
```

## Credentials

Pass the user name with `-u`. Never pass the password with `-P` in a service
definition: command lines are visible to every user via `ps`. Put it in a file
that only the monitoring user can read and pass it with `-f`, or set
`$NTRIP_PASSWORD_FILE` or `$NTRIP_PASSWORD`.

NTRIP 1.0 sends the credentials base64 encoded but unencrypted, as does every
NTRIP 1.0 client.

## Thresholds

`-w` and `-c` take a range as defined by the
[monitoring plugins guidelines](https://www.monitoring-plugins.org/doc/guidelines.html#THRESHOLDFORMAT):
`10` alerts outside 0..10, `10:` below 10, `'~:10'` above 10, `10:20` outside
10..20, and `@10:20` inside 10..20.

Quote a range with `~` on the command line, as shown: bash expands an
unquoted `~:10` to your home directory followed by `:10`.

## Output and exit codes

Every check prints exactly one line: the status, a summary and the performance
data. `0` OK, `1` WARNING, `2` CRITICAL, `3` UNKNOWN. An unreachable caster is
CRITICAL; rejected credentials and a wrong command line are UNKNOWN.

The plugin speaks NTRIP 1.0, which every caster supports.

## Bash completion

`completions/check_ntrip_caster` completes the modes, the options and their
values, also when the plugin is called by its full path. The packages install
it; otherwise copy it to bash-completion's directory:

```sh
install -D -m 0644 completions/check_ntrip_caster /usr/share/bash-completion/completions/check_ntrip_caster
```

## Tests

```sh
python3 -m unittest -v
```

## License

GPL-2.0-or-later, see [LICENSE](LICENSE).
