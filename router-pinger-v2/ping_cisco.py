
# ping_cisco.py
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
MAX_WORKERS = 5 # Adjust based on your Cisco router's SSH session limit
MAX_RETRIES = 1 # Ping-level retries per IP within a single round
READ_TIMEOUT = 20
SSH_RETRY_DELAY = 5 # Seconds between SSH reconnect attempts
ROUND_DELAY = 5 # Seconds to wait between retry rounds


# ---------------------------------------------------------------------------
# Core ping + parse
# ---------------------------------------------------------------------------

def ping_from_router(conn, ip):
    """
    Run a ping from Cisco router and parse output.
    Returns (status, avg_latency, connectivity).
    """
    cmd = f"ping {ip} repeat {PING_COUNT}"
    try:
        output = conn.send_command_timing(cmd, delay_factor=2, read_timeout=READ_TIMEOUT)
    except Exception as e:
        print(f"[Cisco] Netmiko timeout on {ip}: {e}")
        return "Error", None, "Unknown"

    status = "Unknown/Error"
    avg_latency = None
    connectivity = "Unknown"

    if "Success rate is 0 percent" in output or "0 packets received" in output:
        status = "Fail"
    elif "Success rate is" in output and "round-trip min/avg/max" in output:
        status = "Success"
        match = re.search(r"min/avg/max = (\d+)/(\d+)/(\d+)", output)
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
            print(f"[Cisco] SSH connect attempt #{attempt} to {config['host']}...")
            conn = ConnectHandler(**config, fast_cli=True)
            print(f"[Cisco] SSH connected on attempt #{attempt}")
            return conn
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            print(f"[Cisco] SSH attempt #{attempt} failed: {e}. Retrying in {SSH_RETRY_DELAY}s...")
        except Exception as e:
            print(f"[Cisco] Unexpected SSH error on attempt #{attempt}: {e}. Retrying in {SSH_RETRY_DELAY}s...")
        attempt += 1
        time.sleep(SSH_RETRY_DELAY)
    return None


# ---------------------------------------------------------------------------
# CSV helpers — update rows in-place
# ---------------------------------------------------------------------------

