#!/usr/bin/python3

import logging
import re
import sys

from pathlib import Path


logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format="%(asctime)s %(levelname)-8s %(message)s")


# text / chord / bar replacements
# translate_text = {"‘": "'", "’": "'", "&": "\\&", "[": "{[}", "]": "{]}", "_": "{\\_}", "^": "\\^{}", "~": "{\\textasciitilde}", "\t": " "}
translate_text = {"<": "\\u2329", ">": "\\u232A", "[": "\\u2329", "]": "\\u232A"}
translate_chords = {"NC": "N.C.", "N/C": "N.C.", "aug": "+", "ø": "/o"}
translate_bars = {
    ":|:": "\\leftrightrepeat\\space",
    "|:": "\\leftrepeat\\space\\nolinebreak",
    ":|": "\\nolinebreak\\rightrepeat\\space",
    "|||": "\\nolinebreak\\stopbar\\space",
    "||": "\\doublebar\\space",
    "|": "\\normalbar\\space",
}

pattern_translate_text = re.compile("|".join(re.escape(key) for key in translate_text))
pattern_translate_chords = re.compile("|".join(re.escape(key) for key in translate_chords))
pattern_translate_bars = re.compile("|".join(re.escape(key) for key in translate_bars))


# pattern for splitting a line into words
pattern_non_whitespace = re.compile("\S+")

# chord components
pattern_chord_root = "[A-Ha-h][#b]?m?"
pattern_chord_quality = "(?:[0245679]|11|aug|[6]?add(?:2|4|9|11)?|maj(?:7|9|11)(?:sus[24])?|[67]?sus[24]?|dim|\\+|\\*|ø)?"
pattern_chord_bass = "(?:\/(?:[A-H][#b]?|9))?"
pattern_chord_appendix = "[*]*"
pattern_chord_no = "NC|N/C|N\.C\."
pattern_chord_full = f"{pattern_chord_root}{pattern_chord_quality}{pattern_chord_bass}{pattern_chord_appendix}|{pattern_chord_no}"

# chord with or without brackets
pattern_chord = re.compile(f"(?P<b>\()?(?:{pattern_chord_full})(?(b)\))")

# chordline marks
pattern_chordline_mark = re.compile(f"[-.'/]+")

# chordline bars and marks are accepted in a chord line besides chords
pattern_chordline_separator = re.compile(f"{pattern_translate_bars.pattern}|{pattern_chordline_mark.pattern}")


# pattern for metadata in 1st line or filename ("artist - title")
pattern_metadata_line = re.compile("(?P<artist>.+) - (?P<title>.+)")

# pattern for capo/tuning info in first few lines ("Capo: 5", "tune 1/2 step down", ...)
pattern_capo = re.compile("(?:Capo:|tune)")

pattern_capo_extract = re.compile("^Capo: (?P<capo>[0-9])")

# pattern for repetitions written next to the part header ("2x", "x3", "(4x)", "[x5]", ...)
pattern_repetition = "(?P<sb>\[)?(?P<rb>\()?(?P<x>x)?(?P<repeat>[0-9])(?(x)|x):?(?(rb)\))(?(sb)\])"

# pattern for part header ("[Chorus]", "[Verse 1]", ...) with optional repetition information
pattern_part_header = re.compile(f"(?P<all>\[(?P<name>[^][:]+)\])\s*(?:{pattern_repetition})?\s*")

patterns_part_synonyms = {
    "verse": re.compile("verse( ?[0-9]|\*)?", re.IGNORECASE),
    "chorus": re.compile("(chorus\*?|part|refrain)( ?[0-9])?", re.IGNORECASE),
    "intro": re.compile("intro", re.IGNORECASE),
    "noname": re.compile("interlude\*", re.IGNORECASE),
    "interlude": re.compile("interlude|fill|instrumental|organ|harmonica|piano", re.IGNORECASE),
    "solo": re.compile("solo", re.IGNORECASE),
    "bridge": re.compile("bridge( ?[0-9])?|bridge/solo", re.IGNORECASE),
    "prechorus": re.compile("pre-?chorus( ?[0-9])?", re.IGNORECASE),
    "outro": re.compile("outro|final|end|ending", re.IGNORECASE),
    "info": re.compile("info", re.IGNORECASE),
}

