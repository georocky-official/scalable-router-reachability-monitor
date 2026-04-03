from ping_cisco import router_ping as cisco_ping
from ping_juniper import router_ping as juniper_ping

def get_user_input():
    router_ip = input("Enter router IP: ").strip()
    router_type = input("Router type (cisco/juniper): ").strip().lower()
    method = input("Connection method (ssh/telnet): ").strip().lower()
    username = input("Enter username: ").strip()
    password = input("Enter password: ").strip()
    return router_ip, router_type, method, username, password


def build_router_config(ip, router_type, method, username, password):
    if router_type == "cisco":
        device_type = "cisco_ios" if method == "ssh" else "cisco_ios_telnet"
    elif router_type == "juniper":
        device_type = "juniper_junos"
    else:
        raise ValueError("Unsupported router type")

    return {
        "device_type": device_type,
        "host": ip,
        "username": username,
        "password": password,
    }


def run_ping(router_type, config):
    if router_type == "cisco":
        cisco_ping(config)
    elif router_type == "juniper":
        juniper_ping(config)
    else:
        print("Unsupported router type")


if __name__ == "__main__":
    ip, router_type, method, username, password = get_user_input()
    config = build_router_config(ip, router_type, method, username, password)
    run_ping(router_type, config)

