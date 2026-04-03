import os
import re
import csv
import time
import queue
import threading
import pandas as pd
from datetime import datetime
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from utils import append_to_csv

PING_COUNT = 3
MAX_WORKERS = 6 # Juniper SSH session limit — do not exceed this
MAX_RETRIES = 1 # Ping-level retries per IP within a single round
READ_TIMEOUT = 20
SSH_RETRY_DELAY = 5 # Seconds between SSH reconnect attempts
ROUND_DELAY = 5 # Seconds to wait between retry rounds


# ---------------------------------------------------------------------------
# Core ping + parse
# ---------------------------------------------------------------------------

def ping_from_router(conn, ip):
    """
    Run a ping from Juniper router and parse output.
    Returns (status, avg_latency, connectivity).
    """
    cmd = f"ping rapid {ip} count {PING_COUNT}"
    try:
        output = conn.send_command_timing(cmd, delay_factor=2, read_timeout=READ_TIMEOUT)
    except Exception as e:
        print(f"[Juniper] Netmiko timeout on {ip}: {e}")
        return "Error", None, "Unknown"

    print(f"[Juniper][DEBUG] Output for {ip}:\n{output}\n") # helps diagnose Unknown/Error

    status = "Unknown/Error"
    avg_latency = None
    connectivity = "Unknown"

    # Check packets received — success if at least 1 out of 3 replied
    received_match = re.search(r"(\d+) packets received", output)
    packets_received = int(received_match.group(1)) if received_match else 0

    if packets_received == 0:
        status = "Fail"
    elif packets_received >= 1:
        status = "Success"
        # Handles both integer (1/2/3) and decimal (1.2/2.3/3.4) ms values
        match = re.search(r"min/avg/max/\S+ = ([\d.]+)/([\d.]+)/([\d.]+)", output)
        if match:
            avg_latency = float(match.group(2))
            connectivity = "VSAT" if avg_latency >= 550 else "4G"

    return status, avg_latency, connectivity


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

def connect_with_retry(config, stop_flag_fn):
    """
    Retry SSH connection indefinitely until successful or stop is requested.
    Returns a live Netmiko connection, or None if stopped.
    """
    attempt = 1
    while not stop_flag_fn():
        try:
            print(f"[Juniper] SSH connect attempt #{attempt} to {config['host']}...")
            conn = ConnectHandler(**config, fast_cli=False) # fast_cli=True breaks Juniper prompt handling
            print(f"[Juniper] SSH connected on attempt #{attempt}")
            return conn
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            print(f"[Juniper] SSH attempt #{attempt} failed: {e}. Retrying in {SSH_RETRY_DELAY}s...")
        except Exception as e:
            print(f"[Juniper] Unexpected SSH error on attempt #{attempt}: {e}. Retrying in {SSH_RETRY_DELAY}s...")
        attempt += 1
        time.sleep(SSH_RETRY_DELAY)
    return None


# ---------------------------------------------------------------------------
# CSV helpers — update rows in-place (used for retry rounds)
# ---------------------------------------------------------------------------