versetype_default = "verse"

# verse parts
#versebreak = " \\versebreak"

pattern_text_comment = re.compile(f"^\((?P<text>.*)\)$")

# tab parts
# identify a tab line
pattern_tab = re.compile("(?:\|-|-----|-\|)")

# info parts
pattern_info_chord_description = re.compile(f"(?P<description>[Xx0-9]{{6}})")
pattern_info_chord = re.compile(f"(?P<chord>{pattern_chord_full}): {pattern_info_chord_description.pattern}")

# infobreak = " \\\\"


def basename(filename: str) -> str:
    return Path(filename).stem


def multi_replace(text: str, pattern: re.Pattern, replacements: dict[str, str]):
    return pattern.sub(lambda x: replacements[x.group(0)], text)


class chordsheet_line(str):
    def __init__(self, line: str):
        self.type = self.get_type(line)

    def get_type(self, line: str) -> str:
        if self.is_line_empty(line):
            return "empty"
        elif self.is_line_part_header(line):
            return "part_header"
        elif self.is_line_tab(line):
            return "tab"
        elif self.is_line_chords(line):
            return "chords"
        else:
            return "text"

    def is_line_empty(self, line: str) -> bool:
        return line == ""

    def is_line_part_header(self, line: str) -> bool:
        return pattern_part_header.fullmatch(line) is not None

    def is_line_tab(self, line: str) -> bool:
        return pattern_tab.search(line) is not None

    def is_line_chords(self, line: str) -> bool:
        # list of words (word, position, chord match)
        words: list[tuple[str, int, bool]] = []
        chords: bool = False

        for m in pattern_non_whitespace.finditer(line):
            if pattern_chord.fullmatch(m.group(0)):
                # chord
                words.append((m.group(0), m.start(0), True))
                chords = True
            elif pattern_chordline_separator.fullmatch(m.group(0)):
                # separator (bar or mark)
                words.append((m.group(0), m.start(0), False))
            else:
                # anything not accepted
                return False

        if chords:
            # at least one valid chord

            # keep the list of words so they can be reused
            self.word_list = words

            return True

        else:
            return False


class chordpro_lines:
    def __init__(self, lines: list[str], rep: int = 1):
        self.lines = lines
        self.rep = rep

    def __eq__(self, other):
        if isinstance(other, chordpro_lines):
            return self.rep == other.rep and self.lines == other.lines

        raise NotImplemented

    def __radd__(self, other):
        if other == 0:
            return self
        else:
            return self.__add__(other)

    def __add__(self, other):
        if isinstance(other, chordpro_lines):
            return chordpro_lines(self.lines + other.lines, self.rep)

        raise NotImplemented

    def export(self) -> list[str]:
        if self.rep == 0:
            return []

        result = self.lines.copy()

        if self.rep > 1:
            raise ValueError
        
        return result


