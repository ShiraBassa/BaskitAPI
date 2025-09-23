import time
from tqdm import tqdm
import threading

def worker(bar_id, total_iterations):
    # Main bar for overall progress
    with tqdm(total=total_iterations, position=bar_id*2, desc=f"Bar {bar_id}") as main_bar:
        # Sub-bar that acts as the "message line"
        with tqdm(total=0, position=bar_id*2 + 1, bar_format="{desc}") as msg_bar:
            for i in range(total_iterations):
                time.sleep(0.1)  # Simulate work
                main_bar.update(1)
                # Update the message line
                msg_bar.set_description(f"Processing step {i+1}/{total_iterations}")
                msg_bar.refresh()

if __name__ == "__main__":
    num_bars = 3
    threads = []

    for i in range(num_bars):
        thread = threading.Thread(target=worker, args=(i, (i + 1) * 10))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    print("\nAll bars completed!")