from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.agents.research import ResearchAgent


@pytest.fixture
def mock_gemini_provider():
  with patch("app.ai.agents.research.GeminiProvider") as mock:
    yield mock


@pytest.fixture
def mock_tavily_provider():
  with patch("app.ai.agents.research.TavilyProvider") as mock:
    yield mock


@pytest.fixture
def mock_crawler():
  with patch("app.ai.agents.research.AsyncWebCrawler") as mock:
    yield mock


@pytest.fixture
def mock_firestore():
  with patch("app.ai.agents.research.firestore") as mock:
    yield mock


@pytest.mark.anyio
async def test_discover(mock_gemini_provider, mock_tavily_provider):
  # Setup mocks
  mock_gemini_instance = mock_gemini_provider.return_value
  mock_model = MagicMock()
  mock_response = MagicMock()
  mock_response.content = "General"
  mock_model.generate = AsyncMock(return_value=mock_response)
  mock_gemini_instance.get_model.return_value = mock_model

  mock_tavily_instance = mock_tavily_provider.return_value
  mock_tavily_instance.search = AsyncMock(return_value={"results": [{"title": "Test Title", "url": "http://test.com", "content": "Test content"}]})

  agent = ResearchAgent()
  result = await agent.discover("test query", "user123")

  assert len(result.sources) == 1
  assert result.sources[0].title == "Test Title"

  # Verify router called
  mock_gemini_instance.get_model.assert_called()
  mock_model.generate.assert_called()

  # Verify search called
  mock_tavily_instance.search.assert_called_with(query="test query", search_depth="basic", include_answer=False, include_raw_content=False, max_results=5)


@pytest.mark.anyio
async def test_synthesize(mock_gemini_provider, mock_tavily_provider, mock_crawler, mock_firestore):
  # Setup Mocks
  mock_gemini_instance = mock_gemini_provider.return_value
  mock_model = MagicMock()
  mock_response = MagicMock()
  mock_response.content = "Synthesized Answer"
  mock_response.usage = {"token_count": 100}
  mock_model.generate = AsyncMock(return_value=mock_response)
  mock_gemini_instance.get_model.return_value = mock_model

  # Crawler Mock
  mock_crawler_instance = mock_crawler.return_value
  mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
  mock_crawler_instance.__aexit__.return_value = None

  mock_crawl_result = MagicMock()
  mock_crawl_result.success = True
  mock_crawl_result.markdown = "Markdown content"
  mock_crawler_instance.arun = AsyncMock(return_value=mock_crawl_result)

  # Firestore Mock
  mock_db = MagicMock()
  mock_firestore.client.return_value = mock_db

  agent = ResearchAgent()
  result = await agent.synthesize("query", ["http://url.com"], "user123")

  assert result.answer == "Synthesized Answer"
  assert len(result.sources) == 1

  # Verify calls
  mock_crawler_instance.arun.assert_called()
  mock_model.generate.assert_called()
  # Firestore should be called (via run_in_threadpool which calls _log_to_firestore)
  # We can't easily verify the threadpool execution result here without more complex mocking,
  # but we can assume if no exception raised it worked or logged error.