class song:
    def __init__(self, lines: list[chordsheet_line], filename: str):
        self.lines = lines
        self.filename = filename

        self.metadata: dict[str, str] = {}
        self.metadata_src: list[chordsheet_line] = []
        self.song_parts: list[song_part] = []

        self.get_metadata(self.lines)

        self.get_parts(self.lines)

        self.merge_repeating_parts()
        self.merge_consecutive_tab_parts()

    def export(self) -> list[str]:
        result = []

        result.append(f"# {self.filename}")
        result.append("")

        for line in self.metadata_src:
            result.append(f"# {line}")

        for key, value in self.metadata.items():
            result.append("{{{}: {}}}".format(key, value))
        result.append("")

        # first non-info part to be labelled 'Intro' when it just contains chords
        first_non_info = next((i for i, part in enumerate(self.song_parts) if part.versetype != "info"), None)
        # last part to be labelled 'Outro' when it just contains chords
        last = len(self.song_parts) - 1

        # song parts
        for i, part in enumerate(self.song_parts):
            result.extend(part.export(i == first_non_info, i == last))
            result.append("")

        return result

    def get_metadata(self, lines: list[chordsheet_line]):
        self.get_song_metadata(lines)
        self.add_extended_metadata()

        logging.debug("extracted metadata: {}".format(self.metadata))

    def get_song_metadata(self, lines: list[chordsheet_line]):
        if lines and (m := pattern_metadata_line.fullmatch(lines[0])):
            # get song metadata from first line
            self.metadata.update(m.groupdict())
            self.metadata_src.append(lines.pop(0))
        elif m := pattern_metadata_line.fullmatch(basename(self.filename)):
            # fallback to filename
            self.metadata.update(((key, value.title()) for key, value in m.groupdict().items()))

    def add_extended_metadata(self):
        if "title" in self.metadata.keys():
            if m := re.search("^(The|Die) (.*$)", self.metadata["title"]):
                self.metadata["sorttitle"] = f"{m[2]}, {m[1]}".replace("!", "")

            elif m := re.search("^(.*), (The|Die)", self.metadata["title"]):
                self.metadata["sorttitle"] = self.metadata["title"].replace("!", "")
                self.metadata["title"] = f"{m[2]} {m[1]}"

            elif "!" in self.metadata["title"]:
                self.metadata["sorttitle"] = self.metadata["title"].replace("!", "")

            elif "'" in self.metadata["title"]:
                self.metadata["sorttitle"] = self.metadata["title"].replace("'", "")

        if "artist" in self.metadata.keys():
            if m := re.search("^(.*), (The|Die)", self.metadata["artist"]):
                self.metadata["artist"] = f"{m[2]} {m[1]}"            


    def skip_empty_lines(self, lines: list[chordsheet_line]):
        while lines and lines[0].type == "empty":
            lines.pop(0)

    def add_part(self, part_env: str, part_label: str, part_src: list[chordsheet_line], part_lines: list[chordsheet_line], part_rep: int):
        self.song_parts.append(song_part(versetype=part_env, label=part_label, src=part_src, lines=part_lines, rep=part_rep))

    def get_parts(self, lines: list[chordsheet_line]):
        self.skip_empty_lines(lines)

        # initialize first part
        (part_env, part_label, part_src, part_lines, part_rep) = (None, None, [], [], 1)

        # create an info part when the first line contains capo information
        if lines and pattern_capo.match(lines[0]):
            part_env = "info"
            logging.info("extracting info part")

            # create metadata for capo
            if (m := pattern_capo_extract.match(lines[0])):
                self.metadata["capo"] = m.group("capo")

        for l, line in enumerate(lines):

            # split on part header
            if line.type == "part_header":
                if part_lines or part_env is not None:
                    if not part_lines:
                        logging.warning("zero-length part '{}'".format(part_env))

                    # add previous part
                    self.add_part(part_env, part_label, part_src, part_lines, part_rep)

                # initialize new part
                (part_env, part_label, part_src, part_lines, part_rep) = self.extract_part_header(line)

            elif line.type == "empty":
                if not part_lines:
                    # add leading empty lines to src only
                    part_src.append(line)

                elif (
                    # don't split on empty line followed by text line
                    (l + 1 < len(lines) and lines[l + 1].type == "text")
                    # next line but one must be chords or empty
                    and (l + 2 >= len(lines) or lines[l + 2].type in ["chords", "empty"])
                ):
                    part_src.append(line)
                    part_lines.append(line)

                else:
                    # split part
                    self.add_part(part_env, part_label, part_src, part_lines, part_rep)

                    # initialize next part
                    (part_env, part_label, part_src, part_lines, part_rep) = (None, None, [], [], 1)

            else:
                part_src.append(line)
                part_lines.append(line)

        if part_lines:
            self.add_part(part_env, part_label, part_src, part_lines, part_rep)

    def extract_part_header(self, line: chordsheet_line) -> tuple[str, list[chordsheet_line], list[chordsheet_line], int]:
        if (m := pattern_part_header.fullmatch(line)) is None:
            raise ValueError

        part_env = versetype_default
        part_label = m.group("name")
        part_src = [line]
        part_lines = []
        part_rep = 1

        for v, pattern in patterns_part_synonyms.items():
            if pattern.fullmatch(m.group("name")):
                # name has a match in 'part_synonyms'
                part_env = v
                break

        else:
            # for loop didn't break = name has no match
            logging.warning("unknown versetype: {}".format(m.group("name")))
            part_lines = [chordsheet_line(m.group("all"))]

        if m.group("repeat") is not None:
            logging.debug("found repeating part: {} x{}".format(m.group("name"), m.group("repeat")))
            part_rep = int(m.group("repeat"))

        return part_env, part_label, part_src, part_lines, part_rep

    def merge_repeating_parts(self):
        p = 0
        while p < len(self.song_parts) - 1:
            if self.song_parts[p] == self.song_parts[p + 1] and len(self.song_parts[p].chordpro_lines) > 0:
                logging.debug("found repeating parts")
                self.song_parts[p].chordsheet_src.append("")
                self.song_parts[p].chordsheet_src.extend(self.song_parts[p + 1].chordsheet_src)
                self.song_parts[p].rep += self.song_parts[p + 1].rep
                self.song_parts.pop(p + 1)
            else:
                p += 1

    def merge_consecutive_tab_parts(self):
        p = 0
        while p < len(self.song_parts) - 1:
            if (
                isinstance(self.song_parts[p], tab_part)
                and isinstance(self.song_parts[p + 1], tab_part)
                and self.song_parts[p].rep == 1
                and self.song_parts[p + 1].rep == 1
                and self.song_parts[p + 1].versetype is None
            ):
                logging.debug("found consecutive tab parts")
                self.song_parts[p].chordsheet_src.append("")
                self.song_parts[p].chordsheet_src.extend(self.song_parts[p + 1].chordsheet_src)
                self.song_parts[p].chordsheet_lines.append(chordsheet_line(""))
                self.song_parts[p].chordsheet_lines.extend(self.song_parts[p + 1].chordsheet_lines)
                self.song_parts[p].chordpro_lines.append(chordpro_lines([""]))
                self.song_parts[p].chordpro_lines.extend(self.song_parts[p + 1].chordpro_lines)
                self.song_parts.pop(p + 1)
            else:
                p += 1


