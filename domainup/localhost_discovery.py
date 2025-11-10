from __future__ import annotations

import socket
import subprocess
import re
from typing import List, Dict, Any, Optional
from pathlib import Path


def discover_localhost_services(port_range: range = range(3000, 9000)) -> List[Dict[str, Any]]:
    """
    Discover services running on localhost ports (non-Docker).
    
    Scans for open TCP ports on localhost and tries to identify the processes.
    Returns a list of dicts compatible with ServiceInfo format:
    - name: process name or localhost-{port}
    - port: port number  
    - process: process name if detectable
    - pid: process ID if detectable
    - published: list with single tuple (port/tcp, 127.0.0.1, port) for compatibility
    - networks: empty list (not Docker)
    - exposed: empty list (not Docker)
    - localhost: True (marker to distinguish from Docker services)
    """
    open_services = []
    dev_process_patterns = [
        'node', 'npm', 'yarn', 'pnpm', 'python', 'java', 'vite', 'react', 'flask', 'django', 'gatsby', 'ionic', 'php', 'jupyter', 'angular'
    ]
    common_dev_ports = {3000, 3001, 4000, 5173, 5174, 8000, 8080, 8100, 9000, 4200, 3030, 5000, 8888, 9999}
    for port in port_range:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        if result == 0:
            process_info = _get_process_for_port(port)
            process_name = process_info.get('name', '').lower()
            # Include if process name matches dev patterns OR port is a common dev port
            if any(pat in process_name for pat in dev_process_patterns) or port in common_dev_ports:
                service_name = _generate_service_name(port, process_info)
                open_services.append({
                    'name': service_name,
                    'port': port,
                    'process': process_info.get('name', f'unknown-{port}'),
                    'pid': process_info.get('pid'),
                    'published': [(f'{port}/tcp', '127.0.0.1', str(port))],
                    'networks': [],
                    'exposed': [],
                    'localhost': True,
                    'image': ''
                })
    return open_services


def _get_process_for_port(port: int) -> Dict[str, Any]:
    """
    Try to identify the process using a specific port.
    Uses lsof on macOS/Linux or netstat on Windows.
    """
    try:
        # Try lsof first (macOS/Linux)
        result = subprocess.run(
            ['lsof', '-i', f'tcp:{port}', '-n', '-P'], 
            capture_output=True, 
            text=True,
            timeout=2
        )
        
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            if lines:
                # Parse lsof output: COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
                fields = lines[0].split()
                if len(fields) >= 2:
                    command = fields[0]
                    pid = fields[1]
                    try:
                        return {'pid': int(pid), 'name': command}
                    except ValueError:
                        pass
                
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # lsof not available or timed out, try netstat (cross-platform)
        try:
            result = subprocess.run(
                ['netstat', '-tulpn'], 
                capture_output=True, 
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTEN' in line:
                        # Try to extract process info from netstat
                        match = re.search(r'(\d+)/(\w+)', line)
                        if match:
                            pid, name = match.groups()
                            return {'pid': int(pid), 'name': name}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    
    return {}


def _generate_service_name(port: int, process_info: Dict[str, Any]) -> str:
    """
    Generate a meaningful service name based on port and process info.
    """
    process_name = process_info.get('name', '')
    
    # Common development server patterns
    common_names = {
        3000: 'react-dev',
        3001: 'react-dev-alt', 
        4000: 'vue-dev',
        5173: 'vite-dev',
        5174: 'vite-dev-alt',
        8000: 'django-dev',
        8080: 'http-alt',
        8100: 'ionic-dev',
        9000: 'php-dev',
        4200: 'angular-dev',
        3030: 'gatsby-dev',
        5000: 'flask-dev',
        8888: 'jupyter',
        9999: 'dev-server'
    }
    
    if port in common_names:
        base_name = common_names[port]
    elif process_name:
        # Clean process name and use it
        clean_name = re.sub(r'[^a-zA-Z0-9]', '-', process_name.lower())
        base_name = f"{clean_name}-{port}"
    else:
        base_name = f"localhost-{port}"
    
    # Framework detection from process name
    if process_name:
        lower_proc = process_name.lower()
        if any(name in lower_proc for name in ['node', 'npm', 'yarn', 'pnpm']):
            if port == 3000:
                return 'react-app'
            elif port == 5173:
                return 'vite-app'
            elif port == 4200:
                return 'angular-app'
            else:
                return f'node-app-{port}'
        elif 'python' in lower_proc:
            if port == 8000:
                return 'django-app'
            elif port == 5000:
                return 'flask-app'
            else:
                return f'python-app-{port}'
        elif 'java' in lower_proc:
            return f'java-app-{port}'
    
    return base_name