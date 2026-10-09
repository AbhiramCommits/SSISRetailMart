"""dtexec-style command line front end.

Examples::

    python -m ssis_runtime.cli /PACKAGE ssis/packages/LoadSalesCsv.dtsx /SET BatchId=7
    python -m ssis_runtime.cli /PACKAGE ssis/packages/LoadStores.dtsx \
        /SET BatchId=7 /SET LandingPath=data/landing/

Exit code 0 on success, 1 on failure (matching dtexec conventions).
"""

from __future__ import annotations

import json
import sys

from .engine import execute_package


def _parse_args(argv: list[str]) -> tuple[str | None, dict]:
    package = None
    params: dict = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("/PACKAGE", "--package", "-p"):
            index += 1
            package = argv[index]
        elif token in ("/SET", "--set", "-s"):
            index += 1
            name, _, value = argv[index].partition("=")
            params[name] = value
        elif token.startswith("/SET:"):
            name, _, value = token[len("/SET:") :].partition("=")
            params[name] = value
        elif token.startswith("/") and "=" in token and package:
            name, _, value = token[1:].partition("=")
            params[name] = value
        else:
            if package is None:
                package = token
            else:
                name, _, value = token.partition("=")
                params[name] = value
        index += 1
    return package, params


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    package, params = _parse_args(argv)
    if not package:
        print("usage: python -m ssis_runtime.cli /PACKAGE <file.dtsx> [/SET Name=Value ...]")
        return 1

    result = execute_package(package, params)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