class song_part:
    def __new__(cls, versetype: str, label: str, src: list[chordsheet_line], lines: list[chordsheet_line], rep: int = 1):
        # choose and return a suitable sublass
        if versetype == "info":
            return object.__new__(info_part)
        elif any(line.type == "tab" for line in lines):
            return object.__new__(tab_part)
        else:
            return object.__new__(verse_part)

    def __init__(self, versetype: str, label: str, src: list[chordsheet_line], lines: list[chordsheet_line], rep: int = 1):
        self.versetype = versetype 
        self.label = label
        self.chordsheet_src = src
        self.chordsheet_lines = lines
        self.rep = rep

        self.chordpro_lines: list[chordpro_lines] = self.convert()

    def __eq__(self, other):
        if isinstance(other, song_part):
            return self.chordpro_lines == other.chordpro_lines

        raise NotImplemented

    def get_versetype(self, is_first: bool, is_last: bool, default: str) -> str:
        if self.versetype is not None:
            return self.versetype

        return default

    def export(self, is_first: bool = False, is_last: bool = False) -> list[str]:
        verse_type = self.get_versetype(is_first, is_last, versetype_default)

        result = []
        for line in self.chordsheet_src:
            result.append(f"# {line}")

        if verse_type not in ["chorus", "verse", "noname"] and self.label:
            result.append("{{start_of_{}: {}}}".format(verse_type, self.label))
        else:
            result.append("{{start_of_{}}}".format(verse_type))

        result.extend(self.export_lines())
        result.append("{{end_of_{}}}".format(verse_type))

        if self.rep == 2:
            result.append("{comment: repeat}")
        if self.rep > 2:
            result.append("{{comment: repeat {} times}}".format(self.rep))

        return result

    def export_lines(self) -> list[str]:
        result = []
        for line in self.chordpro_lines:
            result.extend(line.export())

        return result

    def convert(self) -> list[chordpro_lines]:
        raise NotImplemented

    def format_chord(self, chord: str, text: str = "") -> str:
        return "[{}]{}".format(self.clean_post_chord(chord), self.format_text(text, bar_replace=True))

    def format_chord_sep(self, sep: str) -> str:
        return "[*{}]".format(sep)

    def format_text(self, text: str, bar_replace: bool = False) -> str:
        text = multi_replace(text, pattern_translate_text, translate_text)

        if (m := re.match(pattern_text_comment, text)):
            return("{{comment: {}}}".format(m.group("text")))

        return text

    def clean_post_chord(self, chord: str) -> str:
        return multi_replace(chord, pattern_translate_chords, translate_chords)

    def clean_output_line(self, line: str) -> str:
        return line.strip()


