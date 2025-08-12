#!/usr/bin/env python3
"""
Error Benchmark Script
----------------------
Run this file to generate a structured report of many error *categories* your tool should detect:
- Syntax/Parsing errors (simulated via compile() so this file remains runnable)
- Runtime Name/Scope errors
- Runtime Value/Type errors
- Arithmetic/Math errors
- File & I/O errors
- Warnings (Deprecation/Resource/Syntax-like via warnings.warn)
- Static-analysis targets (dead code, unused vars, questionable patterns)

Usage:
    python error_benchmark.py

This prints a JSON-like report of results to stdout.
"""

import sys, math, os, io, warnings, traceback, gc, tempfile, json

# -------- Utilities --------
def run_compile_test(name, code):
    """Attempt to compile a code string and capture Syntax/Indentation/Tab errors."""
    try:
        compile(code, f"<compile_test:{name}>", "exec")
        return {"name": name, "phase": "compile", "status": "PASS", "exception": None}
    except Exception as e:
        etype = type(e).__name__
        return {
            "name": name,
            "phase": "compile",
            "status": "FAIL",
            "exception": {"type": etype, "msg": str(e)}
        }

def run_exec_test(name, func):
    """Run a callable that should trigger a runtime exception."""
    try:
        func()
        return {"name": name, "phase": "runtime", "status": "PASS", "exception": None}
    except Exception as e:
        etype = type(e).__name__
        return {
            "name": name,
            "phase": "runtime",
            "status": "FAIL",
            "exception": {"type": etype, "msg": str(e)}
        }

def run_warning_test(name, warn_callable):
    """Capture warnings emitted by the callable."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        warn_callable()
        items = []
        for wi in w:
            items.append({"category": wi.category.__name__, "message": str(wi.message)})
        return {"name": name, "phase": "warning", "emitted": items}

def header(title):
    print("\n" + "="*80)
    print(title)
    print("="*80)

# -------- 1) Syntax & Parsing (compile-time) --------
compile_tests = [
    ("missing_colon_in_def", "def calculate_area(radius)\n    return 3.14*radius**2"),
    ("bad_print_concat", 'def f():\n    print("Area is: " area)'),
    ("for_missing_colon", "for i in range(5)\n    pass"),
    ("indentation_error", "for i in range(3):\nprint(i)"),
    ("tab_error_mixed_indent", "def f():\n\tif True:\n        return 1\n\treturn 0"),
    ("keyword_misuse", 'class = "not allowed"'),
    ("invalid_identifier", "1abc = 5"),
    ("invalid_string_literal", "s = 'unterminated"),
    ("invalid_number_literal", "x = 0xG1"),
    ("def_missing_parens_and_colon", "def greet\n    pass"),
]

# -------- 2) Runtime Name & Scope Errors --------
def name_error():
    print(unknown_variable)  # NameError

def unbound_local_error():
    x = 1
    def f():
        # x is treated as local due to assignment below, so this read is UnboundLocalError
        print(x)   # UnboundLocalError
        x = 2
    f()

def import_error():
    import nonexistent_module  # ModuleNotFoundError (subclass of ImportError)

def attribute_error():
    "hello".non_existing_method()  # AttributeError

runtime_name_scope = [
    ("NameError", name_error),
    ("UnboundLocalError", unbound_local_error),
    ("ImportError/ModuleNotFoundError", import_error),
    ("AttributeError", attribute_error),
]

# -------- 3) Runtime Value & Type Errors --------
def type_error():
    _ = "100" + 50  # TypeError

def value_error():
    _ = int("abc")  # ValueError

def key_error():
    d = {"a": 1, "b": 2}
    _ = d["c"]  # KeyError

def index_error():
    _ = [][1]  # IndexError

def stop_iteration():
    _ = next(iter(()))  # StopIteration

runtime_value_type = [
    ("TypeError", type_error),
    ("ValueError", value_error),
    ("KeyError", key_error),
    ("IndexError", index_error),
    ("StopIteration", stop_iteration),
]

# -------- 4) Arithmetic & Math Errors --------
def zero_division_error():
    _ = 1 / 0  # ZeroDivisionError

def overflow_error():
    _ = math.exp(1000)  # OverflowError on CPython

def floating_point_error():
    # Hard to trigger organically without numpy/fpectl; raise explicitly to test handling
    raise FloatingPointError("Simulated FloatingPointError for benchmark")

runtime_math = [
    ("ZeroDivisionError", zero_division_error),
    ("OverflowError", overflow_error),
    ("FloatingPointError (simulated)", floating_point_error),
]

# -------- 5) File & I/O Errors --------
def file_not_found_error():
    with open("this_file_should_not_exist_12345.txt", "r"):
        pass

def permission_error():
    # Simulate for portability
    raise PermissionError("Simulated PermissionError for benchmark")

def is_a_directory_error():
    with tempfile.TemporaryDirectory() as d:
        with open(d, "r"):
            pass  # IsADirectoryError

def not_a_directory_error():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    try:
        with open(os.path.join(path, "file.txt"), "w"):
            pass  # NotADirectoryError
    finally:
        os.remove(path)

def generic_os_error():
    os.rename("no_such_src_file_xyz", "no_such_dest_file_xyz")  # OSError subclass (FileNotFoundError)

runtime_io = [
    ("FileNotFoundError", file_not_found_error),
    ("PermissionError (simulated)", permission_error),
    ("IsADirectoryError", is_a_directory_error),
    ("NotADirectoryError", not_a_directory_error),
    ("OSError (rename on missing path)", generic_os_error),
]

# -------- 6) Warnings --------
def deprecation_warning():
    warnings.warn("This API is deprecated.", DeprecationWarning)

def resource_warning():
    warnings.simplefilter("always", ResourceWarning)
    def leak():
        f = open(__file__, "r")  # don't close
    leak()
    gc.collect()  # prompt finalizers; may emit ResourceWarning on some runtimes

def syntax_like_warning():
    # Use of 'is' with a literal is often flagged by linters; we emit explicit warning here
    warnings.warn("'is' used with a literal; use '=='", SyntaxWarning)

warning_tests = [
    ("DeprecationWarning", deprecation_warning),
    ("ResourceWarning (may be environment-dependent)", resource_warning),
    ("SyntaxWarning (explicit)", syntax_like_warning),
]

# -------- 7) Static-analysis targets (no exceptions raised) --------
static_snippets = {
    "dead_code": """
