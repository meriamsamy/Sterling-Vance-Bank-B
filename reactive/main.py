from reactive import reactive_agent
import time

if __name__ == "__main__":
    start = time.perf_counter()
    result = reactive_agent(1001)
    end = time.perf_counter()
    print(result)
    print(f"Execution time: {(end - start) * 1000:.3f} ms")