def update_csv_rows(output_csv, fieldnames, updates: dict):
    """
    Read the CSV, replace rows whose 'Destination IP' is in updates dict,
    and write back. updates = { ip: result_dict }
    Only called after a retry round completes — not during live pinging.
    """
    if not os.path.exists(output_csv):
        return
    rows = []
    with open(output_csv, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ip = row["Destination IP"]
            rows.append(updates[ip] if ip in updates else row)

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def get_unknown_error_ips(output_csv):
    """Return list of IPs whose Ping Result is 'Unknown/Error' in the CSV."""
    if not os.path.exists(output_csv):
        return []
    ips = []
    with open(output_csv, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Ping Result") == "Unknown/Error":
                ips.append(row["Destination IP"])
    return ips


def mark_ips_as_fail(output_csv, fieldnames, ips: list):
    """Replace 'Unknown/Error' with 'Fail' for IPs that couldn't be resolved."""
    if not os.path.exists(output_csv):
        return
    updates = {}
    with open(output_csv, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Destination IP"] in ips and row["Ping Result"] == "Unknown/Error":
                row["Ping Result"] = "Fail"
                updates[row["Destination IP"]] = row
    if updates:
        update_csv_rows(output_csv, fieldnames, updates)


# ---------------------------------------------------------------------------
# Worker — writes each result to CSV immediately (live save)
# ---------------------------------------------------------------------------

def worker(config, ip_queue, output_csv, fieldnames, lock, counter, total_ips,
           done_event, stop_flag_fn, progress_cb=None, progress_offset=0, progress_total=None,
           retry_mode=False):
    """
    Worker thread with its own fresh SSH session.

    KEY BEHAVIOUR: every result is written to CSV immediately after the ping
    completes — so stopping mid-run preserves all results collected so far.

    retry_mode=True → uses update_csv_rows logic (updates existing rows in-place)
    retry_mode=False → appends new rows (first pass)
    """
    conn = None
    # Accumulate retry results here so update_csv_rows can run after round
    retry_buffer = {} if retry_mode else None

    try:
        conn = connect_with_retry(config, stop_flag_fn)
        if conn is None:
            # User stopped during SSH retry — drain remaining queue entries
            while True:
                try:
                    ip = ip_queue.get_nowait()
                except queue.Empty:
                    break
                result = {
                    "Router": config["host"],
                    "Destination IP": ip,
                    "Ping Result": "Stopped",
                    "Average Latency (ms)": "N/A",
                    "Connectivity Type": "Unknown",
                }
                with lock:
                    if not retry_mode:
                        append_to_csv(output_csv, result, fieldnames) # live save
                    else:
                        retry_buffer[ip] = result
                    counter[0] += 1
                    if progress_cb and progress_total:
                        progress_cb(progress_offset + counter[0], progress_total)
                    if counter[0] >= total_ips:
                        done_event.set()
                ip_queue.task_done()
            return

        while True:
            if stop_flag_fn():
                break
            try:
                ip = ip_queue.get_nowait()
            except queue.Empty:
                break

            print(f"[Juniper] Pinging {ip}...")
            retries = 0
            result = None

            while retries <= MAX_RETRIES and not stop_flag_fn():
                try:
                    status, avg_latency, connectivity = ping_from_router(conn, ip)
                    result = {
                        "Router": config["host"],
                        "Destination IP": ip,
                        "Ping Result": status,
                        "Average Latency (ms)": avg_latency if avg_latency is not None else "N/A",
                        "Connectivity Type": connectivity,
                    }
                    break
                except Exception as e:
                    print(f"[Juniper] Error pinging {ip} (retry {retries}): {e}")
                    retries += 1

            if not result:
                result = {
                    "Router": config["host"],
                    "Destination IP": ip,
                    "Ping Result": "Unknown/Error",
                    "Average Latency (ms)": "N/A",
                    "Connectivity Type": "Unknown",
                }

            with lock:
                if not retry_mode:
                    # LIVE SAVE — written to disk immediately, safe if stopped anytime
                    append_to_csv(output_csv, result, fieldnames)
                else:
                    # Retry round — buffer results, update_csv_rows runs after round
                    retry_buffer[ip] = result

                counter[0] += 1
                if progress_cb and progress_total:
                    progress_cb(progress_offset + counter[0], progress_total)
                if counter[0] >= total_ips:
                    done_event.set()

            ip_queue.task_done()

    finally:
        if conn:
            try:
                conn.disconnect()
                print(f"[Juniper] Session closed for {config['host']}")
            except Exception:
                pass
        with lock:
            if counter[0] >= total_ips:
                done_event.set()

    # Return retry buffer so caller can flush it to CSV in one atomic update
    return retry_buffer


# ---------------------------------------------------------------------------
# Round runner
# ---------------------------------------------------------------------------

def router_ping(...):
    raise RuntimeError("Execution logic removed for public version")
    ip_queue = queue.Queue()
    for ip in ips_to_ping:
        ip_queue.put(ip)

    lock = threading.Lock()
    counter = [0]
    done_event = threading.Event()
    total_ips = len(ips_to_ping)
    grand_total = progress_total or total_ips
    threads = []
    thread_buffers = []

    workers_needed = min(MAX_WORKERS, total_ips)
    for _ in range(workers_needed):
        result_holder = [None]
        def thread_target(rh=result_holder):
            rh[0] = worker(
                config, ip_queue, output_csv, fieldnames, lock, counter, total_ips,
                done_event, stop_flag_fn, progress_cb, progress_offset, grand_total,
                retry_mode
            )
        t = threading.Thread(target=thread_target)
        t.daemon = True
        t.start()
        threads.append(t)
        thread_buffers.append(result_holder)

    done_event.wait()
    for t in threads:
        t.join(timeout=10)

    # Merge all worker retry buffers into one dict
    combined_buffer = {}
    for rh in thread_buffers:
        if rh[0]:
            combined_buffer.update(rh[0])
    return combined_buffer


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def router_ping(config, input_excel="input_ips.xlsx", stop_flag_fn=lambda: False, progress_cb=None):
    """
    Ping all IPs from Excel via Juniper router.
    - Uses up to 3 parallel SSH sessions (fresh per round)
    - Results written to CSV IMMEDIATELY after each ping — safe to stop anytime
    - Automatically retries all 'Unknown/Error' IPs in new rounds with 5s delay
    - Retries until zero Unknown/Error remain or no progress detected
    - Any unresolvable IPs → marked as 'Fail'
    """
    if not os.path.exists(input_excel):
        print(f"[Juniper] Input Excel '{input_excel}' not found.")
        return

    ip_df = pd.read_excel(input_excel, engine="openpyxl")
    dest_ips = ip_df.iloc[:, 0].dropna().astype(str).tolist()
    total_ips = len(dest_ips)

    output_csv = f"juniper_ping_results_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fieldnames = ["Router", "Destination IP", "Ping Result", "Average Latency (ms)", "Connectivity Type"]

    print(f"\n🔗 Launching {MAX_WORKERS} SSH sessions to Juniper router {config['host']}...")
    print(f" Total IPs to ping: {total_ips}")
    print(f" Results saving live to: {output_csv}")

    # ---- Round 1: ping all IPs, write each result to CSV live ----
    round_num = 1
    print(f"\n--- Round {round_num} — pinging all {total_ips} IPs ---")
    run_ping_round(
        config, dest_ips, output_csv, fieldnames, stop_flag_fn,
        progress_cb=progress_cb,
        progress_offset=0,
        progress_total=total_ips,
        retry_mode=False # live append per IP
    )

    # ---- Retry rounds for Unknown/Error IPs ----
    prev_unknown = None
    while not stop_flag_fn():
        unknown_ips = get_unknown_error_ips(output_csv)

        if not unknown_ips:
            print("\n✅ No Unknown/Error IPs remaining. All done!")
            break

        # No progress between rounds — mark as Fail and stop
        if prev_unknown is not None and set(unknown_ips) == set(prev_unknown):
            print(f"\n⚠️ {len(unknown_ips)} IP(s) still Unknown/Error with no change.")
            print(" Marking them as 'Fail' and stopping retries.")
            mark_ips_as_fail(output_csv, fieldnames, unknown_ips)
            break

        prev_unknown = unknown_ips
        round_num += 1
        n_unknown = len(unknown_ips)
        print(f"\n--- Round {round_num} — retrying {n_unknown} Unknown/Error IP(s) in {ROUND_DELAY}s ---")
        time.sleep(ROUND_DELAY)

        if progress_cb:
            progress_cb(0, n_unknown)

        retry_buffer = run_ping_round(
            config, unknown_ips, output_csv, fieldnames, stop_flag_fn,
            progress_cb=progress_cb,
            progress_offset=0,
            progress_total=n_unknown,
            retry_mode=True # buffer, then update rows in-place
        )

        # Flush retry results into CSV in one atomic rewrite
        if retry_buffer:
            update_csv_rows(output_csv, fieldnames, retry_buffer)
        print(f" Round {round_num} complete. CSV updated.")

    print(f"\n✅ Results saved to: {output_csv}")
    print(f"✅ Process complete for Juniper router {config['host']}")