def dead():
    return 1
    x = 2  # unreachable
""",
    "unused_variables": """
def unused():
    a = 1  # never used
    b = 2  # never used
    return 0
""",
    "questionable_boolean": """
def qb(x):
    # Always true; linters flag this
    if x == 1 or 2:
        return True
""",
    "eval_usage": """
def insecure(user_input):
    return eval(user_input)  # security smell
""",
    "broad_except": """
def broad():
    try:
        1/0
    except Exception:
        pass  # too broad
""",
    "mut_default_arg": """
def mdfa(x, acc=[]):
    acc.append(x)  # mutable default arg
    return acc
""",
}

def main():
    report = {
        "compile": [],
        "runtime": [],
        "warnings": [],
        "static_snippets": list(static_snippets.keys()),
        "python": sys.version,
    }

    header("1) COMPILE-TIME TESTS (Syntax/Indent/Tab/Identifiers)")
    for name, code in compile_tests:
        res = run_compile_test(name, code)
        report["compile"].append(res)
        print(f"- {name}: {res['status']}"
              + (f" | {res['exception']['type']}: {res['exception']['msg']}" if res['exception'] else ""))

    header("2) RUNTIME TESTS — Name & Scope")
    for name, fn in runtime_name_scope:
        res = run_exec_test(name, fn)
        report["runtime"].append(res)
        print(f"- {name}: {res['status']}"
              + (f" | {res['exception']['type']}: {res['exception']['msg']}" if res['exception'] else ""))

    header("3) RUNTIME TESTS — Value & Type")
    for name, fn in runtime_value_type:
        res = run_exec_test(name, fn)
        report["runtime"].append(res)
        print(f"- {name}: {res['status']}"
              + (f" | {res['exception']['type']}: {res['exception']['msg']}" if res['exception'] else ""))

    header("4) RUNTIME TESTS — Arithmetic/Math")
    for name, fn in runtime_math:
        res = run_exec_test(name, fn)
        report["runtime"].append(res)
        print(f"- {name}: {res['status']}"
              + (f" | {res['exception']['type']}: {res['exception']['msg']}" if res['exception'] else ""))

    header("5) RUNTIME TESTS — File & I/O")
    for name, fn in runtime_io:
        res = run_exec_test(name, fn)
        report["runtime"].append(res)
        print(f"- {name}: {res['status']}"
              + (f" | {res['exception']['type']}: {res['exception']['msg']}" if res['exception'] else ""))

    header("6) WARNINGS")
    for name, wfn in warning_tests:
        res = run_warning_test(name, wfn)
        report["warnings"].append(res)
        emitted = ", ".join([i["category"] for i in res["emitted"]]) or "none"
        print(f"- {name}: {emitted}")

    header("7) STATIC-ANALYSIS TARGETS (for linters; not executed)")
    for key, snippet in static_snippets.items():
        print(f"- {key}: provided")

    print("\n" + "="*80)
    print("SUMMARY (machine-readable)")
    print("="*80)
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