class verse_part(song_part):
    def __init__(self, versetype: str, label: str, src: list[chordsheet_line], lines: list[chordsheet_line], rep: int = 1):
        super().__init__(versetype, label, src, lines, rep)
        #self.merge_repeating_lines()

    def get_versetype(self, is_first: bool, is_last: bool, default: str) -> str:
        if self.versetype is not None:
            return self.versetype

        if all(line.type == "chords" for line in self.chordsheet_lines):
            if is_first:
                return "intro"
            elif is_last:
                return "outro"
            else:
                return "interlude"

        return default

    def convert(self) -> list[chordpro_lines]:
        result = []

        c = 0

        while c < len(self.chordsheet_lines):
            if self.chordsheet_lines[c].type == "chords":
                if c < len(self.chordsheet_lines) - 1 and self.chordsheet_lines[c + 1].type == "text":
                    # chords over text
                    result.append(self.convert_chords_over_text(self.chordsheet_lines[c], self.chordsheet_lines[c + 1]))
                    c += 2
                else:
                    # chords only
                    result.append(self.convert_chords(self.chordsheet_lines[c]))
                    c += 1
            elif self.chordsheet_lines[c].type != "empty":
                # text or other non-empty line
                result.append(self.convert_text(self.chordsheet_lines[c]))
                c += 1
            else:
                # empty line
                c += 1

        return result

    def convert_chords_over_text(self, line_chords: chordsheet_line, line_text: chordsheet_line) -> chordpro_lines:
        chord_list = line_chords.word_list

        # text prior to first chord
        converted = format(self.format_text(line_text[0 : chord_list[0][1]], bar_replace=True))

        for c, (chord, chord_pos, _) in enumerate(chord_list):

            # when this is not the last chord and the text extends the next chord
            if c < len(chord_list) - 1 and (chord_next_pos := chord_list[c + 1][1]) < len(line_text):
                # get the text between this chord and the next chord
                text = line_text[chord_pos:chord_next_pos]
            else:
                # get the text after this chord
                text = line_text[chord_pos:] + " "

            text = re.sub("  +$", " ", text)

            converted += self.format_chord(chord, text)

        return chordpro_lines([self.clean_output_line(converted)])

    def convert_chords(self, line: chordsheet_line) -> chordpro_lines:
        converted = ""

        for (word, _, word_is_chord) in line.word_list:

            if word_is_chord:
                converted += self.format_chord(word)
            else:
                converted += self.format_chord_sep(word)

            converted += " "

        return chordpro_lines([self.clean_output_line(converted)])

    def convert_text(self, line: chordsheet_line) -> chordpro_lines:
        converted = self.format_text(line, bar_replace=True)
        return chordpro_lines([self.clean_output_line(converted)])

    def merge_repeating_lines(self):
        pos = 0

        while pos < len(self.chordpro_lines):

            # check for subsequent matches of 1 to 4 lines
            for repeat_length in range(1, 5):

                repeat_count = 1

                # check there is enough space left to compare
                while (compare_start := pos + repeat_count * repeat_length) + repeat_length <= len(self.chordpro_lines):

                    # check all lines match
                    if all(self.chordpro_lines[pos + p] == self.chordpro_lines[compare_start + p] for p in range(repeat_length)):
                        repeat_count += 1
                    else:
                        break

                if repeat_count > 1:
                    logging.debug("found repeating lines (position={}, length={}, count={})".format(pos, repeat_length, repeat_count))

                    # merge line at position
                    self.chordpro_lines[pos] = sum(self.chordpro_lines[pos : pos + repeat_length])
                    self.chordpro_lines[pos].rep = repeat_count

                    # remove merged lines
                    for _ in range(repeat_count * repeat_length - 1):
                        self.chordpro_lines.pop(pos + 1)

                    break

            pos += 1


