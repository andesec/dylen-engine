from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.fixture
def mock_gemini():
    with patch("app.api.routes.research._get_gemini_client") as mock:
        yield mock

@pytest.fixture
def mock_tavily():
    with patch("app.api.routes.research._get_tavily_client") as mock:
        yield mock

def test_discover_endpoint(mock_gemini, mock_tavily):
    # Mock Gemini response for classification
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "General"

    # Setup async return for generate_content
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    mock_gemini.return_value = mock_client

    # Mock Tavily response
    mock_tavily_client = MagicMock()
    mock_tavily_client.search.return_value = {
        "results": [
            {"title": "Test Title", "url": "http://test.com", "content": "Test content"}
        ]
    }
    mock_tavily.return_value = mock_tavily_client

    response = client.post("/v1/research/discover", json={"query": "test query"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Test Title"

def test_synthesize_endpoint(mock_gemini):
    # Mock Crawler
    with patch("app.api.routes.research.AsyncWebCrawler") as mock_crawler_class:
        mock_crawler_instance = mock_crawler_class.return_value
        # Mock context manager
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
        mock_crawler_instance.__aexit__.return_value = None

        # Mock arun results
        mock_result1 = MagicMock()
        mock_result1.success = True
        mock_result1.markdown = "Markdown 1"

        mock_result2 = MagicMock()
        mock_result2.success = True
        mock_result2.markdown = "Markdown 2"

        async def async_arun(url):
            if "url1" in url:
                return mock_result1
            return mock_result2

        mock_crawler_instance.arun = AsyncMock(side_effect=async_arun)

        # Mock Gemini
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Synthesized Answer"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_gemini.return_value = mock_client

        # Mock Firestore logging
        with patch("app.api.routes.research._log_to_firestore") as mock_log:
             response = client.post("/v1/research/synthesize", json={
                 "query": "test query",
                 "urls": ["http://url1.com", "http://url2.com"],
                 "user_id": "user123"
             })

             assert response.status_code == 200
             data = response.json()
             assert data["answer"] == "Synthesized Answer"
             assert len(data["sources"]) == 2
             assert data["sources"][0]["url"] == "http://url1.com"

             # Verify log called
             mock_log.assert_called_once()
