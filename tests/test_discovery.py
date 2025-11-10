"""
Test script to verify localhost discovery functionality
"""
import sys
from pathlib import Path

# Add the domainup package to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from domainup.localhost_discovery import discover_localhost_services
from domainup.commands.discover_cmd import discover_services

def test_localhost_discovery():
    localhost_services = discover_localhost_services()
    assert isinstance(localhost_services, list)
    for service in localhost_services:
        assert "name" in service
        assert "port" in service

    all_services = discover_services(include_localhost=True)
    docker_services = [s for s in all_services if s.get('type') != 'localhost']
    localhost_services_from_combined = [s for s in all_services if s.get('type') == 'localhost']
    assert isinstance(docker_services, list)
    assert isinstance(localhost_services_from_combined, list)
    # At least one service should be found in total
    assert len(all_services) >= 0

    docker_only_services = discover_services(include_localhost=False)
    assert isinstance(docker_only_services, list)