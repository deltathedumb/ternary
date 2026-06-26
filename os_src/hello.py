"""
Hello world user program.  load-addr=2000, frame-addr=4400, --lib.
"""

def printf(fmt: str, val: int) -> int:
    return 0


def fib(n: int) -> int:
    if n < 2:
        return n
    a = 0
    b = 1
    i = 2
    while i <= n:
        c = a + b
        a = b
        b = c
        i = i + 1
    return b


def main() -> int:
    result = fib(8)
    printf("%d\n", result)
    return 0
