"""
Test script to scan for open ports on localhost
"""
import socket
import subprocess
import json
import re
from typing import List, Dict, Any

def scan_localhost_ports(port_range: range = range(3000, 9000)) -> List[Dict[str, Any]]:
    """
    Scan for open TCP ports on localhost in the specified range.
    
    Returns a list of dicts with keys:
    - name: service name (derived from port or process)
    - port: port number
    - process: process name if detectable
    - pid: process ID if detectable
    """
    open_ports = []
    
    for port in port_range:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.1)  # Short timeout
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:  # Port is open
            # Try to get process info for this port
            process_info = get_process_for_port(port)
            open_ports.append({
                'port': port,
                'process': process_info.get('name', f'unknown-{port}'),
                'pid': process_info.get('pid'),
                'name': process_info.get('name', f'localhost-{port}')
            })
    
    return open_ports

def get_process_for_port(port: int) -> Dict[str, Any]:
    """
    Try to identify the process using a specific port.
    """
    try:
        # Use lsof to find process using the port (macOS/Linux)
        result = subprocess.run(
            ['lsof', '-i', f'tcp:{port}', '-t'], 
            capture_output=True, 
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split('\n')[0]
            
            # Get process name
            ps_result = subprocess.run(
                ['ps', '-p', pid, '-o', 'comm='],
                capture_output=True,
                text=True
            )
            if ps_result.returncode == 0:
                process_name = ps_result.stdout.strip()
                return {'pid': int(pid), 'name': process_name}
                
    except Exception:
        pass
    
    return {}

if __name__ == '__main__':
    ports = scan_localhost_ports(range(3000, 9000))
    print("Open localhost ports:")
    for port_info in ports:
        print(f"  {port_info['port']} -> {port_info['process']} (PID: {port_info.get('pid', 'unknown')})")