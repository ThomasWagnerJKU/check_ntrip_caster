"""Tests for the bash completion in completions/check_ntrip_caster."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "check_ntrip_caster")
COMPLETION = os.path.join(ROOT, "completions", "check_ntrip_caster")


def complete(*words, command="check_ntrip_caster", cwd=None, env=None):
    """The candidates bash offers for the last of words, which may be empty."""
    words = (command,) + words
    script = 'source "$1"; shift; COMP_WORDS=("$@"); COMP_CWORD=$(($# - 1)); ' \
             '$(complete -p "$1" | sed -E "s/.*-F ([^ ]+) .*/\\1/"); printf "%s\\n" "${COMPREPLY[@]}"'
    result = subprocess.run(["bash", "-c", script, "bash", COMPLETION] + list(words),
                            capture_output=True, text=True, check=True, cwd=cwd, env=env)
    return [line for line in result.stdout.split("\n") if line]


def help_text(*mode):
    return subprocess.run([PLUGIN] + list(mode) + ["--help"], capture_output=True, text=True,
                          check=True).stdout


def help_options(*mode):
    """The option strings --help of the plugin or of a mode lists."""
    options = set()
    for line in help_text(*mode).split("\n"):
        match = re.match(r"\s{2}(-\S.*?)(?:\s{2}|$)", line)
        if match:
            options.update(re.findall(r"(?<![\w-])-{1,2}[A-Za-z][\w-]*", match.group(1)))
    return options


def help_modes():
    """The modes --help lists, indented below MODE."""
    return set(re.findall(r"^ {4}([a-z]+) ", help_text(), re.MULTILINE))


@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class CompletionTests(unittest.TestCase):
    def test_syntax(self):
        subprocess.run(["bash", "-n", COMPLETION], check=True)

    def test_offers_exactly_the_options_and_modes_of_help(self):
        modes = help_modes()
        self.assertEqual(modes, {"sourcetable", "stream"})
        self.assertEqual(set(complete("")), help_options() | modes)

    def test_offers_exactly_the_options_of_each_mode(self):
        for mode in help_modes():
            self.assertEqual(set(complete(mode, "")), help_options(mode), mode)
            self.assertEqual(set(complete(mode, "-H", "caster", "-m", "RTCM", "")),
                             help_options(mode), mode)

    def test_mode_prefix(self):
        self.assertEqual(complete("so"), ["sourcetable"])
        self.assertEqual(complete("-V", "st"), ["stream"])

    def test_option_prefix(self):
        self.assertEqual(complete("stream", "--l"), ["--leap-seconds"])
        self.assertEqual(complete("sourcetable", "--l"), [])

    def test_files(self):
        with tempfile.TemporaryDirectory() as directory:
            open(os.path.join(directory, "ntrip.password"), "w").close()
            self.assertEqual(complete("stream", "-f", "nt", cwd=directory), ["ntrip.password"])
            self.assertEqual(complete("stream", "--password-file", "=", "nt", cwd=directory),
                             ["ntrip.password"])

    def test_hosts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".hosts") as hosts:
            hosts.write("192.0.2.1 caster\n")
            hosts.flush()
            env = dict(os.environ, HOSTFILE=hosts.name)
            self.assertEqual(complete("stream", "-H", "cas", env=env), ["caster"])
            self.assertEqual(complete("sourcetable", "--hostname", "=", "cas", env=env), ["caster"])

    def test_no_candidates_for_values(self):
        for option in ("-w", "--critical", "-m", "--port", "-u", "-P", "--duration",
                       "--leap-seconds"):
            self.assertEqual(complete("stream", option, ""), [], option)


if __name__ == "__main__":
    unittest.main()