def update_csv_rows(output_csv, fieldnames, updates: dict):
    """
    Read CSV, replace rows whose 'Destination IP' is in updates, write back.
    updates = { ip: result_dict }
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
    """Return list of IPs whose Ping Result is 'Unknown/Error'."""
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
# Worker
# ---------------------------------------------------------------------------

def worker(config, ip_queue, results_store, lock, counter, total_ips,
           done_event, stop_flag_fn, progress_cb=None, progress_offset=0, progress_total=None):
    """
    Worker thread with its own fresh SSH session.
    Writes results into results_store dict { ip: result_dict }.
    Calls progress_cb(done, grand_total) after every IP so the bar moves live.
      progress_offset — IPs already done before this round (for retry rounds)
      progress_total — grand total IPs for the progress bar
    """
    conn = None
    try:
        conn = connect_with_retry(config, stop_flag_fn)
        if conn is None:
            while True:
                try:
                    ip = ip_queue.get_nowait()
                except queue.Empty:
                    break
                with lock:
                    results_store[ip] = {
                        "Router": config["host"],
                        "Destination IP": ip,
                        "Ping Result": "Stopped",
                        "Average Latency (ms)": "N/A",
                        "Connectivity Type": "Unknown",
                    }
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

            print(f"[Cisco] Pinging {ip}...")
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
                    print(f"[Cisco] Error pinging {ip} (retry {retries}): {e}")
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
                results_store[ip] = result
                counter[0] += 1
                # Update progress bar live after every single IP
                if progress_cb and progress_total:
                    progress_cb(progress_offset + counter[0], progress_total)
                if counter[0] >= total_ips:
                    done_event.set()

            ip_queue.task_done()

    finally:
        if conn:
            try:
                conn.disconnect()
                print(f"[Cisco] Session closed for {config['host']}")
            except Exception:
                pass
        with lock:
            if counter[0] >= total_ips:
                done_event.set()


# ---------------------------------------------------------------------------
# Round runner
# ---------------------------------------------------------------------------

def run_ping_round(config, ips_to_ping, stop_flag_fn,
                   progress_cb=None, progress_offset=0, progress_total=None):
    """
    Open fresh SSH sessions and ping a list of IPs.
    Returns results_store dict { ip: result_dict }.
    progress_cb is called after every IP so the GUI bar moves live.
    """
    ip_queue = queue.Queue()
    for ip in ips_to_ping:
        ip_queue.put(ip)

    results_store = {}
    lock = threading.Lock()
    counter = [0]
    done_event = threading.Event()
    total_ips = len(ips_to_ping)
    threads = []
    grand_total = progress_total or total_ips

    workers_needed = min(MAX_WORKERS, total_ips)
    for _ in range(workers_needed):
        t = threading.Thread(
            target=worker,
            args=(config, ip_queue, results_store, lock, counter, total_ips,
                  done_event, stop_flag_fn, progress_cb, progress_offset, grand_total)
        )
        t.daemon = True
        t.start()
        threads.append(t)

    done_event.wait()
    for t in threads:
        t.join(timeout=10)

    return results_store


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def router_ping(config, input_excel="input_ips.xlsx", stop_flag_fn=lambda: False, progress_cb=None):
    """
    Ping all IPs from Excel via Cisco router.
    - Uses up to 5 parallel SSH sessions (fresh per round)
    - Automatically retries all 'Unknown/Error' IPs in new rounds with 5s delay
    - Retries until zero Unknown/Error remain or stop is requested
    - Any unresolvable IPs after rounds with no progress → marked as 'Fail'
    - CSV updated in-place after every round
    """
    if not os.path.exists(input_excel):
        print(f"[Cisco] Input Excel '{input_excel}' not found.")
        return

    ip_df = pd.read_excel(input_excel, engine="openpyxl")
    dest_ips = ip_df.iloc[:, 0].dropna().astype(str).tolist()
    total_ips = len(dest_ips)

    output_csv = f"cisco_ping_results_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fieldnames = ["Router", "Destination IP", "Ping Result", "Average Latency (ms)", "Connectivity Type"]

    print(f"\n🔗 Launching {MAX_WORKERS} SSH sessions to Cisco router {config['host']}...")
    print(f" Total IPs to ping: {total_ips}")

    # ---- Round 1: ping all IPs ----
    round_num = 1
    print(f"\n--- Round {round_num} — pinging all {total_ips} IPs ---")
    all_results = run_ping_round(
        config, dest_ips, stop_flag_fn,
        progress_cb=progress_cb,
        progress_offset=0,
        progress_total=total_ips
    )

    # Write all results to CSV
    for ip in dest_ips:
        result = all_results.get(ip, {
            "Router": config["host"], "Destination IP": ip,
            "Ping Result": "Unknown/Error", "Average Latency (ms)": "N/A", "Connectivity Type": "Unknown"
        })
        append_to_csv(output_csv, result, fieldnames)

    # ---- Retry rounds for Unknown/Error IPs ----
    prev_unknown = None
    while not stop_flag_fn():
        unknown_ips = get_unknown_error_ips(output_csv)

        if not unknown_ips:
            print("\n✅ No Unknown/Error IPs remaining. All done!")
            break

        # No progress between rounds — mark as Fail and stop
        if prev_unknown is not None and set(unknown_ips) == set(prev_unknown):
            print(f"\n⚠️ {len(unknown_ips)} IP(s) still Unknown/Error after retry with no change.")
            print(" Marking them as 'Fail' and stopping retries.")
            mark_ips_as_fail(output_csv, fieldnames, unknown_ips)
            break

        prev_unknown = unknown_ips
        round_num += 1
        n_unknown = len(unknown_ips)
        print(f"\n--- Round {round_num} — retrying {n_unknown} Unknown/Error IP(s) in {ROUND_DELAY}s ---")
        time.sleep(ROUND_DELAY)

        # Reset progress bar for this retry round so user sees movement
        if progress_cb:
            progress_cb(0, n_unknown)

        retry_results = run_ping_round(
            config, unknown_ips, stop_flag_fn,
            progress_cb=progress_cb,
            progress_offset=0,
            progress_total=n_unknown
        )
        update_csv_rows(output_csv, fieldnames, retry_results)
        print(f" Round {round_num} complete. CSV updated.")

    print(f"\n✅ All {total_ips} IPs processed. Results written to {output_csv}")
    print(f"✅ Process complete for Cisco router {config['host']}")