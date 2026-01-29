from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.ai.agents.research import ResearchAgent


# Force anyio to use asyncio
@pytest.fixture
def anyio_backend():
  return "asyncio"


@pytest.fixture
def mock_settings():
  with patch("app.ai.agents.research.get_settings") as mock:
    mock.return_value = MagicMock(gemini_api_key="fake-key", research_router_model="gemini-1.5-flash-test", research_search_max_results=10, research_model="gemini-fake", app_id="test-app")
    yield mock.return_value


@pytest.fixture
def mock_gemini_provider():
  with patch("app.ai.agents.research.GeminiProvider") as mock:
    instance = mock.return_value
    instance.get_model.return_value.generate = AsyncMock()
    yield instance


@pytest.fixture
def mock_tavily_provider():
  with patch("app.ai.agents.research.TavilyProvider") as mock:
    instance = mock.return_value
    instance.search = AsyncMock()
    yield instance


@pytest.fixture
def mock_firestore():
  with patch("firebase_admin.firestore.client") as mock:
    yield mock


@pytest.mark.anyio
async def test_initialization_uses_settings(mock_settings, mock_gemini_provider, mock_tavily_provider):
  agent = ResearchAgent()

  # Check if settings were used
  assert agent.router_model_name == "gemini-1.5-flash-test"
  assert agent.search_max_results == 10

  # Check GeminiProvider init with key
  from app.ai.agents.research import GeminiProvider

  GeminiProvider.assert_called_with(api_key="fake-key")


@pytest.mark.anyio
async def test_classify_query_regex_logic(mock_settings, mock_gemini_provider, mock_tavily_provider):
  agent = ResearchAgent()
  model_mock = agent.gemini_provider.get_model.return_value

  # Scenario 1: Chatty response containing key word
  model_mock.generate.return_value = MagicMock(content="I think this is a General query.")
  category = await agent._classify_query("something general")
  assert category == "General"

  # Scenario 2: Canonical case correction
  model_mock.generate.return_value = MagicMock(content="security")
  category = await agent._classify_query("exploit")
  assert category == "Security"

  # Scenario 3: No match (Fallback)
  model_mock.generate.return_value = MagicMock(content="I don't know.")
  category = await agent._classify_query("random")
  assert category == "General"


@pytest.mark.anyio
async def test_privacy_logging(mock_settings, mock_gemini_provider, mock_tavily_provider, mock_firestore):
  # Patch datetime to avoid timezone issues during testing if environment is weird
  with patch("app.ai.agents.research.datetime") as mock_datetime:
    mock_datetime.now.return_value = "2024-01-01T00:00:00Z"
    # Mock UTC as well since it's accessed as datetime.UTC
    mock_datetime.UTC = "UTC"

    agent = ResearchAgent()

    db_client = mock_firestore.return_value

    # Call _log_to_firestore directly (it's sync)
    data = {"query": "test", "foo": "bar"}
    agent._log_to_firestore(user_id="user123", data=data)

    # Verify calls
    # Since db.collection().document()... chains might return the same mock object,
    # we inspect the leaf node's call history.

    # Get the leaf mock that .add() was called on
    # Assuming the chain structure is consistent, any refernece to the leaf path gives the mocked object
    collection_mock = db_client.collection.return_value.document.return_value.collection.return_value.document.return_value.collection.return_value

    assert collection_mock.add.call_count == 2

    calls = collection_mock.add.call_args_list
    payloads = [call[0][0] for call in calls]

    # One payload should have user_id, one should not
    has_user_id = [p for p in payloads if "user_id" in p]
    missing_user_id = [p for p in payloads if "user_id" not in p]

    assert len(has_user_id) == 1, "Expected exactly one call with user_id"
    assert len(missing_user_id) == 1, "Expected exactly one call without user_id"

    assert has_user_id[0]["user_id"] == "user123"
    assert missing_user_id[0]["query"] == "test"


@pytest.mark.anyio
async def test_crawl_urls_title_extraction(mock_settings, mock_gemini_provider, mock_tavily_provider):
  agent = ResearchAgent()

  # Mock Tavily response for specific URL
  agent.tavily_provider.search.return_value = {"results": [{"content": "Simulated content", "title": "Real Title", "url": "http://example.com"}]}

  urls = ["http://example.com"]
  results = await agent._crawl_urls(urls)

  assert len(results) == 1
  assert results[0]["title"] == "Real Title"
  assert results[0]["markdown"] == "Simulated content"
