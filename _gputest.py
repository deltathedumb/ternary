
from cpu import TernarySystem, ternary_1
import traceback

if __name__ == "__main__":
    s = TernarySystem(ternary_1, num_cores=1, num_graphical_cores=1)
    try:
        s.gpu_cores[0].start()
        s.gpu_cores[0].join()
        print("OK")
    except Exception as e:
        traceback.print_exc()
        print("FAIL:", type(e).__name__, e)