class tab_part(song_part):
    def get_versetype(self, is_first: bool, is_last: bool, default: str) -> str:
        return "tab"

    def convert(self) -> list[chordpro_lines]:
        result = []

        for line in self.chordsheet_lines:
            result.append(line)

        return [chordpro_lines(result)]


class info_part(song_part):
    def export(self, is_first: bool = False, is_last: bool = False) -> list[str]:
        verse_type = self.get_versetype(is_first, is_last, versetype_default)

        result = []
        for line in self.chordsheet_src:
            result.append(f"# {line}")

        for line in self.export_lines():
            result.append(self.format_info_text(line))

        if self.rep >= 2:
            raise ValueError

        return result

    def convert(self) -> list[chordpro_lines]:
        result = []

        for line in self.chordsheet_lines:
            result.append(self.convert_info_line(line))

        return [chordpro_lines(result)]

    def convert_info_line(self, text: chordsheet_line) -> str:
        converted = self.format_text(text)
        converted = pattern_info_chord.sub(self.format_info_chord, converted)
        return converted

    def format_info_chord(self, match: re.Match) -> str:
        return "{}: {}".format(self.format_chord(match.group("chord")), match.group("description"))

    def format_info_text(self, text: str, bar_replace: bool = False) -> str:
        text = multi_replace(text, pattern_translate_text, translate_text)

        if (m := re.match(pattern_text_comment, text)):
            return("{{comment: {}}}".format(m.group("text")))
        else:
            return("{{comment: {}}}".format(text))
        

def convert_file(filename_input: str, filename_output: str) -> bool:
    logging.info("converting '{}' to '{}'".format(filename_input, filename_output))
    lines = read_file(filename_input)
    if lines:
        s = song(lines, filename_input)
        write_file(filename_output, s.export())
        return True
    else:
        logging.error("empty file: '{}'".format(filename_input))
        return False


def read_file(filename: str) -> list[chordsheet_line]:
    with open(filename, "r") as file:
        lines = file.readlines()

    return [chordsheet_line(line.rstrip()) for line in lines]


def write_file(filename: str, lines: list[str]):
    with open(filename, "w") as file:
        file.writelines((f"{line}\n" for line in lines))


def main():
    song_list = []

    for filename_input in sys.argv[1:]:
        filename_output = "songs/{}.cho".format(basename(filename_input))

        if convert_file(filename_input, filename_output):
            song_list.append("\\input{{{}}}".format(filename_output))

    write_file("songs.tex", song_list)


if __name__ == "__main__":
    main()
