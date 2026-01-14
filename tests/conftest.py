import pytest
import sys
import os
from unittest.mock import MagicMock

# Add execution directory to path so tests can import modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../execution'))

# MOCK External Dependencies to prevent CI failures
# This ensures we don't need the actual DB file or API keys in CI
@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    # Mock SQLite DB Connection
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    
    # Mock DB Query Results
    mock_cursor.fetchone.return_value = None # Default empty
    mock_cursor.fetchall.return_value = []
    
    # Mock sqlite3.connect to return our mock connection
    monkeypatch.setattr("sqlite3.connect", lambda path: mock_conn)
    
    # Mock Anthropic Client to avoid API key errors
    mock_anthropic = MagicMock()
    mock_content = MagicMock()
    mock_content.text = '{"audit_results": []}' # Valid JSON response
    mock_anthropic.messages.create.return_value.content = [mock_content]
    
    # We need to mock where it's imported in medical_audit
    # Note: We might need to mock the module `anthropic.Anthropic` if it's instantiated directly
    sys.modules['anthropic'] = MagicMock()
