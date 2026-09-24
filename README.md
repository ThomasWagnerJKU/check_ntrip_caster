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
`10` alerts outside 0..10, `10:` below 10, `~:10` above 10, `10:20` outside
10..20, and `@10:20` inside 10..20.

## Output and exit codes

Every check prints exactly one line: the status, a summary and the performance
data. `0` OK, `1` WARNING, `2` CRITICAL, `3` UNKNOWN. An unreachable caster is
CRITICAL; rejected credentials and a wrong command line are UNKNOWN.

The plugin speaks NTRIP 1.0, which every caster supports.

## License

GPL-2.0-or-later, see [LICENSE](LICENSE).
