# scalable-router-reachability-monitor
Multi-threaded network monitoring tool for parallel router reachability and latency analysis
# 🚀 Scalable Router Reachability Monitor

## 📌 Overview
A scalable, multi-threaded network monitoring tool designed to automate reachability checks across hundreds to thousands of endpoints in parallel.

Built with a focus on performance, reliability, and usability in NOC and large-scale network environments.

---

## ⚙️ Key Features

- 🔹 Parallel execution across multiple routers  
- 🔹 Multi-threaded processing for faster reachability checks  
- 🔹 Support for Cisco and Juniper devices  
- 🔹 Intelligent retry mechanism for failed/unreachable IPs  
- 🔹 Live progress tracking with per-router visibility  
- 🔹 Safe interruption handling with no data loss  
- 🔹 Structured CSV output with latency and connectivity insights  
- 🔹 GUI-based interface for ease of use  

---

## 🧠 Architecture Overview

The tool follows a modular and scalable design:

- **GUI Layer** (CustomTkinter)  
  Handles user interaction and execution control  

- **Controller Layer**  
  Orchestrates execution flow and manages threading  

- **Router Abstraction Layer**  
  Separate modules for Cisco and Juniper devices  

- **Execution Layer**  
  Multi-threaded workers with queue-based processing  

- **Transport Layer**  
  SSH communication using Netmiko  

- **Output Layer**  
  Real-time CSV logging with structured results  

---

## 📸 Screenshots

### Single Router Execution
<img width="591" height="628" alt="image" src="https://github.com/user-attachments/assets/57cab6f9-e748-444d-b3ab-3eeea30cbaf4" />


### Execution Completed
<img width="1441" height="1536" alt="image" src="https://github.com/user-attachments/assets/971bdc54-b3f2-41cf-960f-7f0103241086" />


### Multi-Router Parallel Execution
<img width="1525" height="1536" alt="image" src="https://github.com/user-attachments/assets/ec0d263f-185f-4781-9ccd-a92d7deeb18d" />


### Safe Interruption Handling
<img width="1536" height="1521" alt="image" src="https://github.com/user-attachments/assets/568c5f73-81ee-425d-9377-85cf447b8e13" />


### Sample Output (CSV)
<img width="1126" height="1536" alt="image" src="https://github.com/user-attachments/assets/ae1d1a41-44f0-4c7b-949f-bb1401bb80e2" />


---

## 📊 How It Works

1. Load destination IPs from an Excel file  
2. Establish SSH session(s) to the router  
3. Execute parallel ping operations using worker threads  
4. Parse results for:
   - Reachability (Success/Fail)  
   - Latency  
   - Connectivity type  
5. Save results in CSV format (live logging supported)  
6. Automatically retry failed or unknown IPs  

---

## 📦 Deployment Consideration

The tool is designed to be packaged as a standalone executable, enabling usage in restricted enterprise environments without requiring Python or external dependency installation.

---


## 📈 Performance & Scalability

- Tested with approximately 3000 destination IPs  
- Execution completed within ~12–15 minutes  
- No runtime failures or crashes observed  
- Stable performance during long-running execution  

This demonstrates the tool’s capability to operate in large-scale network environments.


## ⚠️ Note

This repository is intended for demonstration purposes only.

Some components have been intentionally simplified or modified to prevent direct execution.  
The focus is on showcasing system design, architecture, and problem-solving approach.

---

## 🛠️ Tech Stack

- Python  
- Netmiko  
- Pandas  
- CustomTkinter  
- Multithreading  

---

## 🎯 Use Case

Designed for:
- Network Operations Centers (NOC)  
- Large-scale network monitoring environments  
- SD-WAN / multi-site infrastructure validation  
- Automation of repetitive reachability checks
- Minimize Mean Time to Detection (MTTD) by enabling parallel reachability checks across multiple network paths.
  

---

## 🔮 Future Enhancements

- Threshold-based alerting system  
- Dashboard visualization  
- Centralized monitoring interface  
- API-based integration  
- SNMP-based monitoring

---

## 📌 Disclaimer

This project is a generalized implementation for learning and demonstration purposes.  
No real infrastructure data, credentials, or sensitive information is included.

---

## 🤝 Feedback

Open to suggestions, improvements, and discussions around network automation and monitoring systems.
