# tests: lint, mypy

import tempfile
import subprocess
from neuralmonkey.logging import log

# pylint: disable=too-few-public-methods
# to be further refactored


class BeerWrapper(object):
    """Wrapper for BEER scorer"""
    # https://github.com/stanojevic/beer

    def __init__(self, wrapper, name="BEER", encoding="utf-8"):
        self.wrapper = wrapper
        self.encoding = encoding
        self.name = name

    def serialize_to_bytes(self, sentences):
        # type: (List[List[str]]) -> bytes
        joined = [" ".join(r) for r in sentences]
        string = "\n".join(joined) + "\n"
        return string.encode(self.encoding)

    def __call__(self, decoded, references):
        # type: (List[List[str]], List[List[str]]) -> float

        ref_bytes = self.serialize_to_bytes(references)
        dec_bytes = self.serialize_to_bytes(decoded)

        reffile = tempfile.NamedTemporaryFile()
        reffile.write(ref_bytes)
        reffile.flush()

        decfile = tempfile.NamedTemporaryFile()
        decfile.write(dec_bytes)
        decfile.flush()

        args = [self.wrapper, "-r", reffile.name, "-s", decfile.name]

        output_proc = subprocess.run(args,
                                     stderr=subprocess.PIPE,
                                     stdout=subprocess.PIPE)

        proc_stdout = output_proc.stdout.decode("utf-8")  # type: ignore
        lines = proc_stdout.splitlines()

        try:
            beer_score = float(lines[0].split()[-1])
            return beer_score
        except IndexError:
            log("Error: Malformed output from BEER wrapper:", color="red")
            log(proc_stdout, color="red")
            log("=======", color="red")
            return 0.0
        except ValueError:
            log("Value error - beer '{}' is not a number.".format(lines[0]),
                color="red")
            return 0.0
